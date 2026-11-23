"""Model architecture inspection and compatibility verification for mergekit."""

from __future__ import annotations

import json
from typing import Any

from rich.table import Table

from lathe.merge.models import (
    ArchitectureDifference,
    CompatibilityResult,
    ModelArchitectureInfo,
)


def estimate_transformer_parameters(config: dict[str, Any]) -> int:
    """Estimate total parameters of a decoder-only transformer from its config."""
    if "num_parameters" in config and isinstance(config["num_parameters"], int):
        return int(config["num_parameters"])

    vocab_size = int(config.get("vocab_size", 32000))
    hidden_size = int(config.get("hidden_size", config.get("d_model", 4096)))
    num_layers = int(config.get("num_hidden_layers", config.get("n_layer", 32)))
    intermediate_size = int(
        config.get(
            "intermediate_size",
            config.get("hidden_dimension", hidden_size * 4),
        )
    )
    num_attn_heads = int(config.get("num_attention_heads", config.get("n_head", 32)))
    num_kv_heads = int(config.get("num_key_value_heads", num_attn_heads))

    # 1. Embeddings: token embeddings + lm_head (unshared or shared)
    embedding_params = vocab_size * hidden_size
    tie_word_embeddings = config.get(
        "tie_word_embeddings",
        str(config.get("model_type", "")).lower() in ("qwen2", "qwen"),
    )
    lm_head_params = 0 if tie_word_embeddings else (vocab_size * hidden_size)

    # 2. Per layer:
    # Attention: Q, K, V, O projections
    q_proj = hidden_size * hidden_size
    head_dim = hidden_size // num_attn_heads
    kv_dim = num_kv_heads * head_dim
    k_proj = hidden_size * kv_dim
    v_proj = hidden_size * kv_dim
    out_proj = hidden_size * hidden_size
    attn_per_layer = q_proj + k_proj + v_proj + out_proj

    # MLP / FFN: gate, up, down (SwiGLU architecture standard in Llama/Qwen/Mistral)
    mlp_per_layer = 3 * hidden_size * intermediate_size

    # Layer norms: input norm + post-attention norm
    norm_per_layer = 2 * hidden_size

    total_layer_params = num_layers * (attn_per_layer + mlp_per_layer + norm_per_layer)
    final_norm = hidden_size

    return embedding_params + lm_head_params + total_layer_params + final_norm


def parse_model_info_from_configs(
    repo_id: str,
    config_data: dict[str, Any],
    tokenizer_config_data: dict[str, Any] | None = None,
) -> ModelArchitectureInfo:
    """Construct ModelArchitectureInfo from pre-loaded JSON config dictionaries."""
    tok_data = tokenizer_config_data or {}
    model_type = str(config_data.get("model_type", "unknown"))
    hidden_size = int(config_data.get("hidden_size", config_data.get("d_model", 0)))
    num_layers = int(config_data.get("num_hidden_layers", config_data.get("n_layer", 0)))
    vocab_size = int(config_data.get("vocab_size", 0))
    intermediate_size = (
        int(config_data["intermediate_size"]) if "intermediate_size" in config_data else None
    )
    num_attn_heads = (
        int(config_data["num_attention_heads"]) if "num_attention_heads" in config_data else None
    )
    num_kv_heads = (
        int(config_data["num_key_value_heads"]) if "num_key_value_heads" in config_data else None
    )
    tokenizer_class = tok_data.get("tokenizer_class")
    if not tokenizer_class and "tokenizer_model_type" in tok_data:
        tokenizer_class = str(tok_data["tokenizer_model_type"])

    est_params = estimate_transformer_parameters(config_data)

    return ModelArchitectureInfo(
        repo_id=repo_id,
        model_type=model_type,
        hidden_size=hidden_size,
        num_hidden_layers=num_layers,
        vocab_size=vocab_size,
        intermediate_size=intermediate_size,
        num_attention_heads=num_attn_heads,
        num_key_value_heads=num_kv_heads,
        tokenizer_class=tokenizer_class,
        raw_config=config_data,
        raw_tokenizer_config=tok_data,
        estimated_params=est_params,
    )


def fetch_model_info(repo_id: str, hf_token: str | None = None) -> ModelArchitectureInfo:
    """Fetch model architecture and tokenizer configs from Hugging Face Hub without weights."""
    if (
        repo_id.lower().endswith(".gguf")
        or "-gguf" in repo_id.lower()
        or "/gguf" in repo_id.lower()
    ):
        raise ValueError(
            f"Repository '{repo_id}' appears to be a GGUF checkpoint. "
            "lathe merge requires full-precision safetensors repositories."
        )

    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import (
            EntryNotFoundError,
            RepositoryNotFoundError,
        )
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required to fetch model configs. "
            "Install it via 'pip install huggingface-hub'."
        ) from exc

    try:
        config_path = hf_hub_download(
            repo_id=repo_id,
            filename="config.json",
            token=hf_token,
        )
    except RepositoryNotFoundError as exc:
        raise ValueError(f"Hugging Face repository '{repo_id}' was not found.") from exc
    except EntryNotFoundError as exc:
        raise ValueError(
            f"Repository '{repo_id}' does not have a config.json. "
            "Ensure this is a safetensors transformer model repository, not GGUF."
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Failed to fetch config.json for '{repo_id}' from Hugging Face: {exc}"
        ) from exc

    with open(config_path, encoding="utf-8") as f:
        config_data = json.load(f)

    tok_data: dict[str, Any] = {}
    try:
        tok_path = hf_hub_download(
            repo_id=repo_id,
            filename="tokenizer_config.json",
            token=hf_token,
        )
        with open(tok_path, encoding="utf-8") as f:
            tok_data = json.load(f)
    except Exception:
        # Some repos might not have tokenizer_config.json or it's optional
        tok_data = {}

    return parse_model_info_from_configs(repo_id, config_data, tok_data)


def check_compatibility(
    model_a: ModelArchitectureInfo,
    model_b: ModelArchitectureInfo,
) -> CompatibilityResult:
    """Compare two models and determine whether they share compatible architectures for merging."""
    differences: list[ArchitectureDifference] = []
    reasons: list[str] = []

    # 1. Model Type
    type_match = model_a.model_type.lower() == model_b.model_type.lower()
    differences.append(
        ArchitectureDifference(
            attribute="Model Type",
            model_a_value=model_a.model_type,
            model_b_value=model_b.model_type,
            is_matching=type_match,
        )
    )
    if not type_match:
        reasons.append(
            f"Model types differ ('{model_a.model_type}' vs '{model_b.model_type}'). "
            "Weights cannot be interpolated across disparate neural architectures."
        )

    # 2. Hidden Size
    hidden_match = model_a.hidden_size == model_b.hidden_size
    differences.append(
        ArchitectureDifference(
            attribute="Hidden Size (dim)",
            model_a_value=model_a.hidden_size,
            model_b_value=model_b.hidden_size,
            is_matching=hidden_match,
        )
    )
    if not hidden_match:
        reasons.append(
            f"Hidden dimensions differ ({model_a.hidden_size} vs {model_b.hidden_size}). "
            "Layer weight matrices have incompatible shapes."
        )

    # 3. Number of Hidden Layers
    layers_match = model_a.num_hidden_layers == model_b.num_hidden_layers
    differences.append(
        ArchitectureDifference(
            attribute="Hidden Layers",
            model_a_value=model_a.num_hidden_layers,
            model_b_value=model_b.num_hidden_layers,
            is_matching=layers_match,
        )
    )
    if not layers_match:
        reasons.append(
            f"Number of layers differ ({model_a.num_hidden_layers} vs {model_b.num_hidden_layers})."
        )

    # 4. Vocab Size
    vocab_match = model_a.vocab_size == model_b.vocab_size
    differences.append(
        ArchitectureDifference(
            attribute="Vocab Size",
            model_a_value=model_a.vocab_size,
            model_b_value=model_b.vocab_size,
            is_matching=vocab_match,
        )
    )
    if not vocab_match:
        reasons.append(
            f"Vocabulary sizes differ ({model_a.vocab_size} vs {model_b.vocab_size}). "
            "Embedding and output projection matrices cannot align."
        )

    # 5. Tokenizer
    tok_a = model_a.tokenizer_class or "Unknown"
    tok_b = model_b.tokenizer_class or "Unknown"
    tok_match = (
        tok_a == tok_b
        or tok_a == "Unknown"
        or tok_b == "Unknown"
        or tok_a.lower().replace("fast", "") == tok_b.lower().replace("fast", "")
    )
    differences.append(
        ArchitectureDifference(
            attribute="Tokenizer Class",
            model_a_value=tok_a,
            model_b_value=tok_b,
            is_matching=tok_match,
        )
    )
    if not tok_match:
        reasons.append(
            f"Tokenizer classes differ ('{tok_a}' vs '{tok_b}'). Token mappings may mismatch."
        )

    # 6. Attention / KV Heads
    if model_a.num_attention_heads and model_b.num_attention_heads:
        heads_match = model_a.num_attention_heads == model_b.num_attention_heads
        differences.append(
            ArchitectureDifference(
                attribute="Attention Heads",
                model_a_value=model_a.num_attention_heads,
                model_b_value=model_b.num_attention_heads,
                is_matching=heads_match,
            )
        )
        if not heads_match:
            reasons.append("Attention heads count mismatch.")

    is_compatible = (
        type_match
        and hidden_match
        and layers_match
        and vocab_match
        and tok_match
        and len(reasons) == 0
    )

    return CompatibilityResult(
        is_compatible=is_compatible,
        differences=differences,
        model_a_info=model_a,
        model_b_info=model_b,
        reasons=reasons,
    )


def render_compatibility_table(result: CompatibilityResult) -> Table:
    """Render a styled Rich table illustrating parameter comparisons and compatibility."""
    table = Table(
        title="Model Architecture Compatibility Check",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Property", style="bold", width=22)
    table.add_column(f"Model A: {result.model_a_info.repo_id}", width=28)
    table.add_column(f"Model B: {result.model_b_info.repo_id}", width=28)
    table.add_column("Status", width=14)

    for diff in result.differences:
        status_badge = "[green]✓ Match[/green]" if diff.is_matching else "[red]✗ Mismatch[/red]"
        table.add_row(
            diff.attribute,
            str(diff.model_a_value),
            str(diff.model_b_value),
            status_badge,
        )

    return table

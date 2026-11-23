"""Unit tests for model architecture extraction, parameter estimation, and compatibility checks."""

import pytest

from lathe.merge.compatibility import (
    check_compatibility,
    estimate_transformer_parameters,
    fetch_model_info,
    parse_model_info_from_configs,
    render_compatibility_table,
)
from lathe.merge.models import ModelArchitectureInfo


def test_estimate_transformer_parameters_explicit():
    """Explicit num_parameters in config takes precedence."""
    config = {"num_parameters": 7_000_000_000, "vocab_size": 32000, "hidden_size": 4096}
    assert estimate_transformer_parameters(config) == 7_000_000_000


def test_estimate_transformer_parameters_qwen_1_5b():
    """Estimation for Qwen2.5 1.5B architecture produces ~1.54B parameters."""
    config = {
        "model_type": "qwen2",
        "vocab_size": 151936,
        "hidden_size": 1536,
        "num_hidden_layers": 28,
        "intermediate_size": 8960,
        "num_attention_heads": 12,
        "num_key_value_heads": 2,
        "tie_word_embeddings": True,
    }
    params = estimate_transformer_parameters(config)
    # Total params should be in the 1.4B - 1.65B range (~1.54B)
    assert 1_400_000_000 <= params <= 1_650_000_000


def test_parse_model_info():
    """Parse model architecture info from config dictionaries."""
    config = {
        "model_type": "qwen2",
        "hidden_size": 1536,
        "num_hidden_layers": 28,
        "vocab_size": 151936,
        "intermediate_size": 8960,
        "num_attention_heads": 12,
        "num_key_value_heads": 2,
    }
    tok_config = {"tokenizer_class": "Qwen2Tokenizer"}
    info = parse_model_info_from_configs("Qwen/Qwen2.5-Coder-1.5B", config, tok_config)

    assert info.repo_id == "Qwen/Qwen2.5-Coder-1.5B"
    assert info.model_type == "qwen2"
    assert info.hidden_size == 1536
    assert info.num_hidden_layers == 28
    assert info.vocab_size == 151936
    assert info.tokenizer_class == "Qwen2Tokenizer"
    assert info.estimated_params > 1_000_000_000


def test_check_compatibility_success():
    """Models with matching architectures are compatible."""
    model_a = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-1.5B",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
        tokenizer_class="Qwen2TokenizerFast",
        estimated_params=1_540_000_000,
    )
    model_b = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-1.5B-Instruct",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
        tokenizer_class="Qwen2TokenizerFast",
        estimated_params=1_540_000_000,
    )

    result = check_compatibility(model_a, model_b)
    assert result.is_compatible is True
    assert len(result.reasons) == 0

    table = render_compatibility_table(result)
    assert table is not None
    assert "Model Architecture Compatibility Check" in table.title


def test_check_compatibility_model_type_mismatch():
    """Disparate model types must fail compatibility."""
    model_a = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-1.5B",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
    )
    model_b = ModelArchitectureInfo(
        repo_id="meta-llama/Llama-3.2-1B",
        model_type="llama",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
    )

    result = check_compatibility(model_a, model_b)
    assert result.is_compatible is False
    assert any("Model types differ" in r for r in result.reasons)


def test_check_compatibility_hidden_size_mismatch():
    """Mismatched hidden_size must fail compatibility."""
    model_a = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-1.5B",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
    )
    model_b = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-7B",
        model_type="qwen2",
        hidden_size=3584,
        num_hidden_layers=28,
        vocab_size=151936,
    )

    result = check_compatibility(model_a, model_b)
    assert result.is_compatible is False
    assert any("Hidden dimensions differ" in r for r in result.reasons)


def test_check_compatibility_layers_and_vocab_mismatch():
    """Mismatched layers and vocabulary sizes must fail compatibility."""
    model_a = ModelArchitectureInfo(
        repo_id="ModelA",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
    )
    model_b = ModelArchitectureInfo(
        repo_id="ModelB",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=32,
        vocab_size=32000,
    )

    result = check_compatibility(model_a, model_b)
    assert result.is_compatible is False
    assert any("Number of layers differ" in r for r in result.reasons)
    assert any("Vocabulary sizes differ" in r for r in result.reasons)


def test_fetch_model_info_rejects_gguf():
    """GGUF repositories must be rejected immediately."""
    with pytest.raises(ValueError, match="GGUF checkpoint"):
        fetch_model_info("bartowski/Qwen2.5-Coder-1.5B-GGUF")

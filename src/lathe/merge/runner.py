"""Local mergekit execution engine and auto-generated model card creation."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


def is_mergekit_installed() -> bool:
    """Check if the mergekit-yaml executable is available in PATH."""
    return shutil.which("mergekit-yaml") is not None


def generate_model_card(
    name: str,
    models: list[str],
    method: str,
    parameters: dict[str, Any],
    config_yaml: str,
) -> str:
    """Generate a markdown model card (README.md) with metadata frontmatter."""
    base_models_yaml = "\n".join(f"  - {m}" for m in models)
    models_bullet_list = "\n".join(f"- [{m}](https://huggingface.co/{m})" for m in models)
    formatted_params = json.dumps(parameters, indent=2)

    return f"""---
license: apache-2.0
tags:
  - merge
  - mergekit
  - lathe
  - open-weights
base_model:
{base_models_yaml}
---

# {name}

`{name}` is an open-source model merge produced with [Lathe](https://github.com/lathe-agent/lathe)
using [mergekit](https://github.com/arcee-ai/mergekit).

## Source Models

The following parent models were merged into this checkpoint:
{models_bullet_list}

## Merge Configuration

- **Method**: `{method}`
- **Precision**: `float16`
- **Parameters**:
```json
{formatted_params}
```

### mergekit YAML Config

```yaml
{config_yaml.strip()}
```

## Local Inference & Deployment

This merged safetensors checkpoint can be quantized to GGUF format via `llama.cpp`
and deployed locally to Ollama:

1. **Convert to GGUF**:
   ```bash
   python3 llama.cpp/convert_hf_to_gguf.py merges/{name} --outtype f16 --outfile {name}.fp16.gguf
   ```

2. **Quantize to Q4_K_M**:
   ```bash
   ./llama-quantize {name}.fp16.gguf {name}.Q4_K_M.gguf Q4_K_M
   ```

3. **Serve with Ollama**:
   ```bash
   ollama create {name} -f Modelfile
   ollama run {name}
   ```
"""


def write_model_card(
    output_dir: Path | str,
    name: str,
    models: list[str],
    method: str,
    parameters: dict[str, Any],
    config_yaml: str,
) -> Path:
    """Write the model card README.md inside the merge output directory."""
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    card_path = target_dir / "README.md"
    card_content = generate_model_card(
        name=name,
        models=models,
        method=method,
        parameters=parameters,
        config_yaml=config_yaml,
    )
    card_path.write_text(card_content, encoding="utf-8")
    return card_path


def run_mergekit(
    config_path: Path | str,
    output_dir: Path | str,
    copy_tokenizer: bool = True,
    extra_args: list[str] | None = None,
    out_console: Console | None = None,
) -> int:
    """Execute mergekit-yaml with low-memory lazy-unpickle options, streaming progress output."""
    out = out_console or console

    if not is_mergekit_installed():
        raise RuntimeError(
            "mergekit is not installed. Run 'pip install lathe-agent[merge]' or "
            "'pip install mergekit' to enable local model merging, or pass '--colab' "
            "to generate a ready Google Colab notebook."
        )

    cmd = [
        "mergekit-yaml",
        str(config_path),
        str(output_dir),
        "--lazy-unpickle",
        "--allow-crimes",
        "--low-cpu-memory",
    ]
    if copy_tokenizer:
        cmd.append("--copy-tokenizer")
    if extra_args:
        cmd.extend(extra_args)

    out.print(f"[bold cyan]Running mergekit command:[/bold cyan] {' '.join(cmd)}")

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc:
        if proc.stdout:
            for line in proc.stdout:
                out.print(f"[dim]{line.rstrip()}[/dim]")
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"mergekit-yaml execution failed with exit code {ret}.")

    return ret

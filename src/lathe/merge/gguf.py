"""GGUF conversion, quantization, Ollama Modelfile generation, and deployment."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console()

DEFAULT_LLAMA_CPP_TAG = "b4578"
DEFAULT_CHAT_TEMPLATE = (
    "{{- if .System }}<|im_start|>system\n"
    "{{ .System }}<|im_end|>\n"
    "{{- end }}\n"
    "{{- range .Messages }}\n"
    "<|im_start|>{{ .Role }}\n"
    "{{ .Content }}<|im_end|>\n"
    "{{- end }}\n"
    "<|im_start|>assistant\n"
)


def get_llama_cpp_cache_dir() -> Path:
    """Return default cache directory for cloned llama.cpp."""
    return Path.home() / ".cache" / "lathe" / "llama.cpp"


def ensure_llama_cpp(
    cache_dir: Path | str | None = None,
    tag: str = DEFAULT_LLAMA_CPP_TAG,
    out_console: Console | None = None,
) -> Path:
    """Ensure llama.cpp repository is cloned and pinned to the specified release tag."""
    out = out_console or console
    target_dir = Path(cache_dir) if cache_dir else get_llama_cpp_cache_dir()

    script_path = target_dir / "convert_hf_to_gguf.py"
    if target_dir.exists() and script_path.exists():
        return target_dir

    out.print(f"[bold cyan]Cloning llama.cpp ({tag}) into {target_dir}...[/bold cyan]")
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        tag,
        "https://github.com/ggerganov/llama.cpp.git",
        str(target_dir),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        if not script_path.exists():
            raise RuntimeError(
                f"Failed to clone llama.cpp repository from GitHub: {exc.stderr.strip()}"
            ) from exc

    return target_dir


def find_or_build_quantize_binary(
    llama_cpp_dir: Path,
    out_console: Console | None = None,
) -> Path | None:
    """Find existing llama-quantize binary or compile it from source."""
    out = out_console or console

    # 1. Check system PATH
    sys_bin = shutil.which("llama-quantize") or shutil.which("quantize")
    if sys_bin:
        return Path(sys_bin)

    # 2. Check build directories inside llama.cpp
    candidate_paths = [
        llama_cpp_dir / "build" / "bin" / "llama-quantize",
        llama_cpp_dir / "build" / "bin" / "quantize",
        llama_cpp_dir / "llama-quantize",
        llama_cpp_dir / "quantize",
    ]
    for p in candidate_paths:
        if p.is_file() and os.access(p, os.X_OK):
            return p

    # 3. Attempt compilation if cmake or make is available
    out.print("[dim]Compiling llama-quantize binary from source...[/dim]")
    if shutil.which("cmake"):
        try:
            build_dir = llama_cpp_dir / "build"
            subprocess.run(
                ["cmake", "-B", str(build_dir), "-DGGML_BUILD_TESTS=OFF"],
                cwd=str(llama_cpp_dir),
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["cmake", "--build", str(build_dir), "--target", "llama-quantize", "-j4"],
                cwd=str(llama_cpp_dir),
                check=True,
                capture_output=True,
                text=True,
            )
            built_bin = build_dir / "bin" / "llama-quantize"
            if built_bin.is_file():
                return built_bin
        except Exception:
            pass

    if shutil.which("make"):
        try:
            subprocess.run(
                ["make", "-j4", "llama-quantize"],
                cwd=str(llama_cpp_dir),
                check=True,
                capture_output=True,
                text=True,
            )
            built_bin = llama_cpp_dir / "llama-quantize"
            if built_bin.is_file():
                return built_bin
        except Exception:
            pass

    return None


def convert_to_fp16_gguf(
    merge_dir: Path,
    output_f16_path: Path,
    llama_cpp_dir: Path,
    out_console: Console | None = None,
) -> Path:
    """Execute convert_hf_to_gguf.py to produce an unquantized FP16 GGUF file."""
    out = out_console or console
    script_path = llama_cpp_dir / "convert_hf_to_gguf.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Conversion script not found at '{script_path}'.")

    cmd = [
        sys.executable,
        str(script_path),
        str(merge_dir),
        "--outtype",
        "f16",
        "--outfile",
        str(output_f16_path),
    ]

    out.print(
        f"[bold cyan]Converting {merge_dir.name} to FP16 GGUF:[/bold cyan] "
        f"{output_f16_path.name}..."
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"GGUF conversion failed (exit code {proc.returncode}):\n{err_msg}")

    return output_f16_path


def quantize_gguf(
    f16_path: Path,
    output_quant_path: Path,
    quant: str = "Q4_K_M",
    quantize_bin: Path | None = None,
    out_console: Console | None = None,
) -> Path:
    """Quantize an FP16 GGUF file to target format (e.g. Q4_K_M) using llama-quantize."""
    out = out_console or console
    if not quantize_bin or not quantize_bin.exists():
        raise FileNotFoundError(
            "llama-quantize binary could not be found or built. "
            "Install llama.cpp or compile llama-quantize manually."
        )

    cmd = [
        str(quantize_bin),
        str(f16_path),
        str(output_quant_path),
        quant,
    ]

    out.print(f"[bold cyan]Quantizing to {quant}:[/bold cyan] {output_quant_path.name}...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"llama-quantize failed (exit code {proc.returncode}):\n{err_msg}")

    return output_quant_path


def extract_chat_template(merge_dir: Path) -> str:
    """Extract chat_template Jinja string from tokenizer_config.json if available."""
    tok_file = merge_dir / "tokenizer_config.json"
    if tok_file.exists():
        try:
            data = json.loads(tok_file.read_text(encoding="utf-8"))
            if "chat_template" in data and isinstance(data["chat_template"], str):
                return data["chat_template"]
        except Exception:
            pass

    # Check parent models if config.yaml exists
    cfg_file = merge_dir / "config.yaml"
    if cfg_file.exists():
        try:
            import yaml  # type: ignore[import-untyped]

            cfg_data = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
            base_model = cfg_data.get("base_model")
            if base_model:
                from huggingface_hub import hf_hub_download

                tok_path = hf_hub_download(repo_id=base_model, filename="tokenizer_config.json")
                tok_data = json.loads(Path(tok_path).read_text(encoding="utf-8"))
                if "chat_template" in tok_data and isinstance(tok_data["chat_template"], str):
                    return tok_data["chat_template"]
        except Exception:
            pass

    return DEFAULT_CHAT_TEMPLATE


def generate_modelfile(
    gguf_path: Path,
    chat_template: str,
    output_modelfile: Path,
) -> Path:
    """Generate an Ollama Modelfile pointing to the GGUF binary with correct chat template."""
    content = f'''FROM ./{gguf_path.name}

TEMPLATE """{chat_template}"""

PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
'''
    output_modelfile.write_text(content, encoding="utf-8")
    return output_modelfile


def create_ollama_model(
    model_name: str,
    modelfile_path: Path,
    out_console: Console | None = None,
) -> bool:
    """Execute `ollama create <name> -f Modelfile`."""
    out = out_console or console

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        out.print(
            "[yellow]Warning:[/yellow] 'ollama' executable not found in PATH. "
            f"To load the model manually, run:\n"
            f"  cd {modelfile_path.parent} && ollama create {model_name} -f {modelfile_path.name}"
        )
        return False

    out.print(f"[bold green]Creating Ollama model:[/bold green] {model_name}...")
    try:
        proc = subprocess.run(
            [ollama_bin, "create", model_name, "-f", modelfile_path.name],
            cwd=str(modelfile_path.parent),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            out.print(
                f"[yellow]Ollama create failed:[/yellow] {err_msg}\n"
                "Ensure the Ollama daemon is running with 'ollama serve'."
            )
            return False

        out.print(f"[bold green]✓ Successfully created Ollama model:[/bold green] {model_name}")
        return True
    except Exception as exc:
        out.print(f"[yellow]Failed to run ollama create:[/yellow] {exc}")
        return False


def probe_ollama_model_sync(
    model_name: str,
    out_console: Console | None = None,
) -> None:
    """Run `lathe models probe <model_name>` synchronously on the newly created model."""
    out = out_console or console
    try:
        from lathe.models.probe import probe_model

        out.print(f"[bold cyan]Probing capabilities for:[/bold cyan] {model_name}...")
        asyncio.run(probe_model(model=model_name, console=out))
    except Exception as exc:
        out.print(
            f"[dim]Automatic probe skipped or failed ({exc}). "
            f"Run 'lathe models probe {model_name}' manually.[/dim]"
        )


def convert_and_deploy_gguf(
    name: str,
    quant: str = "Q4_K_M",
    base_dir: Path | str | None = None,
    auto_probe: bool = True,
    out_console: Console | None = None,
) -> Path:
    """Complete pipeline: HF safetensors -> FP16 GGUF -> Quantized GGUF -> Ollama -> probe."""
    out = out_console or console
    root = Path(base_dir) if base_dir else Path.cwd()
    merge_dir = root / "merges" / name

    if not merge_dir.exists() or not merge_dir.is_dir():
        raise FileNotFoundError(f"Merge directory not found at '{merge_dir}'.")

    # 1. Ensure llama.cpp
    llama_cpp_dir = ensure_llama_cpp(out_console=out)

    # 2. Convert to FP16 GGUF
    f16_gguf = merge_dir / f"{name}.f16.gguf"
    convert_to_fp16_gguf(merge_dir, f16_gguf, llama_cpp_dir, out_console=out)

    # 3. Quantize
    quantize_bin = find_or_build_quantize_binary(llama_cpp_dir, out_console=out)
    quant_gguf = merge_dir / f"{name}.{quant}.gguf"
    if quantize_bin:
        quantize_gguf(f16_gguf, quant_gguf, quant=quant, quantize_bin=quantize_bin, out_console=out)
        # Optional: remove heavy f16 file to conserve disk space if quant succeeded
        target_gguf = quant_gguf
    else:
        out.print(
            f"[yellow]Could not find or compile llama-quantize.[/yellow] "
            f"Using unquantized FP16 GGUF: {f16_gguf.name}"
        )
        target_gguf = f16_gguf

    # 4. Generate Modelfile
    chat_template = extract_chat_template(merge_dir)
    modelfile_path = merge_dir / "Modelfile"
    generate_modelfile(target_gguf, chat_template, modelfile_path)
    out.print(f"[bold green]✓ Generated Ollama Modelfile:[/bold green] {modelfile_path}")

    # 5. Create in Ollama
    ollama_model_name = f"lathe-{name}"
    created = create_ollama_model(ollama_model_name, modelfile_path, out_console=out)

    # 6. Automatically probe capabilities
    if created and auto_probe:
        probe_ollama_model_sync(ollama_model_name, out_console=out)

    return target_gguf

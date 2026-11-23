"""Unit tests for GGUF conversion, quantization, and Ollama deployment."""

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from lathe.cli import app
from lathe.merge.gguf import (
    DEFAULT_CHAT_TEMPLATE,
    convert_and_deploy_gguf,
    create_ollama_model,
    ensure_llama_cpp,
    extract_chat_template,
    find_or_build_quantize_binary,
    generate_modelfile,
)

runner = CliRunner()


def test_ensure_llama_cpp_existing(tmp_path: Path):
    """When llama.cpp directory already contains conversion script, reuse it."""
    fake_llama = tmp_path / "llama.cpp"
    fake_llama.mkdir(parents=True)
    (fake_llama / "convert_hf_to_gguf.py").write_text("# fake script", encoding="utf-8")

    res = ensure_llama_cpp(cache_dir=fake_llama)
    assert res == fake_llama


def test_extract_chat_template_from_json(tmp_path: Path):
    """Extract chat_template string from local tokenizer_config.json."""
    tok_file = tmp_path / "tokenizer_config.json"
    tok_file.write_text(
        '{"chat_template": "{% for m in messages %}{{ m.content }}{% endfor %}"}', encoding="utf-8"
    )

    template = extract_chat_template(tmp_path)
    assert "{{ m.content }}" in template


def test_extract_chat_template_fallback(tmp_path: Path):
    """Fallback to ChatML template when no tokenizer_config exists."""
    template = extract_chat_template(tmp_path)
    assert "<|im_start|>" in template
    assert template == DEFAULT_CHAT_TEMPLATE


def test_generate_modelfile(tmp_path: Path):
    """Generate Ollama Modelfile with correct parameters and template."""
    gguf_file = tmp_path / "model.Q4_K_M.gguf"
    gguf_file.touch()
    modelfile_path = tmp_path / "Modelfile"

    res = generate_modelfile(gguf_file, "{{ .Prompt }}", modelfile_path)
    assert res == modelfile_path
    content = modelfile_path.read_text(encoding="utf-8")
    assert "FROM ./model.Q4_K_M.gguf" in content
    assert 'TEMPLATE """{{ .Prompt }}"""' in content
    assert 'PARAMETER stop "<|im_start|>"' in content
    assert 'PARAMETER stop "<|im_end|>"' in content


def test_find_or_build_quantize_binary_path(monkeypatch):
    """Find binary from PATH."""
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/usr/local/bin/llama-quantize" if "quantize" in cmd else None
    )
    bin_path = find_or_build_quantize_binary(Path("/tmp/nonexistent"))
    assert bin_path == Path("/usr/local/bin/llama-quantize")


def test_create_ollama_model_missing_binary(tmp_path: Path, monkeypatch):
    """Graceful warning when ollama binary is not installed."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    res = create_ollama_model("lathe-test", tmp_path / "Modelfile")
    assert res is False


def test_create_ollama_model_success(tmp_path: Path, monkeypatch):
    """Successful execution of ollama create."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/ollama")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_proc)

    modelfile = tmp_path / "Modelfile"
    modelfile.touch()
    res = create_ollama_model("lathe-test", modelfile)
    assert res is True


def test_convert_and_deploy_gguf_full(tmp_path: Path, monkeypatch):
    """End-to-end GGUF conversion and deployment pipeline."""
    merge_dir = tmp_path / "merges" / "test-model"
    merge_dir.mkdir(parents=True)
    (merge_dir / "config.yaml").write_text("merge_method: slerp", encoding="utf-8")

    # Mock conversion steps
    monkeypatch.setattr("lathe.merge.gguf.ensure_llama_cpp", lambda **_: tmp_path / "llama")
    monkeypatch.setattr(
        "lathe.merge.gguf.convert_to_fp16_gguf", lambda md, out, ld, **_: out.touch()
    )
    monkeypatch.setattr(
        "lathe.merge.gguf.find_or_build_quantize_binary",
        lambda ld, **_: Path("/usr/bin/llama-quantize"),
    )
    monkeypatch.setattr("lathe.merge.gguf.quantize_gguf", lambda f16, out, **_: out.touch())
    monkeypatch.setattr("lathe.merge.gguf.create_ollama_model", lambda name, mf, **_: True)
    monkeypatch.setattr("lathe.merge.gguf.probe_ollama_model_sync", lambda name, **_: None)

    out_file = convert_and_deploy_gguf("test-model", quant="Q4_K_M", base_dir=tmp_path)
    assert out_file.name == "test-model.Q4_K_M.gguf"
    assert (merge_dir / "Modelfile").exists()


def test_merge_gguf_cli_command(tmp_path: Path, monkeypatch):
    """CLI subcommand lathe merge gguf <name> invocation."""
    monkeypatch.chdir(tmp_path)
    mock_convert = MagicMock(return_value=tmp_path / "out.gguf")
    monkeypatch.setattr("lathe.merge.gguf.convert_and_deploy_gguf", mock_convert)

    result = runner.invoke(app, ["merge", "gguf", "test-model", "--quant", "Q5_K_M", "--no-probe"])
    assert result.exit_code == 0
    assert mock_convert.call_count == 1
    assert mock_convert.call_args[1].get("name") == "test-model"
    assert mock_convert.call_args[1].get("quant") == "Q5_K_M"
    assert mock_convert.call_args[1].get("auto_probe") is False

"""Unit tests for Google Colab notebook (.ipynb) generation."""

import json
from pathlib import Path

from lathe.merge.colab import generate_colab_notebook


def test_generate_colab_notebook(tmp_path: Path):
    """Generate Colab notebook and verify cell structures and commands."""
    config_yaml = "merge_method: slerp\nbase_model: ModelA\n"
    nb_path = generate_colab_notebook(
        "test-model", config_yaml, output_path=tmp_path / "colab.ipynb"
    )

    assert nb_path.exists()
    content = nb_path.read_text(encoding="utf-8")
    data = json.loads(content)

    assert data["nbformat"] == 4
    cells = data["cells"]
    assert len(cells) >= 5

    # Check cell contents
    all_source = "\n".join("".join(c["source"]) for c in cells)

    # 1. Install mergekit
    assert "!pip install -q mergekit huggingface_hub" in all_source
    # 2. Login
    assert "login()" in all_source
    # 3. Config writing
    assert "merge_method: slerp" in all_source
    # 4. Low-memory merge command
    assert "--lazy-unpickle" in all_source
    assert "--allow-crimes" in all_source
    assert "--low-cpu-memory" in all_source
    assert "--copy-tokenizer" in all_source
    # 5. HF Upload
    assert "upload_folder" in all_source

"""Unit tests for mergekit YAML generation (SLERP, TIES, DARE-TIES, Linear)."""

from pathlib import Path

import yaml

from lathe.merge.generator import (
    generate_linear_yaml,
    generate_merge_yaml,
    generate_slerp_yaml,
    generate_ties_yaml,
    write_merge_config,
)
from lathe.merge.models import START_SMALL_PRESET, MergeMethod


def test_generate_slerp_yaml_basic():
    """SLERP YAML generation with scalar t parameter."""
    yaml_str = generate_slerp_yaml(
        model_a="ModelA",
        model_b="ModelB",
        t=0.5,
        num_layers=28,
        base_model="ModelA",
    )
    data = yaml.safe_load(yaml_str)
    assert data["merge_method"] == "slerp"
    assert data["base_model"] == "ModelA"
    assert data["dtype"] == "float16"
    assert data["parameters"]["t"] == 0.5
    assert len(data["slices"]) == 1
    assert data["slices"][0]["sources"][0]["model"] == "ModelA"
    assert data["slices"][0]["sources"][1]["model"] == "ModelB"
    assert data["slices"][0]["sources"][0]["layer_range"] == [0, 28]


def test_generate_slerp_yaml_with_layer_gradients():
    """SLERP YAML generation with self_attn vs mlp gradients."""
    yaml_str = generate_slerp_yaml(
        model_a="ModelA",
        model_b="ModelB",
        t=0.5,
        num_layers=32,
        self_attn_t=[0.0, 0.5, 0.7, 1.0],
        mlp_t=[1.0, 0.5, 0.3, 0.0],
    )
    data = yaml.safe_load(yaml_str)
    assert data["merge_method"] == "slerp"
    params = data["parameters"]["t"]
    assert isinstance(params, list)
    assert any(p.get("filter") == "self_attn" for p in params)
    assert any(p.get("filter") == "mlp" for p in params)


def test_generate_ties_yaml():
    """TIES and DARE-TIES YAML generation."""
    models = [
        {"model": "ModelA", "density": 0.5, "weight": 0.6},
        {"model": "ModelB", "density": 0.5, "weight": 0.4},
    ]
    # Standard TIES
    ties_yaml = generate_ties_yaml(base_model="BaseModel", models=models, dare=False)
    ties_data = yaml.safe_load(ties_yaml)
    assert ties_data["merge_method"] == "ties"
    assert ties_data["base_model"] == "BaseModel"
    assert len(ties_data["models"]) == 3
    assert ties_data["models"][0]["model"] == "BaseModel"
    assert ties_data["models"][1]["parameters"]["density"] == 0.5

    # DARE-TIES
    dare_yaml = generate_ties_yaml(base_model="BaseModel", models=models, dare=True)
    dare_data = yaml.safe_load(dare_yaml)
    assert dare_data["merge_method"] == "dare_ties"


def test_generate_linear_yaml():
    """Linear weighted average YAML generation."""
    models = [
        {"model": "ModelA", "weight": 0.7},
        {"model": "ModelB", "weight": 0.3},
    ]
    linear_yaml = generate_linear_yaml(models)
    data = yaml.safe_load(linear_yaml)
    assert data["merge_method"] == "linear"
    assert len(data["models"]) == 2
    assert data["models"][0]["parameters"]["weight"] == 0.7
    assert data["models"][1]["parameters"]["weight"] == 0.3


def test_generate_merge_yaml_dispatcher():
    """High-level dispatcher supports all method strings."""
    slerp = generate_merge_yaml(
        MergeMethod.SLERP,
        "ModelA",
        "ModelB",
        parameters={"t": 0.6},
    )
    assert "merge_method: slerp" in slerp

    ties = generate_merge_yaml(
        MergeMethod.TIES,
        "ModelA",
        "ModelB",
        base_model="BaseModel",
        parameters={"density": 0.4, "weight": 0.6},
    )
    assert "merge_method: ties" in ties

    linear = generate_merge_yaml(
        "linear",
        "ModelA",
        "ModelB",
        parameters={"weight_a": 0.5, "weight_b": 0.5},
    )
    assert "merge_method: linear" in linear


def test_write_merge_config(tmp_path: Path):
    """Write configuration YAML to target directory."""
    yaml_str = generate_slerp_yaml("ModelA", "ModelB")
    config_file = write_merge_config("test-merge", yaml_str, base_dir=tmp_path)

    assert config_file.exists()
    assert config_file.name == "config.yaml"
    assert config_file.parent.name == "test-merge"
    assert "merge_method: slerp" in config_file.read_text(encoding="utf-8")


def test_start_small_preset():
    """Start-small preset points to two Qwen2.5 1.5B models."""
    assert START_SMALL_PRESET.name == "qwen2.5-1.5b-coder-instruct"
    assert "Coder-1.5B" in START_SMALL_PRESET.model_a
    assert "1.5B-Instruct" in START_SMALL_PRESET.model_b
    assert START_SMALL_PRESET.method == MergeMethod.SLERP

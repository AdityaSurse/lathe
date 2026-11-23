"""Mergekit YAML configuration generation for SLERP, TIES, DARE-TIES, and Linear."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from lathe.merge.models import MergeMethod


def generate_slerp_yaml(
    model_a: str,
    model_b: str,
    t: float = 0.5,
    num_layers: int = 28,
    base_model: str | None = None,
    self_attn_t: float | list[float] | None = None,
    mlp_t: float | list[float] | None = None,
    dtype: str = "float16",
) -> str:
    """Generate a mergekit YAML configuration for spherical linear interpolation (SLERP)."""
    base = base_model or model_a

    parameters: dict[str, Any] = {}
    if self_attn_t is not None or mlp_t is not None:
        param_list: list[dict[str, Any]] = []
        if self_attn_t is not None:
            param_list.append({"filter": "self_attn", "value": self_attn_t})
        if mlp_t is not None:
            param_list.append({"filter": "mlp", "value": mlp_t})
        param_list.append({"value": t})
        parameters["t"] = param_list
    else:
        parameters["t"] = t

    config_dict = {
        "slices": [
            {
                "sources": [
                    {"model": model_a, "layer_range": [0, num_layers]},
                    {"model": model_b, "layer_range": [0, num_layers]},
                ]
            }
        ],
        "merge_method": "slerp",
        "base_model": base,
        "parameters": parameters,
        "dtype": dtype,
    }

    return str(yaml.dump(config_dict, sort_keys=False, default_flow_style=None))


def generate_ties_yaml(
    base_model: str,
    models: list[dict[str, Any]],
    dare: bool = False,
    normalize: bool = True,
    dtype: str = "float16",
) -> str:
    """Generate a mergekit YAML configuration for TIES or DARE-TIES."""
    model_entries: list[dict[str, Any]] = [{"model": base_model}]
    for m in models:
        entry: dict[str, Any] = {"model": m["model"]}
        params: dict[str, Any] = {}
        if "density" in m:
            params["density"] = float(m["density"])
        if "weight" in m:
            params["weight"] = float(m["weight"])
        if params:
            entry["parameters"] = params
        model_entries.append(entry)

    method_name = "dare_ties" if dare else "ties"
    config_dict = {
        "models": model_entries,
        "merge_method": method_name,
        "base_model": base_model,
        "parameters": {"normalize": normalize},
        "dtype": dtype,
    }

    return str(yaml.dump(config_dict, sort_keys=False, default_flow_style=None))


def generate_linear_yaml(
    models: list[dict[str, Any]],
    normalize: bool = True,
    dtype: str = "float16",
) -> str:
    """Generate a mergekit YAML configuration for Linear model averaging."""
    model_entries: list[dict[str, Any]] = []
    for m in models:
        entry: dict[str, Any] = {"model": m["model"]}
        if "weight" in m:
            entry["parameters"] = {"weight": float(m["weight"])}
        model_entries.append(entry)

    config_dict = {
        "models": model_entries,
        "merge_method": "linear",
        "parameters": {"normalize": normalize},
        "dtype": dtype,
    }

    return str(yaml.dump(config_dict, sort_keys=False, default_flow_style=None))


def generate_merge_yaml(
    method: MergeMethod | str,
    model_a: str,
    model_b: str,
    base_model: str | None = None,
    num_layers: int = 28,
    parameters: dict[str, Any] | None = None,
    dtype: str = "float16",
) -> str:
    """High-level dispatcher generating mergekit YAML based on method and options."""
    params = parameters or {}
    method_str = method.value if isinstance(method, MergeMethod) else str(method).lower()

    if method_str == MergeMethod.SLERP.value:
        t_val = float(params.get("t", 0.5))
        self_attn_t = params.get("self_attn_t")
        mlp_t = params.get("mlp_t")
        return generate_slerp_yaml(
            model_a=model_a,
            model_b=model_b,
            t=t_val,
            num_layers=num_layers,
            base_model=base_model,
            self_attn_t=self_attn_t,
            mlp_t=mlp_t,
            dtype=dtype,
        )

    if method_str in (MergeMethod.TIES.value, MergeMethod.DARE_TIES.value):
        base = base_model or model_a
        density_a = float(params.get("density_a", params.get("density", 0.5)))
        weight_a = float(params.get("weight_a", params.get("weight", 0.5)))
        density_b = float(params.get("density_b", params.get("density", 0.5)))
        weight_b = float(params.get("weight_b", params.get("weight", 0.5)))
        models = [
            {"model": model_a, "density": density_a, "weight": weight_a},
            {"model": model_b, "density": density_b, "weight": weight_b},
        ]
        is_dare = method_str == MergeMethod.DARE_TIES.value
        return generate_ties_yaml(base_model=base, models=models, dare=is_dare, dtype=dtype)

    if method_str == MergeMethod.LINEAR.value:
        weight_a = float(params.get("weight_a", 0.5))
        weight_b = float(params.get("weight_b", 0.5))
        models = [
            {"model": model_a, "weight": weight_a},
            {"model": model_b, "weight": weight_b},
        ]
        return generate_linear_yaml(models=models, dtype=dtype)

    raise ValueError(f"Unsupported merge method: '{method_str}'")


def write_merge_config(
    name: str,
    yaml_content: str,
    base_dir: Path | str | None = None,
) -> Path:
    """Save generated YAML configuration to merges/<name>/config.yaml."""
    root = Path(base_dir) if base_dir else Path.cwd()
    target_dir = root / "merges" / name
    target_dir.mkdir(parents=True, exist_ok=True)
    config_file = target_dir / "config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")
    return config_file

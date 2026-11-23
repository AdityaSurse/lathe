"""Data structures and types for model merging with mergekit."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class MergeMethod(StrEnum):
    """Supported model merging methods."""

    SLERP = "slerp"
    TIES = "ties"
    DARE_TIES = "dare_ties"
    LINEAR = "linear"


@dataclass
class ModelArchitectureInfo:
    """Extracted architectural configuration and metadata for a model."""

    repo_id: str
    model_type: str
    hidden_size: int
    num_hidden_layers: int
    vocab_size: int
    intermediate_size: int | None = None
    num_attention_heads: int | None = None
    num_key_value_heads: int | None = None
    tokenizer_class: str | None = None
    raw_config: dict[str, Any] = field(default_factory=dict)
    raw_tokenizer_config: dict[str, Any] = field(default_factory=dict)
    estimated_params: int = 0


@dataclass
class ArchitectureDifference:
    """Comparison of a single architectural parameter between two models."""

    attribute: str
    model_a_value: Any
    model_b_value: Any
    is_matching: bool


@dataclass
class CompatibilityResult:
    """Result of checking whether two models can be merged."""

    is_compatible: bool
    differences: list[ArchitectureDifference]
    model_a_info: ModelArchitectureInfo
    model_b_info: ModelArchitectureInfo
    reasons: list[str] = field(default_factory=list)


@dataclass
class ResourceEstimate:
    """Hardware resource estimation (RAM, disk) for merging."""

    params_per_model: int
    fp16_bytes_per_model: int
    total_fp16_bytes: int
    estimated_merged_bytes: int
    required_ram_bytes: int
    required_disk_bytes: int
    free_ram_bytes: int | None
    free_disk_bytes: int
    is_ram_sufficient: bool
    is_disk_sufficient: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class MergePreset:
    """Pre-configured start-small or tested merge pair."""

    name: str
    description: str
    model_a: str
    model_b: str
    base_model: str | None
    method: MergeMethod
    default_parameters: dict[str, Any] = field(default_factory=dict)


START_SMALL_PRESET = MergePreset(
    name="qwen2.5-1.5b-coder-instruct",
    description="Qwen2.5 1.5B Coder + Instruct (Start Small - fits on laptop)",
    model_a="Qwen/Qwen2.5-Coder-1.5B",
    model_b="Qwen/Qwen2.5-1.5B-Instruct",
    base_model="Qwen/Qwen2.5-Coder-1.5B",
    method=MergeMethod.SLERP,
    default_parameters={"t": 0.5},
)


@dataclass
class MergeConfig:
    """Legacy or high-level merge configuration specification."""

    base_model: str
    second_model: str
    method: str = "slerp"
    target_quant: str = "Q4_K_M"
    name: str | None = None
    output_dir: Path | None = None

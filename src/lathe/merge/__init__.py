"""Model merging package automating mergekit configurations, quantization, and GGUF conversion."""

from dataclasses import dataclass


@dataclass
class MergeConfig:
    """Defines parameters for SLERP or TIES weight interpolation."""

    base_model: str
    second_model: str
    method: str = "slerp"
    target_quant: str = "Q4_K_M"

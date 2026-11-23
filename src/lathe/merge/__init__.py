"""Model merging package automating mergekit configurations, quantization, and GGUF conversion."""

from lathe.merge.colab import generate_colab_notebook
from lathe.merge.compatibility import (
    check_compatibility,
    estimate_transformer_parameters,
    fetch_model_info,
    parse_model_info_from_configs,
    render_compatibility_table,
)
from lathe.merge.generator import (
    generate_linear_yaml,
    generate_merge_yaml,
    generate_slerp_yaml,
    generate_ties_yaml,
    write_merge_config,
)
from lathe.merge.gguf import (
    convert_and_deploy_gguf,
    create_ollama_model,
    ensure_llama_cpp,
    extract_chat_template,
    generate_modelfile,
)
from lathe.merge.hub import push_to_hub
from lathe.merge.models import (
    START_SMALL_PRESET,
    ArchitectureDifference,
    CompatibilityResult,
    MergeConfig,
    MergeMethod,
    MergePreset,
    ModelArchitectureInfo,
    ResourceEstimate,
)
from lathe.merge.resources import (
    estimate_merge_resources,
    format_bytes,
    format_params,
    render_resource_table,
)
from lathe.merge.runner import (
    generate_model_card,
    is_mergekit_installed,
    run_mergekit,
    write_model_card,
)
from lathe.merge.wizard import run_merge_wizard

__all__ = [
    "START_SMALL_PRESET",
    "ArchitectureDifference",
    "CompatibilityResult",
    "MergeConfig",
    "MergeMethod",
    "MergePreset",
    "ModelArchitectureInfo",
    "ResourceEstimate",
    "check_compatibility",
    "convert_and_deploy_gguf",
    "create_ollama_model",
    "ensure_llama_cpp",
    "estimate_merge_resources",
    "estimate_transformer_parameters",
    "extract_chat_template",
    "fetch_model_info",
    "format_bytes",
    "format_params",
    "generate_colab_notebook",
    "generate_linear_yaml",
    "generate_merge_yaml",
    "generate_model_card",
    "generate_modelfile",
    "generate_slerp_yaml",
    "generate_ties_yaml",
    "is_mergekit_installed",
    "parse_model_info_from_configs",
    "push_to_hub",
    "render_compatibility_table",
    "render_resource_table",
    "run_mergekit",
    "run_merge_wizard",
    "write_merge_config",
    "write_model_card",
]

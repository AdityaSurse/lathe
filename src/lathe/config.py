"""Configuration management for Lathe.

Handles two-level TOML configuration (global ~/.config/lathe/lathe.toml and project ./lathe.toml),
Pydantic validation, secret isolation (from environment / .env only), and CLI helpers.
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

# Load environment variables from .env
load_dotenv()

BackendType = Literal["ollama", "hf", "openai_compat"]

FORBIDDEN_SECRET_KEYS = {
    "hf_token",
    "token",
    "api_token",
    "api_key",
    "apikey",
    "secret",
    "secret_key",
    "password",
    "huggingface_hub_token",
    "auth_token",
}


class ConfigError(Exception):
    """Exception raised for configuration loading and validation errors."""

    def __init__(self, file: str, key: str, message: str) -> None:
        self.file = file
        self.key = key
        self.message = message
        super().__init__(f"[Config Error in {file}] '{key}': {message}")


class RoleConfig(BaseModel):
    """Configuration for an individual model role (planner, coder, reviewer, router)."""

    backend: BackendType
    model: str
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    context_window: int = Field(default=32768, gt=0)
    base_url: str | None = None
    provider: str = "auto"
    supports_tools: bool = True


class RolesConfig(BaseModel):
    """Collection of LLM roles configured for Lathe orchestration."""

    planner: RoleConfig = Field(
        default_factory=lambda: RoleConfig(
            backend="hf",
            model="deepseek-ai/DeepSeek-R1",  # Placeholder for high-parameter reasoning model
            temperature=0.6,
            max_tokens=8192,
            context_window=65536,
        )
    )
    coder: RoleConfig = Field(
        default_factory=lambda: RoleConfig(
            backend="ollama",
            model="hf.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
            temperature=0.2,
            max_tokens=4096,
            context_window=32768,
        )
    )
    reviewer: RoleConfig | None = None
    router: RoleConfig = Field(
        default_factory=lambda: RoleConfig(
            backend="ollama",
            model="hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M",
            temperature=0.0,
            max_tokens=1024,
            context_window=8192,
        )
    )

    def get_reviewer(self) -> RoleConfig:
        """Return the active reviewer model, defaulting to the planner if omitted."""
        return self.reviewer if self.reviewer is not None else self.planner


class SettingsConfig(BaseModel):
    """General runtime and execution settings for Lathe."""

    mode: Literal["single", "dual"] = "dual"
    max_agent_steps: int = Field(default=25, gt=0)
    auto_approve_reads: bool = True
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "rm -rf ~",
            "git reset --hard",
            "mkfs",
            "dd if=",
        ]
    )
    theme: str = "lathe-dark"


class LatheConfig(BaseModel):
    """Root configuration object merging settings and multi-model roles."""

    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    roles: RolesConfig = Field(default_factory=RolesConfig)

    def get_reviewer(self) -> RoleConfig:
        """Shortcut to get the reviewer configuration."""
        return self.roles.get_reviewer()


def get_global_config_path() -> Path:
    """Return default global configuration path: ~/.config/lathe/lathe.toml."""
    return Path.home() / ".config" / "lathe" / "lathe.toml"


def get_project_config_path(project_dir: Path | str | None = None) -> Path:
    """Return project configuration path: ./lathe.toml."""
    base = Path(project_dir) if project_dir is not None else Path.cwd()
    return base / "lathe.toml"


def get_hf_token() -> str | None:
    """Retrieve Hugging Face token from environment variables or .env."""
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def check_for_secrets(data: dict[str, Any], file_path: Path, prefix: str = "") -> None:
    """Recursively ensure no secrets are stored inside TOML configuration files."""
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        low_key = key.lower()
        is_secret = (
            low_key in FORBIDDEN_SECRET_KEYS
            or low_key.endswith("_token")
            or low_key.endswith("_secret")
            or low_key.endswith("_key")
        ) and low_key not in ("max_tokens", "context_window")

        if is_secret:
            raise ConfigError(
                file=str(file_path),
                key=full_key,
                message=(
                    f"Secret '{key}' found in TOML configuration file. "
                    "Secrets must be loaded from environment variables (HF_TOKEN) or .env, "
                    "never stored in lathe.toml."
                ),
            )
        if isinstance(value, dict):
            check_for_secrets(value, file_path, full_key)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override dictionary into base dictionary."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def validate_required_secrets(config: LatheConfig, source_hint: str = "environment") -> None:
    """Validate that required API tokens exist in environment for configured cloud backends."""
    roles_requiring_hf: list[str] = []
    if config.roles.planner.backend == "hf":
        roles_requiring_hf.append("roles.planner")
    if config.roles.coder.backend == "hf":
        roles_requiring_hf.append("roles.coder")
    if config.roles.reviewer is not None and config.roles.reviewer.backend == "hf":
        roles_requiring_hf.append("roles.reviewer")
    if config.roles.router.backend == "hf":
        roles_requiring_hf.append("roles.router")

    if roles_requiring_hf and not get_hf_token():
        roles_str = ", ".join(roles_requiring_hf)
        first_role = roles_requiring_hf[0]
        raise ConfigError(
            file=source_hint,
            key=f"{first_role}.backend",
            message=(
                f"Role(s) {roles_str} configured with backend='hf', but HF_TOKEN is not set. "
                "Provide HF_TOKEN in your environment or .env file."
            ),
        )


def _format_pydantic_error(e: ValidationError, file_name: str) -> ConfigError:
    """Transform Pydantic ValidationError into a user-friendly ConfigError."""
    first = e.errors()[0]
    loc_parts = [str(x) for x in first.get("loc", ())]
    key = ".".join(loc_parts)
    msg = first.get("msg", "Invalid value")

    # Clean up enum/literal errors
    if "Input should be 'ollama', 'hf' or 'openai_compat'" in msg:
        input_val = first.get("input")
        msg = f"Invalid backend '{input_val}'. Must be one of: 'ollama', 'hf', 'openai_compat'"

    return ConfigError(file=file_name, key=key, message=msg)


def load_config(
    project_dir: Path | str | None = None,
    global_path: Path | str | None = None,
    require_secrets: bool = True,
) -> LatheConfig:
    """Load two-level configuration with project overriding global.

    Args:
        project_dir: Working directory to locate ./lathe.toml (defaults to cwd).
        global_path: Explicit global path (defaults to ~/.config/lathe/lathe.toml).
        require_secrets: If True, checks that HF_TOKEN is present when HF backend is used.

    Returns:
        Validated LatheConfig instance.
    """
    g_path = Path(global_path) if global_path is not None else get_global_config_path()
    p_path = get_project_config_path(project_dir)

    # Base default configuration
    merged_data = LatheConfig().model_dump()
    source_file = "defaults"

    # 1. Global config (~/.config/lathe/lathe.toml)
    if g_path.is_file():
        source_file = str(g_path)
        try:
            with open(g_path, "rb") as f:
                g_data = tomllib.load(f)
            check_for_secrets(g_data, g_path)
            merged_data = deep_merge(merged_data, g_data)
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(file=str(g_path), key="syntax", message=f"Malformed TOML: {e}") from e

    # 2. Project config (./lathe.toml) - overrides global
    if p_path.is_file():
        source_file = str(p_path)
        try:
            with open(p_path, "rb") as f:
                p_data = tomllib.load(f)
            check_for_secrets(p_data, p_path)
            merged_data = deep_merge(merged_data, p_data)
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(file=str(p_path), key="syntax", message=f"Malformed TOML: {e}") from e

    # 3. Validate merged schema with Pydantic
    try:
        config = LatheConfig.model_validate(merged_data)
    except ValidationError as e:
        raise _format_pydantic_error(e, source_file) from e

    # 4. Check secrets if requested
    if require_secrets:
        validate_required_secrets(config, source_file)

    return config


COMMENTED_TOML_TEMPLATE = """# Lathe Configuration File
# Project-level config (overrides ~/.config/lathe/lathe.toml)
# Note: Secrets (HF_TOKEN) must NEVER be placed in this file; use environment variables or .env.

[settings]
mode = "dual"                  # "single" (coder only) or "dual" (planner + coder)
max_agent_steps = 10           # Max execution steps per task
auto_approve_reads = true      # Auto-allow non-mutating file reads and ast queries
theme = "lathe-dark"           # Rich terminal color theme
blocked_commands = [
    "rm -rf /",
    "rm -rf ~",
    "git reset --hard",
    "mkfs",
    "dd if="
]

[roles.planner]
backend = "hf"                 # "ollama" | "hf" | "openai_compat"
model = "deepseek-ai/DeepSeek-R1" # Reasoning model for planning and review
temperature = 0.6
max_tokens = 8192
context_window = 65536

[roles.coder]
backend = "ollama"
model = "hf.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M"
temperature = 0.2
max_tokens = 4096
context_window = 32768

# [roles.reviewer]
# Optional: if omitted, reviewer inherits planner configuration
# backend = "hf"
# model = "deepseek-ai/DeepSeek-R1"
# temperature = 0.2
# max_tokens = 4096
# context_window = 32768

[roles.router]
backend = "ollama"
model = "hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M"
temperature = 0.0
max_tokens = 1024
context_window = 8192
"""


def _serialize_toml_value(val: Any) -> str:
    """Format primitive Python values to TOML literal syntax."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, list):
        items = ", ".join(_serialize_toml_value(item) for item in val)
        return f"[{items}]"
    if val is None:
        return '""'
    return f'"{val}"'


def dump_toml(data: dict[str, Any]) -> str:
    """Serialize a dictionary to a standard TOML string."""
    lines: list[str] = []

    # 1. Top-level simple settings
    settings = data.get("settings", {})
    if settings:
        lines.append("[settings]")
        for k, v in settings.items():
            lines.append(f"{k} = {_serialize_toml_value(v)}")
        lines.append("")

    # 2. Roles
    roles = data.get("roles", {})
    for role_name in ["planner", "coder", "reviewer", "router"]:
        role_data = roles.get(role_name)
        if role_data is not None and isinstance(role_data, dict):
            lines.append(f"[roles.{role_name}]")
            for k, v in role_data.items():
                if v is not None:
                    lines.append(f"{k} = {_serialize_toml_value(v)}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def _coerce_value(raw: str) -> Any:
    """Attempt smart coercion of CLI string inputs into types (bool, int, float, str)."""
    low = raw.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def set_config_value(key_path: str, raw_value: str, target_file: Path) -> LatheConfig:
    """Set a dot-delimited configuration key in target TOML file and validate.

    Args:
        key_path: Key in dot notation, e.g. "roles.coder.model" or "settings.max_agent_steps".
        raw_value: String value provided from CLI.
        target_file: Path to lathe.toml to modify.

    Returns:
        Updated LatheConfig.
    """
    # Load existing raw dict or start fresh
    current_data: dict[str, Any] = {}
    if target_file.is_file():
        try:
            with open(target_file, "rb") as f:
                current_data = tomllib.load(f)
        except Exception as e:
            raise ConfigError(
                file=str(target_file), key="syntax", message=f"Malformed TOML: {e}"
            ) from e

    parts = key_path.split(".")
    if not parts or any(not p for p in parts):
        raise ConfigError(file=str(target_file), key=key_path, message="Invalid empty key segment.")

    # Check for forbidden secrets
    if any(p.lower() in FORBIDDEN_SECRET_KEYS for p in parts):
        raise ConfigError(
            file=str(target_file),
            key=key_path,
            message=(
                "Cannot set secrets in lathe.toml. Use environment variables (HF_TOKEN) or .env."
            ),
        )

    # Traverse & update nested dict
    curr = current_data
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]

    coerced = _coerce_value(raw_value)
    curr[parts[-1]] = coerced

    # Validate merged configuration with defaults
    merged = deep_merge(LatheConfig().model_dump(), current_data)
    try:
        validated_config = LatheConfig.model_validate(merged)
    except ValidationError as e:
        raise _format_pydantic_error(e, str(target_file)) from e

    # Write validated TOML back to file
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(dump_toml(current_data), encoding="utf-8")

    return validated_config

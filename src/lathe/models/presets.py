"""Model presets for local Ollama runtimes (Qwen, Gemma, Mixed).

Provides preconfigured roles (planner, coder, reviewer, router) tuned for
accuracy, speed, and RAM efficiency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lathe.config import RoleConfig
from lathe.llm.types import Message


@dataclass(frozen=True)
class ModelPreset:
    """Preconfigured multi-model team for planner, coder, reviewer, and router roles."""

    name: str
    display_name: str
    description: str
    planner: RoleConfig
    coder: RoleConfig
    reviewer: RoleConfig
    router: RoleConfig

    def get_unique_models(self) -> list[str]:
        """Return list of distinct model identifiers needed by this preset."""
        seen: list[str] = []
        for r in (self.planner, self.coder, self.reviewer, self.router):
            if r.model not in seen:
                seen.append(r.model)
        return seen

    def to_toml_dict(self) -> dict[str, Any]:
        """Convert preset roles into dictionary structure for lathe.toml."""
        return {
            "roles": {
                "planner": self.planner.model_dump(exclude_none=True),
                "coder": self.coder.model_dump(exclude_none=True),
                "reviewer": self.reviewer.model_dump(exclude_none=True),
                "router": self.router.model_dump(exclude_none=True),
            }
        }


# Qwen Preset (Default): DeepSeek-R1 planner + Qwen2.5-Coder 7B coder + Qwen2.5-Coder 1.5B router
PRESET_QWEN = ModelPreset(
    name="qwen",
    display_name="Qwen Team (Default)",
    description=(
        "DeepSeek-R1 Distill 7B reasoning planner, Qwen2.5-Coder 7B execution coder, "
        "and lightweight Qwen 1.5B router."
    ),
    planner=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF:Q4_K_M",
        temperature=0.6,
        max_tokens=8192,
        context_window=32768,
    ),
    coder=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    reviewer=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF:Q4_K_M",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    router=RoleConfig(
        backend="ollama",
        model="hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M",
        temperature=0.0,
        max_tokens=1024,
        context_window=8192,
    ),
)

# Gemma Preset: Google Gemma family across all roles
PRESET_GEMMA = ModelPreset(
    name="gemma",
    display_name="Google Gemma Team",
    description=(
        "Pure Google Gemma setup: gemma4:e4b for planning, coding, and code review, "
        "paired with ultra-fast gemma4:e2b for task routing."
    ),
    planner=RoleConfig(
        backend="ollama",
        model="gemma4:e4b",
        temperature=0.6,
        max_tokens=8192,
        context_window=32768,
    ),
    coder=RoleConfig(
        backend="ollama",
        model="gemma4:e4b",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    reviewer=RoleConfig(
        backend="ollama",
        model="gemma4:e4b",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    router=RoleConfig(
        backend="ollama",
        model="gemma4:e2b",
        temperature=0.0,
        max_tokens=1024,
        context_window=32768,
    ),
)

# Mixed Preset: Qwen 7B coder + DeepSeek-R1 planner + Gemma 2B router
PRESET_MIXED = ModelPreset(
    name="mixed",
    display_name="Mixed Hybrid Team",
    description=(
        "Best-of-both hybrid: Qwen2.5-Coder 7B coder, DeepSeek-R1 Distill 7B reasoning planner, "
        "and Google Gemma 2B fast router."
    ),
    planner=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF:Q4_K_M",
        temperature=0.6,
        max_tokens=8192,
        context_window=32768,
    ),
    coder=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    reviewer=RoleConfig(
        backend="ollama",
        model="hf.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF:Q4_K_M",
        temperature=0.2,
        max_tokens=4096,
        context_window=32768,
    ),
    router=RoleConfig(
        backend="ollama",
        model="gemma4:e2b",
        temperature=0.0,
        max_tokens=1024,
        context_window=32768,
    ),
)

PRESETS: dict[str, ModelPreset] = {
    "qwen": PRESET_QWEN,
    "gemma": PRESET_GEMMA,
    "mixed": PRESET_MIXED,
}


def get_preset(name: str) -> ModelPreset:
    """Retrieve preset by name (case-insensitive) or raise ValueError."""
    key = name.strip().lower()
    if key in PRESETS:
        return PRESETS[key]
    valid = ", ".join(PRESETS.keys())
    raise ValueError(f"Unknown model preset '{name}'. Available presets: {valid}")


def list_presets() -> list[ModelPreset]:
    """Return all available model presets."""
    return list(PRESETS.values())


def strip_thinking_blocks(text: str) -> str:
    """Remove <think>...</think> and <thought>...</thought> reasoning blocks from model output.

    Handles DeepSeek-R1 and Gemma thinking-mode generations to isolate pure JSON or code.
    """
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<thought>[\s\S]*?</thought>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def format_messages_with_system_fallback(
    messages: list[Message],
    support_system: bool = True,
) -> list[dict[str, Any]]:
    """Format messages for Ollama API, prepending system prompt if system role is unsupported.

    If support_system is False (e.g. for model templates lacking system role tags),
    system prompt contents are concatenated and prefixed to the first user message.
    """
    if support_system:
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            formatted.append(entry)
        return formatted

    # Fallback: extract all system messages
    system_parts: list[str] = [m.content for m in messages if m.role == "system" and m.content]
    system_text = "\n\n".join(system_parts).strip()

    formatted_fallback: list[dict[str, Any]] = []
    first_user_handled = False

    for msg in messages:
        if msg.role == "system":
            continue

        entry = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]

        if msg.role == "user" and not first_user_handled:
            if system_text:
                entry["content"] = f"{system_text}\n\n{msg.content}"
            first_user_handled = True

        formatted_fallback.append(entry)

    # If there was a system prompt but NO user message in history
    if not first_user_handled and system_text:
        formatted_fallback.insert(0, {"role": "user", "content": system_text})

    return formatted_fallback


def generate_preset_toml(preset: ModelPreset) -> str:
    """Generate complete lathe.toml configuration text using the specified preset."""
    return f"""# Lathe Configuration File
# Initialized with preset: {preset.name} ({preset.display_name})
# Project-level config (overrides ~/.config/lathe/lathe.toml)
# Note: Secrets (HF_TOKEN) must NEVER be placed in this file; use environment variables or .env.

[settings]
mode = "auto"                   # "auto" (task router) | "single" (coder) | "dual" (planner + coder)
max_agent_steps = 25           # Maximum execution steps per task
auto_approve_reads = true      # Automatically permit non-mutating file inspection
theme = "lathe-dark"           # Rich terminal color theme
blocked_commands = [
    "rm -rf /",
    "rm -rf ~",
    "git reset --hard",
    "mkfs",
    "dd if="
]

[roles.planner]
backend = "{preset.planner.backend}"
model = "{preset.planner.model}"
temperature = {preset.planner.temperature}
max_tokens = {preset.planner.max_tokens}
context_window = {preset.planner.context_window}

[roles.coder]
backend = "{preset.coder.backend}"
model = "{preset.coder.model}"
temperature = {preset.coder.temperature}
max_tokens = {preset.coder.max_tokens}
context_window = {preset.coder.context_window}

[roles.reviewer]
backend = "{preset.reviewer.backend}"
model = "{preset.reviewer.model}"
temperature = {preset.reviewer.temperature}
max_tokens = {preset.reviewer.max_tokens}
context_window = {preset.reviewer.context_window}

[roles.router]
backend = "{preset.router.backend}"
model = "{preset.router.model}"
temperature = {preset.router.temperature}
max_tokens = {preset.router.max_tokens}
context_window = {preset.router.context_window}
"""


def apply_preset_to_toml_file(preset: ModelPreset, target_path: Path) -> None:
    """Write preset roles into target lathe.toml, creating it or updating roles section."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists():
        target_path.write_text(generate_preset_toml(preset), encoding="utf-8")
        return

    content = target_path.read_text(encoding="utf-8")
    # If [roles] sections exist, replace the roles block cleanly
    roles_block = f"""[roles.planner]
backend = "{preset.planner.backend}"
model = "{preset.planner.model}"
temperature = {preset.planner.temperature}
max_tokens = {preset.planner.max_tokens}
context_window = {preset.planner.context_window}

[roles.coder]
backend = "{preset.coder.backend}"
model = "{preset.coder.model}"
temperature = {preset.coder.temperature}
max_tokens = {preset.coder.max_tokens}
context_window = {preset.coder.context_window}

[roles.reviewer]
backend = "{preset.reviewer.backend}"
model = "{preset.reviewer.model}"
temperature = {preset.reviewer.temperature}
max_tokens = {preset.reviewer.max_tokens}
context_window = {preset.reviewer.context_window}

[roles.router]
backend = "{preset.router.backend}"
model = "{preset.router.model}"
temperature = {preset.router.temperature}
max_tokens = {preset.router.max_tokens}
context_window = {preset.router.context_window}
"""
    if "[roles" in content:
        # Replace everything from the first [roles. to the next top-level table or EOF
        cleaned = re.sub(
            r"\[roles\.[a-z]+\][\s\S]*?(?=\n\[(?!roles)[a-zA-Z0-9_\-]+\]|\Z)",
            "",
            content,
        ).rstrip()
        new_content = f"{cleaned}\n\n{roles_block}"
    else:
        new_content = f"{content.rstrip()}\n\n{roles_block}"

    target_path.write_text(new_content, encoding="utf-8")

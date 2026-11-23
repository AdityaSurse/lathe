"""Multi-tiered permission engine, security blocklist, and environment scrubbing."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

# =====================================================================
# 1. Permission Enums & Data Structures
# =====================================================================


class PermissionMode(StrEnum):
    """Operational mode determining automated approval rules."""

    DEFAULT = "default"  # read=auto; write/execute/network=ask
    AUTO = "auto"  # auto-approves write tools; asks for shell/execute
    YOLO = "yolo"  # approves all tools after warning; blocklist still enforced


class PermissionDecision(StrEnum):
    """Result decision of an authorization check."""

    ALLOW = "allow"
    DENY = "deny"
    EDIT = "edit"


@dataclass
class PermissionResult:
    """Detailed evaluation result returned by the permission engine."""

    decision: PermissionDecision
    reason: str | None = None
    edited_command: str | None = None
    message_to_model: str | None = None

    @property
    def is_allowed(self) -> bool:
        """Return True if execution is permitted (allow or edit)."""
        return self.decision == PermissionDecision.ALLOW or self.decision == PermissionDecision.EDIT

    @property
    def is_denied(self) -> bool:
        """Return True if execution was rejected."""
        return self.decision == PermissionDecision.DENY


# =====================================================================
# 2. Hard Security Blocklist
# =====================================================================

DEFAULT_BLOCKLIST_PATTERNS: list[str] = [
    # rm -rf / or ~ or $HOME (recursive deletion targeting root or home)
    r"\brm\s+-[a-zA-Z0-9]*r[a-zA-Z0-9]*\s+(/|~|\$HOME|\${HOME})($|\s|/|\*)",
    r"\brm\s+.*-(r|f).*-(r|f).*\s+(/|~|\$HOME|\${HOME})($|\s|/|\*)",
    # sudo
    r"\bsudo\b",
    # mkfs filesystem creation
    r"\bmkfs(\.[a-zA-Z0-9]+)?\b",
    # dd write to raw device nodes
    r"\bdd\b.*of=/dev/(sd[a-z]|hd[a-z]|nvme[0-9]|vd[a-z]|disk[0-9]|null|zero|mem|kmem|port|\*)",
    r"\bdd\b.*of=/dev/",
    # piped remote execution (curl | sh, wget | bash, etc.)
    r"\b(curl|wget|fetch)\b.*\|\s*(sh|bash|zsh|dash|python[0-9.]*|perl|ruby)\b",
    # force push to git repositories
    r"\bgit\s+push\s+.*(--force|-f\b|--force-with-lease)",
    # dangerous global permissive mode
    r"\bchmod\s+.*(-R.*777|777.*-R)",
    # fork bombs
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    r"\bfork\s+while\s+fork\b",
]


def is_blocked_command(
    command: str,
    custom_patterns: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Check if a shell command string matches any forbidden blocklist patterns."""
    patterns = list(DEFAULT_BLOCKLIST_PATTERNS)
    if custom_patterns:
        patterns.extend(custom_patterns)

    for pat in patterns:
        if re.search(pat, command, re.IGNORECASE):
            return True, pat
    return False, None


# =====================================================================
# 3. Environment Variable Scrubbing
# =====================================================================

FORBIDDEN_ENV_NAMES: frozenset[str] = frozenset(
    {
        "HF_TOKEN",
        "TOKEN",
        "KEY",
        "SECRET",
        "PASSWORD",
        "API_KEY",
        "APIKEY",
        "AUTH_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "ACCESS_KEY",
        "SECRET_KEY",
    }
)


def is_sensitive_env_var(key: str) -> bool:
    """Identify sensitive secret, credential, or token environment variable names."""
    upper = key.upper()
    if upper in FORBIDDEN_ENV_NAMES:
        return True
    if any(
        upper.endswith(suffix)
        for suffix in (
            "_TOKEN",
            "_KEY",
            "_SECRET",
            "_PASSWORD",
            "_AUTH",
            "_API_KEY",
            "_APIKEY",
        )
    ):
        return True
    return bool(upper.startswith("HF_"))


def scrub_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized copy of environment variables with all secret keys stripped."""
    source = env if env is not None else dict(os.environ)
    return {k: v for k, v in source.items() if not is_sensitive_env_var(k)}


# =====================================================================
# 4. Persistent Permission Store (.lathe/permissions.json)
# =====================================================================


class PermissionsStore:
    """Manages project-scoped persistent authorization rules in .lathe/permissions.json."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.root = Path(workspace_root).resolve()
        self.file_path = self.root / ".lathe" / "permissions.json"
        self._data: dict[str, list[str]] = {"always_allow": [], "denied": []}
        self.load()

    def load(self) -> None:
        """Load permissions from JSON file if present."""
        if self.file_path.is_file():
            try:
                content = self.file_path.read_text(encoding="utf-8")
                self._data = json.loads(content)
            except (OSError, json.JSONDecodeError):
                self._data = {"always_allow": [], "denied": []}

    def save(self) -> None:
        """Persist permissions to project .lathe/permissions.json."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            pass

    @property
    def always_allow(self) -> list[str]:
        """Return the list of persistent always-allowed patterns."""
        return self._data.setdefault("always_allow", [])

    def add_always_allow(self, pattern: str) -> None:
        """Add a pattern to always-allow list and persist to disk."""
        pattern = pattern.strip()
        if pattern and pattern not in self.always_allow:
            self.always_allow.append(pattern)
            self.save()

    def is_always_allowed(self, target: str) -> bool:
        """Match command or action string against always-allow patterns."""
        for pat in self.always_allow:
            if fnmatch.fnmatch(target, pat):
                return True
            clean_pat = pat.rstrip("*")
            if clean_pat and target.startswith(clean_pat):
                return True
        return False


# =====================================================================
# 5. Permission Engine
# =====================================================================


class PermissionEngine:
    """Enforces authorization gates, blocklist guards, and interactive confirmations."""

    def __init__(
        self,
        workspace_root: Path | str,
        mode: PermissionMode = PermissionMode.DEFAULT,
        input_handler: Callable[[str], str] | None = None,
        console: Console | None = None,
        custom_blocklist: list[str] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.mode = mode
        self.input_handler = input_handler
        self.console = console or Console()
        self.custom_blocklist = custom_blocklist or []
        self.store = PermissionsStore(self.workspace_root)
        self.warned_yolo = False

    def emit_yolo_warning(self) -> None:
        """Display red alert banner when YOLO mode is active."""
        if not self.warned_yolo:
            self.console.print(
                "\n[bold red]⚠️  WARNING: YOLO mode active. All operations will be approved "
                "without confirmation prompts. Dangerous blocklist commands remain strictly "
                "forbidden.[/bold red]\n"
            )
            self.warned_yolo = True

    def check_permission(
        self,
        tool: Any,
        args: dict[str, Any],
        ctx: Any = None,
    ) -> PermissionResult:
        """Evaluate authorization policy for a proposed tool invocation."""
        risk_level = getattr(tool, "risk_level", "read")
        tool_name = getattr(tool, "name", "unknown")

        # 1. Read operations are always auto-allowed
        if risk_level == "read":
            return PermissionResult(decision=PermissionDecision.ALLOW)

        # 2. Hard blocklist check for shell executions - ALWAYS enforced in every mode
        command = args.get("command", "") if tool_name == "run_shell" else ""
        if command:
            blocked, rule = is_blocked_command(command, self.custom_blocklist)
            if blocked:
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=(
                        f"Command '{command}' is blocked by security policy: "
                        f"matches forbidden pattern '{rule}'."
                    ),
                )

        # 3. Check persistent 'always allow' patterns from .lathe/permissions.json
        if command and self.store.is_always_allowed(command):
            return PermissionResult(decision=PermissionDecision.ALLOW)

        # 4. Mode-based automated rules
        if self.mode == PermissionMode.YOLO:
            self.emit_yolo_warning()
            return PermissionResult(decision=PermissionDecision.ALLOW)

        if self.mode == PermissionMode.AUTO and risk_level == "write":
            # --auto approves write tools (write_file, edit_file), but still asks for shell
            return PermissionResult(decision=PermissionDecision.ALLOW)

        # 5. Interactive confirmation prompt
        return self._prompt_user(tool, args)

    def _prompt_user(self, tool: Any, args: dict[str, Any]) -> PermissionResult:
        """Prompt user for interactive authorization decision."""
        tool_name = getattr(tool, "name", "unknown")
        risk_level = getattr(tool, "risk_level", "write")
        command = args.get("command", "")

        # Render Rich notification panel
        risk_styled = f"[{self._risk_color(risk_level)}]{risk_level}[/]"
        if command:
            panel = Panel(
                f"[bold cyan]Command:[/bold cyan] {command}\n"
                f"[bold cyan]Risk Level:[/bold cyan] {risk_styled}",
                title="[bold yellow]Permission Request: Execute Shell[/bold yellow]",
                border_style="yellow",
            )
        else:
            path = args.get("path", "")
            panel = Panel(
                f"[bold cyan]Tool:[/bold cyan] {tool_name}\n"
                f"[bold cyan]Target Path:[/bold cyan] {path}\n"
                f"[bold cyan]Risk Level:[/bold cyan] {risk_styled}",
                title="[bold yellow]Permission Request: Workspace Modification[/bold yellow]",
                border_style="yellow",
            )
        self.console.print(panel)

        prompt_str = (
            "[y]es / [n]o / [a]lways for this pattern"
            + (" / [e]dit command" if command else "")
            + " / [d]eny with message: "
        )

        # Get response via custom handler or interactive input
        if self.input_handler is not None:
            user_choice = self.input_handler(prompt_str).strip().lower()
        elif not sys.stdin.isatty():
            # Non-interactive automated environments reject mutating operations by default
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Non-interactive session: user confirmation required.",
            )
        else:
            try:
                user_choice = input(prompt_str).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason="User cancelled prompt.",
                )

        if user_choice in ("y", "yes"):
            return PermissionResult(decision=PermissionDecision.ALLOW)

        if user_choice in ("n", "no"):
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Action denied by user.",
            )

        if user_choice in ("a", "always"):
            # Derive pattern for always-allow
            if command:
                first_word = command.split()[0] if command.split() else command
                pattern = f"{first_word}*"
            else:
                pattern = f"{tool_name}*"

            self.store.add_always_allow(pattern)
            self.console.print(f"[dim]Added '{pattern}' to .lathe/permissions.json[/dim]")
            return PermissionResult(decision=PermissionDecision.ALLOW)

        if user_choice in ("e", "edit") and command:
            new_cmd = self._get_input("Edit command: ", default=command)
            # Verify edited command against blocklist
            blocked, rule = is_blocked_command(new_cmd, self.custom_blocklist)
            if blocked:
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason=f"Edited command '{new_cmd}' is blocked by security policy.",
                )
            return PermissionResult(
                decision=PermissionDecision.EDIT,
                edited_command=new_cmd,
            )

        if user_choice in ("d", "deny"):
            msg = self._get_input("Message for the agent: ")
            return PermissionResult(
                decision=PermissionDecision.DENY,
                message_to_model=f"Denied by user: {msg}",
            )

        # Default fallback
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason="Unrecognized option; action denied.",
        )

    def _get_input(self, prompt: str, default: str = "") -> str:
        """Prompt for secondary input string with handler support."""
        if self.input_handler is not None:
            return self.input_handler(prompt)
        try:
            val = input(prompt).strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            return default

    @staticmethod
    def _risk_color(risk: str) -> str:
        if risk == "read":
            return "green"
        if risk == "write":
            return "yellow"
        if risk == "execute":
            return "magenta"
        return "red"

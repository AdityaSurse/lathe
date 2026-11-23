"""Custom slash command loader and prompt template expansion (.lathe/commands/<name>.md)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from lathe.config import get_global_config_path


class CustomCommand(BaseModel):
    """Metadata and prompt template for a custom slash command."""

    name: str
    path: str
    template: str
    description: str = "Custom user command"
    is_global: bool = False

    def render(self, args: list[str]) -> str:
        """Substitute $ARGS and positional $1, $2, etc. in template."""
        rendered = self.template

        # Full argument string
        arg_string = " ".join(args).strip()
        rendered = rendered.replace("$ARGS", arg_string)

        # Positional placeholders: $1 through $9
        for idx in range(1, 10):
            placeholder = f"${idx}"
            val = args[idx - 1] if idx - 1 < len(args) else ""
            rendered = rendered.replace(placeholder, val)

        return rendered.strip()


class CustomCommandManager:
    """Discovers and expands markdown command templates in .lathe/commands/<name>.md."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root is not None else Path.cwd()
        )
        self.local_dir = self.workspace_root / ".lathe" / "commands"
        self.global_dir = get_global_config_path().parent / "commands"

    def _ensure_local_dir(self) -> Path:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        return self.local_dir

    def _extract_description(self, content: str, default: str) -> str:
        """Extract a short description from the first heading or line."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return default
        first = lines[0]
        if first.startswith("#"):
            return re.sub(r"^#+\s*", "", first).strip()
        return first[:50]

    def load_commands(self) -> dict[str, CustomCommand]:
        """Load all custom commands from global and local command directories.

        Local project commands take precedence over global commands of the same name.
        """
        commands: dict[str, CustomCommand] = {}

        # 1. Global commands (~/.config/lathe/commands/*.md)
        if self.global_dir.is_dir():
            try:
                for fpath in self.global_dir.glob("*.md"):
                    if not fpath.is_file():
                        continue
                    name = fpath.stem.lower()
                    try:
                        content = fpath.read_text(encoding="utf-8")
                        desc = self._extract_description(content, f"Custom command /{name}")
                        commands[name] = CustomCommand(
                            name=name,
                            path=str(fpath),
                            template=content,
                            description=desc,
                            is_global=True,
                        )
                    except OSError:
                        pass
            except OSError:
                pass

        # 2. Local commands (.lathe/commands/*.md)
        if self.local_dir.is_dir():
            try:
                for fpath in self.local_dir.glob("*.md"):
                    if not fpath.is_file():
                        continue
                    name = fpath.stem.lower()
                    try:
                        content = fpath.read_text(encoding="utf-8")
                        desc = self._extract_description(content, f"Custom command /{name}")
                        commands[name] = CustomCommand(
                            name=name,
                            path=str(fpath),
                            template=content,
                            description=desc,
                            is_global=False,
                        )
                    except OSError:
                        pass
            except OSError:
                pass

        return commands

    def get_command(self, name: str) -> CustomCommand | None:
        """Retrieve a custom command by name (without leading slash)."""
        clean_name = name.lstrip("/").lower()
        commands = self.load_commands()
        return commands.get(clean_name)

    def render_prompt(self, name: str, args: list[str]) -> str | None:
        """Render prompt text for a custom command with argument substitution."""
        cmd = self.get_command(name)
        if not cmd:
            return None
        return cmd.render(args)

    def save_command(
        self,
        name: str,
        template: str,
        is_global: bool = False,
    ) -> Path:
        """Save a new custom command template."""
        clean_name = name.lstrip("/").lower()
        target_dir = self.global_dir if is_global else self._ensure_local_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{clean_name}.md"
        target_path.write_text(template.strip() + "\n", encoding="utf-8")
        return target_path

    def delete_command(self, name: str) -> bool:
        """Remove a custom command file."""
        clean_name = name.lstrip("/").lower()
        local_path = self.local_dir / f"{clean_name}.md"
        global_path = self.global_dir / f"{clean_name}.md"

        deleted = False
        if local_path.is_file():
            try:
                local_path.unlink()
                deleted = True
            except OSError:
                pass
        if not deleted and global_path.is_file():
            try:
                global_path.unlink()
                deleted = True
            except OSError:
                pass
        return deleted

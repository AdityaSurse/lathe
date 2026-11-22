"""Custom prompt_toolkit completer supporting @file path completion and /slash commands."""

from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

SLASH_COMMAND_HINTS = [
    ("/help", "Show list of available slash commands"),
    ("/model", "Switch active model: /model <role> <id>"),
    ("/mode", "Switch mode: /mode single|dual"),
    ("/clear", "Clear the terminal screen"),
    ("/tokens", "View session token usage statistics"),
    ("/exit", "Exit Lathe REPL session"),
    ("/undo", "Restore the last checkpoint taken"),
    ("/checkpoints", "List all session checkpoints"),
    ("/restore", "Restore checkpoint: /restore <n>"),
    ("/diff", "Show session modifications unified diff"),
]


class LatheCompleter(Completer):
    """Completes @file repo paths and /slash commands."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path.cwd()

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        """Yield autocompletions for @file paths and /slash commands."""
        text_before_cursor = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)

        # 1. Slash command autocompletion
        if text_before_cursor.startswith("/") and " " not in text_before_cursor:
            for cmd, desc in SLASH_COMMAND_HINTS:
                if cmd.startswith(text_before_cursor):
                    yield Completion(
                        text=cmd,
                        start_position=-len(text_before_cursor),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        # 2. @file path autocompletion
        if word.startswith("@"):
            prefix = word[1:]
            for rel_path in self._search_paths(prefix):
                yield Completion(
                    text=f"@{rel_path}",
                    start_position=-len(word),
                    display=f"@{rel_path}",
                    display_meta="file" if not rel_path.endswith("/") else "dir",
                )

    def _search_paths(self, prefix: str) -> list[str]:
        """Search workspace directory for paths matching prefix."""
        root = self.workspace_root
        target_dir = root
        search_term = prefix

        if "/" in prefix:
            parts = prefix.split("/")
            rel_dir = "/".join(parts[:-1])
            search_term = parts[-1]
            candidate_dir = (root / rel_dir).resolve()
            if candidate_dir.is_dir() and candidate_dir.is_relative_to(root):
                target_dir = candidate_dir
            else:
                return []

        if not target_dir.is_dir():
            return []

        matches: list[str] = []
        try:
            for entry in target_dir.iterdir():
                name = entry.name
                if name.startswith(".") or name in ("__pycache__", "node_modules", ".venv"):
                    continue
                if name.lower().startswith(search_term.lower()):
                    try:
                        rel = entry.relative_to(root)
                        matches.append(str(rel) + ("/" if entry.is_dir() else ""))
                    except ValueError:
                        continue
        except Exception:
            pass

        return sorted(matches)

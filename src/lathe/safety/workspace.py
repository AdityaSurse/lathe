"""Workspace boundary enforcement, path resolution security, and ignore rule matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "build",
        "dist",
    }
)


class WorkspaceError(Exception):
    """Base exception for workspace access or configuration errors."""


class PathEscapeError(WorkspaceError):
    """Raised when a path resolution attempts to escape the workspace root."""


class FileAccessError(WorkspaceError):
    """Raised when file or directory operations fail within the workspace."""


@dataclass
class IgnoreRule:
    """Compiled ignore pattern matching gitignore specifications."""

    pattern: str
    negate: bool
    dir_only: bool
    regex: re.Pattern[str]

    def matches(self, rel_posix_path: str, is_dir: bool = False) -> bool:
        """Check if relative POSIX path matches this rule."""
        if self.dir_only and not is_dir:
            return False
        return bool(self.regex.search(rel_posix_path))


def parse_ignore_line(line: str) -> IgnoreRule | None:
    """Parse a single line from .gitignore or .latheignore into an IgnoreRule."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    negate = False
    if stripped.startswith("!"):
        negate = True
        stripped = stripped[1:].strip()

    if not stripped:
        return None

    dir_only = False
    if stripped.endswith("/"):
        dir_only = True
        stripped = stripped[:-1].rstrip()

    if not stripped:
        return None

    anchored = False
    if stripped.startswith("/"):
        anchored = True
        stripped = stripped[1:]
    elif "/" in stripped:
        anchored = True

    # Translate glob pattern to regular expression
    regex_parts: list[str] = []
    i = 0
    n = len(stripped)
    while i < n:
        c = stripped[i]
        if c == "*":
            if i + 1 < n and stripped[i + 1] == "*":
                # Double wildcard **
                if i + 2 < n and stripped[i + 2] == "/":
                    regex_parts.append("(?:.+/)?")
                    i += 3
                    continue
                else:
                    regex_parts.append(".*")
                    i += 2
                    continue
            else:
                regex_parts.append("[^/]*")
                i += 1
        elif c == "?":
            regex_parts.append("[^/]")
            i += 1
        elif c in ".+()[]{}^$|\\":
            regex_parts.append("\\" + c)
            i += 1
        else:
            regex_parts.append(c)
            i += 1

    body = "".join(regex_parts)
    final_pattern = f"^{body}$" if anchored else f"(?:^|/){body}$"

    try:
        compiled = re.compile(final_pattern)
    except re.error:
        return None

    return IgnoreRule(
        pattern=line.strip(),
        negate=negate,
        dir_only=dir_only,
        regex=compiled,
    )


class Workspace:
    """Enforces workspace boundaries, path resolution security, and ignore filters."""

    def __init__(
        self,
        root: Path | str | None = None,
        ignored_dirs: set[str] | frozenset[str] | None = None,
        respect_ignore_files: bool = True,
    ) -> None:
        self.root: Path = Path(root).resolve() if root else Path.cwd().resolve()
        self.ignored_dirs: set[str] = (
            set(ignored_dirs) if ignored_dirs is not None else set(DEFAULT_IGNORED_DIRS)
        )
        self.respect_ignore_files = respect_ignore_files
        self.ignore_rules: list[IgnoreRule] = []

        if self.respect_ignore_files:
            self.reload_ignores()

    def reload_ignores(self) -> None:
        """Reload .gitignore and .latheignore from workspace root."""
        self.ignore_rules.clear()

        # Load .gitignore if present
        gitignore_path = self.root / ".gitignore"
        if gitignore_path.is_file():
            self.load_ignore_file(gitignore_path)

        # Load .latheignore if present (appends/overrides)
        latheignore_path = self.root / ".latheignore"
        if latheignore_path.is_file():
            self.load_ignore_file(latheignore_path)

    def load_ignore_file(self, file_path: Path) -> None:
        """Parse and append rules from an ignore file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                rule = parse_ignore_line(line)
                if rule is not None:
                    self.ignore_rules.append(rule)
        except OSError:
            # If ignore file cannot be read, continue with existing rules
            pass

    def resolve_path(self, path: Path | str) -> Path:
        """Safely resolve path within workspace root; refuse paths that escape it.

        Guards against:
        - Directory traversal sequences ('../')
        - Absolute paths outside the workspace root
        - Symlinks pointing outside the workspace root
        - Symlink directory components pointing outside the workspace root
        """
        if isinstance(path, str):
            if "\0" in path:
                raise PathEscapeError(f"Access denied: path contains null byte '{path}'.")
            target = Path(path)
        else:
            target = path

        # If path is absolute, check its resolved location against root
        candidate = target if target.is_absolute() else self.root / target

        try:
            resolved = candidate.resolve()
        except (RuntimeError, OSError) as exc:
            raise PathEscapeError(f"Access denied: cannot resolve path '{path}': {exc}") from exc

        # Strict boundary check against self.root
        if not self._is_within_root(resolved):
            raise PathEscapeError(
                f"Access denied: path '{path}' escapes workspace root '{self.root}'."
            )

        # Also inspect intermediate symlink parents for non-existent targets
        if not candidate.exists() and not self._verify_ancestor_symlinks(candidate):
            raise PathEscapeError(
                f"Access denied: path '{path}' traverses symlink outside workspace root."
            )

        return resolved

    def _is_within_root(self, path: Path) -> bool:
        """Check if path is identical to or within self.root."""
        try:
            return path == self.root or path.is_relative_to(self.root)
        except ValueError:
            return False

    def _verify_ancestor_symlinks(self, path: Path) -> bool:
        """Verify that all existing ancestor directories stay within self.root."""
        curr: Path = path.parent
        while curr != self.root and curr != curr.parent:
            if curr.exists():
                try:
                    resolved_curr = curr.resolve()
                    if not self._is_within_root(resolved_curr):
                        return False
                except OSError:
                    return False
            curr = curr.parent
        return True

    def relpath(self, path: Path | str) -> str:
        """Convert a path into a POSIX-style relative path string from workspace root."""
        p = Path(path)
        if p.is_absolute():
            try:
                resolved = p.resolve()
                if resolved == self.root:
                    return "."
                return resolved.relative_to(self.root).as_posix()
            except ValueError:
                return p.as_posix()

        # Normalize relative path without stripping leading dot from filenames like .pytest_cache
        posix = p.as_posix()
        while posix.startswith("./"):
            posix = posix[2:]
        return posix if posix else "."

    def _matches_rules(self, rel_posix: str, is_dir: bool) -> bool:
        """Evaluate ignore rules in sequence against a relative path."""
        ignored = False
        for rule in self.ignore_rules:
            if rule.matches(rel_posix, is_dir=is_dir):
                ignored = not rule.negate
        return ignored

    def is_ignored(self, path: Path | str, is_dir: bool | None = None) -> bool:
        """Check if a path matches ignored directories or .gitignore/.latheignore rules."""
        rel_posix = self.relpath(path)
        if not rel_posix or rel_posix == ".":
            return False

        # Check default ignored directory names in any path component
        parts = rel_posix.split("/")
        for part in parts:
            if part in self.ignored_dirs or part.endswith(".egg-info"):
                return True

        if is_dir is None:
            full = self.root / rel_posix
            try:
                is_dir = full.is_dir() if full.exists() else False
            except OSError:
                is_dir = False

        # Check if any parent directory is ignored by ignore rules
        for i in range(1, len(parts)):
            parent_dir = "/".join(parts[:i])
            if self._matches_rules(parent_dir, is_dir=True):
                return True

        # Check the target path itself
        return self._matches_rules(rel_posix, is_dir=is_dir)

    def __repr__(self) -> str:
        return f"Workspace(root={self.root!r}, rules={len(self.ignore_rules)})"

"""Project and workspace safety guards."""

from __future__ import annotations

import os
from pathlib import Path


def check_is_project_folder(folder: Path | str | None = None) -> tuple[bool, str | None]:
    """Check if the target directory is a valid project folder.

    Returns:
        (is_project, warning_message): False if folder is ~, /, or not a git repo with >2000 files.
    """
    target = Path(folder).resolve() if folder else Path.cwd().resolve()
    home = Path.home().resolve()
    root = Path("/").resolve()

    # 1. Home directory or root filesystem guard
    if target == home or target == root:
        return False, "Not in a project folder — cd into a project for full features."

    # 2. Check for git repository
    is_git_repo = (target / ".git").is_dir()
    if not is_git_repo:
        # Count files quickly, short-circuiting after 2,001 files
        file_count = 0
        try:
            for root_dir, dirs, files in os.walk(target):
                # Don't recurse into hidden or heavy directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".")
                    and d not in ("node_modules", ".venv", "venv", "__pycache__", "dist", "build")
                ]
                file_count += len(files)
                if file_count > 2000:
                    return False, "Not in a project folder — cd into a project for full features."
        except (PermissionError, OSError):
            return False, "Not in a project folder — cd into a project for full features."

    return True, None

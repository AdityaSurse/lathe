"""Session statistics and bottom status bar toolbar."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.formatted_text import HTML

from lathe.config import LatheConfig
from lathe.llm.types import Usage


@dataclass
class SessionStats:
    """Tracks token consumption and request count across a REPL session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0
    status_message: str | None = None

    def add_usage(self, usage: Usage | None) -> None:
        """Accumulate token counts from a completion or stream terminal chunk."""
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens
        self.request_count += 1


def get_git_branch(cwd: Path | None = None) -> str:
    """Return the name of the current active git branch, or 'no-git'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            branch = res.stdout.strip()
            return branch if branch else "detached"
    except Exception:
        pass
    return "no-git"


def get_repo_name(cwd: Path | None = None) -> str:
    """Return current repository or directory basename."""
    target = cwd or Path.cwd()
    return target.name or str(target)


def render_status_toolbar(config: LatheConfig, stats: SessionStats) -> HTML:
    """Format prompt_toolkit HTML bottom status bar."""
    repo = get_repo_name()
    branch = get_git_branch()
    mode = config.settings.mode

    # Short model names for compact status bar
    coder_name = config.roles.coder.model.split("/")[-1].split(":")[0]
    planner_name = config.roles.planner.model.split("/")[-1].split(":")[0]

    if mode == "dual":
        models_str = f"coder: {coder_name} | planner: {planner_name}"
    elif mode == "auto":
        router_name = config.roles.router.model.split("/")[-1].split(":")[0]
        models_str = f"router: {router_name} | coder: {coder_name}"
    else:
        models_str = f"coder: {coder_name}"

    tokens_str = f"{stats.total_tokens:,}"
    status_extra = (
        f" | <b>status:</b> <ansiyellow>{stats.status_message}</ansiyellow>"
        if stats.status_message
        else ""
    )

    return HTML(
        f"<style bg='#1e293b' fg='#f8fafc'> "
        f"<b>repo:</b> <ansicyan>{repo}</ansicyan> "
        f"| <b>git:</b> <ansigreen>{branch}</ansigreen> "
        f"| <b>mode:</b> <ansiyellow>{mode}</ansiyellow> "
        f"| <b>models:</b> {models_str} "
        f"| <b>tokens:</b> <ansimagenta>{tokens_str}</ansimagenta>"
        f"{status_extra} "
        f"</style>"
    )

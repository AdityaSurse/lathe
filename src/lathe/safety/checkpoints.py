"""Working tree checkpoints with isolated git ref snapshots and non-destructive rollbacks."""

from __future__ import annotations

import contextlib
import datetime
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

CHECKPOINT_REF_PREFIX = "refs/lathe/checkpoints"


@dataclass
class Checkpoint:
    """Snapshot record of working tree state at a specific point in time."""

    session_id: str
    number: int
    ref: str
    commit_sha: str
    tree_sha: str
    timestamp: float
    description: str
    changed_files: list[str] = field(default_factory=list)

    @property
    def formatted_time(self) -> str:
        """Human-readable formatted time string (HH:MM:SS)."""
        return datetime.datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")


class CheckpointManager:
    """Manages working-tree snapshots using temporary git index and custom refs.

    Does not modify the user's working branch HEAD or active staging index (.git/index).
    Snapshots are saved under refs/lathe/checkpoints/<session>/<n>.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        session_id: str | None = None,
        console: Console | None = None,
        prompt_init: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.session_id = session_id or uuid.uuid4().hex[:8]
        self.console = console or Console()
        self._checkpoints: list[Checkpoint] = []
        self._is_git_repo = self._check_git_repo(prompt_init=prompt_init)
        if self._is_git_repo:
            self._load_existing_checkpoints()

    @property
    def is_enabled(self) -> bool:
        """Whether checkpointing is active (requires a valid git repository)."""
        return self._is_git_repo

    def _check_git_repo(self, prompt_init: bool = False) -> bool:
        """Verify repository exists; optionally offer git init or warn."""
        if not shutil.which("git"):
            self.console.print(
                "[yellow]Warning: 'git' binary not found. Checkpoints disabled.[/yellow]"
            )
            return False

        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return True

        if prompt_init:
            try:
                choice = (
                    input(
                        f"'{self.workspace_root}' is not a git repository. "
                        "Initialize git repository now? [y/N]: "
                    )
                    .strip()
                    .lower()
                )
                if choice in ("y", "yes"):
                    init_res = subprocess.run(
                        ["git", "init"],
                        cwd=str(self.workspace_root),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if init_res.returncode == 0:
                        self.console.print("[green]Initialized git repository.[/green]")
                        return True
            except (KeyboardInterrupt, EOFError):
                pass

        self.console.print(
            "[yellow]Warning: Not a git repository. "
            "Checkpoints and automatic undo are disabled.[/yellow]"
        )
        return False

    def _load_existing_checkpoints(self) -> None:
        """Discover existing checkpoints for current session if any."""
        ref_prefix = f"{CHECKPOINT_REF_PREFIX}/{self.session_id}/"
        res = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname) %(objectname)", ref_prefix],
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return

        for line in res.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                ref_name, commit_sha = parts[0], parts[1]
                num_str = ref_name.removeprefix(ref_prefix)
                try:
                    num = int(num_str)
                except ValueError:
                    continue

                # Query tree and commit message
                tree_res = subprocess.run(
                    ["git", "rev-parse", f"{commit_sha}^{{tree}}"],
                    cwd=str(self.workspace_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                tree_sha = tree_res.stdout.strip() if tree_res.returncode == 0 else ""

                msg_res = subprocess.run(
                    ["git", "log", "-1", "--format=%s", commit_sha],
                    cwd=str(self.workspace_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                desc = msg_res.stdout.strip() if msg_res.returncode == 0 else f"Checkpoint {num}"

                self._checkpoints.append(
                    Checkpoint(
                        session_id=self.session_id,
                        number=num,
                        ref=ref_name,
                        commit_sha=commit_sha,
                        tree_sha=tree_sha,
                        timestamp=time.time(),
                        description=desc,
                    )
                )
        self._checkpoints.sort(key=lambda c: c.number)

    def create_checkpoint(self, description: str = "") -> Checkpoint | None:
        """Create a working-tree snapshot ref without touching branch HEAD or index.

        Uses a separate temporary index file via GIT_INDEX_FILE so the user's staged
        changes in .git/index and active commit history remain completely unaffected.
        """
        if not self._is_git_repo:
            return None

        number = len(self._checkpoints) + 1
        ref_name = f"{CHECKPOINT_REF_PREFIX}/{self.session_id}/{number}"
        temp_index = (
            self.workspace_root
            / ".git"
            / f"lathe_idx_{self.session_id}_{number}_{uuid.uuid4().hex[:6]}"
        )
        env = dict(os.environ, GIT_INDEX_FILE=str(temp_index))

        try:
            # 1. Populate temp index with current working tree
            subprocess.run(
                ["git", "add", "--all"],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                check=True,
            )

            # 2. Write tree object from temp index
            tree_proc = subprocess.run(
                ["git", "write-tree"],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            tree_sha = tree_proc.stdout.strip()

            # 3. Create commit object from tree
            desc = description.strip() or f"Checkpoint {number}"
            commit_proc = subprocess.run(
                ["git", "commit-tree", tree_sha, "-m", desc],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            commit_sha = commit_proc.stdout.strip()

            # 4. Update the checkpoint ref
            subprocess.run(
                ["git", "update-ref", ref_name, commit_sha],
                cwd=str(self.workspace_root),
                capture_output=True,
                check=True,
            )

            # 5. Compute changed files compared to previous checkpoint
            changed_files: list[str] = []
            if self._checkpoints:
                prev_tree = self._checkpoints[-1].tree_sha
                diff_cmd = [
                    "git",
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    prev_tree,
                    tree_sha,
                ]
                diff_proc = subprocess.run(
                    diff_cmd,
                    cwd=str(self.workspace_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if diff_proc.returncode == 0:
                    changed_files = [
                        line.strip()
                        for line in diff_proc.stdout.strip().splitlines()
                        if line.strip()
                    ]
            else:
                ls_proc = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", tree_sha],
                    cwd=str(self.workspace_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if ls_proc.returncode == 0:
                    changed_files = [
                        line.strip() for line in ls_proc.stdout.strip().splitlines() if line.strip()
                    ]

            ckpt = Checkpoint(
                session_id=self.session_id,
                number=number,
                ref=ref_name,
                commit_sha=commit_sha,
                tree_sha=tree_sha,
                timestamp=time.time(),
                description=desc,
                changed_files=changed_files,
            )
            self._checkpoints.append(ckpt)
            return ckpt

        except Exception as exc:
            self.console.print(f"[dim]Checkpoint creation failed: {exc}[/dim]")
            return None
        finally:
            if temp_index.exists():
                with contextlib.suppress(OSError):
                    temp_index.unlink()

    def restore(self, number: int) -> bool:
        """Restore working directory to the tree of checkpoint `number`.

        Overwrites modified files and cleans newly created files that did not
        exist in the checkpoint, while leaving user's staged index (.git/index) intact.
        """
        if not self._is_git_repo:
            return False

        target_ckpt = next((c for c in self._checkpoints if c.number == number), None)
        if not target_ckpt:
            return False

        temp_index = (
            self.workspace_root
            / ".git"
            / f"lathe_restore_{self.session_id}_{number}_{uuid.uuid4().hex[:6]}"
        )
        env = dict(os.environ, GIT_INDEX_FILE=str(temp_index))

        try:
            # 1. Read checkpoint tree into temp index
            subprocess.run(
                ["git", "read-tree", target_ckpt.tree_sha],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                check=True,
            )

            # 2. Checkout all files from temp index to working directory
            subprocess.run(
                ["git", "checkout-index", "-a", "-f"],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                check=True,
            )

            # 3. Clean files created since checkpoint (excluding ignored files)
            tree_files_proc = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", target_ckpt.tree_sha],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                check=True,
            )
            tree_files = set(tree_files_proc.stdout.splitlines())

            for p in self.workspace_root.rglob("*"):
                if not p.is_file():
                    continue
                rel_str = str(p.relative_to(self.workspace_root))
                # Never remove files in .git or ignored directories
                if rel_str.startswith(".git") or rel_str.startswith(".lathe"):
                    continue
                if rel_str not in tree_files:
                    # Check if file is ignored by git
                    ignore_proc = subprocess.run(
                        ["git", "check-ignore", rel_str],
                        cwd=str(self.workspace_root),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if ignore_proc.returncode != 0:
                        # File is untracked and not ignored: remove it
                        with contextlib.suppress(OSError):
                            p.unlink()

            return True

        except Exception as exc:
            self.console.print(f"[red]Restore failed:[/red] {exc}")
            return False
        finally:
            if temp_index.exists():
                with contextlib.suppress(OSError):
                    temp_index.unlink()

    def undo(self) -> Checkpoint | None:
        """Restore working directory to the most recent previous checkpoint."""
        if not self._checkpoints:
            return None

        # Check if working directory differs from the latest checkpoint
        latest = self._checkpoints[-1]
        diff_proc = subprocess.run(
            ["git", "diff", latest.tree_sha],
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        has_changes_from_latest = diff_proc.returncode == 0 and bool(diff_proc.stdout.strip())

        if has_changes_from_latest:
            # Revert back to latest checkpoint
            target = latest
        elif len(self._checkpoints) >= 2:
            # Revert back to one before latest
            target = self._checkpoints[-2]
            self._checkpoints.pop()
        else:
            target = latest

        if self.restore(target.number):
            return target
        return None

    def list_checkpoints(self) -> list[Checkpoint]:
        """Return list of all registered session checkpoints."""
        return list(self._checkpoints)

    def get_session_diff(self) -> str:
        """Produce unified diff of all changes made during this session."""
        if not self._is_git_repo:
            return ""

        temp_index = (
            self.workspace_root / ".git" / f"lathe_diff_{self.session_id}_{uuid.uuid4().hex[:6]}"
        )
        env = dict(os.environ, GIT_INDEX_FILE=str(temp_index))

        try:
            # Capture current working tree into temp index
            subprocess.run(
                ["git", "add", "--all"],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                check=True,
            )
            curr_proc = subprocess.run(
                ["git", "write-tree"],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            curr_tree = curr_proc.stdout.strip()

            base_tree = self._checkpoints[0].tree_sha if self._checkpoints else "HEAD"
            diff_proc = subprocess.run(
                ["git", "diff", base_tree, curr_tree],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                check=False,
            )
            return diff_proc.stdout if diff_proc.returncode == 0 else ""
        except Exception:
            return ""
        finally:
            if temp_index.exists():
                with contextlib.suppress(OSError):
                    temp_index.unlink()


# Global or active session checkpoint manager registry
_ACTIVE_CHECKPOINT_MANAGERS: dict[str, CheckpointManager] = {}


def get_checkpoint_manager(
    workspace_root: Path | str | None = None,
    session_id: str | None = None,
    prompt_init: bool = False,
) -> CheckpointManager:
    """Retrieve or create singleton CheckpointManager for a workspace."""
    root = Path(workspace_root or Path.cwd()).resolve()
    key = str(root)
    if key not in _ACTIVE_CHECKPOINT_MANAGERS:
        _ACTIVE_CHECKPOINT_MANAGERS[key] = CheckpointManager(
            workspace_root=root,
            session_id=session_id,
            prompt_init=prompt_init,
        )
    return _ACTIVE_CHECKPOINT_MANAGERS[key]


async def suggest_conventional_commit(diff: str, client: Any) -> str:
    """Generate a Conventional Commits message from a diff using an LLM client."""
    from lathe.llm.types import Message

    if not diff.strip():
        return "chore: update workspace"

    prompt = (
        "Write a concise, standard Conventional Commits message (e.g. feat(scope): message, "
        "fix(scope): message, refactor: message) summarizing the following git diff.\n"
        "Return ONLY the single-line commit message. Do not include quotes, markdown formatting, "
        "or explanation.\n\n"
        f"```diff\n{diff[:4000]}\n```"
    )
    messages = [Message(role="user", content=prompt)]
    collected = ""
    try:
        async for chunk in client.chat(messages, stream=False):
            if chunk.delta:
                collected += chunk.delta
    except Exception:
        return "chore: automated changes"

    lines = [ln.strip() for ln in collected.strip().splitlines() if ln.strip()]
    first_line = lines[0].strip("`'\"") if lines else "chore: update workspace"
    return first_line or "chore: update workspace"


async def auto_commit_task(
    workspace_root: Path | str,
    client: Any,
    console: Console | None = None,
    input_handler: Callable[[str], str] | None = None,
) -> bool:
    """Offer optional auto-commit at the end of a task with Conventional Commits message."""
    c = console or Console()
    cm = get_checkpoint_manager(workspace_root)
    diff = cm.get_session_diff()

    if not diff.strip():
        return False

    c.print("\n[dim]Analyzing session changes for commit message...[/dim]")
    commit_msg = await suggest_conventional_commit(diff, client)

    c.print(f"\n[bold cyan]Suggested Commit:[/bold cyan] [bold green]{commit_msg}[/bold green]")
    prompt_str = "Commit changes? [y]es / [n]o / [e]dit message: "

    if input_handler is not None:
        choice = input_handler(prompt_str).strip().lower()
    else:
        try:
            choice = input(prompt_str).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False

    final_msg = commit_msg
    if choice in ("e", "edit"):
        try:
            edited = (
                input_handler("New commit message: ")
                if input_handler
                else input("New commit message: ")
            ).strip()
            if edited:
                final_msg = edited
            else:
                return False
        except (KeyboardInterrupt, EOFError):
            return False
    elif choice not in ("y", "yes"):
        c.print("[dim]Commit skipped.[/dim]")
        return False

    # Stage all changes and commit
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(workspace_root),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", final_msg],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=True,
        )
        c.print(f"[green]Committed:[/green] {final_msg}")
        return True
    except subprocess.CalledProcessError as exc:
        c.print(f"[red]Commit failed:[/red] {exc.stderr.strip() if exc.stderr else exc}")
        return False

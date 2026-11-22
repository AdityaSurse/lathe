"""Git tools for status inspection, diff viewing, commit log, and safe commits."""

from __future__ import annotations

import shutil
import subprocess

from pydantic import BaseModel, Field

from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult

# =====================================================================
# 1. git_status Tool
# =====================================================================


class GitStatusArgs(BaseModel):
    """Arguments for querying git repository working tree status."""

    path: str | None = Field(
        default=None,
        description="Optional relative file or directory path to check status for.",
    )


class GitStatusTool(Tool):
    """Tool to inspect branch, staged changes, unstaged edits, and untracked files."""

    name = "git_status"
    description = (
        "Inspect the git repository status of the workspace.\n"
        "WHEN TO USE:\n"
        "- Check current branch and tracking status.\n"
        "- Discover which files are staged, modified, or untracked.\n"
        "WHEN NOT TO USE:\n"
        "- Do not use to view file contents (use read_file).\n"
        "- Do not use to view detailed code diffs (use git_diff)."
    )
    args_schema = GitStatusArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: GitStatusArgs, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root
        if not shutil.which("git"):
            return ToolResult(ok=False, output="", error="git binary not found.")

        cmd = ["git", "status", "--porcelain=v1", "-b"]
        if args.path:
            cmd.extend(["--", args.path])

        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return ToolResult(
                ok=False,
                output="",
                error=proc.stderr.strip() or "Failed to query git status (is this a git repo?).",
            )

        raw_output = proc.stdout.strip()
        lines = raw_output.splitlines()

        branch_info = lines[0].removeprefix("## ") if lines else "unknown"
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []

        for line in lines[1:]:
            if len(line) < 3:
                continue
            index_code = line[0]
            work_code = line[1]
            file_name = line[3:].strip()

            if index_code in ("M", "A", "D", "R", "C"):
                staged.append(f"{index_code} {file_name}")
            if work_code in ("M", "D"):
                unstaged.append(f"{work_code} {file_name}")
            elif index_code == "?" and work_code == "?":
                untracked.append(file_name)

        summary_lines = [f"Branch: {branch_info}"]
        if staged:
            summary_lines.append(f"Staged ({len(staged)}):")
            summary_lines.extend(f"  {s}" for s in staged[:20])
        else:
            summary_lines.append("Staged: (none)")

        if unstaged:
            summary_lines.append(f"Unstaged changes ({len(unstaged)}):")
            summary_lines.extend(f"  {u}" for u in unstaged[:20])
        else:
            summary_lines.append("Unstaged: (none)")

        if untracked:
            summary_lines.append(f"Untracked files ({len(untracked)}):")
            summary_lines.extend(f"  ? {u}" for u in untracked[:20])

        output_text = "\n".join(summary_lines)
        return ToolResult(
            ok=True,
            output=output_text,
            metadata={
                "branch": branch_info,
                "staged_count": len(staged),
                "unstaged_count": len(unstaged),
                "untracked_count": len(untracked),
            },
        )


# =====================================================================
# 2. git_diff Tool
# =====================================================================


class GitDiffArgs(BaseModel):
    """Arguments for generating unified diffs in the repository."""

    staged: bool = Field(
        default=False,
        description="Show diff of staged changes against HEAD.",
    )
    unstaged: bool = Field(
        default=True,
        description="Show diff of working tree changes against staging index.",
    )
    path: str | None = Field(
        default=None,
        description="Optional relative file or directory path to limit diff.",
    )


class GitDiffTool(Tool):
    """Tool to inspect unified diffs of staged or unstaged workspace modifications."""

    name = "git_diff"
    description = (
        "View unified diffs of modifications in the workspace.\n"
        "WHEN TO USE:\n"
        "- Review changes made by previous edit steps.\n"
        "- Inspect unstaged changes (default) or staged changes (staged=True).\n"
        "- Check modifications on a specific file path."
    )
    args_schema = GitDiffArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: GitDiffArgs, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root
        if not shutil.which("git"):
            return ToolResult(ok=False, output="", error="git binary not found.")

        cmd = ["git", "diff"]
        if args.staged and not args.unstaged:
            cmd.append("--cached")
        elif args.staged and args.unstaged:
            cmd.append("HEAD")

        if args.path:
            cmd.extend(["--", args.path])

        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return ToolResult(
                ok=False,
                output="",
                error=proc.stderr.strip() or "Failed to run git diff.",
            )

        diff_text = proc.stdout.strip()
        if not diff_text:
            return ToolResult(
                ok=True,
                output="(no diff — working tree clean)",
                metadata={"empty": True},
            )

        return ToolResult(
            ok=True,
            output=diff_text,
            metadata={"diff_lines": len(diff_text.splitlines())},
        )


# =====================================================================
# 3. git_log Tool
# =====================================================================


class GitLogArgs(BaseModel):
    """Arguments for querying recent git commits."""

    n: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of commits to retrieve (default 10).",
    )
    path: str | None = Field(
        default=None,
        description="Optional file path to filter commit history.",
    )


class GitLogTool(Tool):
    """Tool to inspect commit history and messages."""

    name = "git_log"
    description = (
        "Display recent git commit history with hashes, authors, and messages.\n"
        "WHEN TO USE:\n"
        "- Understand recent project changes, commit styles, or conventions.\n"
        "- Review commits affecting a specific file."
    )
    args_schema = GitLogArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: GitLogArgs, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root
        if not shutil.which("git"):
            return ToolResult(ok=False, output="", error="git binary not found.")

        cmd = ["git", "log", f"-n{args.n}", "--pretty=format:%h - %an (%cr): %s"]
        if args.path:
            cmd.extend(["--", args.path])

        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            # Check if repo has no commits yet
            empty_check = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=str(workspace_root),
                capture_output=True,
                check=False,
            )
            if empty_check.returncode != 0:
                return ToolResult(ok=True, output="No commits yet (new repository).")
            return ToolResult(
                ok=False,
                output="",
                error=proc.stderr.strip() or "Failed to query git log.",
            )

        output_text = proc.stdout.strip()
        if not output_text:
            return ToolResult(ok=True, output="No commits found.")

        return ToolResult(ok=True, output=output_text)


# =====================================================================
# 4. git_commit Tool (risk = write, asks permission)
# =====================================================================


class GitCommitArgs(BaseModel):
    """Arguments for creating a new git commit."""

    message: str = Field(
        min_length=1,
        description="Conventional commit message (e.g. feat(auth): add JWT login).",
    )
    stage_all: bool = Field(
        default=True,
        description="Whether to stage all tracked and untracked changes before committing.",
    )


class GitCommitTool(Tool):
    """Tool to create a git commit from workspace changes."""

    name = "git_commit"
    description = (
        "Create a git commit with a Conventional Commits message.\n"
        "WHEN TO USE:\n"
        "- Committing verified changes after completing a task or milestone.\n"
        "RISK:\n"
        "- Risk level is 'write' — requires user authorization before proceeding."
    )
    args_schema = GitCommitArgs
    risk_level: RiskLevel = "write"

    async def _execute(self, args: GitCommitArgs, ctx: ToolContext) -> ToolResult:
        workspace_root = ctx.workspace_root
        if not shutil.which("git"):
            return ToolResult(ok=False, output="", error="git binary not found.")

        # Stage changes if requested
        if args.stage_all:
            add_proc = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if add_proc.returncode != 0:
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"Failed to stage changes: {add_proc.stderr.strip()}",
                )

        # Execute commit
        commit_proc = subprocess.run(
            ["git", "commit", "-m", args.message],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_proc.returncode != 0:
            err = commit_proc.stderr.strip() or commit_proc.stdout.strip()
            if "nothing to commit" in err.lower():
                return ToolResult(ok=True, output="Nothing to commit (working tree clean).")
            return ToolResult(ok=False, output="", error=f"Git commit failed: {err}")

        # Retrieve commit SHA
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
        )
        commit_sha = sha_proc.stdout.strip() if sha_proc.returncode == 0 else "unknown"

        summary = f"Commit created successfully: {commit_sha[:8]} — {args.message}"
        return ToolResult(
            ok=True,
            output=summary,
            metadata={"commit_sha": commit_sha, "message": args.message},
        )


# Singleton instances
git_status = GitStatusTool()
git_diff = GitDiffTool()
git_log = GitLogTool()
git_commit = GitCommitTool()

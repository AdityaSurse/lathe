"""Search tools for Lathe: exact regex grep and semantic natural language search."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lathe.safety.workspace import Workspace
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from lathe.tools.files import is_binary_file

MAX_GREP_MATCHES = 50


class GrepSearchArgs(BaseModel):
    """Arguments for grep_search tool."""

    pattern: str = Field(
        description="Search pattern or literal string to search for across workspace files."
    )
    path_glob: str | None = Field(
        default=None,
        description="Optional glob pattern to restrict search (e.g. '*.py', 'src/**/*.ts').",
    )
    regex: bool = Field(
        default=True,
        description=(
            "Whether to treat pattern as a regular expression (default True). "
            "If False, literal search is performed."
        ),
    )


class SemanticSearchArgs(BaseModel):
    """Arguments for semantic_search tool."""

    query: str = Field(
        description=(
            "Natural language query describing desired functionality or concept "
            "(e.g. 'where is user authentication handled?')."
        )
    )
    k: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Maximum number of relevant code chunks to return (default 8).",
    )


def _python_fallback_grep(
    workspace_root: Path,
    pattern: str,
    path_glob: str | None = None,
    regex: bool = True,
    max_matches: int = MAX_GREP_MATCHES,
) -> str:
    """Pure Python fallback for grep search with 2 lines of context."""
    ws = Workspace(workspace_root)
    all_files: list[Path] = []

    for root, dirs, files in os.walk(workspace_root):
        root_path = Path(root)
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and not ws.is_ignored(root_path / d)
            and d not in ("node_modules", ".venv", ".git", "build", "dist")
        ]
        for f in files:
            if f.startswith("."):
                continue
            full_path = root_path / f
            if not ws.is_ignored(full_path):
                all_files.append(full_path)

    if regex:
        try:
            compiled_re = re.compile(pattern)
        except re.error as err:
            return f"Error: Invalid regular expression '{pattern}': {err}"

    matches_found = 0
    output_blocks: list[str] = []

    for file_path in all_files:
        if matches_found >= max_matches:
            break

        rel_path = str(file_path.relative_to(workspace_root))
        if path_glob and not fnmatch.fnmatch(rel_path, path_glob):
            continue

        if is_binary_file(file_path):
            continue

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = text.splitlines()
        matched_indices: set[int] = set()

        for idx, line in enumerate(lines):
            is_match = bool(compiled_re.search(line)) if regex else (pattern in line)
            if is_match:
                matched_indices.add(idx)

        if not matched_indices:
            continue

        sorted_indices = sorted(matched_indices)
        for midx in sorted_indices:
            if matches_found >= max_matches:
                break
            matches_found += 1

            start_ctx = max(0, midx - 2)
            end_ctx = min(len(lines), midx + 3)

            block_lines = [f"{rel_path}:{midx + 1}:"]
            for c_idx in range(start_ctx, end_ctx):
                marker = ">" if c_idx == midx else " "
                line_no = c_idx + 1
                block_lines.append(f"  {marker} {line_no:4d} | {lines[c_idx]}")
            output_blocks.append("\n".join(block_lines))

    if not output_blocks:
        return f"No matches found for pattern '{pattern}'."

    summary = f"Found {matches_found} match{'es' if matches_found != 1 else ''}:\n\n"
    res = summary + "\n\n".join(output_blocks)
    if matches_found >= max_matches:
        res += f"\n\n[Showing top {max_matches} matches. Results capped.]"
    return res


def _ripgrep_search(
    workspace_root: Path,
    pattern: str,
    path_glob: str | None = None,
    regex: bool = True,
    max_matches: int = MAX_GREP_MATCHES,
) -> str | None:
    """Run ripgrep (rg) if installed, returning formatted output with 2 lines of context."""
    rg_path = shutil.which("rg")
    if not rg_path:
        return None

    cmd = [
        rg_path,
        "-n",
        "-C",
        "2",
        "--color",
        "never",
        "--max-count",
        str(max_matches),
    ]

    if not regex:
        cmd.append("-F")

    if path_glob:
        cmd.extend(["-g", path_glob])

    cmd.extend(
        [
            "-g",
            "!node_modules",
            "-g",
            "!.venv",
            "-g",
            "!.git",
            "-g",
            "!dist",
            "-g",
            "!build",
        ]
    )
    cmd.extend(["--", pattern, "."])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None

    if proc.returncode == 1:
        return f"No matches found for pattern '{pattern}'."
    elif proc.returncode == 0:
        raw_output = proc.stdout.strip()
        if not raw_output:
            return f"No matches found for pattern '{pattern}'."
        return raw_output

    return None


def grep_search_sync(
    pattern: str,
    path_glob: str | None = None,
    regex: bool = True,
    workspace_root: Path | None = None,
) -> str:
    """Execute grep search returning matching lines and 2 lines of context."""
    root = workspace_root or Path.cwd()
    rg_result = _ripgrep_search(root, pattern, path_glob=path_glob, regex=regex)
    if rg_result is not None:
        return rg_result
    return _python_fallback_grep(root, pattern, path_glob=path_glob, regex=regex)


def semantic_search_sync(
    query: str,
    k: int = 8,
    workspace_root: Path | None = None,
) -> str:
    """Execute semantic code search across workspace vector index."""
    from lathe.context.index import CodeIndex

    root = workspace_root or Path.cwd()
    index = CodeIndex(workspace_root=root)

    results = index.search(query, k=k)
    if not results:
        return f"No semantic search results found for query: '{query}'."

    output_lines: list[str] = [
        f"Semantic search results for: '{query}' (top {len(results)} chunks):\n"
    ]

    for res in results:
        header = (
            f"### [{res.rank}] {res.file_path}:{res.start_line}-{res.end_line} "
            f"({res.symbol_kind}: {res.symbol_name}) — Score: {res.score:.3f}"
        )
        output_lines.append(header)
        output_lines.append("```")
        output_lines.append(res.content)
        output_lines.append("```\n")

    return "\n".join(output_lines)


class GrepSearchTool(Tool):
    """Tool performing exact or regex search across workspace files."""

    name: str = "grep_search"
    description: str = (
        "Fast text and regex search across workspace files with line numbers "
        "and 2 lines of context. Use this tool when you know the exact name "
        "of a function, class, variable, import, or error message (e.g. 'def get_user', "
        "'class LatheConfig', 'TODO'). Do NOT use for conceptual or fuzzy questions."
    )
    args_schema: type[BaseModel] = GrepSearchArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        if isinstance(args, GrepSearchArgs):
            pattern = args.pattern
            path_glob = args.path_glob
            regex = args.regex
        else:
            pattern = str(args.get("pattern", ""))
            path_glob = args.get("path_glob")
            regex = bool(args.get("regex", True))

        root = ctx.workspace_root
        output = grep_search_sync(pattern, path_glob=path_glob, regex=regex, workspace_root=root)
        return ToolResult(
            ok=True,
            output=output,
            metadata={"pattern": pattern, "regex": regex, "glob": path_glob},
        )

    def __call__(
        self,
        pattern: str,
        path_glob: str | None = None,
        regex: bool = True,
        context: ToolContext | None = None,
    ) -> str:
        root = context.workspace_root if context else Path.cwd()
        return grep_search_sync(pattern, path_glob=path_glob, regex=regex, workspace_root=root)


class SemanticSearchTool(Tool):
    """Tool performing semantic natural language code search across vector index."""

    name: str = "semantic_search"
    description: str = (
        "Semantic natural language search across the workspace using vector embeddings. "
        "Automatically refreshes stale files before searching. Returns top matching code chunks "
        "with file paths, line ranges, symbol headers, and relevance scores. "
        "Use this tool for conceptual queries when you don't know exact function or class names "
        "(e.g. 'where is user authentication handled?', 'how are checkpoints saved?'). "
        "Do NOT use when looking for exact names or string literals (use grep_search instead)."
    )
    args_schema: type[BaseModel] = SemanticSearchArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        if isinstance(args, SemanticSearchArgs):
            query = args.query
            k = args.k
        else:
            query = str(args.get("query", ""))
            k = int(args.get("k", 8))

        root = ctx.workspace_root
        output = semantic_search_sync(query, k=k, workspace_root=root)
        return ToolResult(
            ok=True,
            output=output,
            metadata={"query": query, "k": k},
        )

    def __call__(
        self,
        query: str,
        k: int = 8,
        context: ToolContext | None = None,
    ) -> str:
        root = context.workspace_root if context else Path.cwd()
        return semantic_search_sync(query, k=k, workspace_root=root)


# Singletons for convenient import and registry usage
grep_search = GrepSearchTool()
semantic_search = SemanticSearchTool()

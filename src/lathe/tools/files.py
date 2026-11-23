"""Read-side and create-side workspace file tools with security boundary enforcement."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from lathe.safety.workspace import PathEscapeError, Workspace
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult

DEFAULT_MAX_FILE_SIZE_BYTES = 256 * 1024  # 256 KB limit before requiring line ranges


def is_binary_file(file_path: Path) -> bool:
    """Detect whether a file contains binary or non-UTF-8 content."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(4096)
            if b"\x00" in chunk:
                return True
            # Attempt decoding chunk as UTF-8
            chunk.decode("utf-8")
            return False
    except UnicodeDecodeError:
        return True
    except OSError:
        return False


def render_compact_tree(
    target_dir: Path,
    workspace: Workspace,
    max_depth: int = 2,
    current_depth: int = 1,
    prefix: str = "",
) -> list[str]:
    """Recursively render a compact ASCII tree of directory contents."""
    lines: list[str] = []
    try:
        raw_entries = list(target_dir.iterdir())
    except (PermissionError, OSError) as exc:
        return [f"{prefix}└── [error reading directory: {exc}]"]

    # Filter out entries matching ignored patterns or default ignored directories
    filtered: list[Path] = []
    for entry in raw_entries:
        if not workspace.is_ignored(entry, is_dir=entry.is_dir()):
            filtered.append(entry)

    # Sort directories first, then files, both case-insensitively
    sorted_entries = sorted(
        filtered,
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )

    total = len(sorted_entries)
    for i, entry in enumerate(sorted_entries):
        is_last = i == total - 1
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "
        display_name = entry.name + ("/" if entry.is_dir() else "")
        lines.append(f"{prefix}{connector}{display_name}")

        if entry.is_dir() and current_depth < max_depth:
            sub_lines = render_compact_tree(
                entry,
                workspace=workspace,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                prefix=prefix + child_prefix,
            )
            lines.extend(sub_lines)

    return lines


# =====================================================================
# 1. read_file
# =====================================================================


class ReadFileArgs(BaseModel):
    """Arguments for reading a file from the workspace."""

    path: str = Field(
        description="Path of the file to read (relative to the workspace root).",
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="Optional 1-based start line number (inclusive).",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="Optional 1-based end line number (inclusive).",
    )


class ReadFileTool(Tool):
    """Tool to read the textual contents of a workspace file with numbered lines."""

    name = "read_file"
    description = (
        "Read the textual contents of a file within the workspace with line numbers.\n"
        "WHEN TO USE:\n"
        "- Inspecting existing source code, configuration files, or documentation.\n"
        "- When reading large files, always specify 'start_line' and 'end_line' to inspect "
        "specific sections and conserve token context.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use for binary files (e.g. images, audio, compiled binaries, zip archives).\n"
        "- Do NOT use to list files in a folder (use 'list_dir' instead).\n"
        "- Do NOT use to search for patterns across files (use search/grep tools instead).\n"
        "- Do NOT use paths that escape the workspace root."
    )
    args_schema = ReadFileArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        workspace: Workspace = ctx.get_workspace()
        try:
            resolved_path = workspace.resolve_path(args.path)
        except PathEscapeError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not resolved_path.exists():
            return ToolResult(
                ok=False,
                output="",
                error=f"File not found: '{args.path}'. Verify the path and retry.",
            )

        if resolved_path.is_dir():
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Path '{args.path}' is a directory, not a file. "
                    "Use 'list_dir' to view its contents."
                ),
            )

        if is_binary_file(resolved_path):
            return ToolResult(
                ok=False,
                output="",
                error=f"Cannot read '{args.path}': file is binary or contains non-text characters.",
            )

        try:
            file_stat = resolved_path.stat()
        except OSError as exc:
            return ToolResult(ok=False, output="", error=f"Cannot read '{args.path}': {exc}")

        # Check file size limit if line range is not specified
        if (
            file_stat.st_size > DEFAULT_MAX_FILE_SIZE_BYTES
            and args.start_line is None
            and args.end_line is None
        ):
            size_kb = file_stat.st_size / 1024
            limit_kb = DEFAULT_MAX_FILE_SIZE_BYTES / 1024
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"File '{args.path}' exceeds size limit "
                    f"({size_kb:.1f} KB > {limit_kb:.0f} KB). "
                    "Please specify 'start_line' and 'end_line' to read specific sections."
                ),
            )

        # Validate line range parameters
        if (
            args.start_line is not None
            and args.end_line is not None
            and args.start_line > args.end_line
        ):
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Invalid line range: start_line ({args.start_line}) cannot be "
                    f"greater than end_line ({args.end_line})."
                ),
            )

        # Read lines efficiently
        selected_lines: list[tuple[int, str]] = []
        total_lines = 0
        try:
            with open(resolved_path, encoding="utf-8", errors="replace") as f:
                for line_no, raw_line in enumerate(f, start=1):
                    total_lines += 1
                    if args.start_line is not None and line_no < args.start_line:
                        continue
                    if args.end_line is not None and line_no > args.end_line:
                        continue
                    clean_line = raw_line.rstrip("\r\n")
                    selected_lines.append((line_no, clean_line))
        except OSError as exc:
            return ToolResult(ok=False, output="", error=f"Failed reading '{args.path}': {exc}")

        if total_lines == 0:
            return ToolResult(
                ok=True,
                output="(File is empty)",
                metadata={"path": workspace.relpath(resolved_path), "total_lines": 0},
            )

        if args.start_line is not None and args.start_line > total_lines:
            return ToolResult(
                ok=True,
                output=(
                    f"(File has {total_lines} lines; start_line {args.start_line} "
                    "is beyond end of file)"
                ),
                metadata={
                    "path": workspace.relpath(resolved_path),
                    "total_lines": total_lines,
                    "start_line": args.start_line,
                    "end_line": args.end_line,
                },
            )

        width = max(len(str(total_lines)), 4)
        formatted = [f"{line_no:{width}d} | {line}" for line_no, line in selected_lines]
        rel_path = workspace.relpath(resolved_path)
        body = "\n".join(formatted)
        output_text = (
            f"[UNTRUSTED REPOSITORY CONTENT START: {rel_path}]\n"
            f"{body}\n"
            f"[UNTRUSTED REPOSITORY CONTENT END: {rel_path}]"
        )

        return ToolResult(
            ok=True,
            output=output_text,
            metadata={
                "path": workspace.relpath(resolved_path),
                "total_lines": total_lines,
                "start_line": args.start_line or 1,
                "end_line": args.end_line or total_lines,
                "lines_read": len(selected_lines),
            },
        )


# =====================================================================
# 2. list_dir
# =====================================================================


class ListDirArgs(BaseModel):
    """Arguments for listing directory contents as a compact tree."""

    path: str = Field(
        default=".",
        description="Relative directory path to inspect. Defaults to '.' (workspace root).",
    )
    depth: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum directory traversal depth (default 2).",
    )


class ListDirTool(Tool):
    """Tool to inspect directory structure as a compact hierarchical tree."""

    name = "list_dir"
    description = (
        "List directory contents and structure as a compact tree up to the specified depth.\n"
        "WHEN TO USE:\n"
        "- Exploring repository organization, finding files, or checking directory hierarchy.\n"
        "- Defaults to the workspace root ('.') with depth=2.\n"
        "- Automatically ignores node_modules, .venv, .git, build directories, and rules in "
        ".gitignore/.latheignore.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use to inspect file contents (use 'read_file' instead).\n"
        "- Do NOT set excessive depth on large projects; use 'glob' or targeted paths instead.\n"
        "- Do NOT use paths that escape the workspace root."
    )
    args_schema = ListDirArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: ListDirArgs, ctx: ToolContext) -> ToolResult:
        workspace: Workspace = ctx.get_workspace()
        try:
            resolved_dir = workspace.resolve_path(args.path)
        except PathEscapeError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        if not resolved_dir.exists():
            return ToolResult(
                ok=False,
                output="",
                error=f"Directory not found: '{args.path}'. Verify the path and retry.",
            )

        if not resolved_dir.is_dir():
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Path '{args.path}' is a file, not a directory. "
                    "Use 'read_file' to view its contents."
                ),
            )

        rel_label = workspace.relpath(resolved_dir)
        header = f"{rel_label}/" if rel_label != "." else "."

        tree_lines = render_compact_tree(
            target_dir=resolved_dir,
            workspace=workspace,
            max_depth=args.depth,
            current_depth=1,
        )

        if not tree_lines:
            output_text = f"{header}\n└── (empty)"
        else:
            output_text = f"{header}\n" + "\n".join(tree_lines)

        return ToolResult(
            ok=True,
            output=output_text,
            metadata={
                "path": rel_label,
                "depth": args.depth,
                "entries_rendered": len(tree_lines),
            },
        )


# =====================================================================
# 3. glob
# =====================================================================


class GlobArgs(BaseModel):
    """Arguments for finding files matching a pattern."""

    pattern: str = Field(
        description="Glob pattern to search for (e.g. 'src/**/*.py', 'tests/test_*.py', '*.md').",
    )


class GlobTool(Tool):
    """Tool to find files matching a glob pattern across the workspace."""

    name = "glob"
    description = (
        "Find files matching a glob pattern across the workspace.\n"
        "WHEN TO USE:\n"
        "- Locating files by filename, extension, or path pattern (e.g. 'src/**/*.py', '*.md').\n"
        "- Fast discovery without reading entire directory trees.\n"
        "- Automatically filters out ignored directories (.git, .venv, node_modules, build) "
        "and files matching .gitignore/.latheignore.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use to search for textual content inside files (use search/grep tools instead).\n"
        "- Do NOT use directory traversal sequences ('../') to escape the workspace."
    )
    args_schema = GlobArgs
    risk_level: RiskLevel = "read"

    async def _execute(self, args: GlobArgs, ctx: ToolContext) -> ToolResult:
        workspace: Workspace = ctx.get_workspace()
        pattern = args.pattern.strip()

        # Reject path escape patterns in glob
        if pattern.startswith("../") or "/../" in pattern or pattern == "..":
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Glob pattern '{args.pattern}' cannot contain "
                    "directory traversal sequences ('..')."
                ),
            )

        # Handle leading slash as relative to root
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        try:
            matched_paths = list(workspace.root.glob(pattern))
        except Exception as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"Invalid glob pattern '{args.pattern}': {exc}",
            )

        valid_matches: list[str] = []
        for matched in matched_paths:
            # Skip if resolved path escapes root
            try:
                resolved = workspace.resolve_path(matched)
            except PathEscapeError:
                continue

            if not workspace.is_ignored(resolved, is_dir=resolved.is_dir()):
                valid_matches.append(workspace.relpath(resolved))

        sorted_matches = sorted(set(valid_matches))

        if not sorted_matches:
            return ToolResult(
                ok=True,
                output=f"No files matched pattern: '{args.pattern}'.",
                metadata={"pattern": args.pattern, "matches": [], "count": 0},
            )

        output_text = "\n".join(sorted_matches)
        return ToolResult(
            ok=True,
            output=output_text,
            metadata={
                "pattern": args.pattern,
                "matches": sorted_matches,
                "count": len(sorted_matches),
            },
        )


# =====================================================================
# 4. write_file
# =====================================================================


class WriteFileArgs(BaseModel):
    """Arguments for creating a new file in the workspace."""

    path: str = Field(
        description="Relative path of the new file to create.",
    )
    content: str = Field(
        description="Full textual content to write into the new file.",
    )


class WriteFileTool(Tool):
    """Tool to create a brand new file in the workspace with initial content."""

    name = "write_file"
    description = (
        "Create a brand new file in the workspace with the specified text content.\n"
        "WHEN TO USE:\n"
        "- Creating a new file from scratch. Intermediate directories are created automatically.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use to edit or overwrite existing files (this tool returns an error if the file "
        "already exists; use edit/patch tools instead).\n"
        "- Do NOT use for binary files.\n"
        "- Do NOT use paths that escape the workspace root."
    )
    args_schema = WriteFileArgs
    risk_level: RiskLevel = "write"

    async def _execute(self, args: WriteFileArgs, ctx: ToolContext) -> ToolResult:
        workspace: Workspace = ctx.get_workspace()
        try:
            resolved_path = workspace.resolve_path(args.path)
        except PathEscapeError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        # Enforce that write_file is strictly for NEW files
        if resolved_path.exists():
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"File already exists at '{args.path}'. write_file only creates new files. "
                    "Use edit tools to modify existing files."
                ),
            )

        # Create parent directories if needed
        try:
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"Failed to create file '{args.path}': {exc}",
            )

        line_count = len(args.content.splitlines()) if args.content else 0
        char_count = len(args.content)
        byte_count = len(args.content.encode("utf-8"))
        rel_path = workspace.relpath(resolved_path)

        msg = f"Successfully created file '{rel_path}' ({char_count} chars, {line_count} lines)."
        return ToolResult(
            ok=True,
            output=msg,
            metadata={
                "path": rel_path,
                "lines": line_count,
                "characters": char_count,
                "bytes": byte_count,
            },
        )


# Singleton instances for convenient import
read_file = ReadFileTool()
list_dir = ListDirTool()
glob = GlobTool()
write_file = WriteFileTool()

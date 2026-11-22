"""Atomic search-and-replace file editing tool with diff inspection and encoding preservation."""

from __future__ import annotations

import difflib
import re

from pydantic import BaseModel, Field

from lathe.safety.workspace import PathEscapeError, Workspace
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from lathe.tools.files import is_binary_file
from lathe.ui.diff import print_diff_panel


class EditOperation(BaseModel):
    """A single search-and-replace edit specification."""

    old: str = Field(
        min_length=1,
        description="Exact block of lines or text to search for and replace.",
    )
    new: str = Field(
        description="New replacement text to substitute in place of 'old'.",
    )


class EditFileArgs(BaseModel):
    """Arguments for editing an existing workspace file."""

    path: str = Field(
        description="Path of the file to edit (relative to the workspace root).",
    )
    edits: list[EditOperation] = Field(
        min_length=1,
        description="Ordered list of search-and-replace edits to apply atomically.",
    )


def detect_encoding_and_newline(raw_bytes: bytes) -> tuple[str, str]:
    """Detect file character encoding and dominant newline convention (LF vs CRLF)."""
    # Detect BOM or UTF-8
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            raw_bytes.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "latin-1"

    # Detect dominant line ending
    line_ending = "\r\n" if b"\r\n" in raw_bytes else "\n"
    return encoding, line_ending


def find_all_occurrences(content: str, sub: str) -> list[int]:
    """Return 1-based line numbers where exact substring matches begin."""
    line_numbers: list[int] = []
    start = 0
    while True:
        idx = content.find(sub, start)
        if idx == -1:
            break
        line_no = content[:idx].count("\n") + 1
        line_numbers.append(line_no)
        start = idx + len(sub)
    return line_numbers


def normalize_line(line: str) -> str:
    """Normalize line by collapsing all whitespace sequences to a single space."""
    return " ".join(line.split())


def find_closest_matching_lines(content: str, old: str) -> tuple[int, list[str]]:
    """Locate the window of lines in content most similar to the target old block."""
    c_lines = content.splitlines()
    o_lines = old.splitlines()
    if not c_lines:
        return 1, []

    window_size = max(1, len(o_lines))
    best_ratio = -1.0
    best_start = 0

    target_str = "\n".join(normalize_line(line) for line in o_lines)
    for i in range(max(1, len(c_lines) - window_size + 1)):
        window = c_lines[i : i + window_size]
        window_str = "\n".join(normalize_line(line) for line in window)
        ratio = difflib.SequenceMatcher(None, target_str, window_str).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    start_line_no = best_start + 1
    closest = c_lines[best_start : best_start + window_size]
    return start_line_no, closest


def build_flexible_pattern(text: str) -> str:
    """Build a regex pattern allowing flexible whitespace and spacing around punctuation."""
    tokens = re.findall(r"\w+|[^\w\s]", text)
    if not tokens:
        return ""
    parts = [re.escape(tokens[0])]
    for i in range(1, len(tokens)):
        prev = tokens[i - 1]
        curr = tokens[i]
        if prev.isalnum() and curr.isalnum():
            parts.append(r"\s+")
        else:
            parts.append(r"\s*")
        parts.append(re.escape(curr))
    return "".join(parts)


def apply_single_edit(
    content: str,
    old: str,
    new: str,
    path: str,
) -> tuple[bool, str, str | None]:
    """Apply a single search-and-replace edit to content with fallback heuristics.

    Returns:
        (success, updated_content, error_message)
    """
    # 1. Exact string matching
    exact_count = content.count(old)
    if exact_count == 1:
        updated = content.replace(old, new, 1)
        return True, updated, None

    if exact_count > 1:
        match_lines = find_all_occurrences(content, old)
        return (
            False,
            content,
            (
                f"Ambiguous edit in '{path}': found {exact_count} exact matches for 'old' block "
                f"at line(s) {match_lines}. Please provide more surrounding lines in 'old' "
                "to uniquely identify the location."
            ),
        )

    # 2. Whitespace-insensitive line-based matching
    c_lines = content.splitlines(keepends=True)
    o_lines = old.splitlines(keepends=True)

    norm_c = [normalize_line(line) for line in c_lines]
    norm_o = [normalize_line(line) for line in o_lines]

    line_matches: list[int] = [
        i for i in range(len(norm_c) - len(norm_o) + 1) if norm_c[i : i + len(norm_o)] == norm_o
    ]

    if len(line_matches) == 1:
        start_idx = line_matches[0]
        end_idx = start_idx + len(norm_o)
        # Ensure trailing newline is preserved if original old block had one
        replacement = new if (new.endswith("\n") or not old.endswith("\n")) else new + "\n"

        before = "".join(c_lines[:start_idx])
        after = "".join(c_lines[end_idx:])
        return True, before + replacement + after, None

    if len(line_matches) > 1:
        lines_found = [m + 1 for m in line_matches]
        return (
            False,
            content,
            (
                f"Ambiguous edit in '{path}': found {len(line_matches)} whitespace-insensitive "
                f"matches at line(s) {lines_found}. "
                "Please include more surrounding context in 'old'."
            ),
        )

    # 3. Flexible token-based regex match for inline edits and spacing around punctuation
    pattern = build_flexible_pattern(old)
    if pattern:
        try:
            regex_matches = list(re.finditer(pattern, content))
        except re.error:
            regex_matches = []

        if len(regex_matches) == 1:
            span = regex_matches[0].span()
            updated = content[: span[0]] + new + content[span[1] :]
            return True, updated, None

        if len(regex_matches) > 1:
            lines_found = [content[: m.start()].count("\n") + 1 for m in regex_matches]
            return (
                False,
                content,
                (
                    f"Ambiguous edit in '{path}': found {len(regex_matches)} "
                    f"whitespace-insensitive token matches at line(s) {lines_found}. "
                    "Please provide more surrounding lines."
                ),
            )

    # 4. No match found: retrieve closest matching lines to guide model recovery
    start_line_no, closest_lines = find_closest_matching_lines(content, old)
    closest_fmt = "\n".join(
        f"{start_line_no + idx:4d} | {line}" for idx, line in enumerate(closest_lines)
    )
    if not closest_fmt:
        closest_fmt = "  (file is empty)"

    return (
        False,
        content,
        (
            f"Failed to find match for 'old' block in '{path}'.\n"
            "No exact or whitespace-insensitive match found.\n"
            f"Closest matching lines in the file (around line {start_line_no}):\n"
            f"{closest_fmt}\n"
            "Please check the exact content and retry."
        ),
    )


def calculate_diff(
    original_text: str,
    modified_text: str,
    rel_path: str,
) -> tuple[str, int, int, str]:
    """Generate a unified diff and compute line statistics (+N -M lines)."""
    orig_lines = original_text.splitlines(keepends=True)
    mod_lines = modified_text.splitlines(keepends=True)

    diff_list = list(
        difflib.unified_diff(
            orig_lines,
            mod_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )
    diff_text = "".join(diff_list)

    added = 0
    removed = 0
    for line in diff_list:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1

    summary = f"+{added} -{removed} lines"
    return diff_text, added, removed, summary


class EditFileTool(Tool):
    """Tool to apply atomic search-and-replace edits to existing workspace files."""

    name = "edit_file"
    description = (
        "Perform atomic search-and-replace edits on an existing workspace file.\n"
        "WHEN TO USE:\n"
        "- Modifying, refactoring, or updating existing code or text files.\n"
        "- Applying one or multiple edits atomically (all edits succeed or none apply).\n"
        "- Supply sufficient surrounding context in 'old' to ensure a unique match.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use to create brand new files (use 'write_file' instead).\n"
        "- Do NOT use for binary files.\n"
        "- Do NOT use paths that escape the workspace root."
    )
    args_schema = EditFileArgs
    risk_level: RiskLevel = "write"

    async def _execute(self, args: EditFileArgs, ctx: ToolContext) -> ToolResult:
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
                error=f"Path '{args.path}' is a directory, not a file.",
            )

        if is_binary_file(resolved_path):
            return ToolResult(
                ok=False,
                output="",
                error=f"Cannot edit binary file: '{args.path}'.",
            )

        # Read original bytes and detect encoding and line ending convention
        try:
            raw_bytes = resolved_path.read_bytes()
        except OSError as exc:
            return ToolResult(ok=False, output="", error=f"Cannot read '{args.path}': {exc}")

        encoding, native_newline = detect_encoding_and_newline(raw_bytes)
        try:
            original_text = raw_bytes.decode(encoding)
        except UnicodeDecodeError as exc:
            return ToolResult(ok=False, output="", error=f"Failed decoding '{args.path}': {exc}")

        # Normalize line endings in-memory for consistent matching
        normalized_original = original_text.replace("\r\n", "\n")
        working_content = normalized_original
        rel_path = workspace.relpath(resolved_path)

        # Simulate all edits in sequence; enforce atomic rollback on any failure
        for idx, edit_op in enumerate(args.edits, start=1):
            norm_old = edit_op.old.replace("\r\n", "\n")
            norm_new = edit_op.new.replace("\r\n", "\n")

            success, updated_content, err_msg = apply_single_edit(
                content=working_content,
                old=norm_old,
                new=norm_new,
                path=rel_path,
            )
            if not success:
                # Atomic rollback: file on disk remains completely untouched
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"Edit {idx} of {len(args.edits)} failed: {err_msg}",
                    metadata={"failed_index": idx - 1, "path": rel_path},
                )
            working_content = updated_content

        # Generate unified diff
        diff_text, added, removed, summary = calculate_diff(
            original_text=normalized_original,
            modified_text=working_content,
            rel_path=rel_path,
        )

        # Show colored diff in Rich panel before applying
        print_diff_panel(diff_text, rel_path)

        # Re-apply native line endings (CRLF vs LF)
        if native_newline == "\r\n":
            final_text = working_content.replace("\r\n", "\n").replace("\n", "\r\n")
        else:
            final_text = working_content.replace("\r\n", "\n")

        # Atomically write final content to disk
        try:
            resolved_path.write_bytes(final_text.encode(encoding))
        except OSError as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"Failed writing changes to '{args.path}': {exc}",
            )

        return ToolResult(
            ok=True,
            output=f"Successfully edited '{rel_path}' ({summary}).",
            metadata={
                "path": rel_path,
                "summary": summary,
                "added": added,
                "removed": removed,
                "diff": diff_text,
                "encoding": encoding,
                "line_ending": "CRLF" if native_newline == "\r\n" else "LF",
            },
        )


# Singleton instance for convenient export and registration
edit_file = EditFileTool()

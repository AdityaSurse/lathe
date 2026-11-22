"""Repository map generator utilizing tree-sitter AST symbol indexing and personalized PageRank."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import tree_sitter_language_pack as tslp

from lathe.safety.workspace import Workspace

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

COMMON_IGNORED_IDENTIFIERS: set[str] = {
    "self",
    "cls",
    "this",
    "super",
    "int",
    "str",
    "float",
    "bool",
    "char",
    "void",
    "any",
    "object",
    "string",
    "number",
    "boolean",
    "true",
    "false",
    "null",
    "nil",
    "none",
    "err",
    "error",
    "return",
    "if",
    "else",
    "for",
    "while",
    "switch",
    "case",
    "break",
    "continue",
    "import",
    "from",
    "as",
    "export",
    "default",
    "package",
    "func",
    "fn",
    "def",
    "var",
    "let",
    "const",
    "type",
    "struct",
    "class",
    "interface",
}

DEFINITION_NODE_TYPES: set[str] = {
    "class_definition",
    "class_declaration",
    "class_specifier",
    "function_definition",
    "function_declaration",
    "function_item",
    "method_definition",
    "method_declaration",
    "struct_item",
    "struct_specifier",
    "interface_declaration",
    "trait_item",
    "type_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "enum_item",
    "constructor_declaration",
}

BODY_CONTAINER_TYPES: set[str] = {
    "block",
    "compound_statement",
    "statement_block",
    "declaration_list",
    "field_declaration_list",
    "class_body",
    "enum_body",
}


@dataclass
class SymbolDef:
    """Represents a code definition signature extracted from an AST."""

    name: str
    kind: str
    signature: str
    line: int
    indent: int


@dataclass
class FileSymbols:
    """Indexed definitions and reference identifiers for a single workspace file."""

    path: str
    mtime: float
    size: int
    definitions: list[SymbolDef]
    references: set[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize into a cache-storable dictionary."""
        return {
            "path": self.path,
            "mtime": self.mtime,
            "size": self.size,
            "definitions": [asdict(d) for d in self.definitions],
            "references": sorted(self.references),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileSymbols:
        """Deserialize from a cached dictionary."""
        defs = [SymbolDef(**d) for d in data.get("definitions", [])]
        refs = set(data.get("references", []))
        return cls(
            path=data["path"],
            mtime=data["mtime"],
            size=data["size"],
            definitions=defs,
            references=refs,
        )


def estimate_tokens(text: str) -> int:
    """Heuristic token count estimation (~3.7 characters per token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 3.7))


def extract_symbol_name(node: Any, code_bytes: bytes) -> str:
    """Extract symbol name from AST node across various language grammars."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return code_bytes[name_node.start_byte : name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

    # In Go type_declaration, inspect type_spec child
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                ts_name = child.child_by_field_name("name")
                if ts_name:
                    return code_bytes[ts_name.start_byte : ts_name.end_byte].decode(
                        "utf-8", errors="replace"
                    )

    # In C/C++ function_definition, inspect declarator child
    if node.type in ("function_definition", "declaration"):
        declarator = node.child_by_field_name("declarator")
        if declarator:
            for c in declarator.children:
                if c.type in ("identifier", "field_identifier"):
                    return code_bytes[c.start_byte : c.end_byte].decode("utf-8", errors="replace")
            # If declarator itself is identifier
            if declarator.type in ("identifier", "field_identifier"):
                return code_bytes[declarator.start_byte : declarator.end_byte].decode(
                    "utf-8", errors="replace"
                )

    return ""


def extract_node_signature(node: Any, code_bytes: bytes, kind: str) -> str:
    """Extract signature declaration up to body, removing code bodies."""
    body_node = node.child_by_field_name("body")
    if not body_node:
        for c in node.children:
            if c.type in BODY_CONTAINER_TYPES:
                body_node = c
                break

    if body_node:
        raw_sig = code_bytes[node.start_byte : body_node.start_byte].decode(
            "utf-8", errors="replace"
        )
    else:
        # Fallback to first line of node
        first_line = (
            code_bytes[node.start_byte : node.end_byte]
            .decode("utf-8", errors="replace")
            .splitlines()[0]
        )
        raw_sig = first_line

    cleaned = " ".join(raw_sig.strip().split())
    # Strip trailing '{' or trailing opening tokens for clean display
    cleaned = re.sub(r"\s*\{\s*$", "", cleaned)
    return cleaned.strip()


def parse_file_symbols(file_path: Path, relative_path: str) -> FileSymbols:
    """Parse file with tree-sitter, returning extracted definitions and references."""
    stat = file_path.stat()
    ext = file_path.suffix.lower()
    lang = SUPPORTED_EXTENSIONS.get(ext)
    if not lang:
        return FileSymbols(
            path=relative_path,
            mtime=stat.st_mtime,
            size=stat.st_size,
            definitions=[],
            references=set(),
        )

    try:
        code_bytes = file_path.read_bytes()
    except Exception:
        return FileSymbols(
            path=relative_path,
            mtime=stat.st_mtime,
            size=stat.st_size,
            definitions=[],
            references=set(),
        )

    try:
        parser = tslp.get_parser(lang)
        tree = parser.parse(code_bytes)
    except Exception:
        return FileSymbols(
            path=relative_path,
            mtime=stat.st_mtime,
            size=stat.st_size,
            definitions=[],
            references=set(),
        )

    definitions: list[SymbolDef] = []
    references: set[str] = set()

    def determine_kind(node_type: str) -> str:
        if "class" in node_type:
            return "class"
        if "method" in node_type:
            return "method"
        if "function" in node_type:
            return "function"
        if "struct" in node_type:
            return "struct"
        if "interface" in node_type or "trait" in node_type:
            return "interface"
        if "type" in node_type:
            return "type"
        if "enum" in node_type:
            return "enum"
        return "def"

    def traverse(node: Any, current_indent: int = 0) -> None:
        if node.type in DEFINITION_NODE_TYPES:
            kind = determine_kind(node.type)
            name = extract_symbol_name(node, code_bytes)
            sig = extract_node_signature(node, code_bytes, kind)

            if sig and name:
                definitions.append(
                    SymbolDef(
                        name=name,
                        kind=kind,
                        signature=sig,
                        line=node.start_point[0] + 1,
                        indent=current_indent,
                    )
                )

            # Check if this node has a body container to recurse into with increased indent
            body_node = node.child_by_field_name("body")
            if not body_node:
                for c in node.children:
                    if c.type in BODY_CONTAINER_TYPES:
                        body_node = c
                        break

            if body_node:
                for c in body_node.children:
                    traverse(c, current_indent + 2)
                return

        # Collect references
        if node.type in (
            "identifier",
            "type_identifier",
            "field_identifier",
            "property_identifier",
            "scoped_identifier",
        ):
            text = code_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
            clean_ident = text.strip()
            if len(clean_ident) > 1 and clean_ident.lower() not in COMMON_IGNORED_IDENTIFIERS:
                references.add(clean_ident)

        for c in node.children:
            traverse(c, current_indent)

    traverse(tree.root_node, current_indent=0)

    return FileSymbols(
        path=relative_path,
        mtime=stat.st_mtime,
        size=stat.st_size,
        definitions=definitions,
        references=references,
    )


class RepoMap:
    """Generates compact, high-value repository maps via personalized PageRank ranking."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        token_budget: int = 2048,
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.token_budget = token_budget
        self.cache_dir = self.workspace_root / ".lathe" / "cache"
        self.cache_file = self.cache_dir / "repomap.json"
        self._workspace = Workspace(self.workspace_root)

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """Load cached AST definitions from .lathe/cache/repomap.json."""
        if not self.cache_file.is_file():
            return {}
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_cache(self, cache_data: dict[str, Any]) -> None:
        """Persist AST definitions to .lathe/cache/repomap.json."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            pass

    def scan_workspace(self) -> dict[str, FileSymbols]:
        """Discover and index symbols for all supported files in the repository."""
        cached_data = self._load_cache()
        updated_cache: dict[str, Any] = {}
        file_symbols: dict[str, FileSymbols] = {}

        # Walk workspace files respecting workspace boundary and ignore rules
        for root, dirs, files in os.walk(self.workspace_root):
            root_path = Path(root)

            # Filter out ignored directories in-place
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and not self._workspace.is_ignored(root_path / d)
                and d not in ("node_modules", ".venv", ".git", "build", "dist")
            ]

            for file_name in files:
                if file_name.startswith("."):
                    continue

                full_path = root_path / file_name
                if self._workspace.is_ignored(full_path):
                    continue

                ext = full_path.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                try:
                    rel_path = str(full_path.relative_to(self.workspace_root))
                except ValueError:
                    continue

                try:
                    stat = full_path.stat()
                except OSError:
                    continue

                # Check cache validity
                cached_file = cached_data.get(rel_path)
                if (
                    cached_file
                    and cached_file.get("mtime") == stat.st_mtime
                    and cached_file.get("size") == stat.st_size
                ):
                    fs = FileSymbols.from_dict(cached_file)
                else:
                    fs = parse_file_symbols(full_path, rel_path)

                file_symbols[rel_path] = fs
                updated_cache[rel_path] = fs.to_dict()

        self._save_cache(updated_cache)
        return file_symbols

    def build_graph(
        self, file_symbols: dict[str, FileSymbols]
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """Build reference graph edges between files based on symbol definitions and calls."""
        # Map symbol name -> set of files where it is defined
        symbol_to_files: dict[str, set[str]] = {}
        for path, fs in file_symbols.items():
            for d in fs.definitions:
                symbol_to_files.setdefault(d.name, set()).add(path)

        out_edges: dict[str, set[str]] = {p: set() for p in file_symbols}
        in_edges: dict[str, set[str]] = {p: set() for p in file_symbols}

        for path, fs in file_symbols.items():
            for ref in fs.references:
                target_files = symbol_to_files.get(ref, set())
                for target in target_files:
                    if target != path:
                        out_edges[path].add(target)
                        in_edges[target].add(path)

        return out_edges, in_edges

    def personalized_pagerank(
        self,
        file_symbols: dict[str, FileSymbols],
        out_edges: dict[str, set[str]],
        in_edges: dict[str, set[str]],
        task: str = "",
        mentioned_files: list[str] | None = None,
        edited_files: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Rank repository files using Personalized PageRank with multi-factor weighting."""
        files = list(file_symbols.keys())
        n = len(files)
        if n == 0:
            return []
        if n == 1:
            return [(files[0], 1.0)]

        # Extract task keywords
        task_words = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", task.lower()))
        mentioned_set = set(mentioned_files or [])
        edited_set = set(edited_files or [])

        # Compute personalization vector
        weights: dict[str, float] = {}
        for f in files:
            w = 1.0
            fs = file_symbols[f]

            # Boost 1: User explicitly mentioned file (@file or path)
            if f in mentioned_set or any(m in f for m in mentioned_set):
                w += 20.0

            # Boost 2: File was edited this session
            if f in edited_set or any(e in f for e in edited_set):
                w += 10.0

            # Boost 3: Match task words against filename and defined symbol names
            path_words = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", f.lower()))
            symbol_words = {d.name.lower() for d in fs.definitions}
            overlap = len(task_words & (path_words | symbol_words))
            if overlap > 0:
                w += float(overlap * 3.0)

            weights[f] = w

        total_weight = sum(weights.values())
        p = {f: w / total_weight for f, w in weights.items()}

        # PageRank power iteration
        damping = 0.85
        r = dict(p)

        for _ in range(30):
            next_r = {f: (1.0 - damping) * p[f] for f in files}
            dangling_sum = sum(r[u] for u in files if not out_edges[u])

            for v in files:
                in_sum = sum(r[u] / len(out_edges[u]) for u in in_edges[v])
                next_r[v] += damping * in_sum + damping * dangling_sum * p[v]

            diff = sum(abs(next_r[f] - r[f]) for f in files)
            r = next_r
            if diff < 1e-6:
                break

        sorted_files = sorted(files, key=lambda f: r[f], reverse=True)
        return [(f, r[f]) for f in sorted_files]

    def render_map(
        self,
        ranked_files: list[tuple[str, float]],
        file_symbols: dict[str, FileSymbols],
        token_budget: int | None = None,
    ) -> str:
        """Render top-ranked symbols into an indented text map within token budget."""
        budget = token_budget if token_budget is not None else self.token_budget
        rendered_blocks: list[str] = []
        current_tokens = 0

        for file_path, _ in ranked_files:
            fs = file_symbols.get(file_path)
            if not fs or not fs.definitions:
                continue

            block_lines = [f"{file_path}:"]
            for d in fs.definitions:
                indent = "  " * (d.indent + 1)
                block_lines.append(f"{indent}{d.signature}")

            block_text = "\n".join(block_lines) + "\n"
            block_tokens = estimate_tokens(block_text)

            if current_tokens + block_tokens > budget:
                # If budget is exhausted and we already have content, stop
                if rendered_blocks:
                    break
                # If even first file exceeds budget, fit as many lines as possible
                trimmed_lines = [block_lines[0]]
                for line in block_lines[1:]:
                    test_str = "\n".join(trimmed_lines + [line]) + "\n"
                    if estimate_tokens(test_str) > budget:
                        break
                    trimmed_lines.append(line)
                rendered_blocks.append("\n".join(trimmed_lines) + "\n")
                break

            rendered_blocks.append(block_text)
            current_tokens += block_tokens

        return "\n".join(rendered_blocks).strip()

    def get_repo_map(
        self,
        task: str = "",
        mentioned_files: list[str] | None = None,
        edited_files: list[str] | None = None,
        token_budget: int | None = None,
    ) -> str:
        """Convenience pipeline scanning workspace, ranking symbols, and rendering map."""
        file_symbols = self.scan_workspace()
        if not file_symbols:
            return ""

        out_edges, in_edges = self.build_graph(file_symbols)
        ranked = self.personalized_pagerank(
            file_symbols,
            out_edges,
            in_edges,
            task=task,
            mentioned_files=mentioned_files,
            edited_files=edited_files,
        )
        return self.render_map(ranked, file_symbols, token_budget=token_budget)

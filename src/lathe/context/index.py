"""Semantic code indexing and vector search using tree-sitter AST chunking, SQLite, and numpy."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import numpy as np
import tree_sitter_language_pack as tslp

from lathe.config import EmbeddingsConfig, get_hf_token, load_config
from lathe.context.repomap import (
    DEFINITION_NODE_TYPES,
    SUPPORTED_EXTENSIONS,
    extract_symbol_name,
)
from lathe.safety.workspace import Workspace

DEFAULT_INDEX_DIR = ".lathe/index"
DEFAULT_DB_FILENAME = "code_index.db"


@dataclass
class CodeChunk:
    """Represents an atomic, searchable code chunk (function, class, or logical block)."""

    id: str
    file_path: str
    symbol_name: str
    symbol_kind: str
    start_line: int
    end_line: int
    chunk_hash: str
    content: str
    embedding: np.ndarray | None = None


@dataclass
class SearchResult:
    """Result of a semantic search query against the code index."""

    rank: int
    score: float
    file_path: str
    symbol_name: str
    symbol_kind: str
    start_line: int
    end_line: int
    content: str


def normalize_vector(vec: np.ndarray) -> np.ndarray:
    """Normalize a vector to unit L2 length so dot product equals cosine similarity."""
    norm = float(np.linalg.norm(vec))
    if norm == 0 or np.isnan(norm):
        return vec
    return cast(np.ndarray, vec / norm)


# ---------------------------------------------------------------------------
# Embedding Providers
# ---------------------------------------------------------------------------


class BaseEmbedder(ABC):
    """Abstract base class for vector embedding models."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Generate normalized embeddings for a batch of text chunks."""
        pass

    def embed_query(self, text: str) -> np.ndarray:
        """Generate a normalized embedding for a search query string."""
        results = self.embed_batch([text])
        if not results:
            return np.zeros(128, dtype=np.float32)
        return results[0]


class OllamaEmbedder(BaseEmbedder):
    """Embeddings provider using a local Ollama runtime (e.g. nomic-embed-text)."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a list of texts via Ollama REST API with legacy fallback."""
        if not texts:
            return []

        # 1. Try modern /api/embed endpoint (supports batching)
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": texts},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    raw_embeddings = data.get("embeddings", [])
                    return [
                        normalize_vector(np.array(vec, dtype=np.float32)) for vec in raw_embeddings
                    ]
        except Exception:
            pass

        # 2. Fallback to /api/embeddings (single item prompt)
        results: list[np.ndarray] = []
        try:
            with httpx.Client(timeout=60.0) as client:
                for text in texts:
                    resp = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    if resp.status_code == 200:
                        raw_vec = resp.json().get("embedding", [])
                        results.append(normalize_vector(np.array(raw_vec, dtype=np.float32)))
                    else:
                        results.append(np.zeros(128, dtype=np.float32))
            return results
        except Exception:
            # If Ollama is unavailable, fallback to deterministic vectors
            return DeterministicEmbedder().embed_batch(texts)


class SentenceTransformersEmbedder(BaseEmbedder):
    """Local embeddings provider using sentence-transformers (e.g. BAAI/bge-small-en-v1.5)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
            except ImportError as err:
                raise RuntimeError(
                    "sentence-transformers is not installed. Install it with "
                    "`pip install sentence-transformers` or configure [embeddings] "
                    "provider='ollama' in lathe.toml."
                ) from err
        return self._model

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [np.array(v, dtype=np.float32) for v in vectors]


class HFEmbedder(BaseEmbedder):
    """Embeddings provider using Hugging Face Inference API."""

    def __init__(
        self,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        token: str | None = None,
    ) -> None:
        self.model = model
        self.token = token or get_hf_token()

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        try:
            from huggingface_hub import InferenceClient

            client = InferenceClient(model=self.model, token=self.token)
            results: list[np.ndarray] = []
            for text in texts:
                raw = client.feature_extraction(text)
                arr = np.array(raw, dtype=np.float32).flatten()
                results.append(normalize_vector(arr))
            return results
        except Exception:
            return DeterministicEmbedder().embed_batch(texts)


class DeterministicEmbedder(BaseEmbedder):
    """Fast, deterministic pseudo-embedder for offline environments, fallbacks, and tests.

    Produces reproducible normalized 128-dimensional vectors based on word hashing and n-grams.
    """

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        results: list[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            words = re.findall(r"\w+", text.lower())
            for i, word in enumerate(words):
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dim
                weight = 1.0 / (1.0 + (i * 0.05))
                vec[idx] += weight
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            results.append(vec)
        return results


def create_embedder(config: EmbeddingsConfig) -> BaseEmbedder:
    """Factory creating an embedder instance according to EmbeddingsConfig."""
    provider = config.provider.lower()
    if provider == "ollama":
        base_url = config.base_url or "http://localhost:11434"
        return OllamaEmbedder(model=config.model, base_url=base_url)
    elif provider == "sentence-transformers":
        return SentenceTransformersEmbedder(model_name=config.model)
    elif provider == "hf":
        return HFEmbedder(model=config.model)
    elif provider == "mock" or provider == "deterministic":
        return DeterministicEmbedder()
    return OllamaEmbedder(model=config.model)


# ---------------------------------------------------------------------------
# AST Code Chunking
# ---------------------------------------------------------------------------


def determine_chunk_kind(node: Any) -> str:
    """Classify AST node type into a human-readable symbol kind."""
    node_type = getattr(node, "type", str(node))
    if "class" in node_type:
        return "class"
    if "method" in node_type:
        return "method"
    if "function" in node_type:
        p = getattr(node, "parent", None)
        while p:
            p_type = getattr(p, "type", "")
            if "class" in p_type or "struct" in p_type or "interface" in p_type:
                return "method"
            p = getattr(p, "parent", None)
        return "function"
    if "struct" in node_type:
        return "struct"
    if "interface" in node_type or "trait" in node_type:
        return "interface"
    if "type" in node_type:
        return "type"
    if "enum" in node_type:
        return "enum"
    return "block"


def chunk_file(file_path: Path, relative_path: str) -> list[CodeChunk]:
    """Chunk a file into semantic function/class units using tree-sitter or line blocks."""
    try:
        code_bytes = file_path.read_bytes()
    except Exception:
        return []

    if not code_bytes:
        return []

    ext = file_path.suffix.lower()
    lang = SUPPORTED_EXTENSIONS.get(ext)
    chunks: list[CodeChunk] = []

    # 1. Attempt tree-sitter AST chunking if language grammar is supported
    if lang:
        try:
            parser = tslp.get_parser(lang)
            tree = parser.parse(code_bytes)

            def collect_definitions(node: Any) -> None:
                if node.type in DEFINITION_NODE_TYPES:
                    kind = determine_chunk_kind(node)
                    sym_name = extract_symbol_name(node, code_bytes)
                    name = sym_name or f"{kind}_{node.start_point[0] + 1}"
                    chunk_text = (
                        code_bytes[node.start_byte : node.end_byte]
                        .decode("utf-8", errors="replace")
                        .strip()
                    )

                    start_l = node.start_point[0] + 1
                    end_l = node.end_point[0] + 1
                    chunk_h = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                    cid = f"{relative_path}:{name}:{start_l}"

                    chunks.append(
                        CodeChunk(
                            id=cid,
                            file_path=relative_path,
                            symbol_name=name,
                            symbol_kind=kind,
                            start_line=start_l,
                            end_line=end_l,
                            chunk_hash=chunk_h,
                            content=chunk_text,
                        )
                    )

                for child in node.children:
                    collect_definitions(child)

            collect_definitions(tree.root_node)
        except Exception:
            pass

    # 2. If tree-sitter found no definition chunks (e.g. script, config, doc), use block chunking
    if not chunks:
        text = code_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return []

        # If file is short (<60 lines), keep as a single chunk
        if total_lines <= 60:
            chunk_text = text.strip()
            chunk_h = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            fname = Path(relative_path).name
            chunks.append(
                CodeChunk(
                    id=f"{relative_path}:{fname}:1",
                    file_path=relative_path,
                    symbol_name=fname,
                    symbol_kind="file",
                    start_line=1,
                    end_line=total_lines,
                    chunk_hash=chunk_h,
                    content=chunk_text,
                )
            )
        else:
            # Windowed chunks: 50 lines with 10 lines overlap
            window = 50
            overlap = 10
            start = 0
            while start < total_lines:
                end = min(start + window, total_lines)
                chunk_slice = lines[start:end]
                chunk_text = "\n".join(chunk_slice).strip()
                if chunk_text:
                    chunk_h = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                    cid = f"{relative_path}:block:{start + 1}"
                    chunks.append(
                        CodeChunk(
                            id=cid,
                            file_path=relative_path,
                            symbol_name=f"block_{start + 1}",
                            symbol_kind="block",
                            start_line=start + 1,
                            end_line=end,
                            chunk_hash=chunk_h,
                            content=chunk_text,
                        )
                    )
                if end == total_lines:
                    break
                start += window - overlap

    return chunks


# ---------------------------------------------------------------------------
# Semantic Code Index (SQLite + numpy)
# ---------------------------------------------------------------------------


class CodeIndex:
    """Manages workspace vector index storage in SQLite with incremental change detection."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        embedder: BaseEmbedder | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.index_dir = self.workspace_root / DEFAULT_INDEX_DIR
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.index_dir / DEFAULT_DB_FILENAME)

        if embedder is not None:
            self.embedder = embedder
        else:
            try:
                cfg = load_config(self.workspace_root)
                self.embedder = create_embedder(cfg.embeddings)
            except Exception:
                self.embedder = DeterministicEmbedder()

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema for files and chunks."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    file_hash TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    symbol_name TEXT NOT NULL,
                    symbol_kind TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    chunk_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(chunk_hash);")
            conn.commit()

    def get_stale_status(
        self,
    ) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]], list[str]]:
        """Identify added, modified, and deleted workspace files."""
        ws = Workspace(self.workspace_root)
        current_files: dict[str, Path] = {}

        for root, dirs, files in os.walk(self.workspace_root):
            root_path = Path(root)
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and not ws.is_ignored(root_path / d)
                and d not in ("node_modules", ".venv", ".git", "build", "dist")
            ]

            for file_name in files:
                if file_name.startswith("."):
                    continue
                full_path = root_path / file_name
                if ws.is_ignored(full_path):
                    continue

                ext = full_path.suffix.lower()
                if ext in SUPPORTED_EXTENSIONS or ext in (
                    ".md",
                    ".toml",
                    ".json",
                    ".yaml",
                    ".yml",
                    ".sh",
                    ".txt",
                    ".sql",
                ):
                    try:
                        rel = str(full_path.relative_to(self.workspace_root))
                        current_files[rel] = full_path
                    except ValueError:
                        continue

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, mtime, size FROM files;")
            db_files = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

        added: list[tuple[Path, str]] = []
        modified: list[tuple[Path, str]] = []
        deleted: list[str] = []

        for rel_path, file_path in current_files.items():
            try:
                stat = file_path.stat()
            except OSError:
                continue

            if rel_path not in db_files:
                added.append((file_path, rel_path))
            else:
                db_mtime, db_size = db_files[rel_path]
                if stat.st_mtime != db_mtime or stat.st_size != db_size:
                    modified.append((file_path, rel_path))

        for db_path in db_files:
            if db_path not in current_files:
                deleted.append(db_path)

        return added, modified, deleted

    def is_stale(self) -> bool:
        """Check whether workspace files have changed since last indexing."""
        added, modified, deleted = self.get_stale_status()
        return bool(added or modified or deleted)

    def refresh(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        force: bool = False,
    ) -> dict[str, int]:
        """Incrementally update or rebuild index, re-embedding only new/changed chunks."""
        if force:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM chunks;")
                conn.execute("DELETE FROM files;")
                conn.commit()

        added, modified, deleted = self.get_stale_status()
        files_to_process = added + modified
        total_files = len(files_to_process)

        stats = {
            "files_indexed": 0,
            "chunks_indexed": 0,
            "chunks_reused": 0,
            "files_deleted": len(deleted),
        }

        with self._get_connection() as conn:
            # 1. Remove deleted files
            for rel in deleted:
                conn.execute("DELETE FROM chunks WHERE file_path = ?;", (rel,))
                conn.execute("DELETE FROM files WHERE path = ?;", (rel,))

            # 2. Process added and modified files
            for idx, (file_path, rel_path) in enumerate(files_to_process):
                if progress_callback:
                    progress_callback(rel_path, idx + 1, total_files)

                try:
                    stat = file_path.stat()
                    file_bytes = file_path.read_bytes()
                except OSError:
                    continue

                file_h = hashlib.sha256(file_bytes).hexdigest()
                new_chunks = chunk_file(file_path, rel_path)

                # Check existing embeddings for identical chunk hashes across DB before deletion
                chunks_needing_embed: list[CodeChunk] = []
                for chunk in new_chunks:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT embedding FROM chunks "
                        "WHERE chunk_hash = ? AND embedding IS NOT NULL LIMIT 1;",
                        (chunk.chunk_hash,),
                    )
                    cached_row = cursor.fetchone()
                    if cached_row and cached_row[0]:
                        chunk.embedding = np.frombuffer(cached_row[0], dtype=np.float32)
                        stats["chunks_reused"] += 1
                    else:
                        chunks_needing_embed.append(chunk)

                # Remove existing chunks for this file before re-inserting
                conn.execute("DELETE FROM chunks WHERE file_path = ?;", (rel_path,))

                # Batch embed new / changed chunks
                if chunks_needing_embed:
                    texts = [c.content for c in chunks_needing_embed]
                    vectors = self.embedder.embed_batch(texts)
                    for chunk, vec in zip(chunks_needing_embed, vectors, strict=False):
                        chunk.embedding = vec
                        stats["chunks_indexed"] += 1

                # Insert all chunks into database
                for chunk in new_chunks:
                    blob = (
                        chunk.embedding.astype(np.float32).tobytes()
                        if chunk.embedding is not None
                        else None
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO chunks
                        (id, file_path, symbol_name, symbol_kind, start_line,
                         end_line, chunk_hash, content, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            chunk.id,
                            chunk.file_path,
                            chunk.symbol_name,
                            chunk.symbol_kind,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.chunk_hash,
                            chunk.content,
                            blob,
                        ),
                    )

                # Update files table
                conn.execute(
                    """
                    INSERT OR REPLACE INTO files (path, mtime, size, file_hash)
                    VALUES (?, ?, ?, ?);
                    """,
                    (rel_path, stat.st_mtime, stat.st_size, file_h),
                )
                stats["files_indexed"] += 1

            conn.commit()

        return stats

    def refresh_if_stale(self) -> dict[str, int]:
        """Auto-refresh index if any workspace files are modified, added, or deleted."""
        if self.is_stale():
            return self.refresh()
        return {"files_indexed": 0, "chunks_indexed": 0, "chunks_reused": 0, "files_deleted": 0}

    def search(self, query: str, k: int = 8) -> list[SearchResult]:
        """Search code chunks by natural language semantic query using cosine similarity."""
        self.refresh_if_stale()

        query_vec = self.embedder.embed_query(query)
        if query_vec is None or len(query_vec) == 0:
            return []

        query_vec = normalize_vector(query_vec)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, file_path, symbol_name, symbol_kind,
                       start_line, end_line, content, embedding
                FROM chunks
                WHERE embedding IS NOT NULL;
                """
            )
            rows = cursor.fetchall()

        if not rows:
            return []

        embeddings_list: list[np.ndarray] = []
        metadata_list: list[tuple[str, str, str, str, int, int, str]] = []

        for row in rows:
            cid, fpath, sname, skind, start_l, end_l, content, blob = row
            vec = np.frombuffer(blob, dtype=np.float32)
            if len(vec) == len(query_vec):
                embeddings_list.append(vec)
                metadata_list.append((cid, fpath, sname, skind, start_l, end_l, content))

        if not embeddings_list:
            return []

        matrix = np.vstack(embeddings_list)
        # Cosine similarity via dot product (since vectors are unit-normalized)
        scores = np.dot(matrix, query_vec)

        # Select top k indices
        top_k_indices = np.argsort(scores)[::-1][:k]

        results: list[SearchResult] = []
        for rank, idx in enumerate(top_k_indices, start=1):
            cid, fpath, sname, skind, start_l, end_l, content = metadata_list[idx]
            score = float(scores[idx])
            results.append(
                SearchResult(
                    rank=rank,
                    score=score,
                    file_path=fpath,
                    symbol_name=sname,
                    symbol_kind=skind,
                    start_line=start_l,
                    end_line=end_l,
                    content=content,
                )
            )

        return results

    def get_stats(self) -> dict[str, Any]:
        """Return counts of indexed files, chunks, and disk storage usage."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM files;")
            file_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM chunks;")
            chunk_count = cursor.fetchone()[0]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "files": file_count,
            "chunks": chunk_count,
            "db_size_bytes": db_size,
            "db_path": str(self.db_path),
        }

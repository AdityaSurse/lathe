"""Tests for semantic code indexing, AST chunking, SQLite storage, and vector search."""

from pathlib import Path

import numpy as np
import pytest

from lathe.context.index import (
    CodeIndex,
    DeterministicEmbedder,
    chunk_file,
    normalize_vector,
)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Create a temporary fixture repository with distinct functionality."""
    repo = tmp_path / "fixture_repo"
    repo.mkdir()

    # 1. Authentication module
    (repo / "auth.py").write_text(
        '''"""User authentication and credential token verification."""

class AuthenticationService:
    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key

    def login_user(self, username: str, password_hash: str) -> bool:
        """Authenticate user credentials and issue session jwt token."""
        if username == "admin" and password_hash == "valid":
            return True
        return False

    def revoke_token(self, token_id: str) -> None:
        """Invalidate an active user session token."""
        pass
''',
        encoding="utf-8",
    )

    # 2. Billing & Payment module
    (repo / "billing.py").write_text(
        '''"""Billing, credit card payment processing, and invoicing."""

class PaymentGateway:
    def charge_credit_card(self, customer_id: str, amount_cents: int) -> bool:
        """Charge the customer's credit card and record invoice transaction."""
        return amount_cents > 0

    def refund_transaction(self, transaction_id: str) -> None:
        """Refund an authorized billing charge."""
        pass
''',
        encoding="utf-8",
    )

    # 3. Database connection module
    (repo / "database.py").write_text(
        '''"""Database connection pooling and SQL query executor."""

def connect_postgres(host: str, port: int) -> str:
    """Establish connection pool to PostgreSQL relational database."""
    return f"postgres://{host}:{port}/db"

def execute_sql_query(query: str) -> list[dict]:
    """Execute SQL query statement and return matching database records."""
    return [{"result": query}]
''',
        encoding="utf-8",
    )

    return repo


def test_chunk_file_ast_extraction(fixture_repo: Path) -> None:
    """Verify AST extraction produces function and class chunks with correct metadata."""
    auth_path = fixture_repo / "auth.py"
    chunks = chunk_file(auth_path, "auth.py")

    assert len(chunks) >= 3  # Class + at least 2 methods
    names = [c.symbol_name for c in chunks]
    kinds = [c.symbol_kind for c in chunks]

    assert "AuthenticationService" in names
    assert "login_user" in names
    assert "revoke_token" in names
    assert "class" in kinds
    assert "method" in kinds

    # Verify line ranges and hashes
    for c in chunks:
        assert c.start_line > 0
        assert c.end_line >= c.start_line
        assert len(c.chunk_hash) == 64
        assert len(c.content) > 0


def test_chunk_file_fallback_blocks(tmp_path: Path) -> None:
    """Verify non-code or unsupported files are chunked into block units."""
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Project Title\n\nSome documentation text.\n" * 10, encoding="utf-8")

    chunks = chunk_file(readme_path, "README.md")
    assert len(chunks) >= 1
    assert chunks[0].symbol_kind in ("file", "block")


def test_normalize_vector() -> None:
    """Verify L2 vector normalization."""
    vec = np.array([3.0, 4.0], dtype=np.float32)
    normed = normalize_vector(vec)
    assert np.isclose(np.linalg.norm(normed), 1.0)

    zero_vec = np.zeros(4, dtype=np.float32)
    normed_zero = normalize_vector(zero_vec)
    assert np.all(normed_zero == 0.0)


def test_code_index_initial_build(fixture_repo: Path) -> None:
    """Verify index creation and SQLite database population."""
    embedder = DeterministicEmbedder(dim=128)
    index = CodeIndex(workspace_root=fixture_repo, embedder=embedder)

    stats = index.refresh()
    assert stats["files_indexed"] == 3
    assert stats["chunks_indexed"] > 0
    assert stats["chunks_reused"] == 0

    assert not index.is_stale()

    db_stats = index.get_stats()
    assert db_stats["files"] == 3
    assert db_stats["chunks"] == stats["chunks_indexed"]
    assert db_stats["db_size_bytes"] > 0


def test_code_index_incremental_update_and_cache_reuse(fixture_repo: Path) -> None:
    """Verify unchanged files are skipped and untouched chunks reuse cached embeddings."""
    embedder = DeterministicEmbedder(dim=128)
    index = CodeIndex(workspace_root=fixture_repo, embedder=embedder)
    stats1 = index.refresh()
    assert stats1["chunks_indexed"] > 0

    # 1. Unchanged workspace -> 0 files processed
    stats2 = index.refresh()
    assert stats2["files_indexed"] == 0
    assert stats2["chunks_indexed"] == 0

    # 2. Modify only one function in auth.py
    auth_file = fixture_repo / "auth.py"
    current_content = auth_file.read_text(encoding="utf-8")
    modified_content = current_content.replace(
        "return False",
        "# Modified login logic\n        return False",
    )
    # Ensure mtime changes
    import time

    time.sleep(0.05)
    auth_file.write_text(modified_content, encoding="utf-8")

    assert index.is_stale()
    stats3 = index.refresh()

    assert stats3["files_indexed"] == 1
    # Untouched chunks (e.g. revoke_token) reuse cached embedding BLOBs
    assert stats3["chunks_reused"] > 0
    assert not index.is_stale()


def test_code_index_deleted_file_removal(fixture_repo: Path) -> None:
    """Verify deleted workspace files are purged from files and chunks tables."""
    embedder = DeterministicEmbedder(dim=128)
    index = CodeIndex(workspace_root=fixture_repo, embedder=embedder)
    index.refresh()

    # Delete billing.py
    billing_file = fixture_repo / "billing.py"
    billing_file.unlink()

    assert index.is_stale()
    stats = index.refresh()
    assert stats["files_deleted"] == 1

    db_stats = index.get_stats()
    assert db_stats["files"] == 2


def test_semantic_search_top_k_ranking(fixture_repo: Path) -> None:
    """Verify semantic search returns relevant code chunks sorted by cosine similarity."""
    embedder = DeterministicEmbedder(dim=128)
    index = CodeIndex(workspace_root=fixture_repo, embedder=embedder)
    index.refresh()

    # Query authentication
    results = index.search("login user authentication credentials session jwt token", k=3)
    assert len(results) > 0
    top = results[0]
    assert "auth.py" in top.file_path
    assert top.rank == 1
    assert top.score > 0.0
    assert "login_user" in top.content or "AuthenticationService" in top.content

    # Query payment / billing
    bill_results = index.search("charge credit card payment customer invoice", k=3)
    assert len(bill_results) > 0
    top_bill = bill_results[0]
    assert "billing.py" in top_bill.file_path
    assert "charge_credit_card" in top_bill.content or "PaymentGateway" in top_bill.content


def test_code_index_force_rebuild(fixture_repo: Path) -> None:
    """Verify force rebuild purges and re-indexes all chunks."""
    embedder = DeterministicEmbedder(dim=128)
    index = CodeIndex(workspace_root=fixture_repo, embedder=embedder)
    index.refresh()

    rebuild_stats = index.refresh(force=True)
    assert rebuild_stats["files_indexed"] == 3
    assert rebuild_stats["chunks_indexed"] > 0

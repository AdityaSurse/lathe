"""Unit tests for session state saving, listing, and loading."""

from __future__ import annotations

import time
from pathlib import Path

from lathe.llm.types import Message
from lathe.memory.sessions import SessionManager


def test_save_and_load_session(tmp_path: Path):
    """Save full session components and verify faithful deserialization."""
    mgr = SessionManager(tmp_path)

    messages = [
        Message(role="user", content="Refactor database schema"),
        Message(role="assistant", content="I will update migrations."),
    ]
    plan = {
        "goal": "Refactor database",
        "steps": [{"id": 1, "title": "Add column", "status": "completed"}],
    }
    stats = {
        "total": {"calls": 2, "input_tokens": 100, "output_tokens": 50, "tokens_per_second": 35.0}
    }

    s_dir = mgr.save_session(
        session_id="sess_1234",
        messages=messages,
        plan=plan,
        stats=stats,
        mode="dual",
        title="Custom Title",
    )
    assert s_dir.exists()
    assert (s_dir / "session.json").exists()
    assert (s_dir / "messages.json").exists()
    assert (s_dir / "plan.json").exists()
    assert (s_dir / "stats.json").exists()

    loaded = mgr.load_session("sess_1234")
    assert loaded is not None
    assert loaded.info.session_id == "sess_1234"
    assert loaded.info.title == "Custom Title"
    assert loaded.info.mode == "dual"
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["content"] == "Refactor database schema"
    assert loaded.plan["goal"] == "Refactor database"


def test_list_sessions_ordering(tmp_path: Path):
    """list_sessions returns sessions ordered newest first."""
    mgr = SessionManager(tmp_path)

    mgr.save_session("old_sess", messages=[Message(role="user", content="Old task")])
    time.sleep(0.05)
    mgr.save_session("new_sess", messages=[Message(role="user", content="New task")])

    sessions = mgr.list_sessions()
    assert len(sessions) == 2
    assert sessions[0].session_id == "new_sess"
    assert sessions[1].session_id == "old_sess"


def test_get_latest_session(tmp_path: Path):
    """get_latest_session retrieves the most recent session."""
    mgr = SessionManager(tmp_path)
    assert mgr.get_latest_session() is None

    mgr.save_session("first_sess", messages=[Message(role="user", content="One")])
    latest = mgr.get_latest_session()
    assert latest is not None
    assert latest.session_id == "first_sess"


def test_delete_session(tmp_path: Path):
    """delete_session removes session directory cleanly."""
    mgr = SessionManager(tmp_path)
    mgr.save_session("to_delete", messages=[])
    assert mgr.get_session_dir("to_delete").exists()

    assert mgr.delete_session("to_delete") is True
    assert not mgr.get_session_dir("to_delete").exists()
    assert mgr.delete_session("non_existent") is False

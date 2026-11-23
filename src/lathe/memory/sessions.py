"""Session state persistence, discovery, and restoration across Lathe agent runs."""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lathe.llm.types import Message


class SessionInfo(BaseModel):
    """Metadata summary of a saved session."""

    session_id: str
    created_at: str
    updated_at: str
    title: str = "Interactive Session"
    mode: str = "auto"
    message_count: int = 0
    total_tokens: int = 0
    path: str = ""

    @property
    def display_time(self) -> str:
        """Formatted display string for session selection."""
        try:
            dt = datetime.fromisoformat(self.updated_at)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.updated_at[:19]


class SessionData(BaseModel):
    """Complete loaded session state including messages, plan, and telemetry."""

    info: SessionInfo
    messages: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    def to_messages(self) -> list[Message]:
        """Convert serialized message dicts back to Lathe Message objects."""
        result: list[Message] = []
        for m in self.messages:
            with contextlib.suppress(Exception):
                result.append(
                    Message(
                        role=m.get("role", "user"),
                        content=m.get("content", ""),
                        tool_call_id=m.get("tool_call_id"),
                    )
                )
        return result


class SessionManager:
    """Manages persistent session directories under .lathe/sessions/<id>/."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root is not None else Path.cwd()
        )
        self.sessions_dir = self.workspace_root / ".lathe" / "sessions"

    def _ensure_sessions_dir(self) -> Path:
        """Ensure .lathe/sessions exists."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        return self.sessions_dir

    def get_session_dir(self, session_id: str) -> Path:
        """Return path to a specific session directory."""
        return self.sessions_dir / session_id

    def save_session(
        self,
        session_id: str,
        messages: list[Message] | list[dict[str, Any]] | None = None,
        plan: Any | None = None,
        checkpoints: list[Any] | None = None,
        stats: Any | None = None,
        title: str | None = None,
        mode: str = "auto",
        total_tokens: int = 0,
    ) -> Path:
        """Save active session state to .lathe/sessions/<session_id>/."""
        self._ensure_sessions_dir()
        s_dir = self.get_session_dir(session_id)
        s_dir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now(UTC).isoformat()
        metadata_file = s_dir / "session.json"

        # Load existing metadata if available to preserve created_at
        existing_info: dict[str, Any] = {}
        if metadata_file.is_file():
            with contextlib.suppress(Exception):
                existing_info = json.loads(metadata_file.read_text(encoding="utf-8"))

        created_at = existing_info.get("created_at", now_iso)
        resolved_title = title or existing_info.get("title")

        # Normalize messages
        raw_messages: list[dict[str, Any]] = []
        if messages:
            for m in messages:
                if isinstance(m, Message):
                    raw_messages.append(
                        {
                            "role": m.role,
                            "content": m.content,
                            "tool_call_id": m.tool_call_id,
                        }
                    )
                elif isinstance(m, dict):
                    raw_messages.append(m)

        # Infer title from first user message if not set
        if not resolved_title and raw_messages:
            for msg in raw_messages:
                if msg.get("role") == "user" and msg.get("content"):
                    first_line = msg["content"].strip().splitlines()[0]
                    resolved_title = first_line[:40] + "..." if len(first_line) > 40 else first_line
                    break
        if not resolved_title:
            resolved_title = f"Session {session_id}"

        # 1. session.json
        info = SessionInfo(
            session_id=session_id,
            created_at=created_at,
            updated_at=now_iso,
            title=resolved_title,
            mode=mode,
            message_count=len(raw_messages),
            total_tokens=total_tokens or existing_info.get("total_tokens", 0),
            path=str(s_dir),
        )
        metadata_file.write_text(info.model_dump_json(indent=2), encoding="utf-8")

        # 2. messages.json
        (s_dir / "messages.json").write_text(json.dumps(raw_messages, indent=2), encoding="utf-8")

        # 3. plan.json
        if plan is not None:
            if hasattr(plan, "model_dump"):
                plan_dict = plan.model_dump()
            elif isinstance(plan, dict):
                plan_dict = plan
            else:
                plan_dict = {"raw": str(plan)}
            (s_dir / "plan.json").write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")

        # 4. checkpoints.json
        if checkpoints is not None:
            raw_checkpoints = []
            for ck in checkpoints:
                if hasattr(ck, "__dict__"):
                    raw_checkpoints.append(
                        {
                            "number": getattr(ck, "number", 0),
                            "tree_sha": getattr(ck, "tree_sha", ""),
                            "timestamp": getattr(ck, "timestamp", 0.0),
                            "description": getattr(ck, "description", ""),
                            "changed_files": getattr(ck, "changed_files", []),
                        }
                    )
                elif isinstance(ck, dict):
                    raw_checkpoints.append(ck)
            (s_dir / "checkpoints.json").write_text(
                json.dumps(raw_checkpoints, indent=2), encoding="utf-8"
            )

        # 5. stats.json
        if stats is not None:
            if hasattr(stats, "to_dict"):
                stats_dict = stats.to_dict()
            elif isinstance(stats, dict):
                stats_dict = stats
            else:
                stats_dict = {}
            (s_dir / "stats.json").write_text(json.dumps(stats_dict, indent=2), encoding="utf-8")

        return s_dir

    def load_session(self, session_id: str) -> SessionData | None:
        """Load session state from .lathe/sessions/<session_id>/."""
        s_dir = self.get_session_dir(session_id)
        if not s_dir.is_dir():
            return None

        metadata_file = s_dir / "session.json"
        if not metadata_file.is_file():
            return None

        try:
            info_dict = json.loads(metadata_file.read_text(encoding="utf-8"))
            info = SessionInfo.model_validate(info_dict)
        except Exception:
            return None

        # Load messages
        messages: list[dict[str, Any]] = []
        msg_file = s_dir / "messages.json"
        if msg_file.is_file():
            try:
                messages = json.loads(msg_file.read_text(encoding="utf-8"))
            except Exception:
                messages = []

        # Load plan
        plan: dict[str, Any] | None = None
        plan_file = s_dir / "plan.json"
        if plan_file.is_file():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception:
                plan = None

        # Load checkpoints
        checkpoints: list[dict[str, Any]] = []
        ck_file = s_dir / "checkpoints.json"
        if ck_file.is_file():
            try:
                checkpoints = json.loads(ck_file.read_text(encoding="utf-8"))
            except Exception:
                checkpoints = []

        # Load stats
        stats: dict[str, Any] = {}
        stats_file = s_dir / "stats.json"
        if stats_file.is_file():
            try:
                stats = json.loads(stats_file.read_text(encoding="utf-8"))
            except Exception:
                stats = {}

        return SessionData(
            info=info,
            messages=messages,
            plan=plan,
            checkpoints=checkpoints,
            stats=stats,
        )

    def list_sessions(self) -> list[SessionInfo]:
        """Return list of all sessions in workspace sorted by updated_at descending."""
        if not self.sessions_dir.is_dir():
            return []

        results: list[SessionInfo] = []
        try:
            for item in self.sessions_dir.iterdir():
                if not item.is_dir():
                    continue
                meta_file = item / "session.json"
                if meta_file.is_file():
                    try:
                        data = json.loads(meta_file.read_text(encoding="utf-8"))
                        info = SessionInfo.model_validate(data)
                        results.append(info)
                    except Exception:
                        pass
        except OSError:
            return []

        # Sort newest first
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results

    def get_latest_session(self) -> SessionInfo | None:
        """Retrieve metadata of the most recently updated session."""
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def delete_session(self, session_id: str) -> bool:
        """Remove a session directory completely."""
        s_dir = self.get_session_dir(session_id)
        if s_dir.is_dir():
            try:
                shutil.rmtree(s_dir)
                return True
            except OSError:
                return False
        return False

"""Safety system enforcing boundaries, whitelisting, confirmations, and security rules."""

from enum import Enum

from lathe.safety.workspace import (
    DEFAULT_IGNORED_DIRS,
    FileAccessError,
    IgnoreRule,
    PathEscapeError,
    Workspace,
    WorkspaceError,
)


class ActionPermission(Enum):
    """Classification of action permission categories."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


__all__ = [
    "DEFAULT_IGNORED_DIRS",
    "ActionPermission",
    "FileAccessError",
    "IgnoreRule",
    "PathEscapeError",
    "Workspace",
    "WorkspaceError",
]

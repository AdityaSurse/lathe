"""Safety system enforcing boundaries, whitelisting, confirmations, and security rules."""

from enum import Enum

from lathe.safety.permissions import (
    DEFAULT_BLOCKLIST_PATTERNS,
    FORBIDDEN_ENV_NAMES,
    PermissionDecision,
    PermissionEngine,
    PermissionMode,
    PermissionResult,
    PermissionsStore,
    is_blocked_command,
    is_sensitive_env_var,
    scrub_env,
)
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
    "DEFAULT_BLOCKLIST_PATTERNS",
    "DEFAULT_IGNORED_DIRS",
    "FORBIDDEN_ENV_NAMES",
    "ActionPermission",
    "FileAccessError",
    "IgnoreRule",
    "PathEscapeError",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionMode",
    "PermissionResult",
    "PermissionsStore",
    "Workspace",
    "WorkspaceError",
    "is_blocked_command",
    "is_sensitive_env_var",
    "scrub_env",
]

"""Safety system enforcing boundaries, whitelisting, confirmations, and security rules."""

from enum import Enum

from lathe.safety.guard import check_is_project_folder

from lathe.safety.checkpoints import (
    CHECKPOINT_REF_PREFIX,
    Checkpoint,
    CheckpointManager,
    auto_commit_task,
    get_checkpoint_manager,
    suggest_conventional_commit,
)
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
    "ActionPermission",
    "CHECKPOINT_REF_PREFIX",
    "Checkpoint",
    "CheckpointManager",
    "DEFAULT_BLOCKLIST_PATTERNS",
    "DEFAULT_IGNORED_DIRS",
    "FORBIDDEN_ENV_NAMES",
    "check_is_project_folder",
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
    "auto_commit_task",
    "get_checkpoint_manager",
    "is_blocked_command",
    "is_sensitive_env_var",
    "scrub_env",
    "suggest_conventional_commit",
]

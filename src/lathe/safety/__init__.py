"""Safety and permission system enforcing whitelisting, confirmations, and security rules."""

from enum import Enum


class ActionPermission(Enum):
    """Classification of action permission categories."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

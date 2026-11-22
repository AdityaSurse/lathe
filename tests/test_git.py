"""Alias entry point for git tool tests."""

from tests.tools.test_git import (
    git_repo,
    test_git_commit_tool_authorization_and_execution,
    test_git_diff_tool,
    test_git_log_tool,
    test_git_status_tool_clean_and_modified,
    test_git_tools_in_default_registry,
)

__all__ = [
    "git_repo",
    "test_git_commit_tool_authorization_and_execution",
    "test_git_diff_tool",
    "test_git_log_tool",
    "test_git_status_tool_clean_and_modified",
    "test_git_tools_in_default_registry",
]

"""Alias entry point for checkpoint tests (singular)."""

from tests.safety.test_checkpoints import (
    git_repo,
    test_checkpoint_creation_uses_isolated_refs,
    test_non_git_repository_handling,
    test_restore_specific_checkpoint,
    test_session_diff_generation,
    test_suggest_conventional_commit_with_mock_client,
    test_user_staged_changes_remain_untouched_by_checkpoint_and_undo,
)

__all__ = [
    "git_repo",
    "test_checkpoint_creation_uses_isolated_refs",
    "test_non_git_repository_handling",
    "test_restore_specific_checkpoint",
    "test_session_diff_generation",
    "test_suggest_conventional_commit_with_mock_client",
    "test_user_staged_changes_remain_untouched_by_checkpoint_and_undo",
]

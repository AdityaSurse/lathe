"""Context management module responsible for token counting, AST indexing, and budget allocation."""

from dataclasses import dataclass


@dataclass
class ContextBudget:
    """Enforces target token budgets across different prompt context segments."""

    system_prompt_pct: float = 0.10
    repo_ast_pct: float = 0.15
    open_files_pct: float = 0.35
    conversation_pct: float = 0.20
    tool_results_pct: float = 0.20

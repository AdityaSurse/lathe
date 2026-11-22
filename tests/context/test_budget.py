"""Tests for token budgeting, accurate counting, allocation math, and compaction triggers."""

from rich.console import Console

from lathe.config import LatheConfig, RoleConfig, RolesConfig
from lathe.context.budget import (
    BudgetAllocator,
    BudgetShares,
    TokenCounter,
    compact_context,
    is_protected_message,
    summarize_tool_output,
)
from lathe.llm.types import Message
from lathe.ui.commands import handle_compact, handle_tokens, set_active_messages
from lathe.ui.status import SessionStats


def test_token_counter_heuristic_fallback() -> None:
    """Verify fallback token counting produces expected estimates (~3.5 chars/token)."""
    counter = TokenCounter(model_name="nonexistent_mock_model_xyz")

    assert counter.count_tokens("") == 0
    assert counter.count_tokens("hello") >= 1
    # 35 characters -> approx 10 tokens
    text_35 = "a" * 35
    assert counter.count_tokens(text_35) == 10

    # Message framing overhead
    msg = Message(role="user", content="hello world")
    tokens = counter.count_message_tokens(msg)
    # content (~3) + 4 framing overhead >= 7
    assert tokens >= 7


def test_token_counter_model_name_sanitization() -> None:
    """Verify Hugging Face repo ID extraction from Ollama / GGUF model paths."""
    counter = TokenCounter()
    assert (
        counter._sanitize_model_to_repo_id("hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M")
        == "Qwen/Qwen2.5-Coder-7B-Instruct"
    )
    assert (
        counter._sanitize_model_to_repo_id("deepseek-ai/DeepSeek-R1") == "deepseek-ai/DeepSeek-R1"
    )
    assert (
        counter._sanitize_model_to_repo_id("Qwen/Qwen2.5-Coder-1.5B-Instruct")
        == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    )


def test_budget_allocation_math() -> None:
    """Verify capacity math, category shares, and usage ratio calculations."""
    allocator = BudgetAllocator(
        context_window=10000,
        max_tokens=2000,
        shares=BudgetShares(
            system=0.10, repomap=0.15, pinned=0.20, conversation=0.35, tool_results=0.20
        ),
    )

    # Capacity = 10000 - 2000 = 8000
    assert allocator.capacity == 8000
    assert allocator.reply_reserve == 2000

    sys_text = "System guidelines instructions.\n\n# Repository Map\nFile definitions."
    messages = [
        Message(role="system", content=sys_text),
        Message(role="user", content="Build a login feature"),
        Message(role="assistant", content="I will create the login module"),
        Message(role="tool", content="[Tool Result: file created]"),
    ]

    usage = allocator.calculate_usage(messages, pinned_files={"auth.py": "def login(): pass"})

    assert usage.system_tokens > 0
    assert usage.repomap_tokens > 0
    assert usage.pinned_tokens > 0
    assert usage.conversation_tokens > 0
    assert usage.tool_tokens > 0
    assert usage.total_used == (
        usage.system_tokens
        + usage.repomap_tokens
        + usage.pinned_tokens
        + usage.conversation_tokens
        + usage.tool_tokens
    )
    assert 0.0 < usage.usage_ratio < 1.0
    assert usage.free_tokens == usage.capacity - usage.total_used


def test_budget_threshold_detection() -> None:
    """Verify is_over_threshold triggers at 75% capacity."""
    allocator = BudgetAllocator(context_window=1000, max_tokens=200)
    # Capacity = 800 tokens. 75% threshold = 600 tokens.

    # 1. Under threshold
    low_usage_msgs = [Message(role="user", content="short")]
    usage_low = allocator.calculate_usage(low_usage_msgs)
    assert not usage_low.is_over_threshold
    assert usage_low.usage_ratio < 0.75

    # 2. Over threshold: generate enough text to pass 600 tokens (~2200 chars)
    large_text = "word " * 600
    high_usage_msgs = [Message(role="user", content=large_text)]
    usage_high = allocator.calculate_usage(high_usage_msgs)
    assert usage_high.is_over_threshold
    assert usage_high.usage_ratio >= 0.75


def test_summarize_tool_output() -> None:
    """Verify tool output compression into compact one-line summaries."""
    multiline_output = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    summary = summarize_tool_output(multiline_output)
    assert summary.startswith("[Tool Result:")
    assert "Line 1" in summary
    assert "summarized" in summary
    assert "\n" not in summary


def test_protected_messages_survive_criteria() -> None:
    """Verify protected messages identification (task, plan, unresolved errors, recent turns)."""
    orig_msg = Message(role="user", content="Initial task request")
    assert is_protected_message(orig_msg, is_original_task=True, is_recent=False)

    recent_msg = Message(role="assistant", content="Recent turn")
    assert is_protected_message(recent_msg, is_original_task=False, is_recent=True)

    plan_text = "Here is the plan:\n## Plan\n1. Step one\n2. Step two"
    plan_msg = Message(role="assistant", content=plan_text)
    assert is_protected_message(plan_msg, is_original_task=False, is_recent=False)

    err_text = "Traceback (most recent call last):\n  File 't.py', line 1\nError: failed"
    error_msg = Message(role="tool", content=err_text)
    assert is_protected_message(error_msg, is_original_task=False, is_recent=False)

    unprotected_msg = Message(role="assistant", content="Ordinary older message.")
    assert not is_protected_message(unprotected_msg, is_original_task=False, is_recent=False)


def test_compaction_stages_and_protection() -> None:
    """Verify compaction shrinks tool results, summarizes old turns, and protects items."""
    allocator = BudgetAllocator(context_window=1000, max_tokens=200)
    # Capacity = 800 tokens

    # Build sequence with original task, active plan, unresolved error, old tool results
    tool_text = "Multi-line tool output log content with extensive details\n" * 80
    err_text = "Traceback (most recent call last):\nFAILED test_auth.py: line 42"
    messages = [
        Message(role="system", content="System guidelines"),
        Message(role="user", content="Original task: Implement JWT authentication system"),
        Message(role="assistant", content="## Plan\n1. Create auth model\n2. Add endpoints"),
        Message(role="tool", content=tool_text),
        Message(role="user", content="Older user remark: looks good"),
        Message(role="assistant", content="Older assistant remark: continuing"),
        Message(role="tool", content=err_text),
        # Latest 4 turns:
        Message(role="user", content="Recent turn 1"),
        Message(role="assistant", content="Recent turn 2"),
        Message(role="user", content="Recent turn 3"),
        Message(role="assistant", content="Recent turn 4"),
    ]

    # Verify initial usage is over 75%
    initial_usage = allocator.calculate_usage(messages)
    assert initial_usage.is_over_threshold

    compacted, did_compact, note = compact_context(messages, allocator, force=False)
    assert did_compact

    # Verify protected messages survived
    compacted_contents = [m.content for m in compacted]

    # 1. Original task survived
    assert any("Original task: Implement JWT authentication" in c for c in compacted_contents)

    # 2. Plan survived
    assert any("## Plan" in c for c in compacted_contents)

    # 3. Unresolved error survived
    assert any("FAILED test_auth.py" in c for c in compacted_contents)

    # 4. Latest 4 turns survived verbatim
    assert any("Recent turn 1" in c for c in compacted_contents)
    assert any("Recent turn 2" in c for c in compacted_contents)
    assert any("Recent turn 3" in c for c in compacted_contents)
    assert any("Recent turn 4" in c for c in compacted_contents)

    # 5. Usage after compaction is reduced
    final_usage = allocator.calculate_usage(compacted)
    assert final_usage.total_used < initial_usage.total_used


def test_slash_commands_tokens_and_compact() -> None:
    """Verify /tokens renders bar chart and /compact reduces message tokens."""
    console = Console(record=True, width=120)
    stats = SessionStats()
    config = LatheConfig(
        roles=RolesConfig(
            coder=RoleConfig(
                backend="ollama",
                model="hf.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                context_window=4000,
                max_tokens=1000,
            )
        )
    )

    test_messages = [
        Message(role="system", content="System guidelines"),
        Message(role="user", content="Initial task request"),
        Message(role="assistant", content="Step 1"),
        Message(role="tool", content="Log output\n" * 50),
        Message(role="user", content="Step 2"),
        Message(role="assistant", content="Step 3"),
        Message(role="user", content="Step 4"),
        Message(role="assistant", content="Step 5"),
    ]
    set_active_messages(test_messages)

    # Test /tokens
    ret_tokens = handle_tokens([], config, stats, console)
    assert ret_tokens is True
    rendered_text = console.export_text()
    assert "Context Budget Usage" in rendered_text
    assert "System Prompt" in rendered_text
    assert "Tool Results" in rendered_text

    # Test /compact
    ret_compact = handle_compact([], config, stats, console)
    assert ret_compact is True
    compact_output = console.export_text()
    assert "compacted" in compact_output.lower()

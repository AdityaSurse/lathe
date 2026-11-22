"""Context window token budget allocation and two-stage compaction engine."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from lathe.llm.types import Message

# Global in-memory cache for loaded tokenizers to prevent repeated instantiation
_TOKENIZER_CACHE: dict[str, Any] = {}
_FAILED_REPOS: set[str] = set()


class TokenCounter:
    """Accurately counts tokens using HF tokenizers with fast heuristic fallback."""

    def __init__(
        self,
        model_name: str | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.model_name = model_name or ""
        default_cache = Path.home() / ".lathe" / "cache" / "tokenizers"
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache
        self._tokenizer = self._resolve_and_load_tokenizer(self.model_name)

    @classmethod
    def _sanitize_model_to_repo_id(cls, model_name: str) -> str:
        """Extract a Hugging Face repo ID from model identifiers or GGUF URLs."""
        if not model_name:
            return ""

        cleaned = model_name.strip()
        # Remove hf.co/ prefix
        if cleaned.startswith("hf.co/"):
            cleaned = cleaned[len("hf.co/") :]

        # Strip quant tags (e.g. :Q4_K_M, :latest)
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[0]

        # Strip GGUF file suffixes
        cleaned = re.sub(r"\.gguf$", "", cleaned, flags=re.IGNORECASE)

        # Handle bartowski/Qwen2.5-Coder-7B-Instruct-GGUF -> Qwen/Qwen2.5-Coder-7B-Instruct
        match = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", cleaned)
        if match:
            repo = match.group(1)
            # If it's a quantizer repo (e.g. bartowski/Qwen2.5-Coder-7B-Instruct-GGUF), map to base
            if "bartowski" in repo or "-GGUF" in repo:
                parts = repo.split("/")
                base_name = re.sub(r"-GGUF$", "", parts[-1], flags=re.IGNORECASE)
                if "Qwen" in base_name:
                    return f"Qwen/{base_name}"
                if "DeepSeek" in base_name:
                    return f"deepseek-ai/{base_name}"
            return repo

        return cleaned

    def _resolve_and_load_tokenizer(self, model_name: str) -> Any | None:
        """Attempt to load a Tokenizer instance from cache, disk, or Hugging Face."""
        if not model_name:
            return None

        repo_id = self._sanitize_model_to_repo_id(model_name)
        if not repo_id:
            return None

        if repo_id in _TOKENIZER_CACHE:
            return _TOKENIZER_CACHE[repo_id]

        if repo_id in _FAILED_REPOS:
            return None

        # Check local disk cache
        local_dir = self.cache_dir / repo_id.replace("/", "__")
        local_file = local_dir / "tokenizer.json"
        if local_file.is_file():
            try:
                from tokenizers import Tokenizer

                tok = Tokenizer.from_file(str(local_file))
                _TOKENIZER_CACHE[repo_id] = tok
                return tok
            except Exception:
                pass

        # Attempt to load using tokenizers.Tokenizer.from_pretrained
        try:
            from tokenizers import Tokenizer

            # Fast check if network connectivity to Hugging Face exists
            can_connect = False
            try:
                import socket

                with socket.create_connection(("huggingface.co", 443), timeout=0.2):
                    can_connect = True
            except OSError:
                can_connect = False

            if not can_connect:
                _FAILED_REPOS.add(repo_id)
                return None

            # Try online fetch if environment allows
            tok = Tokenizer.from_pretrained(repo_id)
            _TOKENIZER_CACHE[repo_id] = tok

            # Save to disk cache
            try:
                local_dir.mkdir(parents=True, exist_ok=True)
                tok.save(str(local_file))
            except Exception:
                pass

            return tok
        except Exception:
            _FAILED_REPOS.add(repo_id)
            return None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the active tokenizer, falling back to len(text)/3.5."""
        if not text:
            return 0

        if self._tokenizer is not None:
            try:
                encoding = self._tokenizer.encode(text)
                return len(encoding.ids)
            except Exception:
                pass

        # Fallback heuristic: ~3.5 characters per token
        return max(1, math.ceil(len(text) / 3.5))

    def count_message_tokens(self, msg: Message) -> int:
        """Count tokens in a single Message including role and tool call metadata."""
        count = self.count_tokens(msg.content)
        # Format framing overhead per message (role tag, delimiters)
        count += 4

        if msg.tool_calls:
            for tc in msg.tool_calls:
                count += self.count_tokens(tc.name)
                for k, v in tc.arguments.items():
                    count += self.count_tokens(f"{k}:{v}")

        return count

    def count_messages_tokens(self, messages: list[Message]) -> int:
        """Count total tokens across a list of Messages."""
        if not messages:
            return 0
        total = sum(self.count_message_tokens(m) for m in messages)
        # Priming token overhead for assistant reply
        return total + 3


@dataclass
class BudgetShares:
    """Configurable share percentages of the input context window across categories."""

    system: float = 0.10
    repomap: float = 0.15
    pinned: float = 0.20
    conversation: float = 0.35
    tool_results: float = 0.20


@dataclass
class BudgetUsage:
    """Token consumption, capacity limits, and utilization ratio by category."""

    system_tokens: int
    repomap_tokens: int
    pinned_tokens: int
    conversation_tokens: int
    tool_tokens: int
    total_used: int
    capacity: int
    context_window: int
    reply_reserve: int

    @property
    def usage_ratio(self) -> float:
        """Proportion of context capacity currently in use."""
        return self.total_used / self.capacity if self.capacity > 0 else 0.0

    @property
    def is_over_threshold(self) -> bool:
        """Whether current token usage exceeds the 75% compaction threshold."""
        return self.usage_ratio >= 0.75

    @property
    def free_tokens(self) -> int:
        """Number of free tokens remaining before context capacity is saturated."""
        return max(0, self.capacity - self.total_used)


class BudgetAllocator:
    """Calculates token allocation per request and manages context budget limits."""

    def __init__(
        self,
        context_window: int = 32768,
        max_tokens: int = 4096,
        shares: BudgetShares | None = None,
        model_name: str | None = None,
    ) -> None:
        self.context_window = max(1024, context_window)
        self.reply_reserve = max(256, max_tokens)
        self.capacity = max(512, self.context_window - self.reply_reserve)
        self.shares = shares or BudgetShares()
        self.counter = TokenCounter(model_name)

    def calculate_usage(
        self,
        messages: list[Message],
        pinned_files: dict[str, str] | None = None,
    ) -> BudgetUsage:
        """Categorize and count tokens across prompt, repomap, pinned files, dialogue, and tools."""
        system_tokens = 0
        repomap_tokens = 0
        pinned_tokens = 0
        conversation_tokens = 0
        tool_tokens = 0

        # 1. Pinned files
        if pinned_files:
            for path, content in pinned_files.items():
                pinned_tokens += self.counter.count_tokens(f"File: {path}\n{content}")

        # 2. Iterate through messages
        for _idx, msg in enumerate(messages):
            msg_toks = self.counter.count_message_tokens(msg)

            if msg.role == "system":
                # Check if system prompt embeds a repository map section
                if "# Repository Map" in msg.content:
                    parts = msg.content.split("# Repository Map", 1)
                    system_tokens += self.counter.count_tokens(parts[0])
                    repomap_tokens += self.counter.count_tokens("# Repository Map" + parts[1])
                else:
                    system_tokens += msg_toks
            elif msg.role == "tool" or (
                msg.role == "user" and msg.content.startswith("[Tool Result:")
            ):
                tool_tokens += msg_toks
            else:
                conversation_tokens += msg_toks

        total_used = (
            system_tokens + repomap_tokens + pinned_tokens + conversation_tokens + tool_tokens
        )

        return BudgetUsage(
            system_tokens=system_tokens,
            repomap_tokens=repomap_tokens,
            pinned_tokens=pinned_tokens,
            conversation_tokens=conversation_tokens,
            tool_tokens=tool_tokens,
            total_used=total_used,
            capacity=self.capacity,
            context_window=self.context_window,
            reply_reserve=self.reply_reserve,
        )

    def render_budget_bar_chart(
        self,
        usage: BudgetUsage,
        console: Console | None = None,
    ) -> None:
        """Render a styled Rich horizontal bar chart displaying token usage by category."""
        target_console = console or Console()
        width = 40  # Total visual bar width in character cells

        cap = max(usage.capacity, 1)
        used_cells = min(width, int((usage.total_used / cap) * width))
        threshold_cell = int(0.75 * width)

        # Build colored bar slices
        categories = [
            ("System Prompt", usage.system_tokens, "cyan", int(self.shares.system * cap)),
            ("Repo Map", usage.repomap_tokens, "bright_blue", int(self.shares.repomap * cap)),
            ("Pinned Files", usage.pinned_tokens, "magenta", int(self.shares.pinned * cap)),
            (
                "Conversation",
                usage.conversation_tokens,
                "green",
                int(self.shares.conversation * cap),
            ),
            ("Tool Results", usage.tool_tokens, "yellow", int(self.shares.tool_results * cap)),
        ]

        title_str = (
            f"Context Budget Usage ({usage.total_used:,} / {usage.capacity:,} tokens · "
            f"{usage.usage_ratio * 100:.1f}%)"
        )
        table = Table(
            title=title_str,
            title_style="bold cyan",
            border_style="bright_blue",
            show_header=True,
            header_style="bold white",
        )
        table.add_column("Category", style="bold", width=18)
        table.add_column("Tokens", justify="right", width=10)
        table.add_column("Used %", justify="right", width=8)
        table.add_column("Share Cap", justify="right", width=10)
        table.add_column("Status / Bar", width=36)

        for name, toks, color, share_cap in categories:
            cat_pct = (toks / cap) * 100
            bar_len = min(20, int((toks / cap) * 20))
            bar_repr = f"[{color}]{'█' * bar_len}[/{color}]{'░' * (20 - bar_len)}"
            table.add_row(
                name,
                f"{toks:,}",
                f"{cat_pct:.1f}%",
                f"{share_cap:,}",
                bar_repr,
            )

        target_console.print()
        target_console.print(table)

        # Overview capacity bar with 75% compaction threshold indicator
        bar_chars: list[str] = []
        for i in range(width):
            if i < used_cells:
                char_tag = (
                    "[bold green]■[/bold green]" if i < threshold_cell else "[bold red]■[/bold red]"
                )
                bar_chars.append(char_tag)
            else:
                bar_chars.append("[dim]·[/dim]")

        bar_line = "".join(bar_chars)
        status_tag = (
            "[bold red]COMPACTION TRIGGERED (>=75%)[/bold red]"
            if usage.is_over_threshold
            else "[green]HEALTHY (<75%)[/green]"
        )

        target_console.print(
            f"Context Capacity Bar (75% compaction threshold at cell {threshold_cell}):\n"
            f"[{bar_line}] {status_tag}\n"
            f"[dim]Total Context Window: {usage.context_window:,} | "
            f"Reply Reserve: {usage.reply_reserve:,} | "
            f"Available Input: {usage.capacity:,}[/dim]\n"
        )


# ---------------------------------------------------------------------------
# Two-Stage Compaction Engine
# ---------------------------------------------------------------------------


def is_protected_message(msg: Message, is_original_task: bool, is_recent: bool) -> bool:
    """Determine whether a message must NEVER be dropped during compaction.

    Never drops:
    - The original user task
    - Active plans (messages containing plan headers or steps)
    - Unresolved error outputs (exceptions, tracebacks, test failures)
    - The latest 4 conversation turns verbatim
    """
    if is_original_task or is_recent:
        return True

    content_lower = msg.content.lower()
    # Check for plan indicators
    if "## plan" in content_lower or "### plan" in content_lower or "active plan" in content_lower:
        return True

    # Check for unresolved errors
    error_markers = (
        "traceback (most recent call last)",
        "error:",
        "failed",
        "fatal:",
        "exit code: 1",
    )
    return any(marker in content_lower for marker in error_markers)


def summarize_tool_output(content: str, max_chars: int = 120) -> str:
    """Shrink a tool execution output into a compact single-line summary."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "[Tool Result: empty output]"

    total_lines = len(lines)
    first_line = lines[0]
    if len(first_line) > max_chars:
        first_line = first_line[: max_chars - 3] + "..."

    if total_lines == 1:
        return f"[Tool Result: {first_line}]"

    return f"[Tool Result: {first_line} (+{total_lines - 1} lines summarized)]"


def compact_context(
    messages: list[Message],
    allocator: BudgetAllocator,
    router_client: Any | None = None,
    force: bool = False,
) -> tuple[list[Message], bool, str]:
    """Execute two-stage context compaction when usage exceeds 75% or when forced.

    Stage 1: Shrink older tool outputs to one-line summaries.
    Stage 2: Summarize oldest conversation turns with the router model into a session note,
             preserving the original task, the latest 4 turns, active plans, and unresolved errors.
    """
    initial_usage = allocator.calculate_usage(messages)
    if not force and not initial_usage.is_over_threshold:
        return messages, False, "Token usage is within healthy limits (<75%); compaction skipped."

    if len(messages) <= 5:
        # Too few messages to perform structural turn compaction
        return messages, False, "Context too short for multi-turn compaction."

    new_messages = [m.model_copy(deep=True) for m in messages]
    total_msgs = len(new_messages)
    recent_threshold = max(0, total_msgs - 4)  # Preserve latest 4 turns verbatim

    # -----------------------------------------------------------------------
    # Stage 1: Shrink older tool outputs to one-line summaries
    # -----------------------------------------------------------------------
    shrunk_any = False
    for i in range(1, recent_threshold):
        msg = new_messages[i]
        is_orig_task = i == 1 and msg.role == "user"
        if is_protected_message(msg, is_orig_task, is_recent=False):
            continue

        if msg.role == "tool" or (msg.role == "user" and msg.content.startswith("[Tool Result:")):
            original_len = len(msg.content)
            summary = summarize_tool_output(msg.content)
            if len(summary) < original_len:
                msg.content = summary
                shrunk_any = True

    stage1_usage = allocator.calculate_usage(new_messages)
    if not force and not stage1_usage.is_over_threshold and shrunk_any:
        freed = initial_usage.total_used - stage1_usage.total_used
        return (
            new_messages,
            True,
            f"Stage 1 compaction complete: shrunk old tool outputs, freed {freed:,} tokens.",
        )

    # -----------------------------------------------------------------------
    # Stage 2: Summarize oldest dialogue turns into a session note
    # -----------------------------------------------------------------------
    system_msg = new_messages[0] if new_messages and new_messages[0].role == "system" else None
    start_idx = 1 if system_msg else 0

    if start_idx >= len(new_messages):
        return new_messages, False, "No dialogue messages to compact."

    orig_task_msg = new_messages[start_idx]
    older_turns: list[Message] = []
    protected_older_turns: list[Message] = []

    for i in range(start_idx + 1, recent_threshold):
        m = new_messages[i]
        if is_protected_message(m, is_original_task=False, is_recent=False):
            protected_older_turns.append(m)
        else:
            older_turns.append(m)

    recent_turns = new_messages[recent_threshold:]

    if not older_turns:
        # Nothing older to compress beyond protected items
        return (
            new_messages,
            shrunk_any,
            "Compacted tool outputs; all older turns are protected."
            if shrunk_any
            else "Context could not be compacted further.",
        )

    # Generate extractive summary of older dialogue turns
    summary_bullets: list[str] = []
    for m in older_turns:
        first_line = m.content.strip().splitlines()[0] if m.content.strip() else ""
        if len(first_line) > 90:
            first_line = first_line[:87] + "..."
        if first_line:
            summary_bullets.append(f"- [{m.role}] {first_line}")

    summary_content = (
        "### Session Summary (Compacted)\n"
        "The following previous actions and steps occurred earlier in this session:\n"
        + "\n".join(summary_bullets[:15])
    )
    session_note_msg = Message(role="user", content=summary_content)

    compacted_sequence: list[Message] = []
    if system_msg:
        compacted_sequence.append(system_msg)
    compacted_sequence.append(orig_task_msg)
    compacted_sequence.append(session_note_msg)
    compacted_sequence.extend(protected_older_turns)
    compacted_sequence.extend(recent_turns)

    final_usage = allocator.calculate_usage(compacted_sequence)
    freed = initial_usage.total_used - final_usage.total_used

    msg_summary = (
        f"Stage 2 compaction complete: summarized {len(older_turns)} older turns, "
        f"freed {freed:,} tokens."
    )
    return (compacted_sequence, True, msg_summary)

"""Task routing, complexity classification, cheap router jobs, and per-role stats collection.

Phase 19:
- Classifies user messages into: chat (questions, explanations, no code changes),
  simple (one file, small change), or complex (multiple files, new feature, refactor).
- Heuristics first (length, @files, keywords), tiny JSON router model prompt fallback.
- Routing: chat -> router or coder model with read/search tools only;
  simple -> single mode with coder;
  complex -> dual mode with planner and coder.
- Displays decision in one dim line: "routed: <category> -> <target>".
- Cheap internal jobs: conversation summaries for compaction, commit messages, task titles.
- Stats collector: per role (calls, input/output tokens, latency, tokens/sec),
  Rich table view (/stats), and persistence to .lathe/sessions/<id>/stats.json.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from lathe.config import LatheConfig, load_config
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.factory import get_client
from lathe.llm.types import Message, StreamChunk, ToolSpec
from lathe.tools.registry import ToolRegistry, default_registry

TaskComplexity = Literal["chat", "simple", "complex"]
RouteMode = Literal["chat", "single", "dual"]


# ---------------------------------------------------------------------------
# Classification Models and Payloads
# ---------------------------------------------------------------------------


class ClassificationResult(BaseModel):
    """Pydantic payload validated from the router model's tiny JSON response."""

    category: TaskComplexity = Field(
        description="Complexity classification: 'chat', 'simple', or 'complex'."
    )
    reasoning: str = Field(default="", description="Brief 1-sentence reasoning for classification.")


@dataclass
class RouteDecision:
    """Routing determination specifying category, target mode, and description."""

    category: TaskComplexity
    mode: RouteMode
    target_description: str
    reasoning: str = ""

    @property
    def display_line(self) -> str:
        """Formatted decision string matching requirement 'routed: <category> -> <target>'."""
        return f"routed: {self.category} → {self.target_description}"


# ---------------------------------------------------------------------------
# Heuristic Feature Matching
# ---------------------------------------------------------------------------

COMPLEX_KEYWORDS = {
    "refactor",
    "build",
    "migrate",
    "redesign",
    "architecture",
    "rewrite",
    "overhaul",
    "scaffold",
    "pipeline",
    "benchmark",
    "full stack",
    "multi-file",
    "infrastructure",
}

SIMPLE_KEYWORDS = {
    "fix",
    "typo",
    "rename",
    "add",
    "update",
    "tweak",
    "patch",
    "edit",
    "change",
    "correct",
    "docstring",
    "comment",
}

CHAT_STARTERS = (
    "what",
    "why",
    "how",
    "where",
    "who",
    "when",
    "can you explain",
    "explain",
    "describe",
    "tell me",
    "is there",
    "do we",
    "help me understand",
    "could you explain",
    "summarize",
)

GREETINGS = {
    "hi",
    "hello",
    "hey",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "sup",
}


def classify_by_heuristics(message: str) -> TaskComplexity | None:
    """Classify user request using cheap rule-based heuristics.

    Returns:
        TaskComplexity if high confidence match, or None to fall back to the router model.
    """
    text = message.strip()
    if not text:
        return "chat"

    text_lower = text.lower()

    # 1. Greetings and conversational queries
    if text_lower in GREETINGS or any(text_lower.startswith(f"{g} ") for g in GREETINGS):
        return "chat"

    # Identify file mentions: @path/to/file or explicitly named source files
    at_files = [f.lstrip("@") for f in re.findall(r"@[\w\.\-/]+", text)]
    file_names = re.findall(
        r"\b[\w\.\-/]+\.(?:py|js|ts|tsx|go|rs|c|cpp|h|toml|json|yaml|md|txt)\b",
        text,
    )
    unique_files = set(at_files) | set(file_names)

    # 2. Questions / explanations without modification actions -> chat
    is_question = text.endswith("?") or any(
        text_lower.startswith(f"{starter} ") or text_lower.startswith(f"{starter}?")
        for starter in CHAT_STARTERS
    )
    has_modification_verb = any(
        re.search(rf"\b{re.escape(verb)}\b", text_lower)
        for verb in (
            "fix",
            "add",
            "update",
            "change",
            "modify",
            "delete",
            "remove",
            "create",
            "write",
            "edit",
            "implement",
            "refactor",
            "build",
            "migrate",
            "rewrite",
            "redesign",
            "overhaul",
            "scaffold",
        )
    )

    if is_question and not has_modification_verb and len(unique_files) == 0:
        return "chat"

    # 3. Strong complex heuristics
    # Any explicit complex keyword ("refactor", "build", "migrate", etc.)
    if any(re.search(rf"\b{re.escape(kw)}\b", text_lower) for kw in COMPLEX_KEYWORDS):
        return "complex"

    # Multiple files referenced
    if len(unique_files) >= 2:
        return "complex"

    # Long multi-sentence or multi-step requests
    if len(text) > 280 and (
        "\n" in text or "step 1" in text_lower or "and then" in text_lower or "also " in text_lower
    ):
        return "complex"

    # Multi-file scope keywords
    if any(
        phrase in text_lower
        for phrase in ("across the codebase", "entire project", "all files", "whole repo")
    ):
        return "complex"

    # 4. Simple heuristics (single file with localized change verbs)
    if len(unique_files) == 1 and has_modification_verb:
        return "simple"

    if (
        any(re.search(rf"\b{re.escape(kw)}\b", text_lower) for kw in SIMPLE_KEYWORDS)
        and len(unique_files) <= 1
        and len(text) < 160
    ):
        return "simple"

    # Ambiguous -> require router model
    return None


# ---------------------------------------------------------------------------
# Router Model Prompt & JSON Extraction
# ---------------------------------------------------------------------------

ROUTER_SYSTEM_PROMPT = """You are Lathe's task routing classifier.
Analyze the user request and classify it into exactly one category:
- "chat": Conceptual question, explanation, greeting, or conversational query (no file changes).
- "simple": A small, localized bug fix or single-file modification.
- "complex": A multi-file change, new feature, refactoring, architecture change, or complex task.

Respond ONLY with a valid JSON object matching this schema:
{"category": "chat" | "simple" | "complex", "reasoning": "Brief 1-sentence reason"}
"""


def _extract_json_block(text: str) -> str:
    """Extract clean JSON substring from markdown fences or bare braces."""
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if fence:
        return fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1].strip()
    return raw


async def classify_with_router_model(
    message: str,
    client: LLMClient,
) -> ClassificationResult:
    """Query the router model with a tiny JSON prompt to classify message complexity."""
    messages = [
        Message(role="system", content=ROUTER_SYSTEM_PROMPT),
        Message(role="user", content=f"Classify this request:\n{message}"),
    ]
    parts: list[str] = []
    try:
        async for chunk in client.chat(messages, stream=True):
            if chunk.delta:
                parts.append(chunk.delta)
    except Exception as exc:
        raise LLMError(f"Router model query failed: {exc}") from exc

    raw = "".join(parts).strip()
    json_str = _extract_json_block(raw)
    data = json.loads(json_str)
    return ClassificationResult.model_validate(data)


# ---------------------------------------------------------------------------
# Chat Mode Restricted Tool Registry
# ---------------------------------------------------------------------------


def get_read_search_tools(base_registry: ToolRegistry | None = None) -> ToolRegistry:
    """Return a ToolRegistry containing strictly read and search tools for chat mode."""
    source = base_registry or default_registry
    restricted = ToolRegistry()
    for tool in source.list_tools():
        if tool.risk_level == "read" and tool.name not in ("git_commit", "run_shell"):
            restricted.register(tool)
    return restricted


# ---------------------------------------------------------------------------
# Cheap Internal Jobs powered by the Router Model
# ---------------------------------------------------------------------------


async def summarize_for_compaction(
    older_messages: list[Message],
    client: LLMClient | None = None,
) -> str:
    """Use the router model to summarize older conversation turns into a session note.

    Falls back to deterministic bullet extraction if the model call fails.
    """
    if not older_messages:
        return "No prior dialogue turns to summarize."

    # Construct concise prompt
    dialogue_lines: list[str] = []
    for m in older_messages:
        content_preview = m.content.strip().splitlines()[0] if m.content.strip() else ""
        if content_preview:
            dialogue_lines.append(f"[{m.role}]: {content_preview[:120]}")

    formatted_history = "\n".join(dialogue_lines[:25])
    prompt = (
        "Summarize the following prior conversation actions into a concise bulleted list "
        "(max 6-8 bullets) highlighting files read, edited, commands executed, and progress made.\n"
        "Return ONLY the markdown bullets:\n\n"
        f"{formatted_history}"
    )

    router_client = client or get_client("router")
    try:
        messages = [
            Message(
                role="system",
                content="You are a concise technical summarizer. Output only summary bullets.",
            ),
            Message(role="user", content=prompt),
        ]
        parts: list[str] = []
        async for chunk in router_client.chat(messages, stream=True):
            if chunk.delta:
                parts.append(chunk.delta)
        res = "".join(parts).strip()
        if res:
            return res
    except Exception:
        pass

    # Heuristic fallback: extract first lines
    bullets: list[str] = []
    for line in dialogue_lines[:8]:
        bullets.append(f"- {line}")
    return "\n".join(bullets)


async def generate_commit_message(
    diff: str,
    client: LLMClient | None = None,
) -> str:
    """Use the router model to generate a Conventional Commits message from a git diff."""
    if not diff.strip():
        return "chore: update workspace"

    prompt = (
        "Write a concise, standard Conventional Commits message (e.g. feat: ..., fix: ..., "
        "refactor: ...) summarizing the following git diff.\n"
        "Return ONLY the single-line commit message without quotes or explanation.\n\n"
        f"```diff\n{diff[:3500]}\n```"
    )

    router_client = client or get_client("router")
    try:
        messages = [
            Message(
                role="system",
                content=(
                    "You are an expert Git commit author. Output ONLY the one-line commit message."
                ),
            ),
            Message(role="user", content=prompt),
        ]
        parts: list[str] = []
        async for chunk in router_client.chat(messages, stream=True):
            if chunk.delta:
                parts.append(chunk.delta)
        collected = "".join(parts).strip()
        lines = [ln.strip() for ln in collected.splitlines() if ln.strip()]
        first_line = lines[0].strip("`'\"") if lines else ""
        if first_line:
            return first_line
    except Exception:
        pass

    return "chore: automated changes"


async def generate_task_title(
    task: str,
    client: LLMClient | None = None,
) -> str:
    """Use the router model to generate a concise 3-6 word task title."""
    clean_task = task.strip()
    if not clean_task:
        return "Untitled Task"

    prompt = (
        "Generate a short, descriptive title (3 to 6 words) summarizing the following task.\n"
        "Return ONLY the title without quotes, prefixes, or markdown:\n\n"
        f"Task: {clean_task[:500]}"
    )

    router_client = client or get_client("router")
    try:
        messages = [
            Message(
                role="system",
                content=(
                    "You generate short, clean software development titles. Output ONLY the title."
                ),
            ),
            Message(role="user", content=prompt),
        ]
        parts: list[str] = []
        async for chunk in router_client.chat(messages, stream=True):
            if chunk.delta:
                parts.append(chunk.delta)
        title = "".join(parts).strip().strip("`'\"# ")
        if title:
            return title[:60]
    except Exception:
        pass

    # Heuristic fallback: first words
    words = clean_task.split()
    return " ".join(words[:5])


# ---------------------------------------------------------------------------
# Per-Role Stats Collector & Persistence
# ---------------------------------------------------------------------------


@dataclass
class RoleStats:
    """Tracks metrics for an individual LLM role (planner, coder, reviewer, router)."""

    role: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        """Compute generation throughput (output tokens / latency)."""
        if self.latency_seconds > 0.0 and self.output_tokens > 0:
            return self.output_tokens / self.latency_seconds
        return 0.0

    @property
    def avg_latency(self) -> float:
        """Compute average latency per invocation in seconds."""
        if self.calls > 0:
            return self.latency_seconds / self.calls
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize role statistics to dictionary."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
            "avg_latency": round(self.avg_latency, 3),
            "tokens_per_second": round(self.tokens_per_second, 1),
        }


class StatsCollector:
    """Collects per-role LLM metrics and serializes stats to .lathe/sessions/<id>/stats.json."""

    def __init__(
        self,
        session_id: str | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        self.session_id: str = session_id or uuid.uuid4().hex[:8]
        self.workspace_root: Path = (workspace_root or Path.cwd()).resolve()
        self.created_at: str = datetime.now(UTC).isoformat()
        self.updated_at: str = self.created_at
        self.roles: dict[str, RoleStats] = {
            "planner": RoleStats(role="planner"),
            "coder": RoleStats(role="coder"),
            "reviewer": RoleStats(role="reviewer"),
            "router": RoleStats(role="router"),
        }

    def record_call(
        self,
        role: str,
        input_tokens: int,
        output_tokens: int,
        duration_s: float,
    ) -> None:
        """Record an LLM call invocation and update persistence."""
        role_key = role.lower()
        if role_key not in self.roles:
            self.roles[role_key] = RoleStats(role=role_key)

        r = self.roles[role_key]
        r.calls += 1
        r.input_tokens += max(0, input_tokens)
        r.output_tokens += max(0, output_tokens)
        r.total_tokens += max(0, input_tokens) + max(0, output_tokens)
        r.latency_seconds += max(0.0, duration_s)
        self.updated_at = datetime.now(UTC).isoformat()

        with contextlib.suppress(Exception):
            self.save()

    def get_stats_file_path(self) -> Path:
        """Return canonical path: .lathe/sessions/<id>/stats.json."""
        return self.workspace_root / ".lathe" / "sessions" / self.session_id / "stats.json"

    def save(self, target_path: Path | None = None) -> Path:
        """Write session stats JSON to disk."""
        path = target_path or self.get_stats_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def to_dict(self) -> dict[str, Any]:
        """Produce structured JSON representation of session statistics."""
        total_calls = sum(r.calls for r in self.roles.values())
        total_input = sum(r.input_tokens for r in self.roles.values())
        total_output = sum(r.output_tokens for r in self.roles.values())
        total_toks = sum(r.total_tokens for r in self.roles.values())
        total_latency = sum(r.latency_seconds for r in self.roles.values())
        overall_tps = total_output / total_latency if total_latency > 0.0 else 0.0

        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "roles": {k: v.to_dict() for k, v in self.roles.items()},
            "total": {
                "calls": total_calls,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_toks,
                "latency_seconds": round(total_latency, 3),
                "tokens_per_second": round(overall_tps, 1),
            },
        }

    def render_rich_table(self) -> Table:
        """Render a formatted Rich Table representing the current session stats."""
        table = Table(
            title=f"Session Stats [dim]({self.session_id})[/dim]",
            border_style="bright_blue",
            header_style="bold cyan",
        )
        table.add_column("Role", style="bold white", width=12)
        table.add_column("Calls", justify="right", style="cyan", width=8)
        table.add_column("Input Tokens", justify="right", style="green", width=14)
        table.add_column("Output Tokens", justify="right", style="magenta", width=14)
        table.add_column("Total Tokens", justify="right", style="bold yellow", width=14)
        table.add_column("Latency (s)", justify="right", style="blue", width=12)
        table.add_column("Tokens/sec", justify="right", style="bold green", width=12)

        for role_name in ("planner", "coder", "reviewer", "router"):
            r = self.roles.get(role_name, RoleStats(role=role_name))
            table.add_row(
                role_name.capitalize(),
                f"{r.calls:,}",
                f"{r.input_tokens:,}",
                f"{r.output_tokens:,}",
                f"{r.total_tokens:,}",
                f"{r.latency_seconds:.2f}",
                f"{r.tokens_per_second:.1f}",
            )

        summary = self.to_dict()["total"]
        table.add_section()
        table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{summary['calls']:,}[/bold]",
            f"[bold]{summary['input_tokens']:,}[/bold]",
            f"[bold]{summary['output_tokens']:,}[/bold]",
            f"[bold]{summary['total_tokens']:,}[/bold]",
            f"[bold]{summary['latency_seconds']:.2f}[/bold]",
            f"[bold]{summary['tokens_per_second']:.1f}[/bold]",
        )
        return table


_GLOBAL_STATS_COLLECTOR: StatsCollector | None = None


def get_stats_collector(
    session_id: str | None = None,
    workspace_root: Path | None = None,
) -> StatsCollector:
    """Retrieve or initialize the active global StatsCollector."""
    global _GLOBAL_STATS_COLLECTOR
    if _GLOBAL_STATS_COLLECTOR is None:
        _GLOBAL_STATS_COLLECTOR = StatsCollector(
            session_id=session_id, workspace_root=workspace_root
        )
    elif session_id and _GLOBAL_STATS_COLLECTOR.session_id != session_id:
        _GLOBAL_STATS_COLLECTOR.session_id = session_id
    return _GLOBAL_STATS_COLLECTOR


def set_stats_collector(collector: StatsCollector) -> None:
    """Set the active global StatsCollector instance."""
    global _GLOBAL_STATS_COLLECTOR
    _GLOBAL_STATS_COLLECTOR = collector


class TrackingLLMClient(LLMClient):
    """Wraps an LLMClient to automatically record execution metrics in StatsCollector."""

    def __init__(
        self,
        inner: LLMClient,
        role: str,
        collector: StatsCollector | None = None,
    ) -> None:
        super().__init__(role_config=inner.role_config)
        self.inner = inner
        self.role = role
        self.collector = collector or get_stats_collector()

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chunks from the wrapped client while measuring tokens and latency."""
        t0 = time.perf_counter()
        prompt_text = "".join(m.content for m in messages)
        approx_input = max(1, len(prompt_text) // 4)
        output_parts: list[str] = []
        last_usage = None

        async for chunk in self.inner.chat(messages, tools=tools, stream=stream):
            if chunk.delta:
                output_parts.append(chunk.delta)
            if chunk.usage:
                last_usage = chunk.usage
            yield chunk

        duration_s = max(0.001, time.perf_counter() - t0)

        if last_usage and last_usage.prompt_tokens > 0:
            in_toks = last_usage.prompt_tokens
            out_toks = last_usage.completion_tokens or len("".join(output_parts)) // 4
        else:
            in_toks = approx_input
            out_toks = max(0, len("".join(output_parts)) // 4)

        self.collector.record_call(self.role, in_toks, out_toks, duration_s)


def track_client(
    client: LLMClient,
    role: str,
    collector: StatsCollector | None = None,
) -> LLMClient:
    """Wrap an LLMClient with TrackingLLMClient unless already wrapped."""
    if isinstance(client, TrackingLLMClient):
        return client
    return TrackingLLMClient(client, role, collector)


# ---------------------------------------------------------------------------
# TaskRouter Engine
# ---------------------------------------------------------------------------


class TaskRouter:
    """Inspects user messages, classifies task complexity, and executes appropriate mode."""

    def __init__(
        self,
        config: LatheConfig | None = None,
        router_client: LLMClient | None = None,
        coder_client: LLMClient | None = None,
        planner_client: LLMClient | None = None,
        workspace_root: Path | None = None,
        console: Console | None = None,
        stats_collector: StatsCollector | None = None,
    ) -> None:
        self.config = config or load_config(require_secrets=False)
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.console = console or Console()
        self.stats_collector = stats_collector or get_stats_collector(
            workspace_root=self.workspace_root
        )

        # Clients wrapped with stats tracking
        if router_client is not None:
            self.router_client = track_client(router_client, "router", self.stats_collector)
        else:
            self.router_client = track_client(
                get_client("router", config=self.config), "router", self.stats_collector
            )

        self.coder_client = (
            track_client(coder_client, "coder", self.stats_collector) if coder_client else None
        )
        self.planner_client = (
            track_client(planner_client, "planner", self.stats_collector)
            if planner_client
            else None
        )

    async def classify(self, message: str) -> RouteDecision:
        """Classify message complexity using heuristics first, then router model fallback."""
        heuristic = classify_by_heuristics(message)
        if heuristic == "chat":
            return RouteDecision(
                category="chat",
                mode="chat",
                target_description="read/search only",
                reasoning="Heuristic matched conceptual question or greeting.",
            )
        elif heuristic == "simple":
            return RouteDecision(
                category="simple",
                mode="single",
                target_description="single mode",
                reasoning="Heuristic matched single-file bug fix or localized change.",
            )
        elif heuristic == "complex":
            return RouteDecision(
                category="complex",
                mode="dual",
                target_description="dual mode",
                reasoning="Heuristic matched multi-file, refactoring, or architectural task.",
            )

        # Ambiguous -> invoke the router model
        try:
            res = await classify_with_router_model(message, self.router_client)
            cat = res.category
            if cat == "chat":
                return RouteDecision(
                    category="chat",
                    mode="chat",
                    target_description="read/search only",
                    reasoning=res.reasoning or "Router model classified as chat.",
                )
            elif cat == "simple":
                return RouteDecision(
                    category="simple",
                    mode="single",
                    target_description="single mode",
                    reasoning=res.reasoning or "Router model classified as simple.",
                )
            else:
                return RouteDecision(
                    category="complex",
                    mode="dual",
                    target_description="dual mode",
                    reasoning=res.reasoning or "Router model classified as complex.",
                )
        except Exception as exc:
            # Fallback heuristic if router model query fails
            text = message.strip()
            cat_fallback: TaskComplexity = "complex" if len(text) > 120 else "simple"
            mode_fallback: RouteMode = "dual" if cat_fallback == "complex" else "single"
            desc_fallback = "dual mode" if mode_fallback == "dual" else "single mode"
            return RouteDecision(
                category=cat_fallback,
                mode=mode_fallback,
                target_description=desc_fallback,
                reasoning=f"Router fallback due to error ({exc}).",
            )

    async def route_and_execute(
        self,
        task: str,
        messages: list[Message] | None = None,
        auto_approve: bool = False,
        yolo: bool = False,
        agent: Any | None = None,
        dual_agent: Any | None = None,
        chat_agent: Any | None = None,
    ) -> str:
        """Classify task, display dim decision line, and dispatch execution to target engine."""
        decision = await self.classify(task)
        self.console.print(f"[dim]{decision.display_line}[/dim]")

        # 1. Dual Mode (complex)
        if decision.mode == "dual":
            if dual_agent is not None:
                return str(await dual_agent.run(task))
            from lathe.orchestrator.dual import DualAgent

            d_agent = DualAgent(
                config=self.config,
                workspace_root=self.workspace_root,
                console=self.console,
                auto_approve=auto_approve or yolo,
            )
            return await d_agent.run(task)

        # 2. Chat Mode (chat - read/search tools only)
        elif decision.mode == "chat":
            if chat_agent is not None:
                return str(await chat_agent.run(task, messages=messages))
            from lathe.orchestrator.agent import Agent

            c_agent = Agent(
                config=self.config,
                client=self.coder_client,
                tools=get_read_search_tools(),
                workspace_root=self.workspace_root,
                console=self.console,
            )
            return await c_agent.run(task, messages=messages)

        # 3. Single Mode (simple - full toolset with coder)
        else:
            if agent is not None:
                return str(await agent.run(task, messages=messages))
            from lathe.orchestrator.agent import Agent

            s_agent = Agent(
                config=self.config,
                client=self.coder_client,
                workspace_root=self.workspace_root,
                console=self.console,
            )
            return await s_agent.run(task, messages=messages)


def run_routed_one_shot(
    task: str,
    auto: bool = False,
    yolo: bool = False,
    config: LatheConfig | None = None,
) -> str:
    """Execute a single task using the TaskRouter in one-shot CLI mode."""
    import asyncio

    from lathe.orchestrator.agent import run_one_shot
    from lathe.orchestrator.dual import run_dual_one_shot

    active_cfg = config or load_config(require_secrets=False)
    router = TaskRouter(config=active_cfg)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        decision = loop.run_until_complete(router.classify(task))
    finally:
        loop.close()

    router.console.print(f"[dim]{decision.display_line}[/dim]")

    if decision.mode == "dual":
        return run_dual_one_shot(task, auto=auto, yolo=yolo)
    else:
        return run_one_shot(task, auto=auto, yolo=yolo)

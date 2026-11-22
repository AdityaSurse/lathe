"""Dual-model orchestrator coordinating Planner and Coder models.

In dual mode:
1. Planner analyzes the task, repo map, and search results to produce a structured JSON Plan.
2. The user inspects the plan as a live checklist, with options to approve [y],
   edit in $EDITOR [e], or reject [n].
3. For each plan step, the Coder agent executes in a focused context (step instructions,
   target files, previous summaries).
4. After each step, the Planner reviews progress and may revise remaining steps
   (insert, remove, reorder).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from lathe.config import LatheConfig, load_config
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.factory import get_client
from lathe.llm.types import Message
from lathe.orchestrator.agent import Agent
from lathe.orchestrator.events import (
    AgentHaltEvent,
    EventBus,
    FinalAnswerEvent,
    PlanCreatedEvent,
    PlanRevisedEvent,
    StepDoneEvent,
    StepStartedEvent,
)
from lathe.safety.checkpoints import CheckpointManager, get_checkpoint_manager
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.tools.registry import ToolRegistry, default_registry


class PlanStep(BaseModel):
    """Atomic step within a structured execution plan."""

    id: int | str = Field(description="Step identifier (integer or string label).")
    title: str = Field(description="Crisp title describing the step objective.")
    files_to_read: list[str] = Field(
        default_factory=list, description="Target workspace files to inspect."
    )
    files_to_change: list[str] = Field(
        default_factory=list, description="Workspace files to modify or create."
    )
    instructions: str = Field(
        description="Detailed, specific instructions for the coder agent on this step."
    )
    done_when: str = Field(
        description="Unambiguous verification criteria or tests to confirm step completion."
    )
    status: str = Field(
        default="pending",
        description="Execution status ('pending', 'in_progress', 'completed', 'failed').",
    )
    summary: str | None = Field(
        default=None, description="Post-execution summary of what was accomplished."
    )


class Plan(BaseModel):
    """Structured task execution plan produced by the planner model."""

    goal: str = Field(description="High-level goal and definition of success.")
    steps: list[PlanStep] = Field(default_factory=list, description="Sequential steps to execute.")
    risks: list[str] = Field(
        default_factory=list,
        description="Identified risks, edge cases, or potential failure points.",
    )


class PlanRevision(BaseModel):
    """Revision payload produced by the planner after reviewing step execution."""

    revised: bool = Field(
        default=False,
        description="Whether remaining steps were modified (inserted, removed, or reordered).",
    )
    explanation: str = Field(
        default="", description="Brief explanation for why revisions were made."
    )
    steps: list[PlanStep] = Field(
        default_factory=list, description="Updated list of remaining steps to execute."
    )


PLANNER_SYSTEM_PROMPT = """You are Lathe's expert software architect and planner.
Your job is to analyze the user's task, codebase repository structure, and relevant code
search results to break down the task into small, verifiable, sequential execution steps.

Rules for planning:
1. Each step must be self-contained, atomic, and focused on a single logical change.
2. Specify exact target files to read and change.
3. Provide crisp, unambiguous instructions for the coder agent.
4. Define clear verification criteria in done_when (e.g. 'Unit tests pass').
5. Identify potential risks, breaking changes, or edge cases in risks.
6. Keep the plan concise (typically 2-6 steps).

You MUST respond ONLY with a valid JSON object matching this schema, without conversational
preamble or Markdown explanations outside the JSON:
{
  "goal": "High-level goal and definition of success",
  "steps": [
    {
      "id": 1,
      "title": "Short title for the step",
      "files_to_read": ["path/to/file.py"],
      "files_to_change": ["path/to/file.py"],
      "instructions": "Specific instructions for the coder agent on what to do in this step",
      "done_when": "Verification criteria to determine if step is complete"
    }
  ],
  "risks": [
    "Potential risk, breaking change, or edge case to watch out for"
  ]
}
"""

REVISION_SYSTEM_PROMPT = """You are Lathe's expert planner reviewing execution progress.
A step has just completed. Review the execution outcome and the remaining planned steps.
Decide if remaining steps should be revised (inserted, removed, reordered, or edited).
If no changes are needed, set "revised": false.

Respond ONLY with a valid JSON object matching this schema:
{
  "revised": true,
  "explanation": "Brief explanation of changes (or 'No changes needed')",
  "steps": [
    {
      "id": 2,
      "title": "Title",
      "files_to_read": [],
      "files_to_change": [],
      "instructions": "Instructions",
      "done_when": "Criteria"
    }
  ]
}
"""


def extract_json_block(text: str) -> str:
    """Extract JSON content from markdown code fences or raw string."""
    text_clean = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text_clean)
    if fence_match:
        return fence_match.group(1).strip()
    first_brace = text_clean.find("{")
    last_brace = text_clean.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text_clean[first_brace : last_brace + 1].strip()
    return text_clean


def gather_search_results(workspace_root: Path, task: str) -> str:
    """Perform quick keyword search across workspace for planner context."""
    from lathe.tools.search import _python_fallback_grep, _ripgrep_search

    words = [w for w in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", task) if len(w) >= 4]
    stop_words = {
        "create",
        "build",
        "implement",
        "update",
        "change",
        "write",
        "tests",
        "phase",
        "make",
        "lathe",
    }
    keywords = [w for w in words if w.lower() not in stop_words][:3]

    if not keywords:
        return "(No specific search keywords extracted)"

    results: list[str] = []
    has_rg = shutil.which("rg") is not None
    for kw in keywords:
        try:
            if has_rg:
                out = _ripgrep_search(workspace_root, kw, regex=False, max_matches=5)
            else:
                out = _python_fallback_grep(workspace_root, kw, regex=False, max_matches=5)
            if out is not None and out.strip() and "No matches found" not in out:
                results.append(f"Matches for '{kw}':\n{out}")
        except Exception:
            pass

    return "\n\n".join(results) if results else "(No search matches found for task keywords)"


class DualAgent:
    """Dual-model coordinator pairing a Planner model with a Coder model."""

    def __init__(
        self,
        config: LatheConfig | None = None,
        planner_client: LLMClient | None = None,
        coder_client: LLMClient | None = None,
        tools: ToolRegistry | None = None,
        permission_engine: PermissionEngine | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        workspace_root: Path | None = None,
        event_bus: EventBus | None = None,
        console: Console | None = None,
        auto_approve: bool = False,
        approval_callback: Callable[[Plan], str | Plan] | None = None,
    ) -> None:
        self.config = config or load_config(require_secrets=False)
        self.workspace_root = workspace_root or Path.cwd()
        self.console = console or Console()
        self.tools = tools or default_registry
        self.event_bus = event_bus or EventBus()
        self.permission_engine = permission_engine
        self.checkpoint_manager = checkpoint_manager
        self.auto_approve = auto_approve
        self.approval_callback = approval_callback

        # Initialize planner and coder clients
        if planner_client is not None:
            self.planner_client = planner_client
        else:
            self.planner_client = get_client("planner", config=self.config)

        if coder_client is not None:
            self.coder_client = coder_client
        else:
            self.coder_client = get_client("coder", config=self.config)

    def _get_repo_map(self, task: str) -> str:
        """Extract repository map signatures for the planner prompt."""
        try:
            from lathe.context.repomap import RepoMap

            budget = getattr(self.config.settings, "repomap_token_budget", 2048)
            rm = RepoMap(workspace_root=self.workspace_root, token_budget=budget)
            map_text = rm.get_repo_map(task=task)
            return map_text or "(Empty repository map)"
        except Exception:
            return "(RepoMap unavailable)"

    async def generate_plan(self, task: str) -> Plan:
        """Prompt the planner model to produce a validated JSON execution plan.

        Retries once with the validation error if the initial response fails validation.
        """
        repo_map = self._get_repo_map(task)
        search_results = gather_search_results(self.workspace_root, task)

        user_content = (
            f"# Task\n{task}\n\n"
            f"# Repository Map\n{repo_map}\n\n"
            f"# Search Results\n{search_results}\n\n"
            "Produce the execution plan JSON matching the required schema."
        )

        messages = [
            Message(role="system", content=PLANNER_SYSTEM_PROMPT),
            Message(role="user", content=user_content),
        ]

        # First attempt
        content_parts: list[str] = []
        try:
            async for chunk in self.planner_client.chat(messages, stream=True):
                if chunk.delta:
                    content_parts.append(chunk.delta)
        except LLMError as err:
            raise RuntimeError(f"Planner LLM failed to generate plan: {err}") from err

        raw_text = "".join(content_parts).strip()

        try:
            json_text = extract_json_block(raw_text)
            plan_data = json.loads(json_text)
            return Plan.model_validate(plan_data)
        except Exception as first_err:
            # Retry once with the validation error
            retry_content = (
                f"Your previous response was not a valid plan JSON or failed validation:\n"
                f"{first_err}\n\n"
                f"Previous output:\n{raw_text}\n\n"
                "Please fix the error and return ONLY the valid JSON plan."
            )
            messages.append(Message(role="assistant", content=raw_text))
            messages.append(Message(role="user", content=retry_content))

            retry_parts: list[str] = []
            try:
                async for chunk in self.planner_client.chat(messages, stream=True):
                    if chunk.delta:
                        retry_parts.append(chunk.delta)
            except LLMError as err:
                raise RuntimeError(f"Planner retry failed: {err}") from err

            retry_raw = "".join(retry_parts).strip()
            retry_json = extract_json_block(retry_raw)
            retry_data = json.loads(retry_json)
            return Plan.model_validate(retry_data)

    def render_plan_checklist(self, plan: Plan) -> None:
        """Render plan checklist in the terminal with status icons and risks."""
        table = Table(
            title=f"📋 Plan Checklist: {plan.goal}",
            title_style="bold cyan",
            border_style="bright_blue",
            show_header=True,
            header_style="bold white",
        )
        table.add_column("Step", style="bold green", width=6)
        table.add_column("Title", style="bold white", width=28)
        table.add_column("Files to Change", style="yellow", width=22)
        table.add_column("Done When", style="dim", width=26)

        for s in plan.steps:
            icon = "✓" if s.status == "completed" else "▶" if s.status == "in_progress" else " "
            change_files = ", ".join(s.files_to_change) if s.files_to_change else "(none)"
            table.add_row(f"[{icon}] {s.id}", s.title, change_files, s.done_when)

        self.console.print()
        self.console.print(table)
        if plan.risks:
            self.console.print("\n[bold yellow]Risks / Considerations:[/bold yellow]")
            for r in plan.risks:
                self.console.print(f"  • [yellow]{r}[/yellow]")
        self.console.print()

    def request_plan_approval(self, plan: Plan) -> tuple[str, Plan]:
        """Prompt user for approval, edit, or rejection of the plan."""
        current_plan = plan

        while True:
            self.render_plan_checklist(current_plan)

            if self.approval_callback is not None:
                cb_res = self.approval_callback(current_plan)
                if isinstance(cb_res, Plan):
                    return "y", cb_res
                choice = str(cb_res).strip().lower()
            elif self.auto_approve or not sys.stdin.isatty():
                choice = "y"
            else:
                try:
                    choice = (
                        self.console.input(
                            "[bold cyan]Approve plan? [y]es / [e]dit / [n]o (reject): [/bold cyan]"
                        )
                        .strip()
                        .lower()
                    )
                except (EOFError, KeyboardInterrupt):
                    choice = "n"

            if choice in ("y", "yes", ""):
                return "y", current_plan

            if choice in ("n", "no", "reject"):
                return "n", current_plan

            if choice in ("e", "edit"):
                editor = os.environ.get("EDITOR") or (
                    "notepad" if sys.platform == "win32" else "nano"
                )
                with tempfile.NamedTemporaryFile(
                    suffix=".json", mode="w+", delete=False, encoding="utf-8"
                ) as tf:
                    tf.write(current_plan.model_dump_json(indent=2))
                    temp_path = Path(tf.name)

                try:
                    subprocess.run([editor, str(temp_path)], check=True)
                    edited_raw = temp_path.read_text(encoding="utf-8")
                    new_plan = Plan.model_validate_json(edited_raw)
                    current_plan = new_plan
                    self.console.print("[bold green]✓ Plan updated from editor.[/bold green]")
                except Exception as err:
                    self.console.print(f"[bold red]Failed to parse edited plan:[/bold red] {err}")
                finally:
                    if temp_path.exists():
                        temp_path.unlink()

    async def _review_and_revise_remaining(
        self,
        completed_step: PlanStep,
        step_summary: str,
        remaining_steps: list[PlanStep],
    ) -> list[PlanStep]:
        """Ask the planner model if remaining steps should be revised after a step completes."""
        if not remaining_steps:
            return []

        remaining_json = json.dumps([s.model_dump() for s in remaining_steps], indent=2)
        user_content = (
            f"Step '{completed_step.title}' has just finished execution.\n\n"
            f"# Execution Summary\n{step_summary}\n\n"
            f"# Remaining Steps\n{remaining_json}\n\n"
            "Would you like to revise the remaining steps? Set revised to true if modifying steps."
        )

        messages = [
            Message(role="system", content=REVISION_SYSTEM_PROMPT),
            Message(role="user", content=user_content),
        ]

        content_parts: list[str] = []
        try:
            async for chunk in self.planner_client.chat(messages, stream=True):
                if chunk.delta:
                    content_parts.append(chunk.delta)
            raw_text = "".join(content_parts).strip()
            rev_data = json.loads(extract_json_block(raw_text))
            revision = PlanRevision.model_validate(rev_data)

            if revision.revised and revision.steps:
                await self.event_bus.emit(
                    PlanRevisedEvent(
                        explanation=revision.explanation or "Planner updated remaining steps.",
                        total_steps=len(revision.steps),
                        remaining_steps=[s.model_dump() for s in revision.steps],
                    )
                )
                return revision.steps
        except Exception:
            # Fall back to original remaining steps on parsing error
            pass

        return remaining_steps

    async def run(self, task: str) -> str:
        """Execute the dual-model planning and execution pipeline."""
        # 1. Planner generates structured plan
        try:
            plan = await self.generate_plan(task)
        except Exception as err:
            err_msg = f"Planning failed: {err}"
            await self.event_bus.emit(AgentHaltEvent(reason=err_msg, total_steps=0))
            await self.event_bus.emit(FinalAnswerEvent(content=err_msg, total_steps=0))
            return err_msg

        # Emit plan created event
        await self.event_bus.emit(
            PlanCreatedEvent(
                plan_goal=plan.goal,
                total_steps=len(plan.steps),
                steps=[s.model_dump() for s in plan.steps],
                risks=plan.risks,
            )
        )

        # 2. Interactive Checklist & User Approval
        decision, approved_plan = self.request_plan_approval(plan)
        if decision != "y":
            reject_msg = "Plan rejected by user."
            await self.event_bus.emit(AgentHaltEvent(reason=reject_msg, total_steps=0))
            await self.event_bus.emit(FinalAnswerEvent(content=reject_msg, total_steps=0))
            return reject_msg

        plan = approved_plan
        previous_summaries: list[str] = []
        current_step_idx = 0

        # 3. Step-by-step Coder execution with focused context
        while current_step_idx < len(plan.steps):
            step = plan.steps[current_step_idx]
            step.status = "in_progress"

            # Emit step started event
            await self.event_bus.emit(
                StepStartedEvent(
                    step_number=current_step_idx + 1,
                    total_steps=len(plan.steps),
                    title=step.title,
                    instructions=step.instructions,
                    files_to_read=step.files_to_read,
                    files_to_change=step.files_to_change,
                    step_index=current_step_idx + 1,
                )
            )

            # Build focused context for the coder
            prompt_sections = [
                f"# Current Plan Step: [{current_step_idx + 1}/{len(plan.steps)}] {step.title}",
                "",
                "## Instructions",
                step.instructions,
                "",
            ]
            if step.files_to_read:
                prompt_sections.append(
                    "## Files to Read\n" + "\n".join(f"- @{f}" for f in step.files_to_read)
                )
            if step.files_to_change:
                prompt_sections.append(
                    "## Files to Change\n" + "\n".join(f"- @{f}" for f in step.files_to_change)
                )
            prompt_sections.extend(
                [
                    "",
                    f"## Done When\n{step.done_when}",
                ]
            )
            if previous_summaries:
                prompt_sections.extend(
                    [
                        "",
                        "## Previous Steps Summary",
                        "\n".join(f"- {s}" for s in previous_summaries),
                    ]
                )

            step_task = "\n".join(prompt_sections)

            # Forward tool and thinking events from step_agent while suppressing intermediate
            # FinalAnswerEvents (which are represented by StepDoneEvent).
            step_bus = EventBus()

            async def _forward_step_event(evt: Any) -> None:
                if not isinstance(evt, FinalAnswerEvent):
                    await self.event_bus.emit(evt)

            step_bus.subscribe(_forward_step_event)

            # Instantiate focused agent loop for this step
            step_agent = Agent(
                config=self.config,
                client=self.coder_client,
                tools=self.tools,
                permission_engine=self.permission_engine,
                checkpoint_manager=self.checkpoint_manager,
                workspace_root=self.workspace_root,
                event_bus=step_bus,
                console=self.console,
            )

            step_result = await step_agent.run(step_task)
            step.status = "completed"
            step.summary = step_result

            # Record summary
            first_summary_line = step_result.strip().split("\n")[0] if step_result else "Done"
            previous_summaries.append(
                f"Step [{current_step_idx + 1}] ({step.title}): {first_summary_line[:120]}"
            )

            # Emit step done event
            await self.event_bus.emit(
                StepDoneEvent(
                    step_number=current_step_idx + 1,
                    total_steps=len(plan.steps),
                    title=step.title,
                    result_summary=step_result,
                    success=True,
                    step_index=current_step_idx + 1,
                )
            )

            # 4. Planner reviews progress and may revise remaining steps
            remaining_unexecuted = plan.steps[current_step_idx + 1 :]
            if remaining_unexecuted:
                revised_remaining = await self._review_and_revise_remaining(
                    completed_step=step,
                    step_summary=step_result,
                    remaining_steps=remaining_unexecuted,
                )
                plan.steps = plan.steps[: current_step_idx + 1] + revised_remaining

            current_step_idx += 1

        # 5. Final completion summary
        final_report = (
            f"## Task Complete: {plan.goal}\n\n"
            f"Successfully executed {len(plan.steps)} planned steps:\n"
            + "\n".join(
                f"- **[{s.id}] {s.title}**: {s.summary[:100] if s.summary else 'Completed'}"
                for s in plan.steps
            )
        )
        await self.event_bus.emit(
            FinalAnswerEvent(
                content=final_report,
                total_steps=len(plan.steps),
                step_index=len(plan.steps),
            )
        )
        return final_report


def run_dual_one_shot(
    task: str,
    auto: bool = False,
    yolo: bool = False,
    config: LatheConfig | None = None,
) -> str:
    """Run dual agent in one-shot mode (`lathe --dual "task"`) and return final result."""
    from lathe.ui.agent_view import TerminalAgentUI

    active_config = config or load_config(require_secrets=False)
    console = Console()
    workspace = Path.cwd()

    mode = PermissionMode.DEFAULT
    if yolo:
        mode = PermissionMode.YOLO
    elif auto:
        mode = PermissionMode.AUTO

    permission_engine = PermissionEngine(workspace, mode=mode, console=console)
    if yolo:
        permission_engine.emit_yolo_warning()

    checkpoint_mgr = get_checkpoint_manager(workspace, prompt_init=False)

    dual_agent = DualAgent(
        config=active_config,
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=workspace,
        console=console,
        auto_approve=yolo or auto,
    )

    ui = TerminalAgentUI(console=console)
    ui.attach(dual_agent.event_bus)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(dual_agent.run(task))
    finally:
        loop.close()

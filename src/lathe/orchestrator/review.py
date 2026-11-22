"""Code review module evaluating coder step diffs against the Lathe review rubric."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from lathe.config import LatheConfig, load_config
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.factory import get_client
from lathe.llm.types import Message
from lathe.prompts import get_review_system_prompt
from lathe.tools.tests import TestRunResult


class ReviewIssue(BaseModel):
    """Specific problem identified by the reviewer in a modified file."""

    file: str = Field(description="Workspace relative path of the file containing the issue.")
    line: int | None = Field(default=None, description="Optional line number where problem occurs.")
    problem: str = Field(description="Clear explanation of the problem found.")
    suggestion: str = Field(description="Constructive suggestion for resolving the problem.")


class ReviewVerdict(BaseModel):
    """Verdict returned by the reviewer model."""

    verdict: Literal["approve", "revise"] = Field(
        description="Whether the step is approved or requires revision."
    )
    issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="List of issues that must be addressed if verdict is 'revise'.",
    )
    summary: str = Field(
        default="",
        description="Concise summary explaining the review findings.",
    )


def extract_review_json(text: str) -> str:
    """Extract JSON object from code fences or raw text string."""
    clean = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
    if match:
        return match.group(1).strip()
    first_brace = clean.find("{")
    last_brace = clean.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return clean[first_brace : last_brace + 1].strip()
    return clean


class StepReviewer:
    """Evaluates coder step output against the rubric using the REVIEWER model."""

    def __init__(
        self,
        config: LatheConfig | None = None,
        client: LLMClient | None = None,
    ) -> None:
        self.config = config or load_config(require_secrets=False)
        if client is not None:
            self.client = client
        else:
            self.client = get_client("reviewer", config=self.config)

    async def review_step(
        self,
        step_title: str,
        step_instructions: str,
        done_when: str,
        diff: str,
        test_results: TestRunResult,
    ) -> ReviewVerdict:
        """Run rubric evaluation on step code changes and test execution."""
        system_prompt = get_review_system_prompt()

        if test_results.command == "none":
            test_info = "- Automated Tests: (None detected or configured for this project)\n"
        else:
            test_status = "PASSED" if test_results.is_success else "FAILED"
            test_info = (
                f"- Command: {test_results.command}\n"
                f"- Status: {test_status} (exit code: {test_results.exit_code})\n"
                f"- Results: {test_results.passed} passed, {test_results.failed} failed\n"
            )
            if test_results.failing_output:
                test_info += f"\nFailing Test Details:\n{test_results.failing_output}\n"

        diff_text = diff.strip() if diff.strip() else "(No file modifications detected)"

        user_content = (
            f"# Step Review Request\n\n"
            f"## Step Title\n{step_title}\n\n"
            f"## Step Instructions\n{step_instructions}\n\n"
            f"## Done When Criteria\n{done_when}\n\n"
            f"## Code Changes (Diff)\n```diff\n{diff_text}\n```\n\n"
            f"## Test Results\n{test_info}\n\n"
            "Evaluate these changes against the rubric. Return ONLY the JSON verdict."
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_content),
        ]

        content_parts: list[str] = []
        try:
            async for chunk in self.client.chat(messages, stream=True):
                if chunk.delta:
                    content_parts.append(chunk.delta)
        except LLMError as err:
            # If reviewer LLM fails, fall back to testing status
            if not test_results.is_success:
                return ReviewVerdict(
                    verdict="revise",
                    summary=f"Reviewer query failed ({err}), but tests failed.",
                    issues=[
                        ReviewIssue(
                            file="tests",
                            problem=test_results.failing_output or "Tests failed.",
                            suggestion="Fix failing tests.",
                        )
                    ],
                )
            return ReviewVerdict(
                verdict="approve",
                summary="Reviewer call failed but tests passed; auto-approving.",
            )

        raw_text = "".join(content_parts).strip()
        try:
            json_text = extract_review_json(raw_text)
            data = json.loads(json_text)
            verdict = ReviewVerdict.model_validate(data)
        except Exception:
            # Fallback heuristic if JSON parsing fails
            if "revise" in raw_text.lower():
                verdict = ReviewVerdict(
                    verdict="revise",
                    summary="Reviewer requested revision (unstructured response).",
                    issues=[
                        ReviewIssue(
                            file="unknown",
                            problem=raw_text[:200],
                            suggestion="Review step requirements.",
                        )
                    ],
                )
            else:
                verdict = ReviewVerdict(
                    verdict="approve",
                    summary="Step approved.",
                )

        # Defense-in-depth: if tests failed, verdict MUST NOT be approve
        if not test_results.is_success and verdict.verdict == "approve":
            verdict.verdict = "revise"
            failing_snippet = test_results.failing_output or f"Exit code {test_results.exit_code}"
            verdict.issues.append(
                ReviewIssue(
                    file="tests",
                    problem=f"Test suite failed: {failing_snippet}",
                    suggestion="Fix failing tests before approving step.",
                )
            )
            verdict.summary = "Tests failed execution. Step must be revised."

        return verdict

"""Task output evaluation for Python, C, and tool-calling benchmark tasks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from lathe.bench.models import BenchTask


def extract_code_block(text: str, language: str) -> str:
    """Extract code from fenced markdown blocks or return raw text."""
    # Match ```python ... ``` or ```c ... ```
    pattern = rf"```{language}\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Match generic ``` ... ```
    generic_match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if generic_match:
        return generic_match.group(1).strip()

    return text.strip()


def evaluate_python_task(
    generated_code: str,
    test_code: str,
    timeout: float = 5.0,
) -> tuple[bool, str | None]:
    """Execute Python code combined with unit tests in an isolated subprocess."""
    clean_code = extract_code_block(generated_code, "python")
    full_script = f"{clean_code}\n\n# --- Test Harness ---\n{test_code}\n"

    try:
        proc = subprocess.run(
            [sys.executable, "-c", full_script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return True, None
        err = proc.stderr.strip() or proc.stdout.strip()
        return False, err or "Python test assertion failed."
    except subprocess.TimeoutExpired:
        return False, f"Execution timed out ({timeout}s)."
    except Exception as exc:
        return False, str(exc)


def evaluate_c_task(
    generated_code: str,
    test_code: str,
    timeout: float = 5.0,
) -> tuple[bool, str | None]:
    """Compile C solution with test harness using clang/gcc and run binary."""
    compiler = shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        return False, "C compiler (clang or gcc) not found in system PATH."

    clean_code = extract_code_block(generated_code, "c")
    full_source = f"{clean_code}\n\n{test_code}\n"

    with tempfile.TemporaryDirectory() as td:
        src_path = Path(td) / "solution.c"
        bin_path = Path(td) / "solution_bin"
        src_path.write_text(full_source, encoding="utf-8")

        # Compile
        compile_proc = subprocess.run(
            [compiler, "-O2", str(src_path), "-o", str(bin_path)],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        if compile_proc.returncode != 0:
            return False, f"C compilation error:\n{compile_proc.stderr.strip()}"

        # Run
        try:
            run_proc = subprocess.run(
                [str(bin_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if run_proc.returncode == 0:
                return True, None
            return False, f"C binary exited with code {run_proc.returncode} (assertion failure)."
        except subprocess.TimeoutExpired:
            return False, f"C execution timed out ({timeout}s)."
        except Exception as exc:
            return False, str(exc)


def evaluate_tool_task(
    raw_output: str,
    expected_tool: str | None,
    expected_args: dict[str, Any],
) -> tuple[bool, str | None]:
    """Parse tool call block and verify name and required arguments match expectations."""
    # 1. Look for <tool_call>{"name": ..., "arguments": ...}</tool_call>
    tool_call_match = re.search(r"<tool_call>(.*?)</tool_call>", raw_output, re.DOTALL)
    candidate_json = tool_call_match.group(1).strip() if tool_call_match else raw_output.strip()

    # If code fenced, strip it
    if candidate_json.startswith("```"):
        candidate_json = extract_code_block(candidate_json, "json")

    try:
        data = json.loads(candidate_json)
    except Exception:
        # Search for first JSON object in string
        brace_start = candidate_json.find("{")
        brace_end = candidate_json.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                data = json.loads(candidate_json[brace_start : brace_end + 1])
            except Exception as err:
                return False, f"Invalid JSON in tool call: {err}"
        else:
            return False, "No valid JSON tool call found in output."

    if not isinstance(data, dict):
        return False, "Parsed tool call is not a JSON object."

    name = data.get("name")
    if expected_tool and name != expected_tool:
        return False, f"Expected tool '{expected_tool}', got '{name}'."

    args = data.get("arguments", {})
    if not isinstance(args, dict):
        return False, "'arguments' field is not a dictionary."

    for k, v in expected_args.items():
        if k not in args:
            return False, f"Missing required argument '{k}' in tool call."
        if str(args[k]).strip() != str(v).strip():
            return False, f"Argument '{k}' mismatch: expected '{v}', got '{args[k]}'."

    return True, None


def evaluate_task_solution(
    task: BenchTask,
    generated_output: str,
) -> tuple[bool, str | None]:
    """Dispatch evaluation to appropriate evaluator based on task language."""
    if task.is_tool_task or task.language == "tool":
        return evaluate_tool_task(
            raw_output=generated_output,
            expected_tool=task.expected_tool,
            expected_args=task.expected_args,
        )

    if task.language == "python":
        return evaluate_python_task(
            generated_code=generated_output,
            test_code=task.test_code,
        )

    if task.language == "c":
        return evaluate_c_task(
            generated_code=generated_output,
            test_code=task.test_code,
        )

    return False, f"Unsupported task language '{task.language}'."

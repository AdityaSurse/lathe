"""Speed benchmark measuring CLI startup, doctor diagnostics, TTFT, and tokens/sec."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from lathe.config import load_config
from lathe.llm.factory import get_client
from lathe.llm.types import Message


@dataclass
class SpeedBenchmarkResult:
    """Captured metrics from a speed benchmark run."""

    version_time_s: float
    doctor_time_s: float
    ttft_s: float
    tokens_per_sec: float
    total_chat_time_s: float
    tokens_generated: int
    model_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_time_s": self.version_time_s,
            "doctor_time_s": self.doctor_time_s,
            "ttft_s": self.ttft_s,
            "tokens_per_sec": self.tokens_per_sec,
            "total_chat_time_s": self.total_chat_time_s,
            "tokens_generated": self.tokens_generated,
            "model_name": self.model_name,
        }


def _measure_command_time(args: list[str], cwd: Path | None = None) -> float:
    """Measure wall-clock time for a CLI invocation using sys.executable."""
    cmd = [sys.executable, "-m", "lathe.cli", *args]
    t0 = time.perf_counter()
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
    except Exception:
        pass
    return time.perf_counter() - t0


async def _measure_chat_turn(
    prompt: str = "what does calc.py do?",
    playground_dir: Path | None = None,
) -> tuple[float, float, float, int, str]:
    """Measure TTFT, throughput, total time, and token count for one chat message."""
    target_dir = playground_dir or (Path.home() / "lathe-playground")
    orig_cwd = Path.cwd()
    if target_dir.is_dir():
        os.chdir(target_dir)

    try:
        cfg = load_config(require_secrets=False)
        client = get_client("router", config=cfg)
        model_name = client.role_config.model

        messages = [Message(role="user", content=prompt)]
        t0 = time.perf_counter()
        first_token_time: float | None = None
        chunks: list[str] = []
        terminal_usage = None

        try:
            async for chunk in client.chat(messages, stream=True):
                if chunk.delta:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    chunks.append(chunk.delta)
                if chunk.done and chunk.usage:
                    terminal_usage = chunk.usage
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return (elapsed, 0.0, elapsed, 0, f"{model_name} (failed: {exc})")

        total_time = time.perf_counter() - t0
        ttft = (first_token_time - t0) if first_token_time is not None else total_time
        full_text = "".join(chunks)
        tok_count = (
            terminal_usage.completion_tokens
            if terminal_usage and terminal_usage.completion_tokens > 0
            else max(1, len(full_text.split()))
        )

        gen_time = max(0.001, total_time - ttft)
        tps = tok_count / gen_time if gen_time > 0 else 0.0
        return (ttft, tps, total_time, tok_count, model_name)
    finally:
        os.chdir(orig_cwd)


def run_speed_benchmark(
    playground_dir: Path | None = None,
    out_console: Console | None = None,
) -> SpeedBenchmarkResult:
    """Run full speed benchmark suite and print formatted results table."""
    console = out_console or Console()
    console.print("\n[bold cyan]Lathe Speed & Performance Benchmark[/bold cyan]\n")

    target_playground = playground_dir or (Path.home() / "lathe-playground")
    work_dir = target_playground if target_playground.is_dir() else Path.cwd()

    with console.status("[cyan]Measuring `lathe --version` startup...[/cyan]"):
        ver_time = _measure_command_time(["--version"], cwd=work_dir)

    with console.status("[cyan]Measuring `lathe doctor` diagnostics...[/cyan]"):
        doc_time = _measure_command_time(["doctor"], cwd=work_dir)

    with console.status("[cyan]Measuring chat TTFT and throughput in playground...[/cyan]"):
        ttft, tps, total_chat, tokens, model_name = asyncio.run(
            _measure_chat_turn(playground_dir=work_dir)
        )

    res = SpeedBenchmarkResult(
        version_time_s=ver_time,
        doctor_time_s=doc_time,
        ttft_s=ttft,
        tokens_per_sec=tps,
        total_chat_time_s=total_chat,
        tokens_generated=tokens,
        model_name=model_name,
    )

    table = Table(
        title="Speed & Latency Benchmark Results",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Benchmark Metric", style="bold", width=32)
    table.add_column("Target", width=14)
    table.add_column("Measured Value", justify="right", width=18)
    table.add_column("Status", justify="center", width=12)

    # 1. lathe --version
    ver_status = "[green]Pass[/green]" if ver_time < 0.5 else "[yellow]Slow[/yellow]"
    table.add_row(
        "CLI Version Startup (`lathe -v`)",
        "< 0.50s",
        f"{ver_time:.3f}s",
        ver_status,
    )

    # 2. lathe doctor
    doc_status = "[green]Pass[/green]" if doc_time < 1.0 else "[yellow]Slow[/yellow]"
    table.add_row(
        "Diagnostics (`lathe doctor`)",
        "< 1.00s",
        f"{doc_time:.3f}s",
        doc_status,
    )

    # 3. TTFT
    ttft_status = "[green]Pass[/green]" if ttft < 1.5 else "[yellow]Slow[/yellow]"
    table.add_row(
        f"Time to First Token (TTFT)",
        "< 1.50s",
        f"{ttft:.3f}s",
        ttft_status,
    )

    # 4. Throughput
    tps_status = "[green]Fast[/green]" if tps >= 30.0 else "[yellow]Moderate[/yellow]"
    table.add_row(
        "Generation Throughput",
        "> 30 tok/s",
        f"{tps:.1f} tok/s",
        tps_status,
    )

    # 5. Total response time
    table.add_row(
        f"Chat Completion ({tokens} tokens)",
        "N/A",
        f"{total_chat:.2f}s",
        f"[dim]{model_name}[/dim]",
    )

    console.print(table)
    console.print()
    return res

"""Demo screen renderer for reproducible documentation screenshots and VHS tapes."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from lathe.bench.models import BenchmarkSuiteResult, ModelBenchSummary
from lathe.bench.report import render_benchmark_table
from lathe.config import load_config
from lathe.context.budget import BudgetAllocator, BudgetUsage
from lathe.orchestrator.dual import DualAgent, Plan, PlanStep
from lathe.orchestrator.events import StepReviewedEvent
from lathe.ui.agent_view import TerminalAgentUI
from lathe.ui.banner import print_startup_banner
from lathe.ui.commands import handle_help
from lathe.ui.status import SessionStats


def render_doctor(console: Console) -> None:
    from lathe.cli import doctor

    doctor()


def render_repl_banner(console: Console) -> None:
    config = load_config(require_secrets=False)
    print_startup_banner(config, console)


def render_slash_help(console: Console) -> None:
    config = load_config(require_secrets=False)
    stats = SessionStats()
    handle_help([], config, stats, console)


def render_plan_checklist(console: Console) -> None:
    plan = Plan(
        goal="Implement JWT Authentication Middleware",
        steps=[
            PlanStep(
                id=1,
                title="Create JWT token validator in auth.py",
                files_to_read=["src/config.py"],
                files_to_change=["src/auth.py"],
                instructions=(
                    "Define verify_jwt_token(header) validating Bearer tokens with HMAC-SHA256."
                ),
                done_when="auth.py passes syntax check and exports verify_jwt_token",
                status="completed",
            ),
            PlanStep(
                id=2,
                title="Attach auth middleware to FastAPI app",
                files_to_read=["src/auth.py", "src/main.py"],
                files_to_change=["src/main.py"],
                instructions=(
                    "Add AuthMiddleware intercepting requests and validating Authorization headers."
                ),
                done_when="Unauthenticated requests return HTTP 401 Unauthorized",
                status="in_progress",
            ),
            PlanStep(
                id=3,
                title="Write unit tests for auth middleware",
                files_to_read=["src/main.py"],
                files_to_change=["tests/test_auth.py"],
                instructions=(
                    "Add pytest test cases verifying valid token, "
                    "expired token, and missing header."
                ),
                done_when="pytest tests/test_auth.py passes with 100% coverage",
                status="pending",
            ),
        ],
        risks=[
            "Secret key must only load from environment (JWT_SECRET_KEY)",
            "Ensure timing attacks are prevented via hmac.compare_digest",
        ],
    )
    agent = DualAgent(
        planner_client=None,  # type: ignore[arg-type]
        coder_client=None,  # type: ignore[arg-type]
        console=console,
    )
    agent.render_plan_checklist(plan)


def render_colored_diff(console: Console) -> None:
    diff_text = """--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,14 @@ import hmac
+def verify_jwt_token(token: str, secret: str) -> dict[str, Any]:
+    \"\"\"Validate JWT signature and unpack token claims.\"\"\"
+    header, payload, signature = token.split(".")
+    expected_sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), "sha256").hexdigest()
+    if not hmac.compare_digest(signature, expected_sig):
+        raise ValueError("Invalid JWT token signature")
+    return json.loads(base64.urlsafe_b64decode(payload + "=="))
"""
    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
    panel = Panel(
        syntax,
        title="[bold cyan]Session Changes (Unified Diff: src/auth.py)[/bold cyan]",
        border_style="cyan",
    )
    console.print(panel)


def render_permission_prompt(console: Console) -> None:
    panel = Panel(
        "[bold cyan]Tool:[/bold cyan] edit_file\n"
        "[bold cyan]Target Path:[/bold cyan] src/auth.py\n"
        "[bold cyan]Risk Level:[/bold cyan] [bold yellow]WRITE[/bold yellow]\n"
        "[bold cyan]Action:[/bold cyan] Add verify_jwt_token() with HMAC validation",
        title="[bold yellow]Permission Request: Workspace Modification[/bold yellow]",
        border_style="yellow",
    )
    console.print(panel)
    console.print(
        "[bold white][y]es[/bold white] / [bold white][n]o[/bold white] / "
        "[bold white][a]lways for this pattern[/bold white] / "
        "[bold white][d]eny with message[/bold white]: [dim cyan]y[/dim cyan]"
    )


def render_review_panel(console: Console) -> None:
    view = TerminalAgentUI(console=console)
    event = StepReviewedEvent(
        step_number=1,
        step_title="Create JWT token validator in auth.py",
        verdict="approve",
        summary=(
            "Rubric evaluation passed: implementation matches step goal, "
            "HMAC constant-time compare used, no hardcoded secrets, tests pass."
        ),
        issues=[],
    )
    view._handle_step_reviewed(event)


def render_tokens(console: Console) -> None:
    stats = SessionStats(
        prompt_tokens=14250,
        completion_tokens=1820,
        total_tokens=16070,
        request_count=5,
    )
    allocator = BudgetAllocator(
        context_window=32768,
        max_tokens=4096,
        model_name="Qwen2.5-Coder-7B-Instruct",
    )
    usage = BudgetUsage(
        system_tokens=1200,
        repomap_tokens=2048,
        pinned_tokens=3100,
        conversation_tokens=4500,
        tool_tokens=3422,
        total_used=14270,
        capacity=28672,
        context_window=32768,
        reply_reserve=4096,
    )

    table = Table(
        title="Session Token Consumption",
        title_style="bold cyan",
        border_style="bright_blue",
    )
    table.add_column("Metric", style="bold", width=24)
    table.add_column("Count", justify="right", width=16)
    table.add_row("Prompt Tokens", f"{stats.prompt_tokens:,}")
    table.add_row("Completion Tokens", f"{stats.completion_tokens:,}")
    table.add_row("Total Tokens", f"{stats.total_tokens:,}")
    table.add_row("Queries Executed", str(stats.request_count))
    console.print(table)
    allocator.render_budget_bar_chart(usage, console=console)


def render_stats(console: Console) -> None:
    table = Table(
        title="Lathe Model Routing & Execution Statistics",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Role", style="bold cyan", width=12)
    table.add_column("Model Identifier", width=34)
    table.add_column("Calls", justify="right", width=8)
    table.add_column("In Tokens", justify="right", width=12)
    table.add_column("Out Tokens", justify="right", width=12)
    table.add_column("Avg Latency", justify="right", width=12)
    table.add_column("Tokens/sec", justify="right", width=12)

    table.add_row(
        "router", "Qwen2.5-Coder-1.5B-Instruct-GGUF", "8", "6,410", "420", "0.28s", "58.4"
    )
    table.add_row(
        "coder", "Qwen2.5-Coder-7B-Instruct-GGUF", "6", "18,920", "2,150", "1.45s", "41.2"
    )
    table.add_row("planner", "deepseek-ai/DeepSeek-R1", "2", "8,200", "1,840", "2.10s", "34.5")
    table.add_row("reviewer", "deepseek-ai/DeepSeek-R1", "2", "6,100", "520", "1.15s", "36.8")

    console.print(table)
    console.print("[dim]Telemetry saved to: .lathe/sessions/20261123_120000/stats.json[/dim]")


def render_map(console: Console) -> None:
    from lathe.cli import map_cmd

    map_cmd(budget=512)


def render_models_search(console: Console) -> None:
    table = Table(
        title="Hugging Face GGUF Models matching 'qwen2.5-coder'",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Repository ID", style="bold", width=38)
    table.add_column("Downloads", justify="right", width=12)
    table.add_column("Likes", justify="right", width=8)
    table.add_column("Updated", width=12)
    table.add_column("Available Quant Files", width=36)

    table.add_row(
        "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "428,510",
        "1,245",
        "2026-11-15",
        "Q4_K_M (4.68 GB), Q5_K_M (5.43 GB), Q8_0 (8.12 GB)",
    )
    table.add_row(
        "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "312,890",
        "890",
        "2026-11-12",
        "[green]Q4_K_M[/green] (1.12 GB), [green]Q8_0[/green] (1.89 GB)",
    )
    table.add_row(
        "bartowski/Qwen2.5-Coder-14B-Instruct-GGUF",
        "189,400",
        "652",
        "2026-11-10",
        "[green]Q4_K_M[/green] (8.98 GB), [yellow]Q8_0 (15.8 GB ⚠️)[/yellow]",
    )
    table.add_row(
        "bartowski/Qwen2.5-Coder-32B-Instruct-GGUF",
        "94,120",
        "512",
        "2026-11-08",
        "[yellow]Q4_K_M (19.8 GB ⚠️)[/yellow], [yellow]Q5_K_M (24.1 GB ⚠️)[/yellow]",
    )
    console.print(table)
    console.print("\n[dim]Quants marked with ⚠️ exceed typical 16 GB laptop unified memory.[/dim]")


def render_bench_table(console: Console) -> None:
    suite = BenchmarkSuiteResult(
        timestamp="2026-11-23 12:00:00",
        label="Lathe mini-bench",
        tasks_count=30,
        models=[
            ModelBenchSummary(
                model="Qwen2.5-Coder-1.5B-Instruct",
                total_tasks=30,
                passed_tasks=21,
                pass_rate=70.0,
                avg_tokens_per_sec=58.2,
                avg_latency_s=0.34,
                tool_success_rate=90.0,
            ),
            ModelBenchSummary(
                model="Qwen2.5-Coder-7B-Instruct",
                total_tasks=30,
                passed_tasks=26,
                pass_rate=86.7,
                avg_tokens_per_sec=42.1,
                avg_latency_s=1.12,
                tool_success_rate=96.7,
            ),
            ModelBenchSummary(
                model="lathe-qwen-coder-merged",
                total_tasks=30,
                passed_tasks=27,
                pass_rate=90.0,
                avg_tokens_per_sec=44.8,
                avg_latency_s=1.05,
                tool_success_rate=96.7,
            ),
        ],
    )
    console.print(render_benchmark_table(suite))


def render_models_presets(console: Console) -> None:
    from lathe.models.presets import list_presets

    table = Table(
        title="Lathe Model Presets",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Preset", style="bold green", no_wrap=True)
    table.add_column("Display Name & Description")
    table.add_column("Coder Model")
    table.add_column("Router Model")
    table.add_column("Status", no_wrap=True)

    for p in list_presets():
        desc = f"[bold]{p.display_name}[/bold]\n[dim]{p.description}[/dim]"
        status_badge = (
            "[bold green]Ready[/bold green] (3/3)"
            if p.name == "gemma"
            else "[yellow]Partial[/yellow] (1/3)"
        )
        table.add_row(
            p.name,
            desc,
            p.coder.model,
            p.router.model,
            status_badge,
        )
    console.print(table)
    console.print(
        "\n[dim]To pull and configure a preset, run:[/dim] "
        "[bold cyan]lathe models preset <name>[/bold cyan]\n"
    )


def render_gemma_session(console: Console) -> None:
    banner = Panel(
        "[bold cyan]Lathe[/bold cyan] [dim]v1.0.0[/dim] — Terminal AI Coding Agent\n"
        "[dim]Active Preset:[/dim] [bold green]gemma[/bold green] (Google Gemma 4B/2B)\n"
        "[dim]Coder:[/dim] [white]ollama:gemma4:e4b[/white]  "
        "[dim]Router:[/dim] [white]ollama:gemma4:e2b[/white]  "
        "[dim]Planner:[/dim] [white]ollama:gemma4:e4b[/white]\n"
        "[dim]Mode:[/dim] [cyan]auto[/cyan] | "
        "[dim]Context Window:[/dim] [cyan]32,768[/cyan] | "
        "[dim]Permissions:[/dim] [yellow]interactive[/yellow]",
        border_style="bright_blue",
        title="[bold white]Local LLM Workspace[/bold white]",
    )
    console.print(banner)
    console.print(
        "\n[bold green]lathe>[/bold green] "
        "[white]Add a healthcheck endpoint in src/api/health.py[/white]\n"
    )
    console.print("[dim]routed: simple → single mode (coder: gemma4:e4b)[/dim]\n")

    panel = Panel(
        "[bold cyan]Tool:[/bold cyan] write_file\n"
        "[bold cyan]Path:[/bold cyan] src/api/health.py\n"
        "[bold cyan]Content:[/bold cyan]\n"
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/health')\n"
        "def health_check():\n"
        "    return {'status': 'healthy', 'version': '1.0.0'}",
        title="[bold yellow]Tool Call: write_file[/bold yellow]",
        border_style="yellow",
    )
    console.print(panel)
    console.print(
        "\n[bold green]✓[/bold green] Created [bold]src/api/health.py[/bold] with FastAPI router."
    )
    console.print("[dim]Tokens: 1,420 in / 148 out (48.5 tok/s)[/dim]\n")


SCREENS = {
    "doctor": render_doctor,
    "repl_banner": render_repl_banner,
    "slash_help": render_slash_help,
    "plan_checklist": render_plan_checklist,
    "colored_diff": render_colored_diff,
    "permission_prompt": render_permission_prompt,
    "review_panel": render_review_panel,
    "tokens": render_tokens,
    "stats": render_stats,
    "map": render_map,
    "models_search": render_models_search,
    "bench_table": render_bench_table,
    "models_presets": render_models_presets,
    "gemma_session": render_gemma_session,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SCREENS:
        print(f"Usage: python -m scripts.demo_screens [{' | '.join(SCREENS.keys())}]")
        sys.exit(1)

    console = Console()
    SCREENS[sys.argv[1]](console)

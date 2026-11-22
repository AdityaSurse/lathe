"""Command-line interface entry point for Lathe."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from typer._click.core import Context as ClickContext
from typer.core import TyperGroup

from lathe import __version__
from lathe.config import (
    COMMENTED_TOML_TEMPLATE,
    ConfigError,
    get_global_config_path,
    get_hf_token,
    get_project_config_path,
    load_config,
    set_config_value,
)
from lathe.models import models_app
from lathe.session import Session, SessionConfig  # noqa: F401

# Load local environment variables (.env) if present
load_dotenv()


class DefaultTaskGroup(TyperGroup):
    """Custom TyperGroup routing non-subcommand arguments to one-shot task execution."""

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        """Route unrecognized positional arguments to the hidden __task__ command."""
        args_list = list(args)
        pos_idx = -1
        i = 0
        while i < len(args_list):
            a = args_list[i]
            if a in (
                "--auto",
                "--yolo",
                "--dual",
                "-v",
                "--version",
                "--help",
                "-h",
            ) or a.startswith("-"):
                i += 1
            else:
                pos_idx = i
                break

        if pos_idx != -1:
            cmd_name = args_list[pos_idx]
            if self.get_command(ctx, cmd_name) is None:
                args_list.insert(pos_idx, "__task__")
        return super().parse_args(ctx, args_list)


app = typer.Typer(
    cls=DefaultTaskGroup,
    name="lathe",
    help="Lathe: Terminal AI coding agent using local and open-source LLMs.",
)
config_app = typer.Typer(
    name="config",
    help="Inspect and manage Lathe configuration files.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")

console = Console()


def version_callback(value: bool) -> None:
    """Print the package version and exit."""
    if value:
        console.print(f"lathe version {__version__}")
        raise typer.Exit()


@app.command(name="__task__", hidden=True)
def run_task(
    ctx: typer.Context,
    task_words: list[str] = typer.Argument(..., help="Task prompt for one-shot agent execution."),
) -> None:
    """Execute a task in one-shot mode and exit."""
    from lathe.config import load_config
    from lathe.orchestrator.agent import run_one_shot
    from lathe.orchestrator.dual import run_dual_one_shot
    from lathe.orchestrator.router import run_routed_one_shot

    auto = ctx.obj.get("auto", False) if ctx.obj else False
    yolo = ctx.obj.get("yolo", False) if ctx.obj else False
    dual = ctx.obj.get("dual", False) if ctx.obj else False
    task = " ".join(task_words)

    active_cfg = load_config(require_secrets=False)
    current_mode = "dual" if dual else getattr(active_cfg.settings, "mode", "auto")

    if current_mode == "dual":
        run_dual_one_shot(task, auto=auto, yolo=yolo)
    elif current_mode == "single":
        run_one_shot(task, auto=auto, yolo=yolo)
    else:  # "auto"
        run_routed_one_shot(task, auto=auto, yolo=yolo, config=active_cfg)
    raise typer.Exit(0)


@app.command(name="map")
def map_cmd(
    budget: int = typer.Option(
        2048,
        "--budget",
        "-b",
        help="Token budget limit for the repository map.",
    ),
) -> None:
    """Print the repository symbol map and definition hierarchy."""
    from lathe.context.repomap import RepoMap

    rm = RepoMap(workspace_root=Path.cwd(), token_budget=budget)
    map_text = rm.get_repo_map()
    if map_text:
        console.print(map_text)
    else:
        console.print("[dim]No symbols found or empty repository.[/dim]")


@app.command(name="index")
def index_cmd(
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        "-r",
        help="Rebuild the entire semantic code index from scratch.",
    ),
    stats: bool = typer.Option(
        False,
        "--stats",
        "-s",
        help="Display semantic code index statistics without rebuilding.",
    ),
) -> None:
    """Build or incrementally refresh the semantic code vector index."""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from lathe.context.index import CodeIndex

    index = CodeIndex(workspace_root=Path.cwd())

    if stats:
        st = index.get_stats()
        console.print("\n[bold cyan]Lathe Code Index Statistics[/bold cyan]")
        console.print(f"  Files Indexed:   [green]{st['files']}[/green]")
        console.print(f"  Chunks Indexed:  [green]{st['chunks']}[/green]")
        console.print(f"  Database Size:   [dim]{st['db_size_bytes'] / 1024:.1f} KB[/dim]")
        console.print(f"  Database Path:   [dim]{st['db_path']}[/dim]\n")
        return

    added, modified, deleted = index.get_stale_status()
    total_files = len(added) + len(modified)

    if not rebuild and total_files == 0 and len(deleted) == 0:
        st = index.get_stats()
        console.print(
            f"[green]✓[/green] Semantic index is up to date ({st['files']} files, "
            f"{st['chunks']} chunks)."
        )
        return

    action_label = "Rebuilding" if rebuild else "Refreshing"
    console.print(f"\n[bold blue]Lathe Code Index[/bold blue]: {action_label} vector index...\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Indexing files...", total=max(total_files, 1))

        def on_progress(rel_path: str, current: int, total: int) -> None:
            progress.update(
                task_id,
                total=total,
                completed=current,
                description=f"Indexing: [dim]{rel_path}[/dim]",
            )

        res = index.refresh(progress_callback=on_progress, force=rebuild)
        progress.update(task_id, completed=max(total_files, 1), description="Indexing complete")

    console.print(
        f"[green]✓[/green] Index {action_label.lower()} complete: "
        f"[bold]{res['files_indexed']}[/bold] files processed, "
        f"[bold]{res['chunks_indexed']}[/bold] chunks embedded, "
        f"[dim]{res['chunks_reused']} chunks reused[/dim], "
        f"[dim]{res['files_deleted']} files removed[/dim].\n"
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="Auto-approve write tools while still prompting for shell execution.",
    ),
    yolo: bool = typer.Option(
        False,
        "--yolo",
        help="Approve all operations automatically (dangerous; blocklist still enforced).",
    ),
    dual: bool = typer.Option(
        False,
        "--dual",
        help="Run in dual mode (planner creates plan, coder executes each step).",
    ),
) -> None:
    """Lathe terminal AI coding agent."""
    ctx.ensure_object(dict)
    ctx.obj["auto"] = auto
    ctx.obj["yolo"] = yolo
    ctx.obj["dual"] = dual

    if yolo:
        from lathe.safety.permissions import PermissionEngine, PermissionMode

        engine = PermissionEngine(Path.cwd(), mode=PermissionMode.YOLO, console=console)
        engine.emit_yolo_warning()

    if ctx.invoked_subcommand is None:
        from lathe.ui.repl import start_repl

        start_repl(auto=auto, yolo=yolo)


@app.command()
def doctor() -> None:
    """Run diagnostics checking Python, Git, Ollama runtime, models, and HF token."""
    table = Table(
        title="Lathe System Diagnostics",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Component / Check", style="bold", width=24)
    table.add_column("Status", width=14)
    table.add_column("Details", style="dim", width=46)

    # 1. Python Version
    py_major = sys.version_info.major
    py_minor = sys.version_info.minor
    py_micro = sys.version_info.micro
    py_ver_str = f"{py_major}.{py_minor}.{py_micro}"
    if (py_major, py_minor) >= (3, 11):
        table.add_row("Python", "[green]Pass[/green]", f"v{py_ver_str} (>=3.11 required)")
    else:
        table.add_row(
            "Python",
            "[red]Fail[/red]",
            f"v{py_ver_str} (Python >=3.11 is required)",
        )

    # 2. Git Binary
    git_path = shutil.which("git")
    if git_path:
        try:
            git_ver_proc = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            git_ver = git_ver_proc.stdout.strip() or "Installed"
            table.add_row("Git", "[green]Pass[/green]", f"{git_ver} ({git_path})")
        except Exception as e:
            table.add_row("Git", "[green]Pass[/green]", f"Found at {git_path} ({e})")
    else:
        table.add_row("Git", "[red]Fail[/red]", "git executable not found on PATH")

    # 3 & 4. Ollama Runtime Service & Models
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_running = False
    installed_models: list[str] = []

    try:
        response = httpx.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=2.0)
        if response.status_code == 200:
            ollama_running = True
            table.add_row("Ollama Service", "[green]Pass[/green]", f"Online at {ollama_url}")
            data = response.json()
            raw_models = data.get("models", [])
            for m in raw_models:
                if isinstance(m, dict) and "name" in m:
                    installed_models.append(str(m["name"]))
        else:
            table.add_row(
                "Ollama Service",
                "[yellow]Warning[/yellow]",
                f"Responded with HTTP status {response.status_code}",
            )
    except Exception:
        table.add_row(
            "Ollama Service",
            "[yellow]Warning[/yellow]",
            f"Not reachable at {ollama_url} (is 'ollama serve' running?)",
        )

    # Ollama Models list
    if ollama_running:
        if installed_models:
            preview = ", ".join(installed_models[:4])
            if len(installed_models) > 4:
                preview += f" (+{len(installed_models) - 4} more)"
            table.add_row(
                "Ollama Models",
                "[green]Pass[/green]",
                f"{len(installed_models)} available: {preview}",
            )
        else:
            table.add_row(
                "Ollama Models",
                "[yellow]Warning[/yellow]",
                "No models found. Run `ollama pull <model>`.",
            )
    else:
        table.add_row(
            "Ollama Models",
            "[dim]Skipped[/dim]",
            "Requires active Ollama service to inspect local models",
        )

    # 5. Hugging Face Token (never print the token value)
    hf_token = get_hf_token()
    if hf_token:
        # Mask length preview without printing secret
        table.add_row(
            "HF_TOKEN",
            "[green]Pass[/green]",
            "Present in environment (value masked)",
        )
    else:
        table.add_row(
            "HF_TOKEN",
            "[yellow]Warning[/yellow]",
            "Not set (optional: needed for HF Inference Providers API)",
        )

    console.print(table)


# --- lathe config subcommands ---


@config_app.command(name="init")
def config_init(
    path: Path = typer.Option(
        Path("lathe.toml"),
        "--path",
        "-p",
        help="Target file path to initialize.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite target file if it already exists.",
    ),
) -> None:
    """Initialize a well-commented lathe.toml configuration file."""
    if path.exists() and not force:
        console.print(
            f"[yellow]Warning: '{path}' already exists. Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(code=1)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(COMMENTED_TOML_TEMPLATE, encoding="utf-8")
    console.print(f"[green]Initialized configuration file at '{path}'[/green]")


@config_app.command(name="show")
def config_show(
    project_dir: Path | None = typer.Option(
        None,
        "--project-dir",
        "-d",
        help="Project directory containing lathe.toml.",
    ),
) -> None:
    """Display active merged configuration and source status in a Rich tree."""
    try:
        cfg = load_config(project_dir=project_dir, require_secrets=False)
    except ConfigError as err:
        console.print(f"[red]Error loading config:[/red] {err}")
        raise typer.Exit(code=1) from err

    tree = Tree("[bold cyan]Lathe Configuration[/bold cyan]")

    # Settings branch
    settings_node = tree.add("[bold white]Settings[/bold white]")
    settings_node.add(f"mode: [bright_yellow]{cfg.settings.mode}[/bright_yellow]")
    settings_node.add(f"max_agent_steps: [bright_cyan]{cfg.settings.max_agent_steps}[/bright_cyan]")
    settings_node.add(
        f"auto_approve_reads: [bright_green]{cfg.settings.auto_approve_reads}[/bright_green]"
    )
    settings_node.add(f"theme: [magenta]{cfg.settings.theme}[/magenta]")
    blocked_node = settings_node.add("blocked_commands")
    for cmd in cfg.settings.blocked_commands:
        blocked_node.add(f"[red]{cmd}[/red]")

    # Roles branch
    roles_node = tree.add("[bold white]Roles[/bold white]")
    for r_name in ["planner", "coder", "reviewer", "router"]:
        if r_name == "reviewer":
            if cfg.roles.reviewer is None:
                roles_node.add("[dim]reviewer: (inherited from planner)[/dim]")
                continue
            r = cfg.roles.reviewer
        else:
            r = getattr(cfg.roles, r_name)

        r_branch = roles_node.add(
            f"[bold green]{r_name}[/bold green] (backend=[yellow]{r.backend}[/yellow])"
        )
        r_branch.add(f"model: [cyan]{r.model}[/cyan]")
        r_branch.add(f"temperature: [dim]{r.temperature}[/dim]")
        r_branch.add(f"max_tokens: [dim]{r.max_tokens}[/dim]")
        r_branch.add(f"context_window: [dim]{r.context_window}[/dim]")
        if r.base_url:
            r_branch.add(f"base_url: [dim]{r.base_url}[/dim]")

    # Secrets branch (masked)
    secrets_node = tree.add("[bold white]Secrets & Environment[/bold white]")
    hf_token = get_hf_token()
    if hf_token:
        masked = f"{hf_token[:4]}****" if len(hf_token) >= 4 else "****"
        secrets_node.add(f"HF_TOKEN: [green]Present[/green] (masked: {masked})")
    else:
        secrets_node.add("HF_TOKEN: [yellow]Not Set[/yellow] (environment / .env)")

    # Sources branch
    sources_node = tree.add("[bold white]Configuration Sources[/bold white]")
    g_path = get_global_config_path()
    p_path = get_project_config_path(project_dir)
    sources_node.add(
        f"Global (~/.config/lathe/lathe.toml): "
        f"{'[green]Found[/green]' if g_path.is_file() else '[dim]Not Found[/dim]'}"
    )
    sources_node.add(
        f"Project (./lathe.toml): "
        f"{'[green]Found[/green]' if p_path.is_file() else '[dim]Not Found[/dim]'}"
    )

    console.print(tree)


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Dot-notation key (e.g. roles.coder.model)"),
    value: str = typer.Argument(..., help="Value to set"),
    path: Path = typer.Option(
        Path("lathe.toml"),
        "--path",
        "-p",
        help="Target lathe.toml file to modify.",
    ),
) -> None:
    """Set a configuration key in lathe.toml and validate."""
    try:
        set_config_value(key, value, path)
        console.print(f"[green]Updated '{key}' = '{value}' in '{path}'[/green]")
    except ConfigError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1) from err


async def _stream_ask(prompt: str, role: str, model_override: str | None = None) -> None:
    """Execute streaming query and print live Markdown with performance metrics."""
    import time

    from rich.live import Live
    from rich.markdown import Markdown

    from lathe.llm.base import LLMError
    from lathe.llm.factory import get_client
    from lathe.llm.types import Message

    cfg = load_config(require_secrets=False)
    client = get_client(role, config=cfg)
    if model_override:
        client.role_config.model = model_override

    messages = [Message(role="user", content=prompt)]
    accumulated_text = ""
    start_time = time.perf_counter()
    terminal_usage = None

    try:
        with Live(Markdown(""), refresh_per_second=15, console=console) as live:
            async for chunk in client.chat(messages, stream=True):
                if chunk.delta:
                    accumulated_text += chunk.delta
                    live.update(Markdown(accumulated_text))
                if chunk.done and chunk.usage:
                    terminal_usage = chunk.usage

        elapsed = time.perf_counter() - start_time
        if terminal_usage and terminal_usage.completion_tokens > 0:
            tokens = terminal_usage.completion_tokens
            speed = tokens / elapsed if elapsed > 0 else 0.0
            console.print(
                f"\n[dim]─── {tokens} tokens in {elapsed:.2f}s "
                f"({speed:.1f} tokens/sec) · model: {client.role_config.model} ───[/dim]"
            )
        else:
            word_count = len(accumulated_text.split())
            speed = word_count / elapsed if elapsed > 0 else 0.0
            console.print(
                f"\n[dim]─── ~{word_count} words in {elapsed:.2f}s "
                f"({speed:.1f} words/sec) · model: {client.role_config.model} ───[/dim]"
            )
    except LLMError as err:
        console.print(f"[red]LLM Error:[/red] {err}")
        raise typer.Exit(code=1) from err


@app.command(name="ask")
def ask(
    prompt: str = typer.Argument(..., help="Prompt or instruction to query the model with."),
    role: str = typer.Option(
        "coder",
        "--role",
        "-r",
        help="Agent role to query (planner, coder, reviewer, router).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Explicit model override.",
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="Auto-approve write tools while still prompting for shell execution.",
    ),
    yolo: bool = typer.Option(
        False,
        "--yolo",
        help="Approve all operations automatically (dangerous; blocklist still enforced).",
    ),
) -> None:
    """Stream a live completion using Rich Markdown, printing tokens and throughput."""
    import asyncio

    if yolo:
        from lathe.safety.permissions import PermissionEngine, PermissionMode

        engine = PermissionEngine(Path.cwd(), mode=PermissionMode.YOLO, console=console)
        engine.emit_yolo_warning()

    asyncio.run(_stream_ask(prompt, role, model_override=model))


@app.command(name="tools")
def tools_cmd(
    name: str | None = typer.Argument(
        None,
        help="Optional tool name to inspect schema and parameters.",
    ),
) -> None:
    """List available agent workspace tools or inspect a specific tool schema."""
    import json

    from rich.syntax import Syntax

    from lathe.tools.registry import default_registry

    if name:
        tool_inst = default_registry.get(name)
        if not tool_inst:
            console.print(f"[red]No tool found named '{name}'.[/red]")
            raise typer.Exit(code=1)

        spec = tool_inst.to_tool_spec()
        console.print(f"\n[bold cyan]Tool:[/bold cyan] [bold green]{spec.name}[/bold green]")
        console.print(f"[bold cyan]Risk Level:[/bold cyan] {tool_inst.risk_level}")
        console.print(f"\n[bold]Description:[/bold]\n{tool_inst.description}\n")
        console.print("[bold]Parameters Schema:[/bold]")
        schema_json = json.dumps(spec.parameters, indent=2)
        console.print(Syntax(schema_json, "json", theme="monokai"))
        return

    table = Table(
        title="Lathe Workspace Tools",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Tool", style="bold green", width=14)
    table.add_column("Risk", width=10)
    table.add_column("Description", width=55)

    for t in default_registry.list_tools():
        risk_color = (
            "green" if t.risk_level == "read" else "yellow" if t.risk_level == "write" else "red"
        )
        summary = t.description.strip().split("\n")[0]
        table.add_row(t.name, f"[{risk_color}]{t.risk_level}[/{risk_color}]", summary)

    console.print(table)


@app.command(name="tool")
def tool_alias(
    name: str | None = typer.Argument(
        None,
        help="Optional tool name to inspect schema and parameters.",
    ),
) -> None:
    """Alias for 'lathe tools'."""
    tools_cmd(name)


if __name__ == "__main__":
    app()

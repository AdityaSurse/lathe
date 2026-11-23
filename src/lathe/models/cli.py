"""Typer CLI interface for model searching, pulling, listing, probing, and role assignment."""

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from lathe.config import get_hf_token, get_project_config_path, set_config_value
from lathe.models.capabilities import get_capabilities_file_path
from lathe.models.local import get_local_ollama_models
from lathe.models.probe import probe_model
from lathe.models.pull import pull_model_with_progress
from lathe.models.ram import format_bytes, get_available_ram_bytes
from lathe.models.search import TARGET_QUANTS, search_gguf_repos

models_app = typer.Typer(
    name="models",
    help="Search, pull, inspect, and configure local and Hugging Face models.",
    no_args_is_help=True,
)
console = Console()


@models_app.command(name="search")
def search(
    query: str = typer.Argument(..., help="Search query for GGUF model repositories."),
    limit: int = typer.Option(5, "--limit", "-l", help="Maximum repositories to display."),
) -> None:
    """Search Hugging Face Hub for GGUF repositories and inspect available quant sizes."""
    token = get_hf_token()
    console.print(
        f"[bold cyan]Searching Hugging Face Hub for GGUF models matching:[/bold cyan] {query}..."
    )

    try:
        results = search_gguf_repos(query=query, limit=limit, token=token)
    except Exception as exc:
        console.print(f"[red]Search failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not results:
        console.print("[yellow]No GGUF models found matching your query.[/yellow]")
        return

    avail_ram = get_available_ram_bytes()
    ram_warning_triggered = False

    table = Table(
        title=f"Hugging Face GGUF Models matching '{query}'",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Repository ID", style="bold", width=36)
    table.add_column("Downloads", justify="right", width=12)
    table.add_column("Likes", justify="right", width=8)
    table.add_column("Updated", width=12)
    table.add_column("Available Quant Files", width=38)

    for r in results:
        quant_parts: list[str] = []
        for q in TARGET_QUANTS:
            if q in r.quants:
                sz = r.quants[q]
                sz_str = format_bytes(sz)
                if avail_ram is not None and sz > avail_ram:
                    quant_parts.append(f"[yellow]{q} ({sz_str} ⚠️)[/yellow]")
                    ram_warning_triggered = True
                else:
                    quant_parts.append(f"[green]{q}[/green] ({sz_str})")

        quants_display = ", ".join(quant_parts) if quant_parts else "[dim]None detected[/dim]"
        table.add_row(
            r.id,
            f"{r.downloads:,}",
            f"{r.likes:,}",
            r.last_modified,
            quants_display,
        )

    console.print(table)
    if ram_warning_triggered and avail_ram is not None:
        console.print(
            f"\n[yellow]⚠️  Quants marked with ⚠️ exceed currently available system RAM "
            f"({format_bytes(avail_ram)}).[/yellow]"
        )


@models_app.command(name="pull")
def pull(
    repo: str = typer.Argument(
        ...,
        help=(
            "Repository identifier with optional quant "
            "(e.g. bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M)."
        ),
    ),
    quant: str = typer.Option(
        "Q4_K_M",
        "--quant",
        "-q",
        help="Default quant format if not specified in repo argument.",
    ),
) -> None:
    """Pull a model through Ollama with live streaming progress."""
    try:
        asyncio.run(pull_model_with_progress(model=repo))
    except Exception as exc:
        console.print(f"[red]Pull failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@models_app.command(name="list")
def list_models() -> None:
    """List locally installed Ollama models and their active role assignments."""
    try:
        models = asyncio.run(get_local_ollama_models())
    except Exception as exc:
        console.print(f"[red]Failed to retrieve local models:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(
        title="Local Ollama Models",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Model Name", style="bold", width=50)
    table.add_column("Size", justify="right", width=12)
    table.add_column("Modified", width=22)
    table.add_column("Assigned Roles", width=22)

    if not models:
        table.add_row(
            "[dim]No local models found (is 'ollama serve' running?)[/dim]",
            "-",
            "-",
            "-",
        )
    else:
        for m in models:
            roles = m.get("roles", [])
            role_badge = (
                " ".join([f"[bold cyan]{r}[/bold cyan]" for r in roles])
                if roles
                else "[dim]Unassigned[/dim]"
            )
            mod_date = str(m.get("modified_at", ""))[:19]
            table.add_row(
                m.get("name", ""),
                m.get("size_formatted", "-"),
                mod_date,
                role_badge,
            )

    console.print(table)


@models_app.command(name="probe")
def probe(
    model: str = typer.Argument(
        ...,
        help=(
            "Model identifier to probe "
            "(e.g. hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M)."
        ),
    ),
) -> None:
    """Probe model tool-calling capability (native vs json_fallback vs none) and cache result."""
    console.print(f"[bold cyan]Probing tool-calling support for:[/bold cyan] {model}...")
    try:
        protocol = asyncio.run(probe_model(model=model, console=console))
    except Exception as exc:
        console.print(f"[red]Probe failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    protocol_colors = {
        "native": "[bold green]native[/bold green] (Model produces native structured tool calls)",
        "json_fallback": (
            "[bold yellow]json_fallback[/bold yellow] (Model produces JSON-in-text tool format)"
        ),
        "none": "[bold red]none[/bold red] (Model does not support tool calling)",
    }
    desc = protocol_colors.get(protocol, protocol)
    cap_path = get_capabilities_file_path()

    console.print(f"\n[bold]Capability Result:[/bold] {desc}")
    console.print(f"[dim]Cached record written to: {cap_path}[/dim]")


@models_app.command(name="use")
def use(
    role: str = typer.Argument(
        ...,
        help="Target agent role to update: 'planner', 'coder', 'router', or 'reviewer'.",
    ),
    model: str = typer.Argument(
        ...,
        help="Model identifier (e.g. hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M).",
    ),
) -> None:
    """Assign a model to a role and update lathe.toml."""
    valid_roles = ("planner", "coder", "router", "reviewer")
    role_norm = role.strip().lower()
    if role_norm not in valid_roles:
        console.print(
            f"[red]Error:[/red] Invalid role '{role}'. Must be one of: {', '.join(valid_roles)}."
        )
        raise typer.Exit(code=1)

    key = f"roles.{role_norm}.model"
    target_path = get_project_config_path()
    try:
        set_config_value(key, model, target_path)
        console.print(
            f"[bold green]Successfully updated {target_path.name}:[/bold green] {key} = '{model}'"
        )
    except Exception as exc:
        console.print(f"[red]Failed to update configuration:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@models_app.command(name="presets")
def list_model_presets() -> None:
    """Display all available model presets and indicate which models are already pulled."""
    from lathe.models.local import _models_match
    from lathe.models.presets import list_presets

    try:
        local_models = asyncio.run(get_local_ollama_models())
        local_names = {m.get("name", "") for m in local_models}
    except Exception:
        local_names = set()

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
        unique_models = p.get_unique_models()
        pulled_count = sum(
            1 for m in unique_models if any(_models_match(m, ln) for ln in local_names)
        )
        total_count = len(unique_models)

        if pulled_count == total_count:
            status_badge = f"[bold green]Ready[/bold green] ({pulled_count}/{total_count})"
        elif pulled_count > 0:
            status_badge = f"[yellow]Partial[/yellow] ({pulled_count}/{total_count})"
        else:
            status_badge = f"[dim]Not Pulled[/dim] (0/{total_count})"

        desc = f"[bold]{p.display_name}[/bold]\n[dim]{p.description}[/dim]"
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


@models_app.command(name="preset")
def apply_model_preset(
    name: str = typer.Argument(
        ...,
        help="Preset name ('qwen', 'gemma', or 'mixed').",
    ),
    global_config: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Write to global configuration (~/.config/lathe/lathe.toml).",
    ),
    project_config: bool = typer.Option(
        False,
        "--project",
        "-p",
        help="Write to project configuration (./lathe.toml).",
    ),
) -> None:
    """Pull missing models for a preset, probe capabilities, and configure lathe.toml."""
    from lathe.config import get_global_config_path, get_project_config_path
    from lathe.models.local import _models_match
    from lathe.models.presets import apply_preset_to_toml_file, get_preset

    try:
        preset = get_preset(name)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"\n[bold cyan]Configuring Preset:[/bold cyan] {preset.display_name}")
    console.print(f"[dim]{preset.description}[/dim]\n")

    # Check which models are already pulled
    try:
        local_models = asyncio.run(get_local_ollama_models())
        local_names = {m.get("name", "") for m in local_models}
    except Exception:
        local_names = set()

    for m in preset.get_unique_models():
        is_pulled = any(_models_match(m, ln) for ln in local_names)
        if is_pulled:
            console.print(f"  [green]✓[/green] [bold]{m}[/bold] is already pulled.")
        else:
            console.print(f"  [yellow]↓ Pulling missing model:[/yellow] [bold]{m}[/bold]")
            try:
                asyncio.run(pull_model_with_progress(model=m, console=console))
            except Exception as exc:
                console.print(f"[red]Failed to pull {m}:[/red] {exc}")
                raise typer.Exit(code=1) from exc

        # Probe model capabilities
        console.print(f"  [cyan]🔍 Probing tool-calling capabilities for:[/cyan] {m}")
        try:
            proto = asyncio.run(probe_model(model=m, console=console))
            console.print(f"  [green]✓[/green] Tool protocol: [bold cyan]{proto}[/bold cyan]")
        except Exception as exc:
            console.print(
                f"  [dim]Notice: Probe could not complete ({exc}); fallback will be used.[/dim]"
            )

    # Determine target file
    if global_config:
        target_path = get_global_config_path()
    elif project_config:
        target_path = get_project_config_path()
    else:
        choice = typer.prompt(
            "Write to [p]roject (./lathe.toml) or [g]lobal (~/.config/lathe/lathe.toml)?",
            default="project",
        )
        if choice.strip().lower().startswith("g"):
            target_path = get_global_config_path()
        else:
            target_path = get_project_config_path()

    apply_preset_to_toml_file(preset, target_path)
    console.print(
        f"\n[bold green]✓ Successfully configured '{preset.name}' preset "
        f"in {target_path}![/bold green]\n"
    )

"""Command-line interface entry point for Lathe."""

import os
import shutil
import subprocess
import sys

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from lathe import __version__
from lathe.session import Session, SessionConfig  # noqa: F401

# Load local environment variables (.env) if present
load_dotenv()

app = typer.Typer(
    name="lathe",
    help="Lathe: Terminal AI coding agent using local and open-source LLMs.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    """Print the package version and exit."""
    if value:
        console.print(f"lathe version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Lathe terminal AI coding agent."""


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
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
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


if __name__ == "__main__":
    app()

"""Hugging Face Hub integration for publishing merged models."""

from __future__ import annotations

import contextlib
from pathlib import Path

from rich.console import Console

from lathe.config import get_hf_token
from lathe.merge.resources import format_bytes

console = Console()


def get_directory_size_bytes(path: Path) -> int:
    """Calculate total byte size of all files in a directory."""
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            with contextlib.suppress(OSError):
                total += p.stat().st_size
    return total


def push_to_hub(
    name: str,
    repo_id: str | None = None,
    private: bool = True,
    base_dir: Path | str | None = None,
    token: str | None = None,
    interactive: bool = True,
    out_console: Console | None = None,
) -> str:
    """Upload a merged model directory in merges/<name> to the Hugging Face Hub."""
    out = out_console or console
    root = Path(base_dir) if base_dir else Path.cwd()
    merge_dir = root / "merges" / name

    if not merge_dir.exists() or not merge_dir.is_dir():
        raise FileNotFoundError(
            f"Merge directory '{merge_dir}' does not exist. "
            f"Build the merge first using 'lathe merge'."
        )

    dir_size = get_directory_size_bytes(merge_dir)
    if dir_size == 0:
        raise ValueError(f"Merge directory '{merge_dir}' is empty. Nothing to push.")

    # 1. Resolve Hugging Face Token
    hf_token = token or get_hf_token()
    if not hf_token:
        # Check huggingface_hub default cache
        try:
            from huggingface_hub import get_token

            hf_token = get_token()
        except Exception:
            pass

    if not hf_token:
        raise ValueError(
            "Hugging Face token not found. Set the HF_TOKEN environment variable "
            "or run 'huggingface-cli login' before pushing."
        )

    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required for uploading models. "
            "Install it via 'pip install huggingface-hub'."
        ) from exc

    api = HfApi()

    # 2. Determine target repo_id
    target_repo = repo_id
    if not target_repo:
        try:
            whoami = api.whoami(token=hf_token)
            username = str(whoami.get("name", ""))
            if not username:
                raise ValueError("Could not resolve Hugging Face username from token.")
            target_repo = f"{username}/{name}"
        except Exception as exc:
            raise ValueError(
                f"Could not determine Hugging Face username: {exc}. "
                "Please specify --repo-id username/model_name."
            ) from exc

    # 3. Interactive confirmation
    vis_badge = "[yellow]private[/yellow]" if private else "[green]public[/green]"
    out.print(
        f"\n[bold cyan]Target Repository:[/bold cyan] {target_repo} ({vis_badge})\n"
        f"[bold cyan]Local Directory:[/bold cyan] {merge_dir} ({format_bytes(dir_size)})\n"
    )

    if interactive:
        import typer

        confirm = typer.confirm(
            f"Are you sure you want to upload '{name}' to Hugging Face?",
            default=False,
        )
        if not confirm:
            out.print("[yellow]Upload cancelled by user.[/yellow]")
            return ""

    out.print(f"[bold green]Creating {target_repo} and uploading files...[/bold green]")

    api.create_repo(
        repo_id=target_repo,
        token=hf_token,
        private=private,
        exist_ok=True,
    )

    api.upload_folder(
        folder_path=str(merge_dir),
        repo_id=target_repo,
        token=hf_token,
        commit_message=f"Upload merged model '{name}' created with Lathe",
    )

    repo_url = f"https://huggingface.co/{target_repo}"
    out.print(f"\n[bold green]Successfully uploaded merged model to:[/bold green] {repo_url}\n")
    return repo_url

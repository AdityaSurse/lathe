"""Ollama model pulling with streaming progress bar and RAM headroom validation."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from lathe.models.ram import format_bytes, get_available_ram_bytes


def normalize_ollama_model_name(repo: str, quant: str = "Q4_K_M") -> str:
    """Normalize input model identifier to Ollama's hf.co/<repo>:<quant> format."""
    trimmed = repo.strip()
    if trimmed.startswith("hf.co/"):
        if ":" in trimmed:
            return trimmed
        return f"{trimmed}:{quant}"

    if "/" in trimmed:
        if ":" in trimmed:
            return f"hf.co/{trimmed}"
        return f"hf.co/{trimmed}:{quant}"

    return trimmed


async def pull_model_stream(
    model: str,
    base_url: str = "http://localhost:11434",
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream download progress events from Ollama's /api/pull endpoint."""
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=httpx.Timeout(3600.0, connect=10.0))

    try:
        url = f"{base_url.rstrip('/')}/api/pull"
        async with http_client.stream(
            "POST", url, json={"model": model, "stream": True}
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"Ollama pull failed ({response.status_code}): "
                    f"{body.decode('utf-8', errors='replace')}"
                )

            async for line in response.aiter_lines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                    yield event
                except json.JSONDecodeError:
                    continue
    finally:
        if owns_client:
            await http_client.aclose()


async def pull_model_with_progress(
    model: str,
    base_url: str = "http://localhost:11434",
    client: httpx.AsyncClient | None = None,
    console: Console | None = None,
    known_size_bytes: int | None = None,
) -> None:
    """Pull model with live Rich progress display and RAM warning."""
    out_console = console or Console()
    normalized_name = normalize_ollama_model_name(model)

    avail_ram = get_available_ram_bytes()
    if avail_ram is not None and known_size_bytes is not None and known_size_bytes > avail_ram:
        out_console.print(
            f"[bold yellow]Warning:[/bold yellow] Model size "
            f"({format_bytes(known_size_bytes)}) exceeds currently available system RAM "
            f"({format_bytes(avail_ram)}). "
            f"Running this model may cause disk swapping or system slowdown.\n"
        )

    out_console.print(f"[bold cyan]Pulling model:[/bold cyan] {normalized_name}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=out_console,
    ) as progress:
        task_id = progress.add_task(f"Pulling {normalized_name}...", total=None)

        last_status = ""
        async for event in pull_model_stream(normalized_name, base_url=base_url, client=client):
            status = event.get("status", "")
            if status and status != last_status:
                last_status = status
                progress.update(task_id, description=f"{normalized_name}: {status}")

            total = event.get("total")
            completed = event.get("completed")
            if total is not None:
                progress.update(task_id, total=total, completed=completed or 0)

            if "error" in event:
                raise RuntimeError(f"Ollama pull error: {event['error']}")

    out_console.print(f"[bold green]Successfully pulled:[/bold green] {normalized_name}")

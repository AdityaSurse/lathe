"""Hardware resource estimation (RAM, disk) and safety checks for model merging."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.table import Table

from lathe.merge.models import ResourceEstimate


def format_bytes(num_bytes: int | float) -> str:
    """Format byte count into human-readable representation (KB, MB, GB, TB)."""
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(val) < 1024.0 or unit == "TB":
            return f"{val:.2f} {unit}"
        val /= 1024.0
    return f"{val:.2f} TB"


def format_params(params: int) -> str:
    """Format parameter count into human-readable string (e.g. 1.54B, 7.2B, 350M)."""
    if params >= 1_000_000_000:
        return f"{params / 1_000_000_000:.2f}B"
    if params >= 1_000_000:
        return f"{params / 1_000_000:.1f}M"
    return f"{params:,}"


def get_available_ram_bytes() -> int | None:
    """Attempt to detect available system RAM in bytes across platforms."""
    # 1. Try psutil if installed
    try:
        import psutil  # type: ignore[import-untyped]

        return int(psutil.virtual_memory().available)
    except Exception:
        pass

    # 2. Linux /proc/meminfo
    if sys.platform.startswith("linux") and os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        return int(parts[1]) * 1024  # kB to bytes
        except Exception:
            pass

    # 3. macOS vm_stat
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["vm_stat"], text=True)
            page_size = 4096
            free_pages = 0
            speculative_pages = 0
            for line in out.splitlines():
                if "page size of" in line:
                    parts = line.split()
                    for p in parts:
                        if p.isdigit():
                            page_size = int(p)
                            break
                elif "Pages free:" in line:
                    free_pages = int(line.split(":")[1].strip().rstrip("."))
                elif "Pages speculative:" in line:
                    speculative_pages = int(line.split(":")[1].strip().rstrip("."))
            if free_pages > 0:
                return (free_pages + speculative_pages) * page_size
        except Exception:
            pass

    # 4. Fallback: total RAM via os.sysconf
    try:
        if (
            hasattr(os, "sysconf")
            and "SC_PAGE_SIZE" in os.sysconf_names
            and "SC_PHYS_PAGES" in os.sysconf_names
        ):
            total_ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            # Heuristic estimate ~50% available
            return int(total_ram * 0.5)
    except Exception:
        pass

    return None


def get_free_disk_bytes(target_dir: Path | str | None = None) -> int:
    """Return free disk space in bytes for the target output directory."""
    check_path = Path(target_dir) if target_dir else Path.cwd()
    if not check_path.exists():
        check_path = check_path.parent
    if not check_path.exists():
        check_path = Path.cwd()
    try:
        usage = shutil.disk_usage(check_path)
        return int(usage.free)
    except Exception:
        return 10 * 1024 * 1024 * 1024  # 10 GB optimistic fallback


def estimate_merge_resources(
    params_per_model: int,
    num_models: int = 2,
    output_dir: Path | str | None = None,
) -> ResourceEstimate:
    """Calculate hardware resource requirements (fp16 disk & RAM) and evaluate system safety."""
    # FP16 precision is 2 bytes per parameter
    fp16_bytes_per_model = params_per_model * 2
    total_fp16_bytes = fp16_bytes_per_model * num_models
    estimated_merged_bytes = fp16_bytes_per_model

    # Required disk: merged model + temp/cache safety margin (~2.5x merged model size)
    required_disk_bytes = int(estimated_merged_bytes * 2.5)

    # Required RAM: mergekit with lazy loading operates layer by layer,
    # but requires approximately 1.0x model size in RAM to avoid thrashing or OOM
    required_ram_bytes = int(fp16_bytes_per_model * 1.0)

    free_ram = get_available_ram_bytes()
    free_disk = get_free_disk_bytes(output_dir)

    is_disk_sufficient = free_disk >= required_disk_bytes
    is_ram_sufficient = free_ram is None or free_ram >= required_ram_bytes

    warnings: list[str] = []
    if not is_disk_sufficient:
        warnings.append(
            f"Free disk space ({format_bytes(free_disk)}) is lower than recommended "
            f"({format_bytes(required_disk_bytes)}). Merging may fail if disk space is exhausted."
        )
    if free_ram is not None and not is_ram_sufficient:
        warnings.append(
            f"Available system RAM ({format_bytes(free_ram)}) is lower than recommended "
            f"({format_bytes(required_ram_bytes)}). Consider using '--colab' to merge in the cloud."
        )

    return ResourceEstimate(
        params_per_model=params_per_model,
        fp16_bytes_per_model=fp16_bytes_per_model,
        total_fp16_bytes=total_fp16_bytes,
        estimated_merged_bytes=estimated_merged_bytes,
        required_ram_bytes=required_ram_bytes,
        required_disk_bytes=required_disk_bytes,
        free_ram_bytes=free_ram,
        free_disk_bytes=free_disk,
        is_ram_sufficient=is_ram_sufficient,
        is_disk_sufficient=is_disk_sufficient,
        warnings=warnings,
    )


def render_resource_table(estimate: ResourceEstimate) -> Table:
    """Render a styled Rich table detailing resource estimates and warnings."""
    table = Table(
        title="Hardware & Resource Requirements (FP16)",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Resource / Metric", style="bold", width=26)
    table.add_column("Requirement / Size", width=22)
    table.add_column("Available System", width=22)
    table.add_column("Status", width=14)

    # 1. Model params
    table.add_row(
        "Model Parameters",
        format_params(estimate.params_per_model),
        "-",
        "[green]Info[/green]",
    )

    # 2. FP16 size per model
    table.add_row(
        "FP16 Size (per model)",
        format_bytes(estimate.fp16_bytes_per_model),
        "-",
        "[green]Info[/green]",
    )

    # 3. Merged model size
    table.add_row(
        "Estimated Merged Size",
        format_bytes(estimate.estimated_merged_bytes),
        "-",
        "[green]Info[/green]",
    )

    # 4. Free Disk
    disk_status = (
        "[green]✓ Pass[/green]" if estimate.is_disk_sufficient else "[yellow]⚠ Low[/yellow]"
    )
    table.add_row(
        "Disk Space (Merges Dir)",
        f"~{format_bytes(estimate.required_disk_bytes)} required",
        format_bytes(estimate.free_disk_bytes),
        disk_status,
    )

    # 5. System RAM
    ram_avail_str = (
        format_bytes(estimate.free_ram_bytes) if estimate.free_ram_bytes is not None else "Unknown"
    )
    ram_status = "[green]✓ Pass[/green]" if estimate.is_ram_sufficient else "[yellow]⚠ Low[/yellow]"
    table.add_row(
        "Available System RAM",
        f"~{format_bytes(estimate.required_ram_bytes)} recommended",
        ram_avail_str,
        ram_status,
    )

    return table

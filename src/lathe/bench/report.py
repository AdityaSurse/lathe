"""Benchmarking reports: Rich comparison table, JSON persistence, and PNG bar chart generation."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from rich.table import Table

from lathe.bench.models import BenchmarkSuiteResult


def render_benchmark_table(suite_result: BenchmarkSuiteResult) -> Table:
    """Render a styled Rich table comparing candidate models on Lathe mini-bench metrics."""
    table = Table(
        title="[bold cyan]Lathe mini-bench[/bold cyan] [dim](Illustrative - Not Official)[/dim]",
        title_style="bold",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Model Evaluated", style="bold", width=34)
    table.add_column("Pass@1", justify="right", width=12)
    table.add_column("Solved", justify="right", width=12)
    table.add_column("Tokens/sec", justify="right", width=14)
    table.add_column("Avg Latency", justify="right", width=14)
    table.add_column("Tool Success", justify="right", width=14)

    for m in suite_result.models:
        pass_color = "green" if m.pass_rate >= 70.0 else "yellow" if m.pass_rate >= 40.0 else "red"
        pass_badge = f"[{pass_color}]{m.pass_rate:.1f}%[/{pass_color}]"
        solved_str = f"{m.passed_tasks}/{m.total_tasks}"
        tps_str = f"{m.avg_tokens_per_sec:.1f} t/s"
        lat_str = f"{m.avg_latency_s:.2f}s"
        tool_color = "green" if m.tool_success_rate >= 80.0 else "yellow"
        tool_badge = f"[{tool_color}]{m.tool_success_rate:.1f}%[/{tool_color}]"

        table.add_row(
            m.model,
            pass_badge,
            solved_str,
            tps_str,
            lat_str,
            tool_badge,
        )

    return table


def save_benchmark_json(
    suite_result: BenchmarkSuiteResult,
    output_dir: Path | str | None = None,
) -> Path:
    """Save benchmark results to bench/results/<date>.json."""
    root = Path(output_dir) if output_dir else Path.cwd() / "bench" / "results"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{suite_result.timestamp}.json"
    json_path.write_text(json.dumps(suite_result.to_dict(), indent=2), encoding="utf-8")
    return json_path


def _create_pure_python_png(
    models: list[str],
    pass_rates: list[float],
    throughputs: list[float],
    output_path: Path,
    width: int = 800,
    height: int = 400,
) -> None:
    """Fallback generator producing a valid PNG bar chart without external libraries."""
    # Create an RGB image buffer filled with dark background (#1e1e2e -> R:30, G:30, B:46)
    bg_r, bg_g, bg_b = 30, 30, 46
    grid_r, grid_g, grid_b = 60, 60, 80
    pass_r, pass_g, pass_b = 52, 211, 153  # emerald green
    tps_r, tps_g, tps_b = 56, 189, 248  # cyan

    pixels = bytearray([bg_r, bg_g, bg_b] * (width * height))

    def set_pixel(x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            idx = (y * width + x) * 3
            pixels[idx] = r
            pixels[idx + 1] = g
            pixels[idx + 2] = b

    def draw_rect(x1: int, y1: int, x2: int, y2: int, r: int, g: int, b: int) -> None:
        for py in range(max(0, y1), min(height, y2)):
            for px in range(max(0, x1), min(width, x2)):
                set_pixel(px, py, r, g, b)

    # Margins and plotting area
    margin_l = 80
    margin_r = 40
    margin_t = 60
    margin_b = 60
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    # Draw grid baseline
    draw_rect(
        margin_l, height - margin_b, width - margin_r, height - margin_b + 2, grid_r, grid_g, grid_b
    )

    # Draw bars for each model
    num_models = max(1, len(models))
    slot_w = plot_w // num_models
    bar_w = min(40, slot_w // 3)

    for i in range(num_models):
        center_x = margin_l + i * slot_w + slot_w // 2
        pr = pass_rates[i] if i < len(pass_rates) else 0.0
        tp = throughputs[i] if i < len(throughputs) else 0.0

        # Bar 1: Pass Rate (0 - 100%)
        bar1_h = int((pr / 100.0) * plot_h)
        b1_x1 = center_x - bar_w - 4
        b1_y1 = height - margin_b - bar1_h
        draw_rect(b1_x1, b1_y1, b1_x1 + bar_w, height - margin_b, pass_r, pass_g, pass_b)

        # Bar 2: Throughput (scaled to max 100 t/s)
        bar2_h = int((min(100.0, tp) / 100.0) * plot_h)
        b2_x1 = center_x + 4
        b2_y1 = height - margin_b - bar2_h
        draw_rect(b2_x1, b2_y1, b2_x1 + bar_w, height - margin_b, tps_r, tps_g, tps_b)

    # Encode raw pixels as standard PNG
    raw_lines = bytearray()
    for row in range(height):
        raw_lines.append(0)  # Filter byte 0 (None)
        start = row * width * 3
        raw_lines.extend(pixels[start : start + width * 3])

    compressed_idat = zlib.compress(bytes(raw_lines), 6)

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    png_data = bytearray(b"\x89PNG\r\n\x1a\n")
    # IHDR chunk: width, height, bit_depth=8, color_type=2 (Truecolor RGB)
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png_data.extend(make_chunk(b"IHDR", ihdr_data))
    # IDAT chunk
    png_data.extend(make_chunk(b"IDAT", compressed_idat))
    # IEND chunk
    png_data.extend(make_chunk(b"IEND", b""))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(png_data))


def generate_benchmark_chart(
    suite_result: BenchmarkSuiteResult,
    output_path: Path | str | None = None,
) -> Path:
    """Generate a clean comparative bar chart PNG saved to assets/bench.png."""
    target_path = Path(output_path) if output_path else Path.cwd() / "assets" / "bench.png"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    model_names = [m.model.split("/")[-1] for m in suite_result.models]
    pass_rates = [m.pass_rate for m in suite_result.models]
    throughputs = [m.avg_tokens_per_sec for m in suite_result.models]

    # 1. Try rendering with matplotlib if installed
    try:
        import matplotlib  # type: ignore[import-not-found]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
        import numpy as np

        x = np.arange(len(model_names))
        bar_width = 0.35

        fig, ax1 = plt.subplots(figsize=(10, 5), dpi=150)
        fig.patch.set_facecolor("#1e1e2e")
        ax1.set_facecolor("#1e1e2e")

        # Pass@1 bars
        ax1.bar(
            x - bar_width / 2,
            pass_rates,
            bar_width,
            label="Pass@1 (%)",
            color="#34d399",
            edgecolor="#10b981",
        )
        ax1.set_ylabel("Pass@1 (%)", color="#34d399", fontsize=11, fontweight="bold")
        ax1.tick_params(axis="y", labelcolor="#34d399")
        ax1.set_ylim(0, 100)

        # Throughput bars on secondary axis
        ax2 = ax1.twinx()
        ax2.bar(
            x + bar_width / 2,
            throughputs,
            bar_width,
            label="Tokens/sec",
            color="#38bdf8",
            edgecolor="#0284c7",
        )
        ax2.set_ylabel("Throughput (tok/sec)", color="#38bdf8", fontsize=11, fontweight="bold")
        ax2.tick_params(axis="y", labelcolor="#38bdf8")

        ax1.set_xticks(x)
        ax1.set_xticklabels(model_names, color="#f8fafc", fontsize=10, fontweight="bold")
        ax1.tick_params(axis="x", colors="#f8fafc")

        # Styling
        plt.title(
            "Lathe mini-bench: Pass@1 & Token Throughput (Illustrative Evaluation)",
            color="#f8fafc",
            fontsize=12,
            fontweight="bold",
            pad=15,
        )
        ax1.spines["bottom"].set_color("#64748b")
        ax1.spines["top"].set_visible(False)
        ax1.spines["left"].set_color("#34d399")
        ax1.spines["right"].set_visible(False)
        ax2.spines["right"].set_color("#38bdf8")
        ax2.spines["top"].set_visible(False)
        ax2.spines["left"].set_visible(False)
        ax1.grid(axis="y", linestyle="--", alpha=0.2, color="#94a3b8")

        plt.tight_layout()
        plt.savefig(str(target_path), facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return target_path

    except Exception:
        # Fallback to pure-Python PNG generator
        _create_pure_python_png(
            models=model_names,
            pass_rates=pass_rates,
            throughputs=throughputs,
            output_path=target_path,
        )
        return target_path

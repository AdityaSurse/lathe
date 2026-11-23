"""Unit tests for hardware resource estimation and warnings."""

from pathlib import Path

from lathe.merge.resources import (
    estimate_merge_resources,
    format_bytes,
    format_params,
    render_resource_table,
)


def test_format_bytes():
    """Format various byte sizes accurately."""
    assert format_bytes(500) == "500.00 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024 * 5) == "5.00 MB"
    assert format_bytes(1024 * 1024 * 1024 * 3) == "3.00 GB"


def test_format_params():
    """Format parameter counts."""
    assert format_params(1_540_000_000) == "1.54B"
    assert format_params(7_000_000_000) == "7.00B"
    assert format_params(500_000_000) == "500.0M"


def test_estimate_merge_resources_fp16_calculation(tmp_path: Path):
    """Resource estimation calculates params * 2 bytes for FP16 precision."""
    params = 1_500_000_000  # 1.5B
    estimate = estimate_merge_resources(params, num_models=2, output_dir=tmp_path)

    assert estimate.params_per_model == 1_500_000_000
    # 1.5B * 2 bytes = 3,000,000,000 bytes (~3.0 GB)
    assert estimate.fp16_bytes_per_model == 3_000_000_000
    assert estimate.total_fp16_bytes == 6_000_000_000
    assert estimate.estimated_merged_bytes == 3_000_000_000

    table = render_resource_table(estimate)
    assert table is not None
    assert "Hardware & Resource Requirements" in table.title


def test_estimate_merge_resources_low_disk_warning(tmp_path: Path, monkeypatch):
    """Low disk space triggers warning."""

    # Mock shutil.disk_usage to return 1 GB free
    class MockUsage:
        free = 1_000_000_000  # 1 GB
        total = 100_000_000_000

    import shutil

    monkeypatch.setattr(shutil, "disk_usage", lambda _: MockUsage())

    estimate = estimate_merge_resources(7_000_000_000, output_dir=tmp_path)
    assert estimate.is_disk_sufficient is False
    assert any("Free disk space" in w for w in estimate.warnings)

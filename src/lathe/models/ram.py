"""System memory detection and byte formatting utilities."""

import re
import subprocess
import sys


def get_available_ram_bytes() -> int | None:
    """Return available system RAM in bytes, or None if detection fails."""
    # macOS
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["vm_stat"], text=True)
            page_size = 4096
            m = re.search(r"page size of (\d+) bytes", out)
            if m:
                page_size = int(m.group(1))

            free_pages = 0
            spec_pages = 0
            inactive_pages = 0
            for line in out.splitlines():
                if "Pages free:" in line:
                    free_pages = int(line.split(":")[1].strip().rstrip("."))
                elif "Pages speculative:" in line:
                    spec_pages = int(line.split(":")[1].strip().rstrip("."))
                elif "Pages inactive:" in line:
                    inactive_pages = int(line.split(":")[1].strip().rstrip("."))

            return (free_pages + spec_pages + inactive_pages) * page_size
        except Exception:
            pass

    # Linux
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        except Exception:
            pass

    # Windows
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return int(stat.ullAvailPhys)
        except Exception:
            pass

    return None


def format_bytes(num_bytes: int | float) -> str:
    """Format byte count into human-readable unit string (B, KB, MB, GB, TB)."""
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(num_bytes)
    unit_idx = 0
    while value >= 1024.0 and unit_idx < len(units) - 1:
        value /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(value)} B"
    return f"{value:.2f} {units[unit_idx]}"

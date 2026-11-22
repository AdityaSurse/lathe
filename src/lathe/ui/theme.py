"""Theme colors and Rich styling for Lathe matching the README palette."""

from rich.console import Console
from rich.theme import Theme

# README Color Palette Constants
PRIMARY = "#38bdf8"  # Sky blue (CLI, headers, prompts)
SECONDARY = "#818cf8"  # Indigo (Orchestrator, planner)
ACCENT = "#f472b6"  # Fuchsia/pink (LLM providers)
SUCCESS = "#34d399"  # Mint emerald (Pass, completed, verified)
WARNING = "#fbbf24"  # Amber (Alerts, review, retry)
ERROR = "#f87171"  # Coral red (Failures, blocked)
DIM = "#94a3b8"  # Slate (Muted info, borders)
BG_DARK = "#0f172a"  # Deep slate
BG_PANEL = "#1e293b"  # Panel slate background
TEXT_LIGHT = "#f8fafc"  # Bright white text

LATHE_THEME = Theme(
    {
        "lathe.primary": PRIMARY,
        "lathe.secondary": SECONDARY,
        "lathe.accent": ACCENT,
        "lathe.success": SUCCESS,
        "lathe.warning": WARNING,
        "lathe.error": ERROR,
        "lathe.dim": DIM,
        "lathe.panel": BG_PANEL,
        "lathe.text": TEXT_LIGHT,
    }
)


def get_console() -> Console:
    """Return a styled Console instance configured with the Lathe theme."""
    return Console(theme=LATHE_THEME)

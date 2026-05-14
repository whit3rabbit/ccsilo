"""Constants and small data classes shared across the TUI subpackage.

Kept dependency-free so any TUI submodule can import from it without circular
risk.
"""

from dataclasses import dataclass


TABS = ["Manage Setup", "Dashboard", "Inspect", "Extract", "Patch"]
TAB_MODES = ["setup-manager", "dashboard", "inspect", "extract", "patch-source"]
DASHBOARD_STEPS = ["Source", "Patches", "Profiles", "Review"]
VARIANT_STEPS = ["Provider", "Name", "Credentials", "MCP", "Models", "Tweaks", "Review"]
ARCHITECT_MODE_TWEAK_ID = "opusplan1m"
VARIANT_MODEL_FIELDS = [
    ("opus", "Opus"),
    ("sonnet", "Sonnet"),
    ("haiku", "Haiku"),
    ("default", "Default"),
    ("small_fast", "Small-fast"),
    ("subagent", "Subagent"),
]
SOURCE_LATEST = "latest"
SOURCE_VERSION = "version"
SOURCE_ARTIFACT = "artifact"

DEFAULT_THEME_ID = "hacker-bbs"
THEME_ORDER = [DEFAULT_THEME_ID, "unicorn", "dark", "light", "high-contrast"]


@dataclass
class MenuOption:
    kind: str
    label: str
    value: object = None


def next_action_label(label):
    return f"Next > {label}"

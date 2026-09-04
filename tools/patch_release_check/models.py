"""Data models and constants for patch release compatibility checks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_REPORTS_DIR = Path("reports") / "patch-compat"
DEFAULT_SMOKE_TIMEOUT_SECONDS = 60
OUTPUT_LIMIT = 4000
DEFAULT_CONFIG = {
    "settings": {
        "themes": [
            {"id": "compat-dark", "name": "Compat Dark", "colors": {"bashBorder": "#ffffff"}},
            {"id": "compat-provider", "name": "Compat Provider", "colors": {"bashBorder": "#dadada"}},
        ],
        "misc": {
            "tokenCountRounding": 1000,
            "statuslineThrottleMs": 750,
            "mcpServerConnectionBatchSize": 10,
        },
        "claudeMdAltNames": ["AGENTS.md", "CLAUDE.md"],
    },
}
DEFAULT_OVERLAYS = {"webfetch": "Patch compatibility smoke overlay."}
SMOKE_ENV_DEFAULTS = {
    "CI": "1",
    "NO_COLOR": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
}

@dataclass
class PatchCheck:
    id: str
    name: str
    group: str
    status: str
    ok: bool
    supported: bool
    tested: bool
    warnings: List[str]
    notes: List[str]
    detail: str = ""


@dataclass
class VersionReport:
    version: str
    ok: bool
    output_path: Path
    summary: Dict[str, int]
    error: Optional[str] = None
    smoke: Optional[Dict[str, Any]] = None

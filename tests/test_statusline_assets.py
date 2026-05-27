import json
import os
import subprocess
import sys
from pathlib import Path

import ccsilo


def test_bundled_yet_another_statusline_renders_minimal_payload(tmp_path):
    script = (
        Path(ccsilo.__file__).parent
        / "data"
        / "statusline"
        / "yet-another-statusline"
        / "statusline_command.py"
    )
    payload = {
        "session_id": "test-session",
        "transcript_path": "",
        "cwd": str(tmp_path),
        "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
        "workspace": {
            "current_dir": str(tmp_path),
            "project_dir": str(tmp_path),
            "added_dirs": [],
        },
        "version": "2.1.0",
        "output_style": {"name": "default"},
        "cost": {
            "total_cost_usd": 0.01,
            "total_duration_ms": 1000,
            "total_api_duration_ms": 100,
            "total_lines_added": 0,
            "total_lines_removed": 0,
        },
        "context_window": {
            "total_input_tokens": 100,
            "total_output_tokens": 20,
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 20,
            },
            "used_percentage": 1,
            "remaining_percentage": 99,
        },
        "rate_limits": {
            "five_hour": {"used_percentage": 0, "resets_at": 0},
            "seven_day": {"used_percentage": 0, "resets_at": 0},
        },
    }
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "config")
    env["COLUMNS"] = "120"

    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()

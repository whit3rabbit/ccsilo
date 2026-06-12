import concurrent.futures
import json
import os
import shlex
import threading
import time
from pathlib import Path

import pytest

from ccsilo import tui
from ccsilo.workspace import (
    DashboardTweakProfile,
    NativeArtifact,
    PatchPackage,
    PatchProfile,
    load_dashboard_tweak_profile,
    load_tui_settings,
    scan_native_downloads,
    save_dashboard_tweak_profile,
    save_tui_settings,
    store_native_download,
)


def _package(patch_id="replace-before", version="0.1.0", name="Replace Before"):
    return PatchPackage(
        patch_id=patch_id,
        version=version,
        name=name,
        path=Path(f"/tmp/{patch_id}/{version}"),
        manifest={"id": patch_id, "version": version, "name": name},
    )


class _FakeStdout:
    def __init__(self, *, tty=True):
        self.tty = tty
        self.writes = []
        self.flushed = False

    def isatty(self):
        return self.tty

    def write(self, text):
        self.writes.append(text)

    def flush(self):
        self.flushed = True


def _profile(
    profile_id="daily-build",
    name="Daily Build",
    patches=None,
):
    patches = patches or [{"id": "replace-before", "version": "0.1.0"}]
    return PatchProfile(
        profile_id=profile_id,
        name=name,
        patches=patches,
        path=Path(f"/tmp/{profile_id}.json"),
        manifest={
            "schemaVersion": 1,
            "id": profile_id,
            "name": name,
            "patches": patches,
        },
    )


def _tweak_profile(
    profile_id="daily-build",
    name="Daily Build",
    tweak_ids=None,
):
    tweak_ids = tweak_ids or [tui.DASHBOARD_TWEAK_IDS[0]]
    return DashboardTweakProfile(
        profile_id=profile_id,
        name=name,
        tweak_ids=tweak_ids,
        path=Path(f"/tmp/{profile_id}.json"),
        manifest={
            "schemaVersion": 1,
            "id": profile_id,
            "name": name,
            "tweakIds": tweak_ids,
        },
    )


def _finish_busy(state, timeout=2.0):
    deadline = time.monotonic() + timeout
    while state.mode == "busy" and time.monotonic() < deadline:
        tui._poll_busy_action(state)
        if state.mode != "busy":
            break
        time.sleep(0.01)
    assert state.mode != "busy"


def _render_screen(state, width=80, height=24):
    from ratatui_py import Color, DrawCmd, Gauge, List as TuiList, Paragraph, Style, Tabs, headless_render_frame

    class FakeTerm:
        def __init__(self):
            self.commands = None

        def draw_frame(self, commands):
            self.commands = commands

    term = FakeTerm()
    tui._render_frame(
        term, state, width, height,
        Paragraph, Style, Color, DrawCmd, Tabs, TuiList, Gauge,
    )
    return headless_render_frame(width, height, term.commands)


def _option_index(options, kind, value=None):
    for index, option in enumerate(options):
        if option.kind == kind and (value is None or option.value == value):
            return index
    raise AssertionError(f"option not found: {kind} {value}")


def test_screen_text_contains_dashboard_first_tab():
    state = tui.TuiState(
        counts="Native: 0  NPM: 0  Extractions: 0  Patch packages: 0  Profiles: 0",
        download_index={"binary": {"latest": "2.1.122"}},
        download_versions=["2.1.122", "2.1.121"],
    )

    screen = tui._screen_text(state)

    assert "Workspace:" in screen
    assert "Dashboard: Source | Manage Setup [Dashboard] Inspect Extract Patch" in screen
    assert "ccsilo |" not in screen
    assert "Dashboard Source | Step 1/4" in screen
    assert "Latest native binary" in screen
    assert "Native 2.1.121" in screen
    assert "Inspect" in screen
    assert "Extract" in screen
    assert "Patch" in screen


def test_default_theme_is_hacker_bbs():
    state = tui.TuiState()

    assert state.theme_id == "hacker-bbs"
    assert tui._theme_name(state.theme_id) == "Hacker BBS"
    assert tui._active_theme(state).theme_id == "hacker-bbs"


def test_cycle_theme_saves_workspace_setting(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    state = tui.TuiState()

    seen = []
    for _ in range(5):
        tui._cycle_theme(state)
        seen.append(state.theme_id)

    assert seen == ["unicorn", "dark", "light", "high-contrast", "hacker-bbs"]
    assert load_tui_settings(root)["themeId"] == "hacker-bbs"
    assert state.message == "Theme saved: Hacker BBS"


def test_load_saved_theme_id_uses_workspace_setting(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    save_tui_settings({"themeId": "high-contrast"}, root=root)
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))

    assert tui._load_saved_theme_id() == "high-contrast"
    assert tui._theme_name("high-contrast") == "High Contrast"


def test_load_saved_theme_id_falls_back_for_unknown_theme(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    save_tui_settings({"themeId": "unknown-theme"}, root=root)
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))

    assert tui._load_saved_theme_id() == "hacker-bbs"


def test_dashboard_theme_key_does_not_probe_variant_helpers(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))

    def fail_variant_text_check(state):
        raise AssertionError("dashboard key handling should not check variant name text")

    monkeypatch.setattr(tui, "_variant_accepts_name_text", fail_variant_text_check)
    state = tui.TuiState(mode="dashboard")

    assert tui._handle_char_key(state, "t") is True
    assert state.theme_id == "unicorn"


def test_variant_name_text_accepts_lowercase_t(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    state = tui.TuiState(mode="variants", variant_step=1, selected_index=0)

    assert tui._handle_char_key(state, "t") is True
    assert state.variant_name == "t"
    assert state.theme_id == "hacker-bbs"


def test_screen_text_includes_theme_and_compact_progress():
    state = tui.TuiState(
        counts="Native: 0  NPM: 0  Extractions: 0  Patch packages: 2  Profiles: 0",
        dashboard_step=1,
        selected_dashboard_tweak_ids=[tui.DASHBOARD_TWEAK_IDS[0]],
    )

    screen = tui._screen_text(state)

    assert "Theme: Hacker BBS" in screen
    assert "Dashboard Patches | Step 2/4" in screen
    assert "Patches 1" in screen
    assert "Wizard: [" not in screen
    assert "Theme T" in screen
    assert "Workspace:" in screen


def test_wizard_next_actions_are_called_out():
    dashboard = tui.TuiState(
        mode="dashboard",
        dashboard_step=1,
        selected_dashboard_tweak_ids=[tui.DASHBOARD_TWEAK_IDS[0]],
    )
    variant = tui.TuiState(mode="variants", variant_step=1, variant_name="mirror")
    credentials = tui.TuiState(
        mode="variants",
        variant_step=2,
        variant_providers=[{"key": "mirror", "authMode": "none"}],
    )

    dashboard.selected_index = next(
        index for index, option in enumerate(tui._dashboard_options(dashboard))
        if option.kind == "patch-continue"
    )

    assert "Next > Continue to profile management" in tui._screen_text(dashboard)
    assert "Next > Continue to credentials" in tui._screen_text(variant)
    assert "Next > Continue to MCP" in tui._screen_text(credentials)


def test_busy_screen_text_shows_progress_and_locks_input():
    state = tui.TuiState(
        mode="busy",
        busy_title="Creating setup",
        busy_detail="Building custom Claude setup mirror",
        busy_ticks=3,
    )

    screen = tui._screen_text(state)

    assert "Creating setup" in screen
    assert "Building custom Claude setup mirror" in screen
    assert "Progress: [" in screen
    assert "Input locked while this runs." in screen
    assert "Keys: input locked while this runs" in screen
    assert tui._handle_char_key(state, "q") is True
    assert state.mode == "busy"


def test_run_tui_does_not_clear_every_frame(monkeypatch):
    import ratatui_py

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, state):
            captured["state"] = state

    monkeypatch.setattr(ratatui_py, "App", FakeApp)
    monkeypatch.setattr(tui, "_load_saved_setup_list_preferences", lambda state: None)
    monkeypatch.setattr(tui, "_refresh_state", lambda state: False)

    tui.run_tui()

    assert captured["clear_each_frame"] is False
    assert captured["tick_ms"] == tui._BUSY_TICK_MS


def test_poll_busy_action_copies_completed_state():
    completed = tui.TuiState(
        mode="health-result",
        selected_setup_id="mirror",
        message="Setup created: /tmp/mirror",
        last_action_summary=["Setup created."],
    )
    future = concurrent.futures.Future()
    future.set_result(completed)
    state = tui.TuiState(
        mode="busy",
        busy_title="Creating setup",
        busy_detail="Building custom Claude setup mirror",
        busy_future=future,
    )

    assert tui._poll_busy_action(state) is True

    assert state.mode == "health-result"
    assert state.selected_setup_id == "mirror"
    assert state.message == "Setup created: /tmp/mirror"
    assert state.last_action_summary == ["Setup created."]
    assert state.busy_future is None
    assert state.busy_title == ""


def test_dashboard_first_run_lists_curated_tweaks_without_dead_end_continue():
    state = tui.TuiState(mode="dashboard", dashboard_step=1)

    screen = tui._screen_text(state)

    assert tui.DASHBOARD_TWEAK_IDS[0] in screen
    assert "Continue to profile management" not in screen

    tui._toggle_selected(state)
    assert state.selected_dashboard_tweak_ids == [tui.DASHBOARD_TWEAK_IDS[0]]

    option_labels = [option.label for option in tui._dashboard_options(state)]
    assert "Next > Continue to profile management" in option_labels

    state.selected_dashboard_tweak_ids = []
    tui._activate_dashboard(state)
    assert state.selected_dashboard_tweak_ids == [tui.DASHBOARD_TWEAK_IDS[0]]


def test_dashboard_tweak_ids_include_first_wave_ports():
    ids = tui._dashboard_tweak_ids()

    assert "suppress-model-launch-notice" in ids
    assert "suppress-native-installer-warning" in ids
    assert "suppress-prompt-caching-warning" in ids
    assert "suppress-rate-limit-options" in ids
    assert "thinking-visibility" in ids
    assert "input-box-border" in ids
    assert "filter-scroll-escape-sequences" in ids


def test_dashboard_tweak_ids_include_latest_safe_ports():
    ids = tui._dashboard_tweak_ids()

    assert "agents-md" in ids
    assert "session-memory" in ids
    assert "opusplan1m" in ids
    assert "mcp-non-blocking" in ids
    assert "mcp-batch-size" in ids
    assert "token-count-rounding" in ids
    assert "statusline-update-throttle" in ids
    assert "auto-accept-plan-mode" in ids
    assert "rtk-shell-prefix" not in ids
    assert "dangerously-skip-permissions" not in ids
    assert "remember-skill" not in ids
    assert "allow-sudo-bypass-permissions" not in ids
    assert "input-pattern-highlighters" not in ids


def test_footer_keys_match_dashboard_step():
    state = tui.TuiState(mode="dashboard", dashboard_step=0)
    footer = tui._footer_text(state)
    assert "R refresh" in footer
    assert "Space toggle" not in footer

    state.dashboard_step = 1
    footer = tui._footer_text(state)
    assert "Space toggle" in footer
    assert "R refresh" not in footer

    state.dashboard_step = 2
    footer = tui._footer_text(state)
    assert "Profile names:" in footer


def test_setup_manager_footer_advertises_quit_early():
    state = tui.TuiState(mode="setup-manager")
    footer = tui._footer_text(state)

    assert "Q/Ctrl+C quit" in footer
    assert footer.index("Q/Ctrl+C quit") < footer.index("Up/Down")
    assert "? more" in footer


def test_compact_key_footer_fits_narrow_width():
    manager = tui.TuiState(mode="setup-manager", variants=[_variant("deepseek-main")])
    detail = tui.TuiState(
        mode="setup-detail",
        variants=[_variant("deepseek-main")],
        selected_setup_id="deepseek-main",
    )

    manager_screen = _render_screen(manager, 70, 24)
    detail_screen = _render_screen(detail, 70, 24)

    assert "Keys: Q/Ctrl+C quit | Enter manage | Up/Down | X run | ? more" in manager_screen
    assert "Keys: Q quit | Enter select | M models | Esc | Up/Down | ?" in detail_screen


def test_footer_keys_match_variant_step():
    state = tui.TuiState(mode="variants", variant_step=1)
    footer = tui._footer_text(state)
    assert "Setup names:" in footer
    assert "Space tweak" not in footer

    state.variant_step = 2
    footer = tui._footer_text(state)
    assert "Credentials:" in footer
    assert "toggle local API key storage" in footer

    state.variant_step = 3
    footer = tui._footer_text(state)
    assert "MCP servers:" in footer
    assert "Space MCP" in footer

    state.variant_step = 4
    footer = tui._footer_text(state)
    assert "Models:" in footer

    state.variant_step = 5
    footer = tui._footer_text(state)
    assert "Space tweak" in footer
    assert "Variant names:" not in footer


def test_activate_reports_action_and_refresh_failures(monkeypatch):
    state = tui.TuiState(mode="dashboard")

    def fail_action(app_state):
        raise RuntimeError("boom")

    def fail_refresh(app_state):
        raise RuntimeError("scan broke")

    monkeypatch.setattr(tui, "_activate_dashboard", fail_action)
    monkeypatch.setattr(tui.TuiState, "refresh", fail_refresh)

    assert tui._activate(state) is True
    assert "Action failed: boom" in state.message
    assert "Refresh failed: scan broke" in state.message


def test_gauge_widget_renders_with_headless_ratatui():
    from ratatui_py import Color, DrawCmd, Gauge, Style, headless_render_frame

    theme = tui._active_theme(tui.TuiState(theme_id="unicorn"))
    gauge = tui._gauge_widget("Wizard", 0.5, "2/4 Patches", Gauge, Style, Color, theme)
    screen = headless_render_frame(40, 3, [DrawCmd.gauge(gauge, (0, 0, 40, 3))])

    assert "Wizard" in screen
    assert "2/4 Patches" in screen


def test_render_frame_themes_full_surface():
    from ratatui_py import Color, DrawCmd, Gauge, List as TuiList, Paragraph, Style, Tabs, headless_render_frame_cells

    state = tui.TuiState(theme_id="light")

    class FakeTerm:
        def __init__(self):
            self.commands = None

        def draw_frame(self, commands):
            self.commands = commands

    term = FakeTerm()
    tui._render_frame(
        term, state, 80, 24,
        Paragraph, Style, Color, DrawCmd, Tabs, TuiList, Gauge,
    )

    cells = headless_render_frame_cells(80, 24, term.commands)

    assert cells
    assert all(cell["fg"] != int(Color.Reset) or cell["bg"] != int(Color.Reset) for cell in cells)


def test_render_frame_puts_theme_only_in_bottom_banner():
    state = tui.TuiState(theme_id="hacker-bbs")

    screen = _render_screen(state, 80, 24)
    lines = screen.splitlines()

    assert screen.count("Theme: Hacker BBS") == 1
    assert all("Theme:" not in line for line in lines[:4])
    assert "Theme: Hacker BBS" in "\n".join(lines[-6:])
    assert "Workspace:" in lines[-2]


def test_render_frame_splits_workspace_from_counts():
    state = tui.TuiState(
        counts="Native: 4  NPM: 0  Extractions: 1  Patch bundles: 0  Profiles: 0",
    )

    screen = _render_screen(state, 140, 24)
    lines = screen.splitlines()

    theme_line = next(line for line in lines if "Theme: Hacker BBS" in line)
    workspace_line = next(line for line in lines if "Workspace:" in line)

    assert "Workspace:" not in theme_line
    assert "Native: 4" in theme_line
    assert "Patch bundles: 0" in theme_line
    assert "Native: 4" not in workspace_line


def test_render_frame_places_tabs_in_body_title():
    state = tui.TuiState(
        mode="first-run-setup",
        variant_step=1,
        variant_name="minimax",
        variant_providers=[
            {
                "key": "minimax",
                "label": "Minimax",
                "defaultVariantName": "minimax",
            }
        ],
    )

    lines = _render_screen(state, 140, 24).splitlines()
    context_text = "First run setup Name | Step 2/7 | Provider minimax | Name minimax"

    assert "No Claude Code setups found: Name | [Manage Setup] Dashboard Inspect Extract Patch" in lines[0]
    assert context_text in lines[1]
    assert all("ccsilo |" not in line for line in lines[:4])


def test_render_frame_uses_stable_chrome_for_dashboard_and_inspect():
    dashboard = tui.TuiState(mode="dashboard")
    inspect = tui.TuiState(mode="inspect")

    assert tui.rendering.layout_heights(24) == (0, 6)

    dashboard_lines = _render_screen(dashboard, 80, 24).splitlines()
    inspect_lines = _render_screen(inspect, 80, 24).splitlines()

    assert "Dashboard: Source | Manage Setup [Dashboard] Inspect Extract Patch" in dashboard_lines[0]
    assert "Inspect | Manage Setup Dashboard [Inspect] Extract Patch" in inspect_lines[0]
    assert "Status" in dashboard_lines[-5]
    assert "Status" in inspect_lines[-5]


def test_render_frame_keeps_body_and_footer_at_short_height():
    state = tui.TuiState(
        download_index={"binary": {"latest": "2.1.122"}},
        download_versions=["2.1.122", "2.1.121"],
    )

    screen = _render_screen(state, 80, 18)

    assert "Latest native binary" in screen
    assert "Status: Ready" in screen
    assert "Theme: Hacker BBS" in screen


def test_dashboard_selects_specific_version_without_downloading():
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=0,
        selected_index=3,
        download_index={"binary": {"latest": "2.1.122"}},
        download_versions=["2.1.122", "2.1.121"],
    )

    tui._activate_dashboard(state)

    assert state.dashboard_step == 1
    assert state.dashboard_source_kind == tui.SOURCE_VERSION
    assert state.dashboard_source_version == "2.1.121"


def test_version_list_loads_once_until_manual_refresh(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    from ccsilo.tui import dashboard as dashboard_module
    from ccsilo.tui import state as state_module

    monkeypatch.setattr(state_module, "scan_native_downloads", lambda: [])
    monkeypatch.setattr(state_module, "scan_npm_downloads", lambda: [])
    monkeypatch.setattr(state_module, "scan_extractions", lambda: [])
    monkeypatch.setattr(state_module, "scan_patch_packages", lambda: [])
    monkeypatch.setattr(state_module, "scan_patch_profiles", lambda: [])
    monkeypatch.setattr(state_module, "scan_dashboard_tweak_profiles", lambda: [])
    monkeypatch.setattr(state_module, "scan_variants", lambda: [])
    monkeypatch.setattr(state_module, "list_variant_providers", lambda: [])

    loads = []

    def fake_load_download_index():
        loads.append(True)
        return {"binary": {"latest": "2.1.121", "versions": [{"version": "2.1.121"}]}}

    monkeypatch.setattr(state_module, "load_download_index", fake_load_download_index)
    state = tui.TuiState(mode="dashboard")

    state.refresh()
    state.refresh()

    assert len(loads) == 1
    assert state.download_versions == ["2.1.121"]

    live_checks = []

    def fake_startup_refresh():
        live_checks.append(True)
        return {"binary": {"latest": "2.1.122", "versions": [{"version": "2.1.122"}]}}

    monkeypatch.setattr(tui, "refresh_download_index", fake_startup_refresh)

    tui._refresh_startup_download_index(state)
    tui._refresh_startup_download_index(state)

    assert len(live_checks) == 1
    assert state.download_versions == ["2.1.122"]
    assert state.download_index_checked_live is True

    monkeypatch.setattr(
        dashboard_module,
        "refresh_download_index",
        lambda: {"binary": {"latest": "2.1.123", "versions": [{"version": "2.1.123"}]}},
    )

    tui._refresh_dashboard_index(state)

    assert live_checks == [True]
    assert state.download_versions == ["2.1.123"]
    assert state.download_index_loaded is True


def test_dashboard_toggles_patch_and_loads_profile():
    first = tui.DASHBOARD_TWEAK_IDS[0]
    second = tui.DASHBOARD_TWEAK_IDS[1]
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=1,
        dashboard_tweak_profiles=[_tweak_profile(tweak_ids=[first, second])],
    )

    state.selected_index = 0
    tui._activate_dashboard(state)
    assert state.selected_dashboard_tweak_ids == [first]

    state.selected_index = next(
        index for index, option in enumerate(tui._dashboard_options(state))
        if option.kind == "profile-load"
    )
    tui._activate_dashboard(state)
    assert state.selected_dashboard_tweak_ids == [first, second]
    assert state.dashboard_loaded_profile_id == "daily-build"
    assert state.dashboard_profile_name == "Daily Build"


def test_dashboard_marks_profile_with_missing_patch_invalid():
    first = tui.DASHBOARD_TWEAK_IDS[0]
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=1,
        dashboard_tweak_profiles=[_tweak_profile(tweak_ids=[first, "missing-patch"])],
    )

    option_labels = [option.label for option in tui._dashboard_options(state)]
    state.selected_index = next(
        index for index, option in enumerate(tui._dashboard_options(state))
        if option.kind == "profile-load"
    )
    tui._activate_dashboard(state)

    assert any("invalid, missing missing-patch" in label for label in option_labels)
    assert state.selected_dashboard_tweak_ids == []
    assert "missing missing-patch" in state.message


def test_dashboard_run_rejects_legacy_patch_profile_id():
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=3,
        dashboard_loaded_profile_id="legacy-package-profile",
        patch_profiles=[_profile(profile_id="legacy-package-profile", name="Legacy Package Profile")],
        selected_dashboard_tweak_ids=[tui.DASHBOARD_TWEAK_IDS[0]],
    )

    tui._run_dashboard_build(state)

    assert state.message == (
        "Loaded profile is invalid, missing legacy-package-profile is not a dashboard tweak profile"
    )


def test_dashboard_creates_profile_from_selected_patches(tmp_path, monkeypatch):
    first = tui.DASHBOARD_TWEAK_IDS[0]
    monkeypatch.setenv("CCSILO_WORKSPACE", str(tmp_path / ".ccsilo"))
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=2,
        selected_dashboard_tweak_ids=[first],
        dashboard_profile_name="Focus Build",
    )

    tui._create_dashboard_profile(state)

    profile = load_dashboard_tweak_profile("focus-build", root=tmp_path / ".ccsilo")
    assert profile.name == "Focus Build"
    assert profile.tweak_ids == [first]
    assert state.dashboard_loaded_profile_id == "focus-build"


def test_dashboard_delete_profile_requires_confirmation(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=2,
        dashboard_tweak_profiles=[_tweak_profile()],
        dashboard_loaded_profile_id="daily-build",
    )

    save_dashboard_tweak_profile("Daily Build", [tui.DASHBOARD_TWEAK_IDS[0]], root=root)

    tui._delete_dashboard_profile(state, "daily-build")
    assert state.dashboard_delete_confirm_id == "daily-build"
    assert load_dashboard_tweak_profile("daily-build", root=root).name == "Daily Build"

    tui._delete_dashboard_profile(state, "daily-build")
    assert state.dashboard_delete_confirm_id == ""
    assert state.dashboard_loaded_profile_id == ""


def test_dashboard_run_requires_patches():
    state = tui.TuiState(mode="dashboard", dashboard_step=3)

    tui._run_dashboard_build(state)

    assert state.message == "Select at least one dashboard patch."


def test_dashboard_run_applies_selected_tweaks_to_artifact(monkeypatch, tmp_path):
    calls = []
    artifact = NativeArtifact(
        version="2.1.123",
        platform="darwin-arm64",
        sha256="a" * 64,
        path=tmp_path / "claude",
        metadata={},
    )

    class Result:
        output_path = tmp_path / "claude-patched"

    def fake_apply(source_artifact, tweak_ids):
        calls.append((source_artifact, tweak_ids))
        return Result()

    monkeypatch.setattr(tui, "apply_dashboard_tweaks_to_native", fake_apply)

    state = tui.TuiState(
        mode="dashboard",
        dashboard_step=3,
        dashboard_source_kind=tui.SOURCE_ARTIFACT,
        native_artifacts=[artifact],
        selected_dashboard_tweak_ids=[tui.DASHBOARD_TWEAK_IDS[0]],
    )

    tui._run_dashboard_build(state)

    assert calls == [(artifact, [tui.DASHBOARD_TWEAK_IDS[0]])]
    assert state.message == f"Dashboard build complete: {tmp_path / 'claude-patched'}"


def test_patch_package_apply_handles_stale_selection(monkeypatch, tmp_path):
    artifact = NativeArtifact(
        version="1.2.3",
        platform="darwin-arm64",
        sha256="a" * 64,
        path=tmp_path / "claude",
        metadata={},
    )
    calls = []

    def fake_apply(source_artifact, packages):
        calls.append((source_artifact, packages))

    monkeypatch.setattr(tui, "apply_patch_packages_to_native", fake_apply)
    state = tui.TuiState(
        mode="patch-package",
        native_artifacts=[artifact],
        selected_source_index=0,
        patch_packages=[],
        selected_patch_indexes=[3],
    )

    tui._activate_patch_packages(state)

    assert calls == []
    assert state.message == "Selected patch packages are unavailable."


def test_move_tab_cycles_from_dashboard_to_inspect():
    state = tui.TuiState(mode="dashboard")

    tui._move_tab(state, 1)

    assert state.mode == "inspect"


def test_move_tab_clears_stale_status():
    state = tui.TuiState(mode="dashboard", message="Select at least one patch package.")

    tui._move_tab(state, 1)

    assert state.mode == "inspect"
    assert state.message == ""


def test_inspect_delete_native_artifact_requires_yes(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    staged = tmp_path / "claude"
    staged.write_bytes(b"fake-binary")
    sha = "b" * 64
    path = store_native_download(staged, "2.1.123", "darwin-arm64", sha, root=root)
    artifact = scan_native_downloads(root=root)[0]
    state = tui.TuiState(mode="inspect", native_artifacts=[artifact])

    assert tui._handle_char_key(state, "d") is True

    assert state.mode == "inspect-delete-confirm"
    assert state.inspect_delete_confirm_path == str(path)
    assert path.exists()
    assert "Confirm delete" in _render_screen(state, 100, 24)

    assert tui._handle_char_key(state, "n") is True

    assert state.mode == "inspect"
    assert path.exists()

    assert tui._handle_char_key(state, "d") is True
    assert tui._handle_char_key(state, "y") is True

    assert state.mode == "inspect"
    assert not path.exists()
    assert not path.parent.exists()
    assert state.native_artifacts == []
    assert "Deleted native artifact: 2.1.123 darwin-arm64" in state.message


def test_variants_tab_lists_providers_and_progress():
    state = tui.TuiState(
        mode="variants",
        variant_providers=[
            {
                "key": "mirror",
                "label": "Mirror Claude",
                "description": "Pure Claude",
                "defaultVariantName": "mirror",
            }
        ],
    )

    screen = tui._screen_text(state)

    assert "[Manage Setup]" in screen
    assert "Create setup Provider | Step 1/7" in screen
    assert "mirror  Mirror Claude" in screen


def test_variants_provider_selection_groups_by_type_and_sorts_providers():
    state = tui.TuiState(
        mode="variants",
        variant_providers=[
            {"key": "zai", "label": "Zai Cloud", "description": "Cloud", "section": "cloud"},
            {"key": "openrouter", "label": "OpenRouter", "description": "Gateway", "section": "cloud"},
            {"key": "ollama", "label": "Ollama", "description": "Local", "section": "local"},
            {"key": "ccr-oauth", "label": "CCR OAuth Proxy", "description": "OAuth CCR"},
            {"key": "ccrouter", "label": "CC Router", "description": "Router", "section": "pinned"},
            {"key": "mirror", "label": "Mirror Claude Code", "description": "Pure", "section": "pinned"},
            {"key": "anthropic", "label": "Anthropic Console", "description": "First-party", "section": "cloud"},
            {"key": "alibaba", "label": "Alibaba Cloud", "description": "DashScope", "section": "cloud"},
            {"key": "opencode-go", "label": "OpenCode Go", "description": "Gateway", "section": "cloud"},
            {"key": "lmstudio", "label": "LM Studio", "description": "Local", "section": "local"},
        ],
    )

    options = tui._variant_options(state)
    labels = tui.options.variant_provider_selector_labels(state)

    assert [option.kind for option in options] == ["variant-provider"] * 10
    assert options[0].label.startswith("mirror  Mirror Claude Code")
    assert options[1].label.startswith("ccrouter  CC Router")
    assert options[2].label.startswith("ccr-oauth  CCR OAuth Proxy")
    assert options[3].label.startswith("alibaba  Alibaba Cloud")
    assert options[4].label.startswith("anthropic  Anthropic Console")
    assert options[5].label.startswith("zai  Zai Cloud")
    assert options[6].label.startswith("opencode-go  OpenCode Go")
    assert options[7].label.startswith("openrouter  OpenRouter")
    assert options[8].label.startswith("lmstudio  LM Studio")
    assert options[9].label.startswith("ollama  Ollama")
    assert labels[0] == "Search: none | Filter: All | Showing: 10/10"
    assert labels[1] == "Recommended defaults (3)"
    assert labels[5] == "Direct model APIs (3)"
    assert labels[9] == "Gateways, routers, and custom endpoints (2)"
    assert labels[12] == "Local endpoints (2)"


def test_provider_selector_sections_are_not_selectable():
    state = tui.TuiState(
        mode="variants",
        variant_providers=[
            {"key": "mirror", "label": "Mirror Claude Code", "description": "Pure", "section": "pinned"},
            {"key": "zai", "label": "Zai Cloud", "description": "Cloud", "section": "cloud"},
        ],
    )

    assert state.item_count() == 2
    assert tui.options.variant_provider_selected_label_index(state) == 2

    state.move(1)

    assert tui._selected_variant_option(state).value == 1
    assert tui.options.variant_provider_selected_label_index(state) == 4
    assert tui.options.variant_provider_detail_lines(state)[0] == "Zai Cloud"


def test_provider_selector_search_and_filter_keys():
    state = tui.TuiState(
        mode="variants",
        variant_providers=[
            {"key": "mirror", "label": "Mirror Claude Code", "description": "Pure", "section": "pinned", "authMode": "none"},
            {"key": "zai", "label": "Zai Cloud", "description": "Cloud", "section": "cloud", "mcpServers": ["web-reader"]},
            {"key": "openrouter", "label": "OpenRouter", "description": "Gateway", "section": "cloud", "requiresModelMapping": True},
            {"key": "lmstudio", "label": "LM Studio", "description": "Local", "section": "local", "requiresModelMapping": True},
        ],
    )

    assert tui._handle_char_key(state, "/") is True
    assert state.variant_provider_search_active is True
    assert tui._handle_char_key(state, "z") is True
    assert [option.value for option in tui._variant_options(state)] == [1]
    assert "Search: z (typing) | Filter: All | Showing: 1/4" in tui._screen_text(state)

    assert tui._activate(state) is True
    assert state.variant_provider_search_active is False

    state.variant_provider_search_text = ""
    assert tui._handle_char_key(state, "f") is True
    assert state.variant_provider_filter == "recommended"
    assert [option.value for option in tui._variant_options(state)] == [0, 1]
    assert tui._handle_char_key(state, "f") is True
    assert state.variant_provider_filter == "cloud"
    assert [option.value for option in tui._variant_options(state)] == [1, 2]


def _provider_selector_fixture():
    return [
        {
            "key": "mirror",
            "label": "Mirror Claude",
            "description": "Pure Claude",
            "section": "pinned",
            "authMode": "none",
            "credentialEnv": "",
            "baseUrl": "",
            "models": {},
            "defaultVariantName": "mirror",
            "tui": {
                "headline": "Mirror Claude",
                "features": ["Pure Claude Code behavior", "No provider credential required"],
                "setupNote": "Uses normal Claude authentication.",
            },
        },
        {
            "key": "zai",
            "label": "Z.ai Cloud",
            "description": "GLM provider with official MCP defaults",
            "section": "cloud",
            "authMode": "apiKey",
            "credentialEnv": "Z_AI_API_KEY",
            "baseUrl": "https://api.z.ai/api/anthropic",
            "requiresModelMapping": False,
            "noPromptPack": False,
            "models": {"sonnet": "glm-5-turbo", "opus": "glm-5.1"},
            "mcpServers": ["web-reader"],
            "settingsPermissionsDeny": ["mcp__zai__web_search"],
            "envUnset": ["CLAUDE_CODE_USE_BEDROCK"],
            "modelDiscovery": {"enabled": True},
            "defaultVariantName": "zai",
            "tui": {
                "headline": "Z.ai Coding Plan",
                "features": ["Official Z.ai MCP servers registered"],
                "setupLinks": {"docs": "https://z.ai/docs"},
                "setupNote": "Provide Z_AI_API_KEY.",
            },
        },
    ]


def test_provider_selector_screen_text_includes_highlighted_details():
    state = tui.TuiState(
        mode="first-run-setup",
        selected_index=1,
        variant_providers=_provider_selector_fixture(),
    )

    screen = tui._screen_text(state, height=40)

    assert "Provider details" in screen
    assert "Z.ai Coding Plan" in screen
    assert "GLM provider with official MCP defaults" in screen
    assert "Credential env: Z_AI_API_KEY" in screen
    assert "MCP servers: web-reader" in screen
    assert "Settings deny: mcp__zai__web_search" in screen
    assert "OAuth architect proxy" in screen
    assert "enable OAuth architect proxy on the Tweaks step" in screen
    assert "Requires Claude Code account/login" in screen
    assert "docs: https://z.ai/docs" in screen


def test_provider_selector_two_pane_renders_at_typical_widths():
    state = tui.TuiState(
        mode="variants",
        variant_providers=_provider_selector_fixture(),
        theme_id="hacker-bbs",
    )

    for width, height in ((100, 30), (80, 24)):
        screen = _render_screen(state, width, height)
        lines = screen.splitlines()
        assert "Create setup: Provider" in screen
        assert lines[0].startswith("Create setup: Provider | [Manage Setup]")
        assert lines[1].startswith("┌Provider")
        assert "Create setup: Provider" not in lines[1]
        assert "Provider details" in screen
        assert "Mirror Claude" in screen
        assert "Auth: none" in screen

    assert "No provider credential required" in _render_screen(state, 100, 30)

    state.selected_index = 1
    screen = _render_screen(state, 100, 30)

    assert "Z.ai Coding Plan" in screen
    assert "Credential env: Z_AI_API_KEY" in screen


def test_first_run_provider_selector_header_spans_two_panes():
    state = tui.TuiState(
        mode="first-run-setup",
        variant_providers=_provider_selector_fixture(),
        theme_id="hacker-bbs",
    )

    lines = _render_screen(state, 140, 30).splitlines()

    assert lines[0].startswith("No Claude Code setups found: Provider | [Manage Setup]")
    assert lines[1].startswith("┌Provider")
    assert "┌No Claude Code setups found" not in lines[1]
    assert "Provider details" in lines[1]


def test_variants_wizard_selects_provider_toggles_tweak_and_creates(monkeypatch, tmp_path):
    calls = []
    create_started = threading.Event()
    release_create = threading.Event()

    class Result:
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "mirror"

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        create_started.set()
        release_create.wait(1)
        return Result()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)
    state = tui.TuiState(
        mode="variants",
        variant_providers=[
            {
                "key": "mirror",
                "label": "Mirror Claude",
                "description": "Pure Claude",
                "authMode": "none",
                "credentialEnv": "",
                "models": {},
                "defaultVariantName": "mirror",
            }
        ],
    )

    state.selected_index = 0
    tui._activate_variants(state)
    assert state.variant_step == 1
    assert state.variant_name == "mirror"

    state.selected_index = 1
    tui._activate_variants(state)
    assert state.variant_step == 2

    state.selected_index = 1
    tui._activate_variants(state)
    assert state.variant_step == 3

    state.selected_index = 2
    tui._toggle_selected(state)
    assert state.selected_variant_mcp_ids == ["github"]

    state.selected_index = len(tui._variant_options(state)) - 1
    tui._activate_variants(state)
    assert state.variant_step == 5

    first_tweak = state.selected_variant_tweaks[0]
    options = tui._variant_options(state)
    state.selected_index = next(index for index, option in enumerate(options) if option.value == first_tweak)
    tui._toggle_selected(state)
    assert first_tweak not in state.selected_variant_tweaks

    state.selected_index = len(tui._variant_options(state)) - 1
    tui._activate_variants(state)
    assert state.variant_step == 6

    tui._activate_variants(state)
    assert calls == []
    assert state.mode == "create-preview"
    preview = tui._screen_text(state)
    assert "Setup create preview" in preview
    assert "source binary" not in preview.lower()

    state.selected_index = 3
    start = time.monotonic()
    tui._handle_char_key(state, "y")
    elapsed = time.monotonic() - start
    assert elapsed < 0.2
    assert state.mode == "busy"
    assert "Creating setup" in tui._screen_text(state)
    assert create_started.wait(1)
    release_create.set()
    _finish_busy(state)
    assert calls[0]["provider_key"] == "mirror"
    assert calls[0]["name"] == "mirror"
    assert calls[0]["credential_env"] is None
    assert calls[0]["claude_version"] == "latest"
    assert "source_binary" not in calls[0]
    assert "source_platform" not in calls[0]
    assert calls[0]["model_overrides"] == {}
    assert calls[0]["mcp_ids"] == ["github"]
    assert first_tweak not in calls[0]["tweaks"]
    assert state.mode == "health-result"


def test_variants_wizard_selects_specific_claude_code_version_for_create(monkeypatch, tmp_path):
    calls = []

    class Result:
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "mirror"

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)
    state = tui.TuiState(
        mode="variants",
        variant_step=1,
        variant_name="mirror",
        download_index={"binary": {"latest": "2.1.123"}},
        download_versions=["2.1.123", "2.1.122"],
        variant_providers=[
            {
                "key": "mirror",
                "label": "Mirror Claude",
                "authMode": "none",
                "models": {},
                "defaultVariantName": "mirror",
            }
        ],
    )

    options = tui._variant_options(state)
    labels = [option.label for option in options]
    assert "* Claude Code: latest native binary (2.1.123)" in labels
    state.selected_index = next(index for index, option in enumerate(options) if option.value == "2.1.122")

    tui._activate_variants(state)

    assert state.variant_claude_version == "2.1.122"
    assert state.message == "Claude Code version: 2.1.122"
    labels = [option.label for option in tui._variant_options(state)]
    assert "* Claude Code: 2.1.122" in labels

    state.mode = "create-preview"
    assert "Claude Code: 2.1.122" in tui._screen_text(state)

    tui._run_variant_create(state)

    assert calls[0]["claude_version"] == "2.1.122"


def test_variants_wizard_marks_highest_listed_version_as_latest():
    state = tui.TuiState(
        mode="variants",
        variant_step=1,
        variant_name="mirror",
        download_index={
            "binary": {
                "latest": "2.1.175",
                "versions": [{"version": "2.1.176"}, {"version": "2.1.175"}],
            },
        },
        download_versions=["2.1.176", "2.1.175"],
    )

    labels = [option.label for option in tui._variant_options(state)]

    assert "* Claude Code: latest native binary (2.1.176)" in labels
    assert "  Claude Code: 2.1.176 (latest)" in labels
    assert "  Claude Code: 2.1.175" in labels


def test_variants_credentials_step_edits_endpoint_and_stored_key():
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "description": "Local",
        "section": "local",
        "baseUrl": "http://localhost:1234",
        "authMode": "authToken",
        "credentialEnv": "LM_API_TOKEN",
        "credentialOptional": True,
        "models": {},
        "defaultVariantName": "cclmstudio",
    }
    state = tui.TuiState(mode="variants", variant_step=2, variant_providers=[provider])
    tui._set_variant_provider_defaults(state, provider)

    labels = [option.label for option in tui._variant_options(state)]
    assert "Endpoint: http://localhost:1234" in labels
    assert "Credential env: LM_API_TOKEN" in labels
    assert "[ ] Store API key locally" in labels

    state.selected_index = 2
    tui._toggle_selected(state)
    labels = [option.label for option in tui._variant_options(state)]
    assert "[x] Store API key locally" in labels
    assert "API key: not set" in labels

    state.selected_index = 3
    assert tui._handle_char_key(state, "s") is True
    assert tui._handle_char_key(state, "3") is True
    labels = [option.label for option in tui._variant_options(state)]
    assert "API key: set" in labels
    assert "s3" not in "\n".join(labels)

    state.selected_index = 0
    state.variant_base_url = ""
    for char in "http://localhost:4567":
        tui._handle_char_key(state, char)
    assert state.variant_base_url == "http://localhost:4567"


def test_variants_credentials_continue_validates_endpoint_and_secret():
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "description": "Local",
        "section": "local",
        "baseUrl": "http://localhost:1234",
        "authMode": "authToken",
        "credentialEnv": "LM_API_TOKEN",
        "credentialOptional": True,
        "models": {},
        "defaultVariantName": "cclmstudio",
    }
    state = tui.TuiState(mode="variants", variant_step=2, variant_providers=[provider])
    tui._set_variant_provider_defaults(state, provider)

    state.variant_base_url = "localhost:1234"
    state.selected_index = 3
    tui._activate_variants(state)
    assert state.variant_step == 2
    assert state.message == "Endpoint must be an http:// or https:// URL."

    state.variant_base_url = "http://localhost:1234"
    state.variant_store_secret = True
    state.selected_index = 4
    tui._activate_variants(state)
    assert state.variant_step == 2
    assert state.message == "Enter an API key or turn off local secret storage."


def test_variants_create_preview_redacts_stored_key_and_create_kwargs(monkeypatch, tmp_path):
    calls = []

    class Result:
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "cclmstudio"

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "description": "Local",
        "section": "local",
        "baseUrl": "http://localhost:1234",
        "authMode": "authToken",
        "credentialEnv": "LM_API_TOKEN",
        "credentialOptional": True,
        "models": {},
        "defaultVariantName": "cclmstudio",
    }
    state = tui.TuiState(
        mode="create-preview",
        variant_providers=[provider],
        variant_name="cclmstudio",
        variant_base_url="http://localhost:4567",
        variant_store_secret=True,
        variant_api_key="secret-value",
    )

    screen = tui._screen_text(state)
    assert "Endpoint: http://localhost:4567" in screen
    assert "API key storage: on, key set" in screen
    assert "secret-value" not in screen

    tui._run_variant_create(state)

    assert calls[0]["base_url"] == "http://localhost:4567"
    assert calls[0]["credential_env"] is None
    assert calls[0]["api_key"] == "secret-value"
    assert calls[0]["store_secret"] is True


def test_variants_create_preview_toggles_install_command(monkeypatch, tmp_path):
    install_dir = tmp_path / "home" / ".local" / "bin"
    monkeypatch.setattr(tui, "default_install_dir", lambda allow_create=False: install_dir)
    provider = {
        "key": "mirror",
        "label": "Mirror Claude",
        "authMode": "none",
        "models": {},
        "defaultVariantName": "mirror",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=6,
        variant_name="mirror",
        variant_providers=[provider],
    )

    tui._open_variant_create_preview(state)

    assert state.mode == "create-preview"
    assert state.variant_install_command is True
    assert "Setup name: mirror" in tui._screen_text(state)
    assert "Setup id: mirror" in tui._screen_text(state)
    assert "Command alias: mirror" in tui._screen_text(state)
    assert "Install command: yes" in tui._screen_text(state)

    state.selected_index = 2
    tui._handle_char_key(state, "i")

    assert state.variant_install_command is False
    assert "Install command: no" in tui._screen_text(state)


def test_variants_create_preview_name_edits_sync_default_alias():
    provider = {
        "key": "mirror",
        "label": "Mirror Claude",
        "authMode": "none",
        "models": {},
        "defaultVariantName": "mirror",
    }
    state = tui.TuiState(
        mode="create-preview",
        variant_name="mirror",
        variant_install_alias="mirror",
        variant_providers=[provider],
    )

    state.selected_index = 0
    for char in "-dev":
        tui._handle_char_key(state, char)

    assert state.variant_name == "mirror-dev"
    assert state.variant_install_alias == "mirror-dev"
    screen = tui._screen_text(state)
    assert "Setup name: mirror-dev" in screen
    assert "Setup id: mirror-dev" in screen
    assert "Command alias: mirror-dev" in screen


def test_variants_create_preview_custom_alias_stops_name_sync():
    provider = {
        "key": "mirror",
        "label": "Mirror Claude",
        "authMode": "none",
        "models": {},
        "defaultVariantName": "mirror",
    }
    state = tui.TuiState(
        mode="create-preview",
        variant_name="mirror",
        variant_install_alias="mirror",
        variant_providers=[provider],
    )

    state.selected_index = 1
    for char in "-local":
        tui._handle_char_key(state, char)
    state.selected_index = 0
    for char in "-dev":
        tui._handle_char_key(state, char)

    assert state.variant_name == "mirror-dev"
    assert state.variant_install_alias == "mirror-local"
    assert state.variant_install_alias_customized is True


def test_run_variant_create_installs_selected_command(monkeypatch, tmp_path):
    calls = []
    preflight_calls = []
    install_calls = []

    class FakeVariant:
        variant_id = "mirror"
        name = "mirror"
        path = tmp_path / ".ccsilo" / "variants" / "mirror"
        manifest = {
            "schemaVersion": 1,
            "id": "mirror",
            "name": "mirror",
            "provider": {"key": "mirror"},
            "source": {"version": "latest"},
            "paths": {"wrapper": str(tmp_path / ".ccsilo" / "bin" / "mirror")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    class Result:
        variant = FakeVariant()
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "mirror"
        stages = []

    class InstallResult:
        alias = "cc-mirror"
        path = tmp_path / "home" / ".local" / "bin" / "cc-mirror"
        target = tmp_path / ".ccsilo" / "bin" / "mirror"
        status = "installed"
        on_path = True
        warning = ""

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    def fake_preflight(variant_id, *, target, alias=None, yes=False):
        preflight_calls.append((variant_id, str(target), alias, yes))
        return InstallResult()

    def fake_install(variant, alias=None, yes=False):
        install_calls.append((variant.variant_id, alias, yes))
        return InstallResult()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "inspect_variant_command_install", fake_preflight)
    monkeypatch.setattr(tui, "install_variant_command", fake_install)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)
    provider = {
        "key": "mirror",
        "label": "Mirror Claude",
        "description": "Pure Claude",
        "authMode": "none",
        "credentialEnv": "",
        "models": {},
        "defaultVariantName": "mirror",
    }
    state = tui.TuiState(
        mode="create-preview",
        variant_name="mirror",
        variant_install_alias="cc-mirror",
        variant_install_alias_customized=True,
        variant_providers=[provider],
        variant_install_command=True,
    )

    tui._run_variant_create(state)

    assert calls[0]["provider_key"] == "mirror"
    assert preflight_calls == [("mirror", str(tui.workspace_root() / "bin" / "mirror"), "cc-mirror", True)]
    assert install_calls == [("mirror", "cc-mirror", True)]
    assert state.mode == "health-result"
    assert "Installed command: " in "\n".join(state.last_action_summary)
    assert str(InstallResult.path) in "\n".join(state.last_action_summary)


def test_run_variant_create_skips_blocked_install_command(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    install_dir.mkdir(parents=True)
    blocked = install_dir / "cc-zai"
    blocked.write_text("#!/bin/sh\n", encoding="utf-8")
    calls = []
    install_calls = []

    class FakeVariant:
        variant_id = "zai"
        name = "zai"
        path = root / "variants" / "zai"
        manifest = {
            "schemaVersion": 1,
            "id": "zai",
            "name": "zai",
            "provider": {"key": "zai"},
            "source": {"version": "latest"},
            "paths": {"wrapper": str(root / "bin" / "zai")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    class Result:
        variant = FakeVariant()
        wrapper_path = root / "bin" / "zai"
        stages = []

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    def fake_install_variant_command(*args, **kwargs):
        install_calls.append((args, kwargs))
        raise AssertionError("blocked command install should be skipped")

    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "install_variant_command", fake_install_variant_command)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)
    provider = {
        "key": "zai",
        "label": "Z.AI",
        "description": "Z.AI",
        "authMode": "none",
        "credentialEnv": "",
        "models": {},
        "defaultVariantName": "zai",
    }
    state = tui.TuiState(
        mode="create-preview",
        variant_name="zai",
        variant_install_alias="cc-zai",
        variant_install_alias_customized=True,
        variant_providers=[provider],
        variant_install_command=True,
    )

    tui._run_variant_create(state)

    summary = "\n".join(state.last_action_summary)
    assert len(calls) == 1
    assert install_calls == []
    assert state.mode == "health-result"
    assert "Setup created." in summary
    assert f"Run it with:\n  {root / 'bin' / 'zai'}" in summary
    assert f"Installed command: skipped, existing command preserved: {blocked}" in summary
    assert "Install warning: Refusing to overwrite non-symlink command" in summary
    assert "Health: healthy" in summary
    assert state.message.startswith("Setup created; command install skipped:")
    assert state.selected_setup_id == "zai"
    assert calls[0]["provider_key"] == "zai"
    assert blocked.read_text(encoding="utf-8") == "#!/bin/sh\n"


def test_variants_model_refresh_applies_selected_model(monkeypatch):
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "description": "Local",
        "section": "local",
        "baseUrl": "http://localhost:1234",
        "authMode": "authToken",
        "credentialEnv": "LM_API_TOKEN",
        "credentialOptional": True,
        "requiresModelMapping": True,
        "modelDiscovery": {"enabled": True},
        "models": {},
        "defaultVariantName": "cclmstudio",
    }
    calls = []

    def fake_fetch(endpoint, api_key=None):
        calls.append((endpoint, api_key))
        return ["local/model-b", "local/model-a", "local/model-a"]

    monkeypatch.setattr(tui, "fetch_provider_models", fake_fetch)
    state = tui.TuiState(mode="variants", variant_step=4, variant_providers=[provider])
    tui._set_variant_provider_defaults(state, provider)

    state.selected_index = _option_index(tui._variant_options(state), "variant-model-refresh")
    tui._activate_variants(state)

    assert calls == [("http://localhost:1234", None)]
    assert state.variant_model_choices == ["local/model-a", "local/model-b"]
    assert state.selected_index == _option_index(tui._variant_options(state), "variant-model-choice")

    tui._activate_variants(state)

    assert state.variant_model_overrides == {"opus": "local/model-a"}
    assert state.variant_model_target == "sonnet"
    assert state.message == "Opus model set to local/model-a. Next target: Sonnet."


def test_variants_model_refresh_failure_is_nonfatal(monkeypatch):
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "description": "Local",
        "section": "local",
        "baseUrl": "http://localhost:1234",
        "authMode": "authToken",
        "credentialEnv": "LM_API_TOKEN",
        "credentialOptional": True,
        "requiresModelMapping": True,
        "modelDiscovery": {"enabled": True},
        "models": {},
        "defaultVariantName": "cclmstudio",
    }
    monkeypatch.setattr(tui, "fetch_provider_models", lambda endpoint, api_key=None: (_ for _ in ()).throw(RuntimeError("down")))
    state = tui.TuiState(mode="variants", variant_step=4, variant_providers=[provider])
    tui._set_variant_provider_defaults(state, provider)

    state.selected_index = _option_index(tui._variant_options(state), "variant-model-refresh")
    tui._activate_variants(state)

    assert state.variant_step == 4
    assert state.variant_model_choices == []
    assert state.message == "Model refresh failed: down"


def test_variants_model_picker_search_filters_and_caps():
    provider = {
        "key": "openrouter",
        "label": "OpenRouter",
        "description": "Gateway",
        "section": "cloud",
        "baseUrl": "https://openrouter.ai/api",
        "authMode": "authToken",
        "credentialEnv": "OPENROUTER_API_KEY",
        "requiresModelMapping": True,
        "modelDiscovery": {"enabled": True},
        "models": {},
        "defaultVariantName": "openrouter",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=4,
        variant_providers=[provider],
        variant_model_choices=[*(f"vendor/model-{index:02d}" for index in range(30)), "anthropic/claude-opus"],
    )

    options = tui._variant_options(state)
    assert len([option for option in options if option.kind == "variant-model-choice"]) == 25
    assert any("Showing 25/31 matching models; keep typing to narrow." == option.label for option in options)

    state.selected_index = _option_index(options, "variant-model-refresh")
    assert tui._handle_char_key(state, "/") is True
    assert state.variant_model_search_active is True
    for char in "claude":
        assert tui._handle_char_key(state, char) is True

    options = tui._variant_options(state)
    assert [option.value for option in options if option.kind == "variant-model-choice"] == ["anthropic/claude-opus"]
    assert "Search: claude (typing)" in tui._screen_text(state, height=40)

    assert tui._handle_backspace_key(state) is True
    assert state.variant_model_search_text == "claud"
    assert tui._activate(state) is True
    assert state.variant_model_search_active is False
    assert state.message == "Model search kept: claud"

    state.variant_model_search_text = "missing"
    assert "No models match current search." in tui._screen_text(state, height=40)


def test_variants_model_skip_keeps_required_mapping_guard_and_manual_typing():
    provider = {
        "key": "openrouter",
        "label": "OpenRouter",
        "description": "Gateway",
        "authMode": "authToken",
        "credentialEnv": "OPENROUTER_API_KEY",
        "requiresModelMapping": True,
        "modelDiscovery": {"enabled": True},
        "models": {},
        "defaultVariantName": "openrouter",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=4,
        variant_name="OpenRouter Dev",
        variant_providers=[provider],
        variant_model_choices=["anthropic/claude-opus", "anthropic/claude-sonnet"],
    )

    state.selected_index = _option_index(tui._variant_options(state), "variant-model-skip")
    tui._activate_variants(state)

    assert state.variant_model_choices == []
    assert state.variant_model_search_text == ""
    assert tui._selected_variant_option(state).kind == "variant-model"
    assert tui._selected_variant_option(state).value == "opus"
    assert "variant.json modelOverrides" in state.message

    state.selected_index = _option_index(tui._variant_options(state), "variant-models-continue")
    tui._activate_variants(state)
    assert state.variant_step == 4
    assert state.message == "Set model aliases for: Opus, Sonnet, Haiku"

    for key, value in [
        ("opus", "anthropic/claude-opus"),
        ("sonnet", "anthropic/claude-sonnet"),
        ("haiku", "anthropic/claude-haiku"),
    ]:
        state.selected_index = _option_index(tui._variant_options(state), "variant-model", key)
        state.variant_model_overrides[key] = ""
        for char in value:
            assert tui._handle_char_key(state, char) is True

    state.selected_index = _option_index(tui._variant_options(state), "variant-models-continue")
    tui._activate_variants(state)
    assert state.variant_step == 5


def test_variants_wizard_all_tweaks_lists_latest_curated_ports():
    state = tui.TuiState(mode="variants", variant_step=5, tweak_filter="all")

    labels = [option.label for option in tui._variant_options(state)]
    text = "\n".join(labels)

    assert "agents-md" in text
    assert "session-memory" in text
    assert "Architect Mode  (plan-mode planner / worker routing)" in text
    assert "opusplan1m" not in text
    assert "mcp-non-blocking" in text
    assert "mcp-batch-size" in text
    assert "rtk-shell-prefix" in text
    assert "dangerously-skip-permissions" in text
    assert "disable-telemetry" in text
    assert "disable-prompt-caching" in text
    assert "token-count-rounding" in text
    assert "statusline-update-throttle" in text
    assert "yet-another-statusline" in text


def test_variant_tweak_step_groups_labels_without_selectable_headers():
    state = tui.TuiState(mode="variants", variant_step=5, tweak_filter="all")

    options = tui._variant_options(state)
    labels = tui.options.variant_tweak_selector_labels(state)
    screen = tui._screen_text(state, height=80)

    assert "section" not in {option.kind for option in options}
    assert "-- Recommended defaults --" in labels
    assert "-- Environment variables --" in labels
    assert "-- ui --" in labels
    assert "-- Recommended defaults --" in screen
    assert "-- Environment variables --" in screen
    assert len(labels) > len(options)
    assert state.item_count() == len(options)
    assert tui.options.variant_tweak_selected_label_index(state) == labels.index(options[0].label)
    assert tui._selected_variant_option(state).value == "opusplan1m"

    row_by_option_index = {
        option_index: row_index
        for row_index, (_label, option_index) in enumerate(tui.options.variant_tweak_selector_rows(state))
        if option_index is not None
    }
    rendered_positions = [row_by_option_index[index] for index in range(len(options))]
    assert all(left < right for left, right in zip(rendered_positions, rendered_positions[1:]))
    assert max(
        (right - left for left, right in zip(rendered_positions, rendered_positions[1:])),
        default=0,
    ) <= 2


def test_variants_wizard_recommended_tweaks_include_mcp_and_rtk():
    state = tui.TuiState(mode="variants", variant_step=5, tweak_filter="recommended")

    labels = [option.label for option in tui._variant_options(state)]
    text = "\n".join(labels)

    assert "mcp-non-blocking" in text
    assert "mcp-batch-size" in text
    assert "rtk-shell-prefix" in text
    assert "dangerously-skip-permissions" in text
    assert "yet-another-statusline" not in text


def test_variants_wizard_non_mirror_defaults_include_env_switches():
    provider = {
        "key": "zai",
        "label": "ZAI",
        "description": "Cloud",
        "authMode": "apiKey",
        "credentialEnv": "Z_AI_API_KEY",
        "models": {},
        "defaultVariantName": "zai",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=5,
        tweak_filter="recommended",
        variant_provider_index=0,
        variant_providers=[provider],
    )
    tui._set_variant_provider_defaults(state, provider)

    labels = [option.label for option in tui._variant_options(state)]
    text = "\n".join(labels)

    assert "disable-telemetry" in state.selected_variant_tweaks
    assert "disable-prompt-caching" in state.selected_variant_tweaks
    assert "disable-telemetry" in text
    assert "disable-prompt-caching" in text
    grouped_labels = tui.options.variant_tweak_selector_labels(state)
    assert "-- Recommended defaults --" in grouped_labels
    assert "-- Provider defaults --" in grouped_labels
    assert "-- Environment variables --" not in grouped_labels
    assert grouped_labels.index("-- Provider defaults --") < grouped_labels.index("[x] Disable telemetry  (disable-telemetry)")


def test_variants_wizard_can_uncheck_new_default_tweaks():
    state = tui.TuiState(mode="variants", variant_step=5, tweak_filter="recommended")

    for tweak_id in ("mcp-batch-size", "rtk-shell-prefix", "dangerously-skip-permissions"):
        options = tui._variant_options(state)
        state.selected_index = next(index for index, option in enumerate(options) if option.value == tweak_id)
        tui._toggle_selected(state)

    assert "mcp-batch-size" not in state.selected_variant_tweaks
    assert "rtk-shell-prefix" not in state.selected_variant_tweaks
    assert "dangerously-skip-permissions" not in state.selected_variant_tweaks


def test_ccr_oauth_provider_defaults_to_architect_proxy_and_tweak():
    provider = {
        "key": "ccr-oauth",
        "label": "CCR OAuth Proxy",
        "description": "OAuth CCR",
        "section": "pinned",
        "authMode": "authToken",
        "credentialEnv": "CCROUTER_AUTH_TOKEN",
        "credentialOptional": True,
        "authTokenFallback": "ccrouter-proxy",
        "baseUrl": "http://127.0.0.1:3456",
        "requiresModelMapping": True,
        "models": {},
        "defaultVariantName": "ccr-oauth",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=5,
        variant_provider_index=0,
        variant_providers=[provider],
    )
    tui._set_variant_provider_defaults(state, provider)

    options = tui._variant_options(state)
    labels = [option.label for option in options]

    assert state.variant_model_proxy == "architect"
    assert "opusplan1m" in state.selected_variant_tweaks
    assert "gateway-model-discovery" in state.selected_variant_tweaks
    assert labels.count("[x] Architect Mode  (plan-mode planner / worker routing)") == 1
    assert sum(1 for option in options if option.value == "opusplan1m") == 1
    assert "[x] Gateway model discovery  (gateway-model-discovery)" in labels
    assert "[x] OAuth architect proxy  (requires Claude Code account)" in labels
    assert "Model proxy port: auto" in labels

    state.selected_index = next(index for index, option in enumerate(options) if option.kind == "variant-model-proxy")
    screen = tui._screen_text(state, height=40)
    assert "OAuth architect proxy" in screen
    assert "Requires Claude Code account/login" in screen
    assert "claude-* calls use Claude Code OAuth/session" in screen
    assert "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1" in screen
    assert "unchecking Gateway model discovery disables this proxy" in screen
    preview = "\n".join(tui.rendering.create_preview_labels(state))
    assert "Model proxy: OAuth architect proxy" in preview
    assert "Model proxy requirement: Requires Claude Code account/login" in preview
    assert "Model proxy discovery: sets CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1" in preview

    tui._toggle_selected(state)
    assert state.variant_model_proxy == ""
    assert "opusplan1m" in state.selected_variant_tweaks
    assert "gateway-model-discovery" not in state.selected_variant_tweaks

    state.selected_variant_tweaks.remove("opusplan1m")
    tui._toggle_selected(state)
    assert state.variant_model_proxy == "architect"
    assert "opusplan1m" in state.selected_variant_tweaks
    assert "gateway-model-discovery" in state.selected_variant_tweaks


def test_variants_wizard_opencode_defaults_use_gateway_discovery_without_architect_mode():
    provider = {
        "key": "opencode-go",
        "label": "OpenCode Go",
        "description": "OpenCode Go",
        "section": "cloud",
        "authMode": "apiKey",
        "credentialEnv": "OPENCODE_API_KEY",
        "baseUrl": "https://opencode.ai/zen/go/v1",
        "requiresModelMapping": False,
        "models": {
            "default": "deepseek-v4-pro",
            "opus": "deepseek-v4-pro",
            "sonnet": "deepseek-v4-flash",
            "haiku": "deepseek-v4-flash",
        },
        "modelDiscovery": {"enabled": True},
        "defaultVariantName": "opencode-go",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=5,
        variant_provider_index=0,
        variant_providers=[provider],
    )
    tui._set_variant_provider_defaults(state, provider)

    labels = [option.label for option in tui._variant_options(state)]

    assert state.variant_model_proxy == ""
    assert "opencode-gateway-discovery" in state.selected_variant_tweaks
    assert "opusplan1m" not in state.selected_variant_tweaks
    assert "gateway-model-discovery" in state.selected_variant_tweaks
    assert "[x] OpenCode gateway discovery  (opencode-gateway-discovery)" in labels
    assert "[ ] Architect Mode  (plan-mode planner / worker routing)" in labels
    assert "[ ] OAuth architect proxy  (requires Claude Code account)" in labels
    assert "Model proxy port: auto" not in labels


def test_variants_wizard_unchecking_gateway_discovery_disables_model_proxy():
    provider = {
        "key": "ccr-oauth",
        "label": "CCR OAuth Proxy",
        "description": "CCR",
        "section": "pinned",
        "authMode": "authToken",
        "credentialEnv": "CCROUTER_AUTH_TOKEN",
        "credentialOptional": True,
        "authTokenFallback": "ccrouter-proxy",
        "baseUrl": "http://127.0.0.1:3456",
        "requiresModelMapping": True,
        "models": {},
        "defaultVariantName": "ccr-oauth",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=5,
        variant_provider_index=0,
        variant_providers=[provider],
    )
    tui._set_variant_provider_defaults(state, provider)

    options = tui._variant_options(state)
    state.selected_index = next(
        index
        for index, option in enumerate(options)
        if option.kind == "variant-tweak" and option.value == "gateway-model-discovery"
    )

    tui._toggle_selected(state)

    labels = [option.label for option in tui._variant_options(state)]
    assert state.variant_model_proxy == ""
    assert "gateway-model-discovery" not in state.selected_variant_tweaks
    assert "[ ] OAuth architect proxy  (requires Claude Code account)" in labels
    assert state.message == "Gateway model discovery disabled; OAuth architect proxy disabled."


def test_variants_wizard_architect_mode_toggle_uses_tweak_without_proxy():
    provider = {
        "key": "minimax",
        "label": "MiniMax Cloud",
        "description": "MiniMax",
        "section": "cloud",
        "authMode": "apiKey",
        "credentialEnv": "MINIMAX_API_KEY",
        "baseUrl": "https://api.minimax.io/anthropic",
        "requiresModelMapping": False,
        "models": {
            "default": "MiniMax-M2.7",
            "opus": "MiniMax-M2.7",
            "sonnet": "MiniMax-M2.7",
            "haiku": "MiniMax-M2.7",
        },
        "defaultVariantName": "minimax",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=5,
        variant_provider_index=0,
        variant_providers=[provider],
    )
    tui._set_variant_provider_defaults(state, provider)

    options = tui._variant_options(state)
    labels = [option.label for option in options]

    assert state.variant_model_proxy == ""
    assert "opusplan1m" not in state.selected_variant_tweaks
    assert "[ ] Architect Mode  (plan-mode planner / worker routing)" in labels
    assert "[ ] OAuth architect proxy  (requires Claude Code account)" in labels

    state.selected_index = next(index for index, option in enumerate(options) if option.kind == "variant-architect-mode")
    tui._toggle_selected(state)

    assert "opusplan1m" in state.selected_variant_tweaks
    assert state.variant_model_proxy == ""
    assert state.message == "Architect Mode enabled. Set Planner and Worker aliases in the Models step."


def test_variants_wizard_tweak_step_renders_detail_card():
    from ccsilo.tui.render_labels_details import variant_tweak_detail_text

    state = tui.TuiState(mode="variants", variant_step=5, tweak_filter="all")
    options = tui._variant_options(state)
    state.selected_index = next(index for index, option in enumerate(options) if option.value == "opusplan1m")

    screen = _render_screen(state, 100, 30)
    detail = variant_tweak_detail_text(state)

    assert "Tweak details" in screen
    assert "Architect Mode" in screen
    assert "Versions supported" in screen
    assert "Add an Architect Mode model alias" in screen
    assert "normal Claude Code login/session can still be used" in detail
    assert "Planner/worker aliases" in detail


def test_dashboard_tweak_step_renders_detail_card():
    state = tui.TuiState(mode="dashboard", dashboard_step=1)

    screen = _render_screen(state, 100, 30)

    assert "Tweak details" in screen
    assert "Versions supported" in screen
    assert "Selected for build: no" in screen


def test_variants_wizard_provider_mcp_copy_clarifies_auto_enabled():
    state = tui.TuiState(
        mode="variants",
        variant_step=3,
        variant_providers=[
            {
                "key": "zai",
                "label": "Zai Cloud",
                "credentialEnv": "Z_AI_API_KEY",
                "mcpServers": ["web-reader"],
            }
        ],
    )

    labels = [option.label for option in tui._variant_options(state)]
    preview = "\n".join(tui.rendering._create_preview_mcp_lines(state, state.variant_providers[0]))

    assert "[x] web-reader  auto-enabled for this provider env:Z_AI_API_KEY" in labels
    assert "web-reader (auto-enabled for this provider)" in preview


def test_create_failure_summary_reports_verified_path_state(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))

    def fake_create_variant(**_kwargs):
        setup_dir = root / "variants" / "mirror"
        setup_dir.mkdir(parents=True)
        wrapper = root / "bin" / "mirror"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
        raise RuntimeError("create broke")

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    state = tui.TuiState(
        mode="create-preview",
        variant_name="mirror",
        variant_providers=[
            {
                "key": "mirror",
                "label": "Mirror Claude",
                "description": "Pure Claude",
                "authMode": "none",
                "credentialEnv": "",
                "models": {},
                "defaultVariantName": "mirror",
            }
        ],
    )

    tui._run_variant_create(state)

    summary = "\n".join(state.last_action_summary)
    assert state.mode == "error"
    assert "Create failed." in summary
    assert "Setup directory created: yes" in summary
    assert "Command created: yes" in summary
    assert "Setup config created: no" in summary
    assert "Previous state changed: yes" in summary
    assert "Cleanup needed: yes" in summary


def test_variants_wizard_blocks_required_model_mapping():
    state = tui.TuiState(
        mode="variants",
        variant_step=4,
        selected_index=len(tui.VARIANT_MODEL_FIELDS),
        variant_provider_index=0,
        variant_providers=[
            {
                "key": "openrouter",
                "label": "OpenRouter",
                "description": "Gateway",
                "authMode": "authToken",
                "credentialEnv": "OPENROUTER_API_KEY",
                "requiresModelMapping": True,
                "models": {},
                "defaultVariantName": "openrouter",
            }
        ],
    )

    tui._activate_variants(state)

    assert state.variant_step == 4
    assert state.message == "Set model aliases for: Opus, Sonnet, Haiku"

    state.variant_model_overrides = {
        "opus": "anthropic/claude-opus-4",
        "sonnet": "anthropic/claude-sonnet-4",
        "haiku": "anthropic/claude-haiku-4",
    }
    tui._activate_variants(state)

    assert state.variant_step == 5


def test_variants_architect_mode_model_step_uses_planner_worker_labels():
    provider = {
        "key": "mirror",
        "label": "Mirror Claude Code",
        "description": "Mirror",
        "authMode": "none",
        "models": {},
        "requiresModelMapping": False,
        "defaultVariantName": "mirror",
    }
    state = tui.TuiState(
        mode="variants",
        variant_step=4,
        variant_name="mirror",
        selected_variant_tweaks=["opusplan1m"],
        variant_providers=[provider],
        variant_model_overrides={"opus": "claude-planner", "sonnet": "claude-worker", "default": "claude-worker"},
    )

    labels = [option.label for option in tui._variant_options(state)]

    assert any("Planner -> claude-planner" in label for label in labels)
    assert any("Worker -> claude-worker" in label for label in labels)
    assert any("Default worker -> claude-worker" in label for label in labels)

    state.variant_model_target = "sonnet"
    tui._apply_variant_model_choice(state, "claude-worker-2")

    assert state.variant_model_overrides["sonnet"] == "claude-worker-2"
    assert state.variant_model_overrides["default"] == "claude-worker-2"
    assert state.message == "Worker model set to claude-worker-2. Next target: Haiku."


def test_variants_text_inputs_cover_credentials_and_models():
    state = tui.TuiState(mode="variants", variant_step=2, selected_index=0, variant_credential_env="Z_AI_API_KE")

    assert tui._handle_char_key(state, "Y") is True
    assert state.variant_credential_env == "Z_AI_API_KEY"
    assert tui._variant_backspace(state) is True
    assert state.variant_credential_env == "Z_AI_API_KE"

    state.variant_step = 4
    state.selected_index = 0
    assert tui._handle_char_key(state, "g") is True
    assert tui._handle_char_key(state, "l") is True
    assert state.variant_model_overrides["opus"] == "gl"


def test_ccrouter_variant_options_accept_managed_runtime_inputs():
    state = tui.TuiState(
        mode="variants",
        variant_step=2,
        variant_provider_index=0,
        variant_providers=[
            {
                "key": "ccrouter",
                "label": "CC Router",
                "description": "Router",
                "authMode": "authToken",
                "credentialEnv": "CCROUTER_AUTH_TOKEN",
                "credentialOptional": True,
                "authTokenFallback": "ccrouter-proxy",
                "baseUrl": "http://127.0.0.1:3456",
                "models": {},
                "defaultVariantName": "ccrouter",
            }
        ],
    )

    labels = [option.label for option in tui._variant_options(state)]

    assert "Managed CCR" in labels
    assert "Mode: managed" in labels
    assert any(label.startswith("Config source:") for label in labels)
    assert f"NPM package: {tui.CCR_PACKAGE_DEFAULT}" in labels
    assert "Port: auto" in labels
    assert "[x] Auto-start CCR" in labels

    package_index = [option.kind for option in tui._variant_options(state)].index("variant-ccrouter-package")
    state.selected_index = package_index
    state.variant_ccrouter_package = ""
    assert tui._handle_char_key(state, "x") is True
    assert state.variant_ccrouter_package == "x"
    assert tui._variant_backspace(state) is True
    assert state.variant_ccrouter_package == ""

    mode_index = [option.kind for option in tui._variant_options(state)].index("variant-ccrouter-mode")
    state.selected_index = mode_index
    tui._activate_variants(state)
    assert state.variant_ccrouter_mode == "external"


def test_run_variant_create_passes_ccrouter_options(monkeypatch, tmp_path):
    calls = []

    class Result:
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "ccrouter"

        class variant:
            variant_id = "ccrouter"

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    state = tui.TuiState(
        mode="create-preview",
        variant_name="ccrouter",
        variant_ccrouter_mode="managed",
        variant_ccrouter_config="empty",
        variant_ccrouter_package="@musistudio/claude-code-router@2.0.0",
        variant_ccrouter_port="4567",
        variant_ccrouter_autostart=False,
        variant_providers=[
            {
                "key": "ccrouter",
                "label": "CC Router",
                "description": "Router",
                "authMode": "authToken",
                "credentialEnv": "CCROUTER_AUTH_TOKEN",
                "credentialOptional": True,
                "authTokenFallback": "ccrouter-proxy",
                "baseUrl": "http://127.0.0.1:3456",
                "models": {},
                "defaultVariantName": "ccrouter",
            }
        ],
    )

    tui._run_variant_create(state)

    assert calls[0]["provider_key"] == "ccrouter"
    assert calls[0]["ccrouter_mode"] == "managed"
    assert calls[0]["ccrouter_config"] == "empty"
    assert calls[0]["ccrouter_package"] == "@musistudio/claude-code-router@2.0.0"
    assert calls[0]["ccrouter_port"] == "4567"
    assert calls[0]["ccrouter_autostart"] is False


def test_run_variant_create_passes_model_proxy_options(monkeypatch, tmp_path):
    calls = []

    class Result:
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "ccr-oauth"

        class variant:
            variant_id = "ccr-oauth"

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr(tui, "create_variant", fake_create_variant)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    state = tui.TuiState(
        mode="create-preview",
        variant_name="ccr-oauth",
        variant_model_proxy="architect",
        variant_model_proxy_port="4321",
        variant_providers=[
            {
                "key": "ccr-oauth",
                "label": "CCR OAuth Proxy",
                "description": "OAuth CCR",
                "authMode": "authToken",
                "credentialEnv": "CCROUTER_AUTH_TOKEN",
                "credentialOptional": True,
                "authTokenFallback": "ccrouter-proxy",
                "baseUrl": "http://127.0.0.1:3456",
                "models": {},
                "defaultVariantName": "ccr-oauth",
            }
        ],
    )

    tui._run_variant_create(state)

    assert calls[0]["provider_key"] == "ccr-oauth"
    assert calls[0]["model_proxy"] == "architect"
    assert calls[0]["model_proxy_port"] == "4321"
    assert calls[0]["ccrouter_mode"] == "managed"


def test_setup_manager_health_reports_doctor_failure(monkeypatch):
    class Variant:
        variant_id = "mirror"
        name = "Mirror"
        path = Path("/tmp/mirror")
        manifest = {
            "provider": {"key": "mirror"},
            "source": {"version": "2.1.123"},
            "paths": {"wrapper": "/tmp/mirror"},
            "tweaks": [],
        }

    def fail_doctor(name):
        raise RuntimeError("doctor broke")

    monkeypatch.setattr(tui, "doctor_variant", fail_doctor)
    state = tui.TuiState(mode="setup-manager", variants=[Variant()], selected_index=1)

    tui._handle_char_key(state, "h")

    assert state.message == "Health for setup mirror: broken"
    assert state.setup_health["mirror"]["status"] == "broken"


def test_setup_detail_opens_model_editor_and_applies_changes(monkeypatch, tmp_path):
    calls = []
    variant = _variant("lm-local", "LM Local")
    variant.manifest["provider"] = {"key": "lmstudio", "label": "LM Studio"}
    variant.manifest["modelOverrides"] = {"opus": "old-model", "sonnet": "old-model", "haiku": "old-model"}
    variant.manifest["env"] = {"ANTHROPIC_BASE_URL": "http://localhost:1234"}
    variant.manifest["paths"]["wrapper"] = str(tmp_path / "lm-local")
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "baseUrl": "http://localhost:1234",
        "models": {},
        "modelDiscovery": {"enabled": True},
        "requiresModelMapping": True,
    }

    def fake_update_models(variant_id, model_overrides, root=None):
        calls.append((variant_id, model_overrides))
        variant.manifest["modelOverrides"] = dict(model_overrides)
        return variant

    def fake_refresh(state_arg):
        state_arg.variants = [variant]
        return True

    monkeypatch.setattr(tui, "update_variant_models", fake_update_models)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="lm-local",
        variant_providers=[provider],
    )

    tui._handle_char_key(state, "m")

    assert state.mode == "models-edit"
    assert state.models_pending["opus"] == "old-model"
    assert "Edit models: lm-local" in tui._screen_text(state)

    state.selected_index = _option_index(tui._models_edit_options(state), "models-field", "opus")
    state.models_pending["opus"] = ""
    for char in "new-model":
        tui._handle_char_key(state, char)
    tui._apply_models(state)

    assert calls[0][0] == "lm-local"
    assert calls[0][1]["opus"] == "new-model"
    assert calls[0][1]["sonnet"] == "old-model"
    assert state.mode == "health-result"
    assert "Binary rebuilt: no" in "\n".join(state.last_action_summary)


def test_models_editor_refresh_applies_selected_model(monkeypatch):
    variant = _variant("lm-local", "LM Local")
    variant.manifest["provider"] = {"key": "lmstudio", "label": "LM Studio"}
    variant.manifest["modelOverrides"] = {}
    variant.manifest["env"] = {"ANTHROPIC_BASE_URL": "http://localhost:1234"}
    provider = {
        "key": "lmstudio",
        "label": "LM Studio",
        "baseUrl": "http://localhost:1234",
        "models": {},
        "modelDiscovery": {"enabled": True},
        "requiresModelMapping": True,
    }
    calls = []

    def fake_fetch(endpoint, api_key=None):
        calls.append((endpoint, api_key))
        return ["local/model-b", "local/model-a", "local/model-a"]

    monkeypatch.setattr(tui, "fetch_provider_models", fake_fetch)
    state = tui.TuiState(
        mode="models-edit",
        variants=[variant],
        selected_setup_id="lm-local",
        models_variant_id="lm-local",
        variant_providers=[provider],
    )

    state.selected_index = _option_index(tui._models_edit_options(state), "models-refresh")
    tui._activate_models_edit(state)

    assert calls == [("http://localhost:1234", None)]
    assert state.models_choices == ["local/model-a", "local/model-b"]
    assert state.selected_index == _option_index(tui._models_edit_options(state), "models-choice")

    tui._activate_models_edit(state)

    assert state.models_pending == {"opus": "local/model-a"}
    assert state.models_target == "sonnet"
    assert state.message == "Opus model set to local/model-a. Next target: Sonnet."


def test_models_editor_architect_mode_labels_and_worker_default_sync():
    variant = _variant("mirror", "Mirror", tweaks=["opusplan1m"])
    variant.manifest["provider"] = {"key": "mirror", "label": "Mirror Claude Code"}
    variant.manifest["modelOverrides"] = {
        "opus": "claude-planner",
        "sonnet": "claude-worker",
        "default": "claude-worker",
    }
    provider = {
        "key": "mirror",
        "label": "Mirror Claude Code",
        "models": {},
        "modelDiscovery": {},
        "requiresModelMapping": False,
    }
    state = tui.TuiState(
        mode="models-edit",
        variants=[variant],
        selected_setup_id="mirror",
        models_variant_id="mirror",
        models_pending=dict(variant.manifest["modelOverrides"]),
        variant_providers=[provider],
    )

    labels = [option.label for option in tui._models_edit_options(state)]

    assert any("Planner -> claude-planner" in label for label in labels)
    assert any("Worker -> claude-worker" in label for label in labels)
    assert any("Default worker -> claude-worker" in label for label in labels)

    state.models_target = "sonnet"
    tui._apply_models_choice(state, "claude-worker-2")

    assert state.models_pending["sonnet"] == "claude-worker-2"
    assert state.models_pending["default"] == "claude-worker-2"
    assert state.message == "Worker model set to claude-worker-2. Next target: Haiku."


def test_models_editor_search_filters_and_caps():
    variant = _variant("or-local", "OpenRouter Local")
    variant.manifest["provider"] = {"key": "openrouter", "label": "OpenRouter"}
    variant.manifest["modelOverrides"] = {}
    variant.manifest["env"] = {"ANTHROPIC_BASE_URL": "https://openrouter.ai/api"}
    provider = {
        "key": "openrouter",
        "label": "OpenRouter",
        "baseUrl": "https://openrouter.ai/api",
        "models": {},
        "modelDiscovery": {"enabled": True},
        "requiresModelMapping": True,
    }
    state = tui.TuiState(
        mode="models-edit",
        variants=[variant],
        selected_setup_id="or-local",
        models_variant_id="or-local",
        variant_providers=[provider],
        models_choices=[*(f"vendor/model-{index:02d}" for index in range(30)), "anthropic/claude-opus"],
    )

    options = tui._models_edit_options(state)
    assert len([option for option in options if option.kind == "models-choice"]) == 25
    assert any("Showing 25/31 matching models; keep typing to narrow." == option.label for option in options)

    state.selected_index = _option_index(options, "models-refresh")
    assert tui._handle_char_key(state, "/") is True
    assert state.models_search_active is True
    for char in "claude":
        assert tui._handle_char_key(state, char) is True

    options = tui._models_edit_options(state)
    assert [option.value for option in options if option.kind == "models-choice"] == ["anthropic/claude-opus"]
    assert "Search: claude (typing)" in tui._screen_text(state, height=40)

    assert tui._handle_backspace_key(state) is True
    assert state.models_search_text == "claud"
    assert tui._activate(state) is True
    assert state.models_search_active is False
    assert state.message == "Model search kept: claud"

    state.models_search_text = "missing"
    assert "No models match current search." in tui._screen_text(state, height=40)


def test_models_editor_skip_focuses_manual_field_and_preserves_slash_typing():
    variant = _variant("or-local", "OpenRouter Local")
    variant.manifest["provider"] = {"key": "openrouter", "label": "OpenRouter"}
    variant.manifest["modelOverrides"] = {}
    variant.manifest["env"] = {"ANTHROPIC_BASE_URL": "https://openrouter.ai/api"}
    provider = {
        "key": "openrouter",
        "label": "OpenRouter",
        "baseUrl": "https://openrouter.ai/api",
        "models": {},
        "modelDiscovery": {"enabled": True},
        "requiresModelMapping": True,
    }
    state = tui.TuiState(
        mode="models-edit",
        variants=[variant],
        selected_setup_id="or-local",
        models_variant_id="or-local",
        variant_providers=[provider],
        models_choices=["anthropic/claude-opus"],
    )

    state.selected_index = _option_index(tui._models_edit_options(state), "models-skip")
    tui._activate_models_edit(state)

    assert state.models_choices == []
    assert state.models_search_text == ""
    assert tui._selected_models_edit_option(state).kind == "models-field"
    assert tui._selected_models_edit_option(state).value == "opus"
    assert "variant.json modelOverrides" in state.message

    for char in "anthropic/claude-opus":
        assert tui._handle_char_key(state, char) is True

    assert state.models_pending["opus"] == "anthropic/claude-opus"
    assert state.models_search_active is False


# -- Tweaks tab tests ----------------------------------------------------------

def _variant(variant_id="my-variant", name="My Variant", tweaks=None, version="2.1.123"):
    from ccsilo.variants.model import Variant
    tweaks = list(tweaks or [])
    return Variant(
        variant_id=variant_id,
        name=name,
        path=Path(f"/tmp/{variant_id}"),
        manifest={
            "schemaVersion": 1,
            "id": variant_id,
            "name": name,
            "provider": {"key": "kimi", "label": "Kimi"},
            "source": {"version": version, "platform": "darwin-arm64", "sha256": "x", "path": "/tmp/x"},
            "paths": {"wrapper": f"/tmp/bin/{variant_id}"},
            "tweaks": tweaks,
            "runtime": "native",
        },
    )


def test_startup_routes_to_first_run_or_setup_manager():
    empty = tui.TuiState(mode="loading")
    tui._route_startup(empty)
    assert empty.mode == "first-run-setup"
    assert "No Claude Code setups found" in empty.message

    variant = _variant("deepseek-main")
    existing = tui.TuiState(mode="loading", variants=[variant])
    tui._route_startup(existing)
    assert existing.mode == "setup-manager"
    assert existing.selected_setup_id == "deepseek-main"


def test_setup_manager_lists_rows_and_opens_detail():
    variant = _variant("deepseek-main")
    state = tui.TuiState(
        mode="setup-manager",
        variants=[variant],
        setup_health={"deepseek-main": {"status": "healthy"}},
        selected_index=1,
    )

    screen = tui._screen_text(state)
    assert "Setup manager" in screen
    assert "Name" in screen
    assert "Provider" in screen
    assert "Health" in screen
    assert "deepseek-main" in screen
    assert "healthy" in screen
    assert "deepseek-main" in screen

    tui._activate_setup_manager(state)
    assert state.mode == "setup-detail"
    assert state.selected_setup_id == "deepseek-main"


def test_setup_detail_run_action_queues_command(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    wrapper = root / "bin" / "deepseek-main"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    variant = _variant("deepseek-main")
    variant.manifest["paths"]["wrapper"] = str(tmp_path / "tampered-wrapper")
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
    )

    options = tui.options.setup_detail_options(state)
    assert options[0].kind == "setup-action-run"
    assert "Run Claude" in tui._screen_text(state)

    tui._activate_setup_detail(state)

    assert state.pending_run_setup_id == "deepseek-main"
    assert state.pending_run_command == [str(wrapper)]
    assert state.message == "Running setup deepseek-main after setup manager exits."


def test_setup_detail_exposes_edit_and_add_tweaks_actions():
    state = tui.TuiState(
        mode="setup-detail",
        variants=[_variant("deepseek-main")],
        selected_setup_id="deepseek-main",
    )

    labels = [option.label for option in tui.options.setup_detail_options(state)]

    assert "Edit tweaks" in labels
    assert "Add tweaks" in labels


def test_setup_detail_shows_new_claude_code_version():
    variant = _variant("deepseek-main", version="2.1.122")
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={"binary": {"latest": "2.1.123"}},
    )

    labels = [option.label for option in tui.options.setup_detail_options(state)]

    assert "Upgrade Claude Code (2.1.122 -> 2.1.123)" in labels


def test_setup_detail_uses_highest_listed_version_when_latest_marker_lags():
    variant = _variant("deepseek-main", version="2.1.175")
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={
            "binary": {
                "latest": "2.1.175",
                "versions": [{"version": "2.1.176"}, {"version": "2.1.175"}],
            },
        },
        download_versions=["2.1.176", "2.1.175"],
    )

    labels = [option.label for option in tui.options.setup_detail_options(state)]

    assert "Upgrade Claude Code (2.1.175 -> 2.1.176)" in labels


def test_setup_detail_shows_when_claude_code_is_current():
    variant = _variant("deepseek-main", version="2.1.123")
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={"binary": {"latest": "2.1.123"}},
    )

    labels = [option.label for option in tui.options.setup_detail_options(state)]

    assert "Upgrade Claude Code (up to date: 2.1.123)" in labels


def test_setup_detail_edit_tweaks_keeps_current_view():
    variant = _variant("deepseek-main", tweaks=["themes"])
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
        tweak_filter="recommended",
    )
    options = tui.options.setup_detail_options(state)
    state.selected_index = [option.kind for option in options].index("setup-action-tweaks")

    tui._activate_setup_detail(state)

    assert state.mode == "tweak-editor"
    assert state.tweaks_variant_id == "deepseek-main"
    assert state.tweaks_baseline == ("themes",)
    assert state.tweaks_pending == ["themes"]
    assert state.tweak_filter == "recommended"


def test_setup_detail_add_tweaks_opens_all_view():
    variant = _variant("deepseek-main", tweaks=["themes"])
    state = tui.TuiState(
        mode="setup-detail",
        variants=[variant],
        selected_setup_id="deepseek-main",
        selected_index=3,
        tweak_filter="recommended",
    )
    options = tui.options.setup_detail_options(state)
    state.selected_index = [option.kind for option in options].index("setup-action-add-tweaks")

    tui._activate_setup_detail(state)

    assert state.mode == "tweak-editor"
    assert state.selected_setup_id == "deepseek-main"
    assert state.tweaks_variant_id == "deepseek-main"
    assert state.tweaks_baseline == ("themes",)
    assert state.tweaks_pending == ["themes"]
    assert state.tweak_filter == "all"
    assert state.selected_index == 0
    assert state.message == "Showing all available tweaks for this setup."


def test_setup_detail_exposes_managed_ccrouter_actions(monkeypatch):
    calls = []

    class CcrResult:
        command = ["ccr", "status"]
        returncode = 0
        stdout = "Status: Running\n"
        stderr = ""

    def fake_run_ccrouter_command(manifest, args):
        calls.append((manifest, args))
        return CcrResult()

    monkeypatch.setattr(tui, "run_ccrouter_command", fake_run_ccrouter_command)
    variant = _variant("ccrouter")
    variant.manifest["provider"]["key"] = "ccrouter"
    variant.manifest["ccrouter"] = {
        "mode": "managed",
        "homeDir": "/tmp/ccrouter-home",
        "runtimeDir": "/tmp/ccrouter-runtime",
        "configPath": "/tmp/ccrouter-home/.claude-code-router/config.json",
        "packageSpec": tui.CCR_PACKAGE_DEFAULT,
        "installedVersion": "2.0.0",
        "configMode": "empty",
        "autoStart": True,
        "port": 4567,
    }
    state = tui.TuiState(mode="setup-detail", variants=[variant], selected_setup_id="ccrouter")

    labels = [option.label for option in tui.options.setup_detail_options(state)]
    assert "CCR status" in labels
    assert "Start CCR" in labels
    assert "Copy CCR config path" in labels
    assert "CCR config: /tmp/ccrouter-home/.claude-code-router/config.json" in tui._screen_text(state)

    state.selected_index = [option.kind for option in tui.options.setup_detail_options(state)].index("setup-action-ccrouter-status")
    tui._activate_setup_detail(state)

    assert calls[0][1] == ["status"]
    assert state.mode == "health-result"
    assert "Status: Running" in "\n".join(state.last_action_summary)


def test_setup_detail_explains_model_proxy_account_requirement():
    variant = _variant("architect-proxy")
    variant.manifest["modelProxy"] = {
        "mode": "architect",
        "backendUrl": "https://example.test/anthropic",
        "backendAuth": "x-api-key",
        "credentialEnv": "EXAMPLE_API_KEY",
        "port": "auto",
    }
    state = tui.TuiState(mode="setup-detail", variants=[variant], selected_setup_id="architect-proxy")

    screen = tui._screen_text(state)

    assert "Model proxy: OAuth architect proxy" in screen
    assert "Requires Claude Code account/login" in screen
    assert "claude-* requests use Claude Code OAuth/session" in screen
    assert "non-Claude model aliases use the provider backend" in screen
    assert "Model proxy backend: https://example.test/anthropic" in screen


def test_setup_manager_run_shortcut_requires_row_then_queues(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    wrapper = root / "bin" / "deepseek-main"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    variant = _variant("deepseek-main")
    variant.manifest["paths"]["wrapper"] = str(tmp_path / "tampered-wrapper")
    state = tui.TuiState(mode="setup-manager", variants=[variant], selected_index=0)

    assert tui._handle_char_key(state, "x") is True
    assert state.pending_run_command == []
    assert state.message == "Select a setup first."

    state.selected_index = 1
    assert tui._handle_char_key(state, "x") is False
    assert state.pending_run_setup_id == "deepseek-main"
    assert state.pending_run_command == [str(wrapper)]


def test_run_pending_setup_executes_wrapper(tmp_path):
    output = tmp_path / "ran.txt"
    wrapper = tmp_path / "deepseek-main"
    wrapper.write_text(f"#!/bin/sh\necho ran > {shlex.quote(str(output))}\n", encoding="utf-8")
    wrapper.chmod(0o755)
    state = tui.TuiState(
        pending_run_setup_id="deepseek-main",
        pending_run_command=[str(wrapper)],
    )

    assert tui._run_pending_setup(state) == 0
    assert output.read_text(encoding="utf-8") == "ran\n"


def test_clear_terminal_for_external_command_writes_clear_when_tty(monkeypatch):
    stdout = _FakeStdout(tty=True)
    monkeypatch.setattr(tui.sys, "stdout", stdout)

    tui._clear_terminal_for_external_command()

    assert stdout.writes == ["\033[2J\033[H"]
    assert stdout.flushed is True


def test_run_pending_setup_clears_before_wrapper(monkeypatch, tmp_path):
    wrapper = tmp_path / "deepseek-main"
    state = tui.TuiState(
        pending_run_setup_id="deepseek-main",
        pending_run_command=[str(wrapper)],
    )
    calls = []

    def fake_clear():
        calls.append("clear")

    def fake_run(command, check=False):
        calls.append(("run", command, check))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(tui, "_clear_terminal_for_external_command", fake_clear)
    monkeypatch.setattr(tui.subprocess, "run", fake_run)

    assert tui._run_pending_setup(state) == 0

    assert calls == ["clear", ("run", [str(wrapper)], False)]


def test_setup_manager_search_filters_rows_and_keeps_create_action():
    deepseek = _variant("deepseek-main")
    openrouter = _variant("openrouter-dev")
    openrouter.manifest["provider"]["key"] = "openrouter"
    state = tui.TuiState(
        mode="setup-manager",
        variants=[deepseek, openrouter],
        setup_search_text="openrouter",
    )

    options = tui.options.setup_manager_options(state)

    assert options[0].kind == "setup-action-new"
    assert [option.value for option in options if option.kind == "setup-row"] == ["openrouter-dev"]
    screen = tui._screen_text(state)
    assert "Search: openrouter" in screen
    assert "deepseek-main" not in screen

    state.setup_search_text = "missing"
    options = tui.options.setup_manager_options(state)
    assert [option.kind for option in options] == ["setup-action-new"]
    assert "No setups match current search/filter." in tui._screen_text(state)


def test_setup_manager_search_input_does_not_trigger_global_hotkeys(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    state = tui.TuiState(mode="setup-manager", variants=[_variant("deepseek-main")])

    assert tui._handle_char_key(state, "/") is True
    assert state.setup_search_active is True
    assert tui._handle_char_key(state, "q") is True

    assert state.setup_search_text == "q"
    assert state.setup_search_active is True
    assert load_tui_settings(root)["setupList"]["searchText"] == "q"

    assert tui._activate(state) is True
    assert state.setup_search_active is False
    assert state.mode == "setup-manager"


def test_ctrl_c_requests_quit():
    state = tui.TuiState(mode="setup-manager")

    assert tui._handle_char_key(state, "\x03") is False
    assert tui._event_requests_quit({"kind": "key", "code": 0, "ch": 3}, 0) is True
    assert tui._event_requests_quit({"kind": "key", "code": 0, "ch": "c", "mods": ["CONTROL"]}, 0) is True
    assert tui._event_requests_quit({"kind": "key", "key": "ctrl-c"}, 0) is True
    assert tui._event_requests_quit({"kind": "key", "code": 0, "ch": "c"}, 0) is False


def test_setup_manager_loads_and_saves_setup_list_preferences(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    save_tui_settings({
        "themeId": "dark",
        "setupList": {
            "searchText": "openrouter",
            "providerFilter": "openrouter",
            "sortKey": "version",
        },
    }, root=root)
    state = tui.TuiState(theme_id=tui._load_saved_theme_id())

    tui._load_saved_setup_list_preferences(state)

    assert state.theme_id == "dark"
    assert state.setup_search_text == "openrouter"
    assert state.setup_provider_filter == "openrouter"
    assert state.setup_sort_key == "version"

    deepseek = _variant("deepseek-main")
    deepseek.manifest["provider"]["key"] = "deepseek"
    openrouter = _variant("openrouter-dev")
    openrouter.manifest["provider"]["key"] = "openrouter"
    state.mode = "setup-manager"
    state.variants = [deepseek, openrouter]
    state.setup_search_text = ""
    state.setup_provider_filter = "all"
    tui._handle_char_key(state, "p")
    tui._handle_char_key(state, "s")

    saved = load_tui_settings(root)
    assert saved["themeId"] == "dark"
    assert saved["setupList"]["providerFilter"] == "deepseek"
    assert saved["setupList"]["sortKey"] == "name"


def test_setup_manager_provider_filter_cycles_and_refresh_resets(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    from ccsilo.tui import state as state_module

    deepseek = _variant("deepseek-main")
    deepseek.manifest["provider"]["key"] = "deepseek"
    openrouter = _variant("openrouter-dev")
    openrouter.manifest["provider"]["key"] = "openrouter"
    state = tui.TuiState(mode="setup-manager", variants=[deepseek, openrouter])

    tui._handle_char_key(state, "p")
    assert state.setup_provider_filter == "deepseek"
    tui._handle_char_key(state, "p")
    assert state.setup_provider_filter == "openrouter"

    monkeypatch.setattr(state_module, "scan_native_downloads", lambda: [])
    monkeypatch.setattr(state_module, "scan_npm_downloads", lambda: [])
    monkeypatch.setattr(state_module, "scan_extractions", lambda: [])
    monkeypatch.setattr(state_module, "scan_patch_packages", lambda: [])
    monkeypatch.setattr(state_module, "scan_patch_profiles", lambda: [])
    monkeypatch.setattr(state_module, "scan_dashboard_tweak_profiles", lambda: [])
    monkeypatch.setattr(state_module, "scan_variants", lambda: [deepseek])
    monkeypatch.setattr(state_module, "list_variant_providers", lambda: [])
    monkeypatch.setattr(state_module, "load_download_index", lambda: {})
    monkeypatch.setattr(state_module, "download_versions", lambda index, kind: [])

    state.refresh()

    assert state.setup_provider_filter == "all"


def test_setup_manager_sort_orders_rows():
    alpha = _variant("alpha", version="2.1.121")
    alpha.manifest["provider"]["key"] = "zai"
    alpha.manifest["updatedAt"] = "2026-01-03T00:00:00Z"
    beta = _variant("beta", version="2.1.123")
    beta.manifest["provider"]["key"] = "deepseek"
    beta.manifest["updatedAt"] = "2026-01-01T00:00:00Z"
    gamma = _variant("gamma", version="2.1.122")
    gamma.manifest["provider"]["key"] = "openrouter"
    gamma.manifest["updatedAt"] = "2026-01-02T00:00:00Z"
    state = tui.TuiState(
        mode="setup-manager",
        variants=[gamma, beta, alpha],
        setup_health={
            "alpha": {"status": "healthy"},
            "beta": {"status": "broken"},
            "gamma": {"status": "never"},
        },
    )

    def rows():
        return [
            option.value for option in tui.options.setup_manager_options(state)
            if option.kind == "setup-row"
        ]

    assert tui.options.setup_manager_options(state)[0].kind == "setup-action-new"
    state.setup_sort_key = "name"
    assert rows() == ["alpha", "beta", "gamma"]
    state.setup_sort_key = "provider"
    assert rows() == ["beta", "gamma", "alpha"]
    state.setup_sort_key = "health"
    assert rows() == ["beta", "gamma", "alpha"]
    state.setup_sort_key = "updated"
    assert rows() == ["beta", "gamma", "alpha"]
    state.setup_sort_key = "version"
    assert rows() == ["alpha", "gamma", "beta"]


def test_setup_detail_copies_command_and_logs(monkeypatch):
    copied = []
    variant = _variant("deepseek-main")
    state = tui.TuiState(mode="setup-detail", variants=[variant], selected_setup_id="deepseek-main")

    monkeypatch.setattr(tui, "_copy_text_to_clipboard", copied.append)

    tui._handle_char_key(state, "c")

    assert copied == ["/tmp/bin/deepseek-main"]
    assert state.message == "Copied command path for setup deepseek-main."
    assert state.last_action_log == ["Copied command path: /tmp/bin/deepseek-main"]

    tui._handle_char_key(state, "l")
    assert state.mode == "logs"
    assert "Copied command path: /tmp/bin/deepseek-main" in tui._screen_text(state)


def test_help_panel_opens_and_returns_to_context():
    state = tui.TuiState(mode="setup-manager", variants=[_variant("deepseek-main")])

    assert tui._handle_char_key(state, "?") is True

    assert state.mode == "help"
    screen = tui._screen_text(state, height=80)
    assert "Shortcuts" in screen
    assert "Q or Ctrl+C: quit" in screen
    assert "/: search setups" in screen
    assert "C: copy log text" in screen
    assert "Dashboard" in screen
    assert "Space: toggle selected tweak" in screen

    tui._go_back(state)

    assert state.mode == "setup-manager"


def test_setup_detail_copies_config_and_log_text(monkeypatch):
    copied = []
    variant = _variant("deepseek-main")
    state = tui.TuiState(mode="setup-detail", variants=[variant], selected_setup_id="deepseek-main")

    monkeypatch.setattr(tui, "_copy_text_to_clipboard", copied.append)

    tui._handle_char_key(state, "g")
    assert copied == ["/tmp/deepseek-main/variant.json"]
    assert state.message == "Copied setup config path for setup deepseek-main."

    state.mode = "logs"
    state.last_action_log = ["line one", "line two"]
    tui._handle_char_key(state, "c")

    assert copied[-1] == "line one\nline two"
    assert state.message == "Copied log text."


def test_upgrade_preview_applies_update_and_health(monkeypatch, tmp_path):
    variant = _variant("deepseek-main", version="2.1.122")
    calls = []

    class Result:
        wrapper_path = tmp_path / "cc-deepseek"

    def fake_update(name, *, claude_version=None):
        calls.append((name, claude_version))
        return [Result()]

    def fake_refresh(state_arg):
        variant.manifest["source"]["version"] = "2.1.123"
        state_arg.variants = [variant]
        return True

    def fake_doctor(name):
        return [{"id": name, "ok": True, "checks": [{"name": "wrapper", "ok": True, "path": "/tmp/bin/deepseek-main"}]}]

    monkeypatch.setattr(tui, "update_variants", fake_update)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    monkeypatch.setattr(tui, "doctor_variant", fake_doctor)
    state = tui.TuiState(mode="upgrade-preview", variants=[variant], selected_setup_id="deepseek-main")

    tui._run_setup_upgrade(state)

    assert calls == [("deepseek-main", "latest")]
    assert state.mode == "health-result"
    assert "2.1.122 -> 2.1.123" in "\n".join(state.last_action_summary)
    assert "Patches/tweaks reapplied: yes" in "\n".join(state.last_action_summary)
    assert "Health: healthy" in "\n".join(state.last_action_summary)


def test_upgrade_preview_uses_highest_listed_version_when_latest_marker_lags(monkeypatch, tmp_path):
    variant = _variant("deepseek-main", version="2.1.175")
    calls = []

    class Result:
        wrapper_path = tmp_path / "cc-deepseek"

    def fake_update(name, *, claude_version=None):
        calls.append((name, claude_version))
        return [Result()]

    def fake_refresh(state_arg):
        variant.manifest["source"]["version"] = "2.1.176"
        state_arg.variants = [variant]
        return True

    monkeypatch.setattr(tui, "update_variants", fake_update)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    state = tui.TuiState(
        mode="upgrade-preview",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={
            "binary": {
                "latest": "2.1.175",
                "versions": [{"version": "2.1.176"}, {"version": "2.1.175"}],
            },
        },
        download_versions=["2.1.176", "2.1.175"],
    )

    tui._run_setup_upgrade(state)

    assert calls == [("deepseek-main", "2.1.176")]
    assert state.mode == "health-result"
    assert "2.1.175 -> 2.1.176" in "\n".join(state.last_action_summary)


def test_upgrade_preview_shows_latest_status_and_patch_reapply():
    from ccsilo.tui.render_labels_modes import upgrade_preview_labels

    variant = _variant("deepseek-main", tweaks=["themes"], version="2.1.122")
    variant.manifest["patches"] = [{"id": "replace-before", "version": "0.1.0"}]
    state = tui.TuiState(
        mode="upgrade-preview",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={"binary": {"latest": "2.1.123"}},
    )

    labels = upgrade_preview_labels(state)

    assert "Latest available: 2.1.123" in labels
    assert "Update available: yes" in labels
    assert "Target Claude Code: latest (2.1.123)" in labels
    assert "Tweak count: 1" in labels
    assert "Patch package refs: 1" in labels
    assert "Reapply patches/tweaks: yes" in labels


def test_upgrade_preview_y_enters_busy_then_finishes(monkeypatch, tmp_path):
    variant = _variant("deepseek-main", version="2.1.122")
    calls = []

    class Result:
        wrapper_path = tmp_path / "cc-deepseek"

    def fake_update(name, *, claude_version=None):
        calls.append((name, claude_version))
        return [Result()]

    def fake_refresh(state_arg):
        variant.manifest["source"]["version"] = "2.1.123"
        state_arg.variants = [variant]
        return True

    monkeypatch.setattr(tui, "update_variants", fake_update)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    state = tui.TuiState(mode="upgrade-preview", variants=[variant], selected_setup_id="deepseek-main")

    assert tui._handle_char_key(state, "y") is True
    assert state.mode == "busy"
    assert "Upgrading setup" in tui._screen_text(state)

    _finish_busy(state)

    assert calls == [("deepseek-main", "latest")]
    assert state.mode == "health-result"
    assert "Health: healthy" in "\n".join(state.last_action_summary)


def test_upgrade_failure_summary_reports_verified_state(monkeypatch, tmp_path):
    from ccsilo.variants.model import VariantBuildError, VariantBuildStage

    variant = _variant("deepseek-main", version="2.1.122")
    variant.path = tmp_path / "deepseek-main"
    variant.path.mkdir()
    wrapper = tmp_path / "cc-deepseek"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    binary = tmp_path / "claude"
    binary.write_text("binary\n", encoding="utf-8")
    (variant.path / "variant.json").write_text("{}", encoding="utf-8")
    variant.manifest["paths"]["wrapper"] = str(wrapper)
    variant.manifest["paths"]["binary"] = str(binary)
    target_artifact = NativeArtifact(
        version="2.1.123",
        platform="darwin-arm64",
        sha256="b" * 64,
        path=tmp_path / "downloaded-claude",
        metadata={},
    )

    def fake_update(name, *, claude_version=None):
        assert name == "deepseek-main"
        assert claude_version == "2.1.123"
        stages = [
            VariantBuildStage("prepare directories", "ok", "/tmp/deepseek-main"),
            VariantBuildStage("patch binary", "failed", "anchor missing"),
        ]
        raise VariantBuildError("deepseek-main", "patch binary", RuntimeError("patch stage broke"), stages)

    def fake_refresh(state_arg):
        state_arg.variants = [variant]
        state_arg.native_artifacts = [target_artifact]
        return True

    monkeypatch.setattr(tui, "update_variants", fake_update)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    monkeypatch.setattr(tui, "load_variant", lambda name: variant)
    state = tui.TuiState(
        mode="upgrade-preview",
        variants=[variant],
        selected_setup_id="deepseek-main",
        download_index={"binary": {"latest": "2.1.123"}},
    )

    tui._run_setup_upgrade(state)

    summary = "\n".join(state.last_action_summary)
    assert state.mode == "health-result"
    assert "Upgrade failed: deepseek-main" in summary
    assert "Base download succeeded: verified" in summary
    assert "Command replaced: no" in summary
    assert "Previous setup remains active: yes" in summary
    assert "Failed stage: update/rebuild: patch binary failed for deepseek-main: patch stage broke" in summary
    assert "Backend stages:" in summary
    assert "patch binary: failed (anchor missing)" in summary
    assert "rollback" not in summary.lower()


def test_delete_requires_typed_setup_id(monkeypatch, tmp_path):
    variant = _variant("deepseek-main")
    variant.path = tmp_path / "deepseek-main"
    variant.path.mkdir()
    wrapper = tmp_path / "cc-deepseek"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    installed = tmp_path / "install-bin" / "deepseek-main"
    installed.parent.mkdir()
    installed.write_text("#!/bin/sh\n", encoding="utf-8")
    variant.manifest["paths"]["wrapper"] = str(wrapper)
    variant.manifest["installs"] = [
        {
            "managedBy": "ccsilo",
            "alias": "deepseek-main",
            "path": str(installed),
            "target": str(wrapper),
            "createdAt": "2026-01-01T00:00:00Z",
        }
    ]
    calls = []

    def fake_remove(name, *, yes=False):
        calls.append((name, yes))
        wrapper.unlink()
        installed.unlink()
        variant.path.rmdir()
        return True

    def fake_refresh(state_arg):
        state_arg.variants = []
        return True

    monkeypatch.setattr(tui, "remove_variant", fake_remove)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    state = tui.TuiState(
        mode="delete-confirm",
        variants=[variant],
        selected_setup_id="deepseek-main",
        delete_confirm_text="wrong",
    )

    tui._run_setup_delete(state)
    assert calls == []
    assert "exactly" in state.message

    state.delete_confirm_text = "deepseek-main"
    tui._run_setup_delete(state)
    assert calls == [("deepseek-main", True)]
    assert state.mode == "setup-manager"
    assert "Shared downloads untouched: yes" in "\n".join(state.last_action_summary)
    assert "Installed commands removed: yes" in "\n".join(state.last_action_summary)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_delete_removes_unrecorded_setup_command_symlink(monkeypatch, tmp_path):
    root = tmp_path / ".ccsilo"
    home = tmp_path / "home"
    setup_dir = root / "variants" / "zai"
    wrapper = root / "bin" / "zai"
    install_dir = home / ".local" / "bin"
    setup_dir.mkdir(parents=True)
    wrapper.parent.mkdir(parents=True)
    install_dir.mkdir(parents=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    installed = install_dir / "zai"
    os.symlink(wrapper, installed)
    manifest = {
        "schemaVersion": 1,
        "id": "zai",
        "name": "zai",
        "provider": {"key": "zai"},
        "source": {"version": "1.2.3"},
        "paths": {"wrapper": str(wrapper)},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    (setup_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    monkeypatch.setenv("HOME", str(home))
    variant = tui.load_variant("zai")

    def fake_refresh(state_arg):
        state_arg.variants = []
        return True

    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    state = tui.TuiState(
        mode="delete-confirm",
        variants=[variant],
        selected_setup_id="zai",
        delete_confirm_text="zai",
    )

    tui._run_setup_delete(state)

    summary = "\n".join(state.last_action_summary)
    assert state.mode == "setup-manager"
    assert not setup_dir.exists()
    assert not wrapper.exists()
    assert not installed.exists()
    assert not installed.is_symlink()
    assert "Installed commands removed: yes" in summary


def test_delete_failure_summary_uses_failure_wording(monkeypatch, tmp_path):
    variant = _variant("deepseek-main")
    variant.path = tmp_path / "deepseek-main"
    variant.path.mkdir()
    wrapper = tmp_path / "cc-deepseek"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    variant.manifest["paths"]["wrapper"] = str(wrapper)

    def fake_remove(name, *, yes=False):
        assert name == "deepseek-main"
        assert yes is True
        raise RuntimeError("permission denied")

    def fake_refresh(state_arg):
        state_arg.variants = [variant]
        return True

    monkeypatch.setattr(tui, "remove_variant", fake_remove)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)
    state = tui.TuiState(
        mode="delete-confirm",
        variants=[variant],
        selected_setup_id="deepseek-main",
        delete_confirm_text="deepseek-main",
    )

    tui._run_setup_delete(state)

    summary = "\n".join(state.last_action_summary)
    assert state.mode == "setup-manager"
    assert "Delete failed: deepseek-main" in summary
    assert "Setup directory removed: no" in summary
    assert "Command removed: no" in summary
    assert "Shared downloads untouched: yes" in summary
    assert state.selected_setup_id == "deepseek-main"


def test_tweak_apply_uses_preview_then_post_health(monkeypatch):
    variant = _variant("deepseek-main", tweaks=["themes"])
    state = tui.TuiState(
        mode="tweak-editor",
        variants=[variant],
        selected_setup_id="deepseek-main",
        tweaks_variant_id="deepseek-main",
        tweaks_baseline=("themes",),
        tweaks_pending=["themes", "patches-applied-indication"],
    )

    tui._begin_tweak_apply_preview(state)
    assert state.tweak_apply_preview is True
    assert "Tweak rebuild preview" in tui._screen_text(state)

    def fake_apply(app_state):
        app_state.tweaks_baseline = tuple(app_state.tweaks_pending)
        app_state.message = "Applied tweaks to setup deepseek-main (+1 added, -0 removed)."

    def fake_doctor(name):
        return [{"id": name, "ok": True, "checks": []}]

    monkeypatch.setattr(tui, "_apply_tweaks", fake_apply)
    monkeypatch.setattr(tui, "doctor_variant", fake_doctor)

    tui._run_tweak_apply(state)

    assert state.mode == "health-result"
    assert state.last_tweak_result == {
        "added": ["patches-applied-indication"],
        "removed": [],
        "health": "healthy",
    }


def test_tweak_apply_y_enters_busy_then_finishes(monkeypatch):
    variant = _variant("deepseek-main", tweaks=["themes"])
    state = tui.TuiState(
        mode="tweak-editor",
        variants=[variant],
        selected_setup_id="deepseek-main",
        tweaks_variant_id="deepseek-main",
        tweaks_baseline=("themes",),
        tweaks_pending=["themes", "patches-applied-indication"],
    )
    tui._begin_tweak_apply_preview(state)

    def fake_apply(app_state):
        app_state.tweaks_baseline = tuple(app_state.tweaks_pending)
        app_state.message = "Applied tweaks to setup deepseek-main (+1 added, -0 removed)."

    monkeypatch.setattr(tui, "_apply_tweaks", fake_apply)
    monkeypatch.setattr(tui, "doctor_variant", lambda name: [{"id": name, "ok": True, "checks": []}])
    monkeypatch.setattr(tui, "_refresh_state", lambda state_arg: True)

    assert tui._handle_char_key(state, "y") is True
    assert state.mode == "busy"
    assert "Rebuilding tweaks" in tui._screen_text(state)

    _finish_busy(state)

    assert state.mode == "health-result"
    assert state.last_tweak_result == {
        "added": ["patches-applied-indication"],
        "removed": [],
        "health": "healthy",
    }


def test_tweaks_tab_initial_state():
    state = tui.TuiState(mode="tweaks-source", variants=[_variant()])
    title, labels = tui.rendering.current_labels(state)
    assert title.startswith("Tweaks: pick setup")
    assert any("my-variant" in label for label in labels)


def test_tweaks_editor_footer_advertises_view_switching():
    state = tui.TuiState(mode="tweak-editor")
    footer = tui._footer_text(state)

    assert "V view" in footer


def test_tweaks_select_variant_enters_edit_mode():
    variant = _variant(tweaks=["themes", "hide-startup-banner"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])

    tui._activate(state)

    assert state.mode == "tweak-editor"
    assert state.tweaks_variant_id == variant.variant_id
    assert state.tweaks_baseline == ("themes", "hide-startup-banner")
    assert state.tweaks_pending == ["themes", "hide-startup-banner"]


def test_tweaks_search_filters_and_keeps_filter_on_enter_and_escape():
    variant = _variant(tweaks=["themes", "hide-startup-banner"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)

    assert tui._handle_char_key(state, "/") is True
    assert state.tweak_search_active is True
    for char in "startup-banner":
        assert tui._handle_char_key(state, char) is True

    options = tui.options.tweaks_edit_options(state)
    assert [option.value for option in options] == ["hide-startup-banner"]
    screen = tui._screen_text(state)
    assert "Search: startup-banner (typing)" in screen

    assert tui._handle_backspace_key(state) is True
    assert state.tweak_search == "startup-banne"
    assert tui._activate(state) is True
    assert state.tweak_search_active is False
    assert "Tweak search kept: startup-banne" == state.message

    tui._handle_char_key(state, "/")
    tui._go_back(state)
    assert state.tweak_search_active is False
    assert state.tweak_search == "startup-banne"


def test_tweaks_search_no_results_message():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)
    state.tweak_search = "no-such-tweak"

    assert tui.options.tweaks_edit_options(state) == []
    assert "No tweaks match current search/filter." in tui._screen_text(state)


def test_tweaks_editor_advanced_view_uses_curated_tweaks_and_env_backed():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant], tweak_filter="advanced")
    tui._activate(state)

    values = [option.value for option in tui.options.tweaks_edit_options(state)]

    assert "agents-md" in values
    assert "session-memory" in values
    assert "opusplan1m" in values
    assert "mcp-non-blocking" not in values
    assert "mcp-batch-size" not in values
    assert "rtk-shell-prefix" not in values
    assert "token-count-rounding" in values
    assert "statusline-update-throttle" in values
    assert "yet-another-statusline" in values
    assert "context-limit" in values
    assert "file-read-limit" in values
    assert "subagent-model" in values
    assert "disable-telemetry" in values
    assert "disable-prompt-caching" in values


def test_tweaks_editor_env_backed_detail_and_toggle():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant], tweak_filter="advanced")
    tui._activate(state)
    state.tweak_search = "context-limit"

    options = tui.options.tweaks_edit_options(state)
    assert [option.value for option in options] == ["context-limit"]

    text = tui._screen_text(state, height=40)
    assert "Context limit" in text
    assert "Group: environment" in text
    assert "Status: env-backed" in text
    assert "CLAUDE_CODE_CONTEXT_LIMIT" in text

    tui._toggle_tweak(state)
    assert "context-limit" in state.tweaks_pending


def test_tweaks_editor_boolean_env_detail_and_toggle():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant], tweak_filter="advanced")
    tui._activate(state)
    state.tweak_search = "disable-telemetry"

    options = tui.options.tweaks_edit_options(state)
    assert [option.value for option in options] == ["disable-telemetry"]

    text = tui._screen_text(state, height=40)
    assert "Disable telemetry" in text
    assert "DISABLE_TELEMETRY=1" in text
    assert "Status: env-backed" in text

    tui._toggle_tweak(state)
    assert "disable-telemetry" in state.tweaks_pending


def test_tweaks_toggle_updates_pending():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)  # enter edit mode
    state.selected_index = 0
    selected_tweak = tui.options.tweaks_edit_options(state)[state.selected_index].value

    tui._toggle_tweak(state)

    assert selected_tweak in state.tweaks_pending
    assert "1 pending change" in state.message


def test_tweaks_discard_reverts():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)
    state.selected_index = 0
    tui._toggle_tweak(state)
    assert state.tweaks_pending != list(state.tweaks_baseline)

    tui._discard_tweaks(state)

    assert state.tweaks_pending == list(state.tweaks_baseline)
    assert "Discarded" in state.message


def test_tweaks_apply_calls_apply_variant(monkeypatch, tmp_path):
    variant = _variant(tweaks=["themes"])
    variant.path = tmp_path / variant.variant_id
    variant.path.mkdir()
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)
    state.selected_index = 0
    tui._toggle_tweak(state)
    pending_before_apply = list(state.tweaks_pending)

    written = {}

    class FakeBuildResult:
        wrapper_path = tmp_path / "wrapper"

    def fake_apply_variant(variant_id, *, claude_version=None, root=None):
        written["called_with"] = (variant_id, claude_version)
        return FakeBuildResult()

    def fake_load_variant(variant_id, root=None):
        return variant

    def fake_validate(manifest):
        written["validated"] = manifest

    def fake_write_json(path, manifest):
        written["written_path"] = path
        written["manifest"] = manifest

    # Refresh after apply re-scans variants; return the same variant with updated tweaks.
    def fake_refresh(state_arg):
        # Simulate the rebuild updating the variant on disk; pending becomes baseline.
        new_tweaks = sorted(set(pending_before_apply))
        variant.manifest["tweaks"] = new_tweaks
        state_arg.variants = [variant]
        return True

    monkeypatch.setattr("ccsilo.variants.apply_variant", fake_apply_variant)
    monkeypatch.setattr("ccsilo.variants.load_variant", fake_load_variant)
    monkeypatch.setattr("ccsilo.variants.model.validate_variant_manifest", fake_validate)
    monkeypatch.setattr("ccsilo.workspace.write_json", fake_write_json)
    monkeypatch.setattr(tui, "_refresh_state", fake_refresh)

    tui._apply_tweaks(state)

    assert written["called_with"] == (variant.variant_id, "2.1.123")
    assert written["manifest"]["tweaks"] == sorted(set(pending_before_apply))
    assert "Applied tweaks" in state.message


def test_tweaks_screen_text_two_pane():
    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant])
    tui._activate(state)  # enter edit

    text = tui._screen_text(state, height=40)

    assert "Edit tweaks" in text
    assert "Tweak details" in text
    assert "Group:" in text
    assert "Versions supported" in text


def test_tweaks_two_pane_renders_at_typical_widths():
    from ratatui_py import Color, DrawCmd, Gauge, List as TuiList, Paragraph, Style, Tabs, headless_render_frame

    variant = _variant(tweaks=["themes"])
    state = tui.TuiState(mode="tweaks-source", variants=[variant], theme_id="hacker-bbs")
    tui._activate(state)  # enter tweaks-edit

    class FakeTerm:
        def __init__(self, w, h):
            self._w, self._h = w, h
            self.commands = None
        def size(self):
            return self._w, self._h
        def draw_frame(self, commands):
            self.commands = commands

    for width, height in ((100, 30), (80, 24)):
        term = FakeTerm(width, height)
        tui._render_frame(
            term, state, width, height,
            Paragraph, Style, Color, DrawCmd, Tabs, TuiList, Gauge,
        )
        assert term.commands, f"no commands at {width}x{height}"

        screen = headless_render_frame(width, height, term.commands)
        assert "Edit tweaks" in screen
        assert "Tweak details" in screen
        # ensure the right pane content was actually rendered
        assert "Group:" in screen

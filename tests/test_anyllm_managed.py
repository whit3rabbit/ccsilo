"""Managed AnyLLM proxy: backend supervision + TUI action wiring."""

import types
from pathlib import Path

from ccsilo.variants import anyllm


def _config(tmp_path, **over):
    config = {
        "binary": "anyllm-proxy",
        "args": ["--webui"],
        "port": 3000,
        "key": "sk-testkey",
        "adminUrl": "http://127.0.0.1:3001/admin/",
        "logPath": str(tmp_path / "anyllm-proxy.log"),
        "pidFilePath": str(tmp_path / "anyllm-proxy.pid"),
    }
    config.update(over)
    return config


class _FakeResp:
    def __init__(self, code, body):
        self._code = code
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self._code

    def read(self, _n=None):
        return self._body


def test_is_running_true_on_health_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(anyllm.urllib.request, "urlopen", lambda *a, **k: _FakeResp(200, b'{"status":"ok"}'))
    assert anyllm.anyllm_is_running(_config(tmp_path)) is True


def test_is_running_false_when_refused(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(anyllm.urllib.request, "urlopen", boom)
    monkeypatch.setattr(anyllm, "_port_open", lambda port: False)
    assert anyllm.anyllm_is_running(_config(tmp_path)) is False


def test_resolve_admin_token_prefers_env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "envtoken")
    token, source = anyllm.resolve_admin_token()
    assert token == "envtoken"
    assert source == "ADMIN_TOKEN env"


def test_resolve_admin_token_reads_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN_PATH", raising=False)
    monkeypatch.setenv("ANYLLM_HOME", str(tmp_path))
    (tmp_path / ".admin_token").write_text("a" * 64 + "\n", encoding="utf-8")
    token, source = anyllm.resolve_admin_token()
    assert token == "a" * 64
    assert source == str(tmp_path / ".admin_token")


def test_resolve_admin_token_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN_PATH", raising=False)
    monkeypatch.setenv("ANYLLM_HOME", str(tmp_path))
    token, _ = anyllm.resolve_admin_token()
    assert token is None


def test_admin_url_appends_token(tmp_path):
    config = _config(tmp_path)
    assert anyllm.anyllm_admin_url(config, None) == "http://127.0.0.1:3001/admin/"
    assert anyllm.anyllm_admin_url(config, "tok") == "http://127.0.0.1:3001/admin/?token=tok"


def test_start_reuses_running_proxy(tmp_path, monkeypatch):
    monkeypatch.setattr(anyllm, "anyllm_is_running", lambda config: True)

    def no_launch(*a, **k):
        raise AssertionError("Popen must not run when the proxy is already up")

    monkeypatch.setattr(anyllm.subprocess, "Popen", no_launch)
    result = anyllm.start_anyllm(_config(tmp_path))
    assert result.ok and result.running
    assert "reusing" in result.detail


class _FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return None


def test_start_launches_with_inbound_key(tmp_path, monkeypatch):
    calls = {"env": None, "argv": None}
    # not running at the reuse-check, then ready on the first poll
    states = iter([False, True])
    monkeypatch.setattr(anyllm, "anyllm_is_running", lambda config: next(states))
    monkeypatch.setattr(anyllm, "find_anyllm_proxy_binary", lambda: "/opt/homebrew/bin/anyllm-proxy")

    def fake_popen(argv, env=None, **kwargs):
        calls["argv"] = argv
        calls["env"] = env
        return _FakeProc()

    monkeypatch.setattr(anyllm.subprocess, "Popen", fake_popen)
    config = _config(tmp_path)
    result = anyllm.start_anyllm(config, wait=2.0)

    assert result.ok and result.running and result.pid == 4242
    assert calls["argv"] == ["/opt/homebrew/bin/anyllm-proxy", "--webui"]
    assert calls["env"]["PROXY_API_KEYS"] == "sk-testkey"
    assert calls["env"]["LISTEN_PORT"] == "3000"
    assert Path(config["pidFilePath"]).read_text(encoding="utf-8") == "4242"


def test_stop_signals_pid_and_clears_file(tmp_path, monkeypatch):
    config = _config(tmp_path)
    Path(config["pidFilePath"]).write_text("999", encoding="utf-8")
    monkeypatch.setattr(anyllm, "anyllm_is_running", lambda config: False)
    signalled = {}

    def fake_kill(pid, sig):
        signalled.setdefault("first", (pid, sig))
        # SIGTERM lands; the sig 0 liveness probe reports the process gone
        if sig == 0:
            raise OSError("no such process")

    monkeypatch.setattr(anyllm.os, "kill", fake_kill)
    result = anyllm.stop_anyllm(config)
    assert result.ok and not result.running
    assert signalled["first"][0] == 999
    assert not Path(config["pidFilePath"]).exists()


def test_stop_when_external(tmp_path, monkeypatch):
    # running but no pid file -> ccsilo did not start it
    monkeypatch.setattr(anyllm, "anyllm_is_running", lambda config: True)
    result = anyllm.stop_anyllm(_config(tmp_path))
    assert not result.ok and result.running
    assert "not started by ccsilo" in result.detail


def test_doctor_checks_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(anyllm, "anyllm_is_running", lambda config: False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    checks = anyllm.anyllm_doctor_checks({"localProxy": _config(tmp_path)})
    names = {c["name"] for c in checks}
    assert names == {"anyllm-admin-token", "anyllm-running"}
    # informational: never turns a fresh setup red
    assert all(c["ok"] for c in checks)


def test_doctor_checks_empty_without_local_proxy():
    assert anyllm.anyllm_doctor_checks({}) == []


# --- TUI wiring -----------------------------------------------------------

def _variant(tmp_path):
    return types.SimpleNamespace(
        variant_id="ccanyllm",
        manifest={
            "provider": {"key": "anyllm"},
            "source": {"version": "2.1.0"},
            "localProxy": _config(tmp_path),
        },
        path=tmp_path,
    )


def test_setup_detail_options_include_anyllm_actions(tmp_path):
    from ccsilo.tui import options_setup as opt

    variant = _variant(tmp_path)
    state = types.SimpleNamespace(
        selected_setup_id="ccanyllm",
        variants=[variant],
        setup_health={},
        download_index={},
        mode="setup-detail",
        selected_index=0,
    )
    kinds = {o.kind for o in opt.setup_detail_options(state)}
    assert {
        "setup-action-anyllm-status",
        "setup-action-anyllm-start",
        "setup-action-anyllm-stop",
        "setup-action-anyllm-restart",
        "setup-action-anyllm-ui",
        "setup-action-anyllm-copy-token",
    } <= kinds


def test_managed_anyllm_gate_false_for_plain_variant():
    from ccsilo.tui.options_setup import _managed_anyllm

    plain = types.SimpleNamespace(manifest={"provider": {"key": "zai"}})
    assert _managed_anyllm(plain) is False


def test_run_setup_anyllm_ui_shows_token(tmp_path, monkeypatch):
    import ccsilo.tui as tui
    from ccsilo.tui import setup_actions_setup as sas

    monkeypatch.setenv("ADMIN_TOKEN", "showme")
    opened = {}
    monkeypatch.setattr(sas.webbrowser, "open", lambda url: opened.setdefault("url", url) or True)
    monkeypatch.setattr(sas, "anyllm_is_running", lambda config: True)

    state = types.SimpleNamespace(
        variants=[_variant(tmp_path)],
        message="",
        last_action_summary=[],
        last_action_log=[],
        mode="setup-detail",
        selected_index=0,
        selected_setup_id="ccanyllm",
    )
    tui._run_setup_anyllm_action(state, "ccanyllm", "ui")

    assert opened["url"].startswith("http://127.0.0.1:3001/admin/?token=showme")
    assert any("Admin token: showme" in line for line in state.last_action_summary)
    assert state.mode == "health-result"

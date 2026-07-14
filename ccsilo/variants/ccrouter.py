"""Managed Claude Code Router support for ccrouter variants."""

import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .._utils import atomic_write_text_no_symlink

CCR_PROVIDER_KEY = "ccrouter"
CCR_OAUTH_PROVIDER_KEY = "ccr-oauth"
CCR_PROVIDER_KEYS = {CCR_PROVIDER_KEY, CCR_OAUTH_PROVIDER_KEY}
# Pinned, not @latest: claude-code-router 3.x (2026-07) is a rewrite that
# drops the .claude-code-router.pid file for service.json, ignores config.json
# PORT in favor of its own gateway port, and stores config in sqlite. ccsilo's
# managed integration (pid-file detection, PORT-in-config, ANTHROPIC_BASE_URL
# from that port) only works with the 1.x-2.x model. Bump this deliberately
# after adapting the integration; do not float to @latest.
CCR_PACKAGE_DEFAULT = "@musistudio/claude-code-router@1.0.73"
# claude-code-router 3.x is incompatible with the managed integration above.
CCR_INCOMPATIBLE_MAJOR = 3
CCR_MODE_MANAGED = "managed"
CCR_MODE_EXTERNAL = "external"
CCR_CONFIG_COPY_GLOBAL = "copy-global"
CCR_CONFIG_EMPTY = "empty"
CCR_CONFIG_SHARED_HOME = "shared-home"
CCR_CONFIG_DIRNAME = ".claude-code-router"
CCR_CONFIG_FILENAME = "config.json"
CCR_RUNTIME_DIRNAME = "ccr-runtime"
CCR_HOME_DIRNAME = "ccr-home"
CCR_MIN_NODE_MAJOR = 20

_CCR_MODES = {CCR_MODE_MANAGED, CCR_MODE_EXTERNAL}
_CCR_CONFIG_MODES = {CCR_CONFIG_COPY_GLOBAL, CCR_CONFIG_EMPTY, CCR_CONFIG_SHARED_HOME}


@dataclass
class CcrCommandResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str


def default_ccrouter_config_mode(home: Optional[Path] = None) -> str:
    return CCR_CONFIG_COPY_GLOBAL if _global_config_path(home).is_file() else CCR_CONFIG_EMPTY


def ccrouter_manifest_for_create(
    provider_key: str,
    variant_dir: Path,
    *,
    mode: Optional[str] = None,
    config_mode: Optional[str] = None,
    package_spec: Optional[str] = None,
    port: Optional[object] = None,
    auto_start: Optional[bool] = None,
    home: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    if provider_key not in CCR_PROVIDER_KEYS:
        values = [mode, config_mode, package_spec, port]
        if any(value not in (None, "") for value in values) or auto_start is not None:
            allowed = ", ".join(sorted(CCR_PROVIDER_KEYS))
            raise ValueError(f"ccrouter options can only be used with --provider {allowed}")
        return None

    resolved_mode = _validate_choice(mode or CCR_MODE_MANAGED, _CCR_MODES, "ccrouter mode")
    resolved_auto_start = True if auto_start is None else bool(auto_start)
    runtime_dir = variant_dir / CCR_RUNTIME_DIRNAME

    if resolved_mode == CCR_MODE_EXTERNAL:
        return {
            "mode": CCR_MODE_EXTERNAL,
            "autoStart": False,
        }

    resolved_config_mode = _validate_choice(
        config_mode or default_ccrouter_config_mode(home),
        _CCR_CONFIG_MODES,
        "ccrouter config mode",
    )
    resolved_port = _resolve_port(port)
    home_dir = _managed_home_dir(variant_dir, resolved_config_mode, home=home)
    return {
        "mode": CCR_MODE_MANAGED,
        "packageSpec": _package_spec(package_spec),
        "configMode": resolved_config_mode,
        "autoStart": resolved_auto_start,
        "port": resolved_port,
        "homeDir": str(home_dir),
        "runtimeDir": str(runtime_dir),
        "tmpDir": str(variant_dir / "tmp"),
    }


def prepare_ccrouter_manifest(manifest: Dict, variant_dir: Path) -> Dict[str, object]:
    config = normalize_ccrouter_manifest(manifest.get("ccrouter"), variant_dir)
    if config.get("mode") != CCR_MODE_MANAGED:
        return config

    runtime_dir = Path(str(config["runtimeDir"]))
    home_dir = Path(str(config["homeDir"]))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    home_dir.mkdir(parents=True, exist_ok=True)
    config_dir = home_dir / CCR_CONFIG_DIRNAME
    config_dir.mkdir(parents=True, exist_ok=True)

    installed_version = _ensure_local_package(runtime_dir, str(config["packageSpec"]))
    config["installedVersion"] = installed_version
    config_path = _ensure_config(config, config_dir)
    config["configPath"] = str(config_path)
    runtime_bin = runtime_dir / "node_modules" / ".bin" / "ccr"
    config["binPath"] = str(runtime_bin)
    _sync_env_from_config(manifest, config_path)
    return config


def normalize_ccrouter_manifest(value: object, variant_dir: Path) -> Dict[str, object]:
    config = dict(value) if isinstance(value, dict) else {}
    mode = _validate_choice(str(config.get("mode") or CCR_MODE_MANAGED), _CCR_MODES, "ccrouter mode")
    if mode == CCR_MODE_EXTERNAL:
        return {"mode": CCR_MODE_EXTERNAL, "autoStart": False}
    config_mode = _validate_choice(
        str(config.get("configMode") or default_ccrouter_config_mode()),
        _CCR_CONFIG_MODES,
        "ccrouter config mode",
    )
    return {
        "mode": CCR_MODE_MANAGED,
        "packageSpec": _package_spec(config.get("packageSpec")),
        "configMode": config_mode,
        "autoStart": bool(config.get("autoStart", True)),
        "port": _resolve_port(config.get("port")),
        "homeDir": str(config.get("homeDir") or _managed_home_dir(variant_dir, config_mode)),
        "runtimeDir": str(config.get("runtimeDir") or (variant_dir / CCR_RUNTIME_DIRNAME)),
        "tmpDir": str(config.get("tmpDir") or (variant_dir / "tmp")),
        **{
            key: config[key]
            for key in ("installedVersion", "configPath", "binPath")
            if key in config
        },
    }


def ccrouter_doctor_checks(manifest: Dict) -> List[Dict[str, object]]:
    config = manifest.get("ccrouter")
    if not isinstance(config, dict) or config.get("mode") != CCR_MODE_MANAGED:
        return []

    runtime_dir = Path(str(config.get("runtimeDir") or ""))
    home_dir = Path(str(config.get("homeDir") or ""))
    bin_path = Path(str(config.get("binPath") or runtime_dir / "node_modules" / ".bin" / "ccr"))
    config_path = Path(str(config.get("configPath") or home_dir / CCR_CONFIG_DIRNAME / CCR_CONFIG_FILENAME))
    checks = [
        {"name": "ccrouter-runtime", "ok": runtime_dir.is_dir(), "path": str(runtime_dir)},
        {"name": "ccrouter-bin", "ok": bin_path.exists(), "path": str(bin_path)},
        {"name": "ccrouter-home", "ok": home_dir.is_dir(), "path": str(home_dir)},
        {"name": "ccrouter-config", "ok": config_path.is_file(), "path": str(config_path)},
    ]
    config_ok = False
    config_detail = ""
    port_ok = False
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_ok = isinstance(payload, dict)
            port = payload.get("PORT", config.get("port"))
            port_ok = isinstance(_resolve_port(port), int)
        except Exception as exc:
            config_detail = str(exc)
    checks.append({"name": "ccrouter-config-valid", "ok": config_ok, "path": str(config_path), "detail": config_detail})
    checks.append({"name": "ccrouter-port", "ok": port_ok, "path": str(config_path)})

    version_ok, version_detail = ccr_version_supported(config.get("installedVersion"))
    checks.append({"name": "ccrouter-version", "ok": version_ok, "path": str(runtime_dir), "detail": version_detail})

    node_ok, node_detail = node_version_ok()
    checks.append({"name": "ccrouter-node", "ok": node_ok, "path": shutil.which("node") or "node", "detail": node_detail})
    running = ccrouter_is_running(config)
    checks.append({"name": "ccrouter-running", "ok": running, "path": str(home_dir), "detail": "warning: service is stopped" if not running else ""})
    return checks


def ccr_version_supported(version: object) -> tuple:
    # Unknown version does not block: external mode and old manifests omit it.
    text = str(version or "").strip().lstrip("v")
    if not text:
        return True, ""
    try:
        major = int(text.split(".", 1)[0])
    except (TypeError, ValueError):
        return True, f"unrecognized ccr version: {text}"
    if major >= CCR_INCOMPATIBLE_MAJOR:
        return False, (
            f"ccr {text} is unsupported: the {major}.x rewrite is incompatible. "
            "Reapply this setup with --ccrouter-package "
            "'@musistudio/claude-code-router@1.0.73'."
        )
    return True, f"ccr {text}"


def node_version_ok() -> tuple:
    node = shutil.which("node")
    if not node:
        return False, "node not found"
    try:
        result = subprocess.run([node, "--version"], text=True, capture_output=True, check=False, timeout=10)
    except Exception as exc:
        return False, str(exc)
    version = (result.stdout or result.stderr or "").strip().lstrip("v")
    try:
        major = int(version.split(".", 1)[0])
    except (TypeError, ValueError):
        return False, f"unrecognized node version: {version or 'unknown'}"
    return major >= CCR_MIN_NODE_MAJOR, f"node {version}"


def ccrouter_command_env(config: Dict[str, object]) -> Dict[str, str]:
    env = dict(os.environ)
    if config.get("mode") != CCR_MODE_MANAGED:
        return env
    home_dir = str(config.get("homeDir") or "")
    runtime_dir = Path(str(config.get("runtimeDir") or ""))
    bin_dir = runtime_dir / "node_modules" / ".bin"
    if home_dir:
        env["HOME"] = home_dir
        env["USERPROFILE"] = home_dir
    if bin_dir:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    tmp_dir = Path(str(config.get("tmpDir") or "")) if config.get("tmpDir") else (Path(home_dir).parent / "tmp" if home_dir else None)
    if tmp_dir:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(tmp_dir)
    return env


def run_ccrouter_command(manifest: Dict, args: List[str], *, timeout: int = 30) -> CcrCommandResult:
    config = manifest.get("ccrouter")
    if not isinstance(config, dict) or config.get("mode") != CCR_MODE_MANAGED:
        raise ValueError("Setup is not a managed ccrouter variant")
    bin_path = Path(str(config.get("binPath") or Path(str(config.get("runtimeDir"))) / "node_modules" / ".bin" / "ccr"))
    command = [str(bin_path if bin_path.exists() else "ccr"), *args]
    result = subprocess.run(
        command,
        env=ccrouter_command_env(config),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return CcrCommandResult(command=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


def ccrouter_is_running(config: Dict[str, object]) -> bool:
    if config.get("mode") != CCR_MODE_MANAGED:
        return False
    home_dir = Path(str(config.get("homeDir") or ""))
    pid_file = home_dir / CCR_CONFIG_DIRNAME / ".claude-code-router.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _ensure_local_package(runtime_dir: Path, package_spec: str) -> str:
    package_json = runtime_dir / "node_modules" / "@musistudio" / "claude-code-router" / "package.json"
    bin_path = runtime_dir / "node_modules" / ".bin" / "ccr"
    if not package_json.is_file() or not bin_path.exists():
        subprocess.run(
            ["npm", "install", "--prefix", str(runtime_dir), package_spec],
            check=True,
            text=True,
            capture_output=True,
            timeout=300,
        )
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("version") or "")


def _ensure_config(config: Dict[str, object], config_dir: Path) -> Path:
    config_path = config_dir / CCR_CONFIG_FILENAME
    if not config_path.exists():
        mode = str(config.get("configMode") or CCR_CONFIG_EMPTY)
        if mode == CCR_CONFIG_COPY_GLOBAL:
            _copy_global_config(config_dir)
        if not config_path.exists():
            _write_minimal_config(config_path, int(config["port"]))
    if str(config.get("configMode")) in {CCR_CONFIG_COPY_GLOBAL, CCR_CONFIG_EMPTY}:
        _write_port_if_valid(config_path, int(config["port"]))
    return config_path


def _copy_global_config(config_dir: Path) -> None:
    source_dir = _global_config_dir()
    if not source_dir.is_dir():
        return
    for name in (CCR_CONFIG_FILENAME, "presets", "plugins"):
        source = source_dir / name
        target = config_dir / name
        if not source.exists() or target.exists() or target.is_symlink():
            continue
        if source.is_symlink():
            continue
        if source.is_dir():
            _copy_tree_no_symlinks(source, target)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _copy_tree_no_symlinks(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_symlink():
            continue
        if item.is_dir():
            _copy_tree_no_symlinks(item, destination)
        elif item.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _write_minimal_config(path: Path, port: int) -> None:
    payload = {"PORT": port, "Providers": [], "Router": {}}
    atomic_write_text_no_symlink(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_port_if_valid(path: Path, port: int) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    if payload.get("PORT") == port:
        return
    payload["PORT"] = port
    atomic_write_text_no_symlink(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _sync_env_from_config(manifest: Dict, config_path: Path) -> None:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    port = _resolve_port(payload.get("PORT"))
    api_key = str(payload.get("APIKEY") or "ccrouter-proxy")
    timeout = str(payload.get("API_TIMEOUT_MS") or "600000")
    env = dict(manifest.get("env") or {})
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["ANTHROPIC_AUTH_TOKEN"] = api_key
    env["NO_PROXY"] = "127.0.0.1"
    env["API_TIMEOUT_MS"] = timeout
    manifest["env"] = env


def _managed_home_dir(variant_dir: Path, config_mode: str, *, home: Optional[Path] = None) -> Path:
    if config_mode == CCR_CONFIG_SHARED_HOME:
        return Path(home).expanduser() if home is not None else Path.home()
    return variant_dir / CCR_HOME_DIRNAME


def _global_config_dir(home: Optional[Path] = None) -> Path:
    return (Path(home).expanduser() if home is not None else Path.home()) / CCR_CONFIG_DIRNAME


def _global_config_path(home: Optional[Path] = None) -> Path:
    return _global_config_dir(home) / CCR_CONFIG_FILENAME


def _package_spec(value: object) -> str:
    package_spec = str(value or CCR_PACKAGE_DEFAULT).strip()
    if not package_spec:
        raise ValueError("ccrouter package spec must be non-empty")
    return package_spec


def _resolve_port(value: object) -> int:
    if value in (None, "", "auto"):
        return _free_port()
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ccrouter port must be auto or an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("ccrouter port must be between 1 and 65535")
    return port


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _validate_choice(value: str, allowed: set, label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return value

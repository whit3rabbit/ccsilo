"""Detection and setup-local sync for user-installed Claude Code integrations."""

import copy
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .._utils import atomic_write_text_no_symlink


CONTEXT7_ID = "context7"
RTK_ID = "rtk"
ANYLLM_PROXY_ID = "anyllm-proxy"
KNOWN_LOCAL_INTEGRATION_IDS = (CONTEXT7_ID, RTK_ID, ANYLLM_PROXY_ID)
RTK_HOOK_COMMAND = "rtk hook claude"
CONTEXT7_MCP_URL = "https://mcp.context7.com/mcp"
CONTEXT7_PLUGIN_SPEC = "context7@claude-plugins-official"

# anyllm-proxy release metadata (bump when publishing a new proxy version).
ANYLLM_PROXY_VERSION = "0.16.0"
ANYLLM_PROXY_RELEASE_BASE = (
    "https://github.com/whit3rabbit/anyllm-proxy/releases/download/"
    f"v{ANYLLM_PROXY_VERSION}/"
)
ANYLLM_PROXY_TAP = "whit3rabbit/tap/anyllm-proxy"
# Installed binary is anyllm-proxy (hyphen) since 0.12.0; the crate/package name
# stays anyllm_proxy (cargo install), but Homebrew/deb/release archives all ship
# the hyphenated executable.
ANYLLM_PROXY_BIN = "anyllm-proxy"
ANYLLM_PROXY_HOMEBREW_DIRS = "/opt/homebrew:/usr/local"
ANYLLM_PROXY_LOCAL_BIN = ".local/bin"


@dataclass(frozen=True)
class LocalIntegrationStatus:
    id: str
    name: str
    available: bool
    missing: Tuple[str, ...] = ()
    details: Tuple[str, ...] = ()
    paths: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalIntegrationInstallResult:
    id: str
    changed: bool
    summary: Tuple[str, ...]
    output: str = ""


def normalize_integration_ids(ids: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for raw_id in ids:
        integration_id = str(raw_id or "").strip()
        if not integration_id:
            continue
        if integration_id not in KNOWN_LOCAL_INTEGRATION_IDS:
            raise ValueError(f"Unknown local integration id: {integration_id}")
        if integration_id not in normalized:
            normalized.append(integration_id)
    return normalized


def detect_local_integrations(*, home: Optional[os.PathLike] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, LocalIntegrationStatus]:
    return {
        CONTEXT7_ID: detect_context7(home=home, env=env),
        RTK_ID: detect_rtk(home=home, env=env),
        ANYLLM_PROXY_ID: detect_anyllm_proxy(home=home, env=env),
    }


def detect_context7(*, home: Optional[os.PathLike] = None, env: Optional[Dict[str, str]] = None) -> LocalIntegrationStatus:
    home_path = _home_path(home=home, env=env)
    claude_config_path = home_path / ".claude.json"
    rule_path = home_path / ".claude" / "rules" / "context7.md"
    skill_path = home_path / ".claude" / "skills" / "context7-mcp" / "SKILL.md"
    server = _context7_server(home_path)

    missing = []
    details = []
    paths = {
        "claudeConfig": str(claude_config_path),
        "rule": str(rule_path),
        "skill": str(skill_path),
    }
    if server is None:
        missing.append("mcp")
    else:
        details.append("MCP server: context7")
    if not rule_path.is_file():
        missing.append("rule")
    else:
        details.append("Rule: rules/context7.md")
    if not skill_path.is_file():
        missing.append("skill")
    else:
        details.append("Skill: skills/context7-mcp/SKILL.md")

    return LocalIntegrationStatus(
        id=CONTEXT7_ID,
        name="Context7",
        available=not missing,
        missing=tuple(missing),
        details=tuple(details),
        paths=paths,
    )


def detect_rtk(*, home: Optional[os.PathLike] = None, env: Optional[Dict[str, str]] = None) -> LocalIntegrationStatus:
    env = os.environ if env is None else env
    home_path = _home_path(home=home, env=env)
    settings_path = home_path / ".claude" / "settings.json"
    rtk_bin = find_rtk_binary(env=env)
    hook = _rtk_hook_entry(home_path)
    missing = []
    details = []
    paths = {"settings": str(settings_path)}
    if rtk_bin:
        details.append(f"Binary: {rtk_bin}")
        paths["binary"] = rtk_bin
    else:
        missing.append("binary")
    if hook is None:
        missing.append("hook")
    else:
        details.append("Hook: PreToolUse Bash")
    return LocalIntegrationStatus(
        id=RTK_ID,
        name="RTK",
        available=rtk_bin is not None,
        missing=tuple(missing),
        details=tuple(details),
        paths=paths,
    )


def find_rtk_binary(*, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    override = str(env.get("CCSILO_RTK_BIN") or "").strip()
    if override and _is_executable(Path(override)):
        return override
    path_value = env.get("PATH")
    found = shutil.which("rtk", path=path_value)
    if found:
        return found
    homebrew_dirs = str(env.get("CCSILO_RTK_HOMEBREW_DIRS", "/opt/homebrew:/usr/local"))
    for prefix in [item for item in homebrew_dirs.split(os.pathsep) if item]:
        candidate = Path(prefix) / "opt" / "rtk" / "bin" / "rtk"
        if _is_executable(candidate):
            return str(candidate)
    return None


def sync_local_integrations(
    integration_ids: Iterable[str],
    config_dir,
    *,
    home: Optional[os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, bool]:
    selected = normalize_integration_ids(integration_ids or [])
    config_dir = Path(config_dir)
    home_path = _home_path(home=home, env=env)
    changed = {}
    if CONTEXT7_ID in selected:
        changed[CONTEXT7_ID] = _sync_context7(config_dir, home_path)
    if RTK_ID in selected:
        changed[RTK_ID] = _sync_rtk(config_dir, home_path)
    return changed


def find_anyllm_proxy_binary(*, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    override = str(env.get("CCSILO_ANYLLM_PROXY_BIN") or "").strip()
    if override and _is_executable(Path(override)):
        return override
    path_value = env.get("PATH")
    found = shutil.which(ANYLLM_PROXY_BIN, path=path_value)
    if found:
        return found
    for prefix in [item for item in ANYLLM_PROXY_HOMEBREW_DIRS.split(os.pathsep) if item]:
        candidate = Path(prefix) / "opt" / "anyllm-proxy" / "bin" / ANYLLM_PROXY_BIN
        if _is_executable(candidate):
            return str(candidate)
    home_local = Path(env.get("HOME") or "~").expanduser() / ANYLLM_PROXY_LOCAL_BIN / ANYLLM_PROXY_BIN
    if _is_executable(home_local):
        return str(home_local)
    return None


def detect_anyllm_proxy(*, home: Optional[os.PathLike] = None, env: Optional[Dict[str, str]] = None) -> LocalIntegrationStatus:
    env = os.environ if env is None else env
    bin_path = find_anyllm_proxy_binary(env=env)
    missing = () if bin_path else ("binary",)
    details = (f"Binary: {bin_path}",) if bin_path else ()
    paths = {"binary": bin_path} if bin_path else {}
    return LocalIntegrationStatus(
        id=ANYLLM_PROXY_ID,
        name="AnyLLM Proxy",
        available=bin_path is not None,
        missing=tuple(missing),
        details=tuple(details),
        paths=paths,
    )


def install_local_integration(
    integration_id: str,
    *,
    home: Optional[os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
) -> LocalIntegrationInstallResult:
    integration_id = normalize_integration_ids([integration_id])[0]
    env = dict(os.environ if env is None else env)
    if integration_id == CONTEXT7_ID:
        return _install_context7(env=env)
    if integration_id == ANYLLM_PROXY_ID:
        return install_anyllm_proxy(env=env)
    return _install_rtk(home=home, env=env)


def _sync_context7(config_dir: Path, home_path: Path) -> bool:
    changed = False
    server = _context7_server(home_path)
    if server is not None:
        config_path = config_dir / ".claude.json"
        config = _read_json(config_path)
        servers = dict(config.get("mcpServers") or {})
        if "context7" not in servers:
            servers["context7"] = server
            config["mcpServers"] = servers
            _write_json(config_path, config)
            changed = True
    changed = _copy_text_if_present(
        home_path / ".claude" / "rules" / "context7.md",
        config_dir / "rules" / "context7.md",
    ) or changed
    changed = _copy_text_if_present(
        home_path / ".claude" / "skills" / "context7-mcp" / "SKILL.md",
        config_dir / "skills" / "context7-mcp" / "SKILL.md",
    ) or changed
    return changed


def _sync_rtk(config_dir: Path, home_path: Path) -> bool:
    hook_entry = _rtk_hook_entry(home_path)
    if hook_entry is None:
        return False
    settings_path = config_dir / "settings.json"
    settings = _read_json(settings_path)
    hooks = settings.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError(f"{settings_path} hooks must be an object")
    pre_tool_use = hooks.get("PreToolUse")
    if pre_tool_use is None:
        pre_tool_use = []
    if not isinstance(pre_tool_use, list):
        raise ValueError(f"{settings_path} hooks.PreToolUse must be a list")
    if _contains_rtk_hook({"hooks": {"PreToolUse": pre_tool_use}}):
        return False
    pre_tool_use.append(hook_entry)
    hooks["PreToolUse"] = pre_tool_use
    settings["hooks"] = hooks
    _write_json(settings_path, settings)
    return True


def _context7_server(home_path: Path) -> Optional[Dict[str, object]]:
    config = _read_json(home_path / ".claude.json")
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    server = servers.get("context7")
    if not isinstance(server, dict):
        return None
    return copy.deepcopy(server)


def _rtk_hook_entry(home_path: Path) -> Optional[Dict[str, object]]:
    settings = _read_json(home_path / ".claude" / "settings.json")
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return None
    pre_tool_use = hooks.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return None
    for group in pre_tool_use:
        if not isinstance(group, dict):
            continue
        hook_items = group.get("hooks")
        if not isinstance(hook_items, list):
            continue
        for hook in hook_items:
            if _is_rtk_hook(hook):
                matcher = str(group.get("matcher") or "Bash")
                return {
                    "matcher": matcher,
                    "hooks": [copy.deepcopy(hook)],
                }
    return None


def _contains_rtk_hook(settings: Dict[str, object]) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    pre_tool_use = hooks.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return False
    for group in pre_tool_use:
        if not isinstance(group, dict):
            continue
        hook_items = group.get("hooks")
        if not isinstance(hook_items, list):
            continue
        if any(_is_rtk_hook(hook) for hook in hook_items):
            return True
    return False


def _is_rtk_hook(hook) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and str(hook.get("command") or "").strip() == RTK_HOOK_COMMAND
    )


def _install_context7(*, env: Dict[str, str]) -> LocalIntegrationInstallResult:
    claude = shutil.which("claude", path=env.get("PATH"))
    if not claude:
        raise ValueError("Claude Code command not found on PATH")
    home_path = _home_path(home=None, env=env)
    output = []
    plugin = _run_command(
        [claude, "plugin", "install", CONTEXT7_PLUGIN_SPEC, "--scope", "user"],
        env=env,
    )
    output.append(plugin)
    summary = ["Context7 plugin install command completed."]
    api_key = str(env.get("CONTEXT7_API_KEY") or "")
    if _context7_server(home_path) is not None:
        summary.append("Context7 MCP server is already configured.")
    elif api_key:
        mcp_payload = _run_command(
            [
                claude,
                "mcp",
                "add",
                "--scope",
                "user",
                "--transport",
                "http",
                "context7",
                CONTEXT7_MCP_URL,
                "--header",
                f"CONTEXT7_API_KEY: {api_key}",
            ],
            env=env,
            redactions=[api_key],
        )
        output.append(mcp_payload)
        summary.append("Context7 MCP server configured with CONTEXT7_API_KEY.")
    else:
        summary.append("CONTEXT7_API_KEY is not set; skipped API-key MCP configuration.")
    return LocalIntegrationInstallResult(CONTEXT7_ID, True, tuple(summary), "\n".join(output))


def _install_rtk(*, home: Optional[os.PathLike], env: Dict[str, str]) -> LocalIntegrationInstallResult:
    home_path = _home_path(home=home, env=env)
    if find_rtk_binary(env=env) is None:
        if sys.platform != "darwin":
            raise ValueError("RTK is missing and automatic install is only supported on macOS with Homebrew")
        brew = shutil.which("brew", path=env.get("PATH"))
        if not brew:
            raise ValueError("RTK is missing and Homebrew is not available on PATH")
        output = _run_command([brew, "install", "rtk"], env=env)
        return LocalIntegrationInstallResult(
            RTK_ID,
            True,
            ("RTK Homebrew install command completed.", "Run the prep action again if the Claude hook is still missing."),
            output,
        )
    if _rtk_hook_entry(home_path) is None:
        rtk = find_rtk_binary(env=env) or "rtk"
        output = _run_command(
            [rtk, "init", "--global", "--hook-only", "--auto-patch"],
            env=env,
        )
        return LocalIntegrationInstallResult(
            RTK_ID,
            True,
            ("RTK Claude hook install command completed.",),
            output,
        )
    return LocalIntegrationInstallResult(RTK_ID, False, ("RTK binary and Claude hook are already detected.",), "")


def install_anyllm_proxy(*, env: Dict[str, str]) -> LocalIntegrationInstallResult:
    if find_anyllm_proxy_binary(env=env) is not None:
        return LocalIntegrationInstallResult(
            ANYLLM_PROXY_ID, False, ("AnyLLM proxy binary is already installed.",), ""
        )
    is_mac = sys.platform == "darwin"
    output: List[str] = []
    if is_mac:
        brew = shutil.which("brew", path=env.get("PATH"))
        if brew:
            output.append(_run_command([brew, "install", ANYLLM_PROXY_TAP], env=env))
            return LocalIntegrationInstallResult(
                ANYLLM_PROXY_ID, True, ("AnyLLM proxy Homebrew install completed.",), "\n".join(output)
            )
        output.append(_install_anyllm_proxy_tarball(env=env))
        return LocalIntegrationInstallResult(
            ANYLLM_PROXY_ID, True, ("AnyLLM proxy installed from the macOS tarball.",), "\n".join(output)
        )
    # Linux
    dpkg = shutil.which("dpkg", path=env.get("PATH"))
    if dpkg:
        deb_url = _anyllm_proxy_deb_url()
        deb_path = _download_to_temp(deb_url, "anyllm-proxy.deb")
        output.append(_run_command(["sudo", dpkg, "-i", str(deb_path)], env=env))
        return LocalIntegrationInstallResult(
            ANYLLM_PROXY_ID, True, ("AnyLLM proxy installed via dpkg.",), "\n".join(output)
        )
    dpkg_deb = shutil.which("dpkg-deb", path=env.get("PATH"))
    if dpkg_deb:
        output.append(_install_anyllm_proxy_from_deb(db_extract=dpkg_deb, env=env))
        return LocalIntegrationInstallResult(
            ANYLLM_PROXY_ID, True, ("AnyLLM proxy extracted from the .deb (no root required).",), "\n".join(output)
        )
    raise ValueError(
        "AnyLLM proxy install requires dpkg (Debian/Ubuntu) or dpkg-deb. "
        "Install dpkg, or download the .deb from "
        f"{ANYLLM_PROXY_RELEASE_BASE} and extract usr/bin/{ANYLLM_PROXY_BIN} to your PATH."
    )


def _anyllm_proxy_deb_url() -> str:
    arch = "arm64" if _host_arch() in ("arm64", "aarch64") else "amd64"
    return f"{ANYLLM_PROXY_RELEASE_BASE}anyllm-proxy_{ANYLLM_PROXY_VERSION}-1_{arch}.deb"


def _install_anyllm_proxy_from_deb(*, db_extract: str, env: Dict[str, str]) -> str:
    deb_url = _anyllm_proxy_deb_url()
    deb_path = _download_to_temp(deb_url, "anyllm-proxy.deb")
    with tempfile.TemporaryDirectory() as extract_dir:
        _run_command([db_extract, "-x", str(deb_path), extract_dir], env=env)
        extracted = Path(extract_dir) / "usr" / "bin" / ANYLLM_PROXY_BIN
        if not extracted.is_file():
            raise ValueError(f"{ANYLLM_PROXY_BIN} not found in .deb extraction at {extracted}")
        return _place_anyllm_proxy_binary(extracted, env=env)


def _install_anyllm_proxy_tarball(*, env: Dict[str, str]) -> str:
    if _host_arch() in ("arm64", "aarch64"):
        asset = f"anyllm-proxy-{ANYLLM_PROXY_VERSION}-macos-arm64.tar.gz"
    else:
        asset = f"anyllm-proxy-{ANYLLM_PROXY_VERSION}-macos-x86_64.tar.gz"
    url = f"{ANYLLM_PROXY_RELEASE_BASE}{asset}"
    tarball = _download_to_temp(url, asset)
    with tempfile.TemporaryDirectory() as extract_dir:
        with tarfile.open(tarball, "r:gz") as tf:
            member = _tarball_member_named(tf, ANYLLM_PROXY_BIN)
            tf.extract(member, path=extract_dir)
        extracted = Path(extract_dir) / member.name.lstrip("./")
        return _place_anyllm_proxy_binary(extracted, env=env)


def _tarball_member_named(tf: "tarfile.TarFile", name: str) -> "tarfile.TarInfo":
    for member in tf.getmembers():
        if member.name.rstrip("/").split("/")[-1] == name and member.isfile():
            return member
    raise ValueError(f"{name} not found in release tarball")


def _place_anyllm_proxy_binary(source: Path, *, env: Dict[str, str]) -> str:
    if not source.is_file():
        raise ValueError(f"{ANYLLM_PROXY_BIN} binary missing after extraction: {source}")
    home = Path(env.get("HOME") or "~").expanduser()
    local_bin = home / ANYLLM_PROXY_LOCAL_BIN
    local_bin.mkdir(parents=True, mode=0o755, exist_ok=True)
    dest = local_bin / ANYLLM_PROXY_BIN
    shutil.copyfile(source, dest)
    dest.chmod(0o755)
    path_value = env.get("PATH", "")
    on_path = str(local_bin) in path_value.split(os.pathsep)
    if on_path or find_anyllm_proxy_binary(env={**env, "PATH": path_value}):
        return f"Installed {dest}"
    return (
        f"Installed {dest}. Add {local_bin} to your PATH "
        f"(e.g. export PATH={local_bin}:$PATH) to use it."
    )


def _download_to_temp(url: str, filename: str) -> Path:
    dest = Path(tempfile.gettempdir()) / filename
    req = urllib.request.Request(url, headers={"User-Agent": "ccsilo"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise ValueError(f"Download failed or empty: {url}")
    return dest


def _host_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "amd64"


def _run_command(args: List[str], *, env: Dict[str, str], redactions: Optional[List[str]] = None) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    output = _redact(output, redactions or [])
    if proc.returncode != 0:
        raise ValueError(f"Command exited {proc.returncode}: {output.strip() or args[0]}")
    return output


def _redact(text: str, values: Iterable[str]) -> str:
    redacted = text
    for value in values:
        if value:
            redacted = redacted.replace(value, "<redacted>")
    return redacted


def _copy_text_if_present(source: Path, target: Path) -> bool:
    if not source.is_file():
        return False
    text = source.read_text(encoding="utf-8")
    if target.exists() and not target.is_symlink():
        try:
            if target.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    atomic_write_text_no_symlink(target, text)
    return True


def _read_json(path: Path) -> Dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Dict) -> None:
    atomic_write_text_no_symlink(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _home_path(*, home: Optional[os.PathLike], env: Optional[Dict[str, str]]) -> Path:
    if home is not None:
        return Path(home).expanduser()
    env = os.environ if env is None else env
    return Path(env.get("HOME") or "~").expanduser()


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False

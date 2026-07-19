"""Variant wrapper script + secrets/config writers."""

import os
import shlex
import stat
from pathlib import Path
from typing import Dict, Optional

from .._utils import (
    atomic_write_bytes_no_symlink,
    atomic_write_text_no_symlink,
    require_env_name,
    safe_child_path,
    utc_now as _utc_now,
)
from ..providers import (
    apply_provider_claude_config,
    ensure_onboarding_state,
    find_anyllm_proxy_binary,
    get_provider,
    provider_auth_bootstrap_enabled,
    provider_patch_config,
    sync_local_integrations,
)
from ..workspace import read_json, write_json
from .ccrouter import CCR_PROVIDER_KEYS
from .splash import shell_splash_lines
from .tweaks import YET_ANOTHER_STATUSLINE_TWEAK_ID

SECRETS_FILE = "secrets.env"
SECRETS_FILE_MODE = 0o600
ARCHITECT_MODE_TWEAK_ID = "opusplan1m"
_YET_ANOTHER_STATUSLINE_SOURCE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "statusline"
    / YET_ANOTHER_STATUSLINE_TWEAK_ID
)
_YET_ANOTHER_STATUSLINE_FILES = (
    ("statusline_command.py", 0o755),
    ("statusline/themes.py", 0o644),
    ("LICENSE", 0o644),
)


def write_variant_config(manifest: Dict) -> None:
    paths = manifest["paths"]
    config_dir = Path(paths["configDir"])
    _write_settings_config(manifest, config_dir)
    model_proxy = manifest.get("modelProxy")
    if isinstance(model_proxy, dict) and model_proxy.get("mode") in {"architect", "openai"}:
        runtime_config = {
            "mode": model_proxy["mode"],
            "backendUrl": model_proxy["backendUrl"],
            "backendAuth": model_proxy["backendAuth"],
            "backendModels": list(model_proxy["backendModels"]),
            "anthropicModels": list(model_proxy["anthropicModels"]),
            "anthropicUrl": model_proxy.get("anthropicUrl") or "https://api.anthropic.com",
            "timeoutMs": int(model_proxy.get("timeoutMs") or 600_000),
            "backendFormat": model_proxy.get("backendFormat") or "anthropic",
        }
        for key in ("backendProviderKey", "backendProviderLabel", "backendModelsUrl"):
            value = model_proxy.get(key)
            if value:
                runtime_config[key] = value
        write_json(
            Path(model_proxy["runtimeConfigPath"]),
            runtime_config,
        )
    apply_provider_claude_config(
        manifest["provider"]["key"],
        config_dir,
        auth_bootstrap=not (isinstance(model_proxy, dict) and model_proxy.get("mode") in {"architect", "openai"}),
        optional_mcp_ids=(manifest.get("mcp") or {}).get("selected", []),
        read_json=read_json,
        write_json=write_json,
    )
    sync_local_integrations((manifest.get("integrations") or {}).get("selected", []), config_dir)
    sync_setup_config_tweaks(manifest, config_dir)
    tweak_config = provider_patch_config(manifest["provider"]["key"])
    theme_ids = {
        theme.get("id")
        for theme in tweak_config.get("settings", {}).get("themes", [])
        if isinstance(theme.get("id"), str)
    }
    # Write theme and onboarding state so new variants boot directly into
    # branded dark, while preserving existing valid theme choices.
    ensure_onboarding_state(
        config_dir,
        theme_id="dark",
        skip_onboarding=True,
        valid_theme_ids=theme_ids,
        read_json=read_json,
        write_json=write_json,
    )
    tweak_config["ccInstallationPath"] = paths["binary"]
    tweak_config["lastModified"] = _utc_now()
    write_json(Path(paths["tweakccDir"]) / "config.json", tweak_config)


def _write_settings_config(manifest: Dict, config_dir: Path) -> None:
    settings_path = config_dir / "settings.json"
    settings = read_json(settings_path) if settings_path.exists() else {}
    existing_env = settings.get("env", {})
    if existing_env is None:
        existing_env = {}
    if not isinstance(existing_env, dict):
        raise ValueError(f"{settings_path} env must be an object")

    env = dict(existing_env)
    next_env = _runtime_env_for_manifest(manifest)
    for key in _previous_manifest_env(manifest):
        if key not in next_env:
            env.pop(key, None)
    env.update(next_env)
    settings["env"] = env
    if _uses_architect_mode(manifest) and not str(settings.get("model") or "").strip():
        settings["model"] = "opusplan"
    write_json(settings_path, settings)


def _runtime_env_for_manifest(manifest: Dict) -> Dict[str, object]:
    env = dict(manifest.get("env") or {})
    if _uses_architect_mode(manifest):
        env.pop("ANTHROPIC_MODEL", None)
    return env


def _uses_architect_mode(manifest: Dict) -> bool:
    return ARCHITECT_MODE_TWEAK_ID in (manifest.get("tweaks") or [])


def _previous_manifest_env(manifest: Dict) -> Dict[str, object]:
    root = str((manifest.get("paths") or {}).get("root") or "").strip()
    if not root:
        return {}
    metadata_path = Path(root) / "variant.json"
    if not metadata_path.exists():
        return {}
    previous = read_json(metadata_path)
    env = previous.get("env") or {}
    if not isinstance(env, dict):
        return {}
    return dict(env)


def sync_setup_config_tweaks(manifest: Dict, config_dir) -> None:
    config_dir = Path(config_dir)
    tweak_ids = set(manifest.get("tweaks") or [])
    if YET_ANOTHER_STATUSLINE_TWEAK_ID in tweak_ids:
        _enable_yet_another_statusline(config_dir)
        return
    _disable_statusline_setting(config_dir)


def _enable_yet_another_statusline(config_dir: Path) -> None:
    command_path = _copy_yet_another_statusline(config_dir)
    settings_path = config_dir / "settings.json"
    settings = read_json(settings_path) if settings_path.exists() else {}
    settings["statusLine"] = {
        "type": "command",
        "command": f"python3 {shlex.quote(str(command_path))}",
    }
    write_json(settings_path, settings)


def _disable_statusline_setting(config_dir: Path) -> None:
    settings_path = config_dir / "settings.json"
    if not settings_path.exists():
        return
    settings = read_json(settings_path)
    if _is_ccsilo_statusline(settings.get("statusLine"), config_dir):
        settings.pop("statusLine", None)
        write_json(settings_path, settings)


def _is_ccsilo_statusline(value, config_dir: Path) -> bool:
    if not isinstance(value, dict) or value.get("type") != "command":
        return False
    command = value.get("command")
    if not isinstance(command, str):
        return False
    managed_command = str(config_dir / "statusline" / YET_ANOTHER_STATUSLINE_TWEAK_ID / "statusline_command.py")
    return managed_command in command


def _copy_yet_another_statusline(config_dir: Path) -> Path:
    target_root = config_dir / "statusline" / YET_ANOTHER_STATUSLINE_TWEAK_ID
    for relative, mode in _YET_ANOTHER_STATUSLINE_FILES:
        source = _YET_ANOTHER_STATUSLINE_SOURCE / relative
        target = safe_child_path(
            config_dir,
            f"statusline/{YET_ANOTHER_STATUSLINE_TWEAK_ID}/{relative}",
            label="statusline asset",
        )
        atomic_write_bytes_no_symlink(target, source.read_bytes(), mode=mode)
    return target_root / "statusline_command.py"


def stored_credential_value(manifest: Dict) -> Optional[str]:
    credential = manifest.get("credential", {})
    if credential.get("mode") != "stored":
        return None
    secrets_path = credential.get("secretsPath") or str(Path(manifest["paths"]["root"]) / SECRETS_FILE)
    secrets = read_secret_exports(Path(secrets_path))
    if not secrets:
        return None

    provider = get_provider(manifest["provider"]["key"])
    preferred = [provider.credential_env, *credential.get("targets", [])]
    for key in preferred:
        if key and secrets.get(key):
            return secrets[key]
    return None


def read_secret_exports(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    validate_secret_file(path)
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) != 2 or parts[0] != "export" or "=" not in parts[1]:
            continue
        key, value = parts[1].split("=", 1)
        if key:
            try:
                result[require_env_name(key, label="secret env key")] = value
            except ValueError:
                continue
    return result


def validate_secret_file(path: Path) -> None:
    path = Path(path)
    try:
        file_stat = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError(f"Cannot inspect secrets file: {path}: {exc}") from exc

    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError(f"Refusing to load symlink secrets file: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"Refusing to load non-regular secrets file: {path}")
    if os.name != "nt":
        mode = file_stat.st_mode & 0o777
        if mode != SECRETS_FILE_MODE:
            raise ValueError(f"Refusing to load secrets file with mode {oct(mode)}: {path}")
        if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
            raise ValueError(f"Refusing to load secrets file owned by another user: {path}")


def write_wrapper(manifest: Dict) -> Path:
    paths = manifest["paths"]
    wrapper_path = Path(paths["wrapper"])
    variant_dir = Path(paths["root"])
    lines = [
        "#!/bin/sh",
        "set -eu",
        f"VARIANT_ROOT={shlex.quote(str(variant_dir))}",
        f"export CLAUDE_CONFIG_DIR={shlex.quote(paths['configDir'])}",
        f"export TWEAKCC_CONFIG_DIR={shlex.quote(paths['tweakccDir'])}",
        f"export CLAUDE_CODE_TMPDIR={shlex.quote(paths['tmpDir'])}",
        'export DISABLE_AUTOUPDATER="${DISABLE_AUTOUPDATER:-1}"',
        'export DISABLE_AUTO_MIGRATE_TO_NATIVE="${DISABLE_AUTO_MIGRATE_TO_NATIVE:-1}"',
    ]
    managed_ccrouter = _managed_ccrouter_config(manifest)
    model_proxy = _model_proxy_config(manifest)
    local_proxy = _local_proxy_config(manifest)
    if managed_ccrouter:
        lines.extend(_ccrouter_home_lines(manifest, managed_ccrouter))
    for key, value in sorted(_runtime_env_for_manifest(manifest).items()):
        env_key = require_env_name(key, label="wrapper env key")
        lines.append(f"export {env_key}={shlex.quote(str(value))}")
    for key in manifest.get("envUnset") or []:
        env_key = require_env_name(key, label="wrapper unset env key")
        lines.append(f"unset {env_key}")
    if "rtk-shell-prefix" in (manifest.get("tweaks") or []):
        lines.extend(_rtk_homebrew_preference_lines(paths["tmpDir"]))
    credential = manifest.get("credential", {})
    if credential.get("mode") == "stored":
        lines.extend(
            [
                'SECRET_FILE="$VARIANT_ROOT/secrets.env"',
                'if [ -e "$SECRET_FILE" ]; then',
                '  if [ -L "$SECRET_FILE" ] || [ ! -f "$SECRET_FILE" ]; then',
                '    echo "Refusing unsafe secrets file: $SECRET_FILE" >&2',
                "    exit 126",
                "  fi",
                '  secret_mode="$(stat -f %Lp "$SECRET_FILE" 2>/dev/null || stat -c %a "$SECRET_FILE" 2>/dev/null || true)"',
                '  secret_owner="$(stat -f %u "$SECRET_FILE" 2>/dev/null || stat -c %u "$SECRET_FILE" 2>/dev/null || true)"',
                '  current_uid="$(id -u 2>/dev/null || true)"',
                '  case "$secret_mode" in 600|0600) ;; *) echo "Refusing secrets file with unsafe mode: $SECRET_FILE" >&2; exit 126 ;; esac',
                '  if [ -z "$secret_owner" ] || [ -z "$current_uid" ] || [ "$secret_owner" != "$current_uid" ]; then',
                '    echo "Refusing secrets file with unsafe owner: $SECRET_FILE" >&2',
                "    exit 126",
                "  fi",
                '  . "$SECRET_FILE"',
                "fi",
            ]
        )
    elif credential.get("mode") == "env":
        source = require_env_name(credential.get("source"), label="credential source")
        targets = [require_env_name(target, label="credential target") for target in credential.get("targets", [])]
        lines.append(f": ${{{source}:?Set {source} for variant {manifest['id']}}}")
        if not model_proxy:
            for target in targets:
                lines.append(f"export {target}=\"${{{source}}}\"")
    if provider_auth_bootstrap_enabled(manifest["provider"]["key"]) and not model_proxy and not local_proxy:
        lines.extend(_api_key_approval_bootstrap_lines())
    if managed_ccrouter:
        lines.extend(_ccrouter_runtime_lines(manifest, managed_ccrouter))
    if model_proxy:
        lines.extend(_model_proxy_runtime_lines(manifest, model_proxy))
    if local_proxy:
        lines.extend(_local_proxy_runtime_lines(manifest, local_proxy))
    lines.extend(shell_splash_lines())
    launch_args = _launch_args(manifest)
    if manifest.get("runtime", "native") == "node":
        lines.extend(
            [
                'NODE_BIN="${NODE:-node}"',
                '_NODE_CACHE="${VARIANT_ROOT}/.node-cache"',
                "_NODE_USING_PROBE='using x = { [Symbol.dispose]() {} };'",
                '_node_supports_using() { "$1" --input-type=module -e "$_NODE_USING_PROBE" >/dev/null 2>&1; }',
                'if [ -z "${NODE:-}" ] && [ -f "$_NODE_CACHE" ]; then',
                '  _CACHED="$(cat "$_NODE_CACHE" 2>/dev/null)" || _CACHED=""',
                '  if [ -n "$_CACHED" ] && [ -x "$_CACHED" ]; then NODE_BIN="$_CACHED"; fi',
                'fi',
                'if ! _node_supports_using "$NODE_BIN"; then',
                '  for nvm_root in "${NVM_DIR:-}" "${HOME:-}/.nvm"; do',
                '    [ -n "$nvm_root" ] || continue',
                '    [ -d "$nvm_root/versions/node" ] || continue',
                '    for candidate in "$nvm_root"/versions/node/v*/bin/node; do',
                '      if [ -x "$candidate" ] && _node_supports_using "$candidate"; then NODE_BIN="$candidate"; break 2; fi',
                "    done",
                "  done",
                "fi",
                'if ! _node_supports_using "$NODE_BIN"; then',
                '  echo "Variant node runtime requires Node with explicit resource management support. Set NODE=/path/to/node 24+." >&2',
                "  exit 127",
                "fi",
                'if [ -n "$NODE_BIN" ] && [ "$NODE_BIN" != "node" ] && [ "$NODE_BIN" != "${NODE:-}" ]; then',
                '  printf "%s" "$NODE_BIN" > "$_NODE_CACHE" 2>/dev/null || true',
                "fi",
                f"ENTRY_PATH={shlex.quote(paths['entryPath'])}",
                'if [ ! -f "$ENTRY_PATH" ]; then echo "Variant entry is missing: $ENTRY_PATH" >&2; exit 127; fi',
            ]
        )
        if model_proxy or local_proxy:
            cleanup_fn = "cleanup_local_proxy" if local_proxy else "cleanup_model_proxy"
            lines.extend(_preserve_exit_launch_lines(f'"$NODE_BIN" "$ENTRY_PATH"{launch_args} "$@"', cleanup_fn))
        else:
            lines.append(f'exec "$NODE_BIN" "$ENTRY_PATH"{launch_args} "$@"')
    else:
        command = f"{shlex.quote(paths['binary'])}{launch_args} \"$@\""
        if model_proxy or local_proxy:
            cleanup_fn = "cleanup_local_proxy" if local_proxy else "cleanup_model_proxy"
            lines.extend(_preserve_exit_launch_lines(command, cleanup_fn))
        else:
            lines.append(f"exec {command}")
    atomic_write_text_no_symlink(wrapper_path, "\n".join(lines) + "\n", mode=0o755)
    if manifest.get("runtime", "native") == "node":
        _prepopulate_node_cache(variant_dir)
    return wrapper_path


def _prepopulate_node_cache(variant_dir: Path) -> None:
    """Resolve a compatible node and write .node-cache during build."""
    import subprocess

    cache_path = variant_dir / ".node-cache"
    probe = "using x = { [Symbol.dispose]() {} };"
    candidates = [os.environ.get("NODE", "")] if os.environ.get("NODE") else []
    nvm_dir = os.environ.get("NVM_DIR", "") or str(Path.home() / ".nvm")
    nvm_node_dir = Path(nvm_dir) / "versions" / "node"
    if nvm_node_dir.is_dir():
        for child in sorted(nvm_node_dir.iterdir()):
            node_bin = child / "bin" / "node"
            if node_bin.is_file():
                candidates.append(str(node_bin))
    for node_bin in candidates:
        if not node_bin:
            continue
        try:
            r = subprocess.run(
                [node_bin, "--input-type=module", "-e", probe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            continue
        if r.returncode != 0:
            continue
        if Path(node_bin).exists():
            try:
                cache_path.write_text(node_bin)
            except OSError:
                pass
        return


def _managed_ccrouter_config(manifest: Dict) -> Optional[Dict]:
    if (manifest.get("provider") or {}).get("key") not in CCR_PROVIDER_KEYS:
        return None
    config = manifest.get("ccrouter")
    if not isinstance(config, dict) or config.get("mode") != "managed":
        return None
    return config


def _model_proxy_config(manifest: Dict) -> Optional[Dict]:
    config = manifest.get("modelProxy")
    if not isinstance(config, dict) or config.get("mode") not in {"architect", "openai"}:
        return None
    return config


def _local_proxy_config(manifest: Dict) -> Optional[Dict]:
    config = manifest.get("localProxy")
    if not isinstance(config, dict):
        return None
    if not str(config.get("binary") or "").strip():
        return None
    if not isinstance(config.get("port"), int) or config["port"] < 1:
        return None
    return config


def _rtk_homebrew_preference_lines(tmp_dir: str) -> list:
    fallback_dir = Path(str(tmp_dir)) / "rtk-fallback" / "bin"
    return [
        "unset CCSILO_RTK_FALLBACK_BIN",
        'if [ -n "${CCSILO_RTK_BIN:-}" ] && [ -x "$CCSILO_RTK_BIN" ]; then',
        '  case "$CCSILO_RTK_BIN" in */*) _ccsilo_rtk_dir="${CCSILO_RTK_BIN%/*}" ;; *) _ccsilo_rtk_dir="." ;; esac',
        "else",
        "  unset CCSILO_RTK_BIN",
        '  _ccsilo_rtk_dir=""',
        "  if command -v brew >/dev/null 2>&1; then",
        '    _ccsilo_rtk_prefix="$(brew --prefix rtk 2>/dev/null || true)"',
        '    if [ -n "$_ccsilo_rtk_prefix" ] && [ -x "$_ccsilo_rtk_prefix/bin/rtk" ]; then',
        '      _ccsilo_rtk_dir="$_ccsilo_rtk_prefix/bin"',
        "    fi",
        "  fi",
        '  if [ -z "$_ccsilo_rtk_dir" ]; then',
        '    if [ "${CCSILO_RTK_HOMEBREW_DIRS+x}" ]; then',
        '      _ccsilo_rtk_homebrew_dirs="$CCSILO_RTK_HOMEBREW_DIRS"',
        "    else",
        '      _ccsilo_rtk_homebrew_dirs="/opt/homebrew/opt/rtk/bin /usr/local/opt/rtk/bin /home/linuxbrew/.linuxbrew/opt/rtk/bin"',
        "    fi",
        '    for _ccsilo_rtk_candidate in $_ccsilo_rtk_homebrew_dirs; do',
        '      if [ -x "$_ccsilo_rtk_candidate/rtk" ]; then _ccsilo_rtk_dir="$_ccsilo_rtk_candidate"; break; fi',
        "    done",
        "  fi",
        '  if [ -n "$_ccsilo_rtk_dir" ]; then',
        '    CCSILO_RTK_BIN="$_ccsilo_rtk_dir/rtk"',
        "  fi",
        '  if [ -z "${CCSILO_RTK_BIN:-}" ]; then',
        '    _ccsilo_path_rtk="$(command -v rtk 2>/dev/null || true)"',
        '    case "$_ccsilo_path_rtk" in */rtk-fallback/bin/rtk) _ccsilo_path_rtk="" ;; esac',
        '    if [ -n "$_ccsilo_path_rtk" ] && [ -x "$_ccsilo_path_rtk" ]; then',
        '      CCSILO_RTK_BIN="$_ccsilo_path_rtk"',
        '      case "$CCSILO_RTK_BIN" in */*) _ccsilo_rtk_dir="${CCSILO_RTK_BIN%/*}" ;; *) _ccsilo_rtk_dir="." ;; esac',
        "    fi",
        "  fi",
        "fi",
        'if [ -n "${CCSILO_RTK_BIN:-}" ] && [ -x "$CCSILO_RTK_BIN" ]; then',
        '  case "$CCSILO_RTK_BIN" in */*) _ccsilo_rtk_dir="${CCSILO_RTK_BIN%/*}" ;; *) _ccsilo_rtk_dir="." ;; esac',
        '  export PATH="$_ccsilo_rtk_dir${PATH:+:$PATH}"',
        "  export CCSILO_RTK_BIN",
        "else",
        "  unset CCSILO_RTK_BIN",
        f"  _ccsilo_rtk_dir={shlex.quote(str(fallback_dir))}",
        '  mkdir -p "$_ccsilo_rtk_dir"',
        '  CCSILO_RTK_FALLBACK_BIN="$_ccsilo_rtk_dir/rtk"',
        '  _ccsilo_rtk_tmp="$CCSILO_RTK_FALLBACK_BIN.$$"',
        '  cat >"$_ccsilo_rtk_tmp" <<\'SH\'',
        "#!/bin/sh",
        'case "${1:-}" in',
        "  --version|-V|version)",
        "    printf '%s\\n' 'ccsilo rtk fallback (real rtk unavailable)'",
        "    exit 0",
        "    ;;",
        "  gain)",
        "    printf '%s\\n' 'ccsilo rtk fallback: real rtk unavailable; no gain data'",
        "    exit 0",
        "    ;;",
        "esac",
        'if [ "$#" -eq 0 ]; then',
        "  printf '%s\\n' 'ccsilo rtk fallback: pass a command to run' >&2",
        "  exit 2",
        "fi",
        'if [ "$#" -gt 0 ]; then',
        '  exec "$@"',
        "fi",
        "SH",
        '  chmod 755 "$_ccsilo_rtk_tmp"',
        '  mv "$_ccsilo_rtk_tmp" "$CCSILO_RTK_FALLBACK_BIN"',
        '  export PATH="$_ccsilo_rtk_dir${PATH:+:$PATH}"',
        "  export CCSILO_RTK_FALLBACK_BIN",
        "fi",
        "unset _ccsilo_rtk_dir _ccsilo_rtk_prefix _ccsilo_rtk_candidate _ccsilo_rtk_homebrew_dirs _ccsilo_path_rtk _ccsilo_rtk_tmp",
    ]


def _ccrouter_home_lines(manifest: Dict, config: Dict) -> list:
    paths = manifest["paths"]
    runtime_bin = Path(str(config.get("runtimeDir") or "")) / "node_modules" / ".bin"
    return [
        f"export HOME={shlex.quote(str(config['homeDir']))}",
        'export USERPROFILE="$HOME"',
        f"export TMPDIR={shlex.quote(paths['tmpDir'])}",
        f"export PATH={shlex.quote(str(runtime_bin))}:$PATH",
    ]


def _ccrouter_runtime_lines(manifest: Dict, config: Dict) -> list:
    auto_start = "1" if config.get("autoStart", True) else "0"
    return [
        f"CCR_CONFIG={shlex.quote(str(config.get('configPath') or Path(str(config['homeDir'])) / '.claude-code-router' / 'config.json'))}",
        f"CCR_PID_FILE={shlex.quote(str(Path(str(config['homeDir'])) / '.claude-code-router' / '.claude-code-router.pid'))}",
        f"CCR_LOG={shlex.quote(str(Path(manifest['paths']['tmpDir']) / 'ccrouter.log'))}",
        f"CCR_AUTOSTART={auto_start}",
        'if [ ! -f "$CCR_CONFIG" ]; then echo "CCR config is missing: $CCR_CONFIG" >&2; exit 127; fi',
        'if ! command -v ccr >/dev/null 2>&1; then echo "Managed CCR command is missing. Reapply this setup." >&2; exit 127; fi',
        '_ccr_running() {',
        '  [ -f "$CCR_PID_FILE" ] || return 1',
        '  _ccr_pid="$(cat "$CCR_PID_FILE" 2>/dev/null || true)"',
        '  [ -n "$_ccr_pid" ] || return 1',
        '  kill -0 "$_ccr_pid" 2>/dev/null',
        '}',
        'if [ "$CCR_AUTOSTART" = "1" ] && ! _ccr_running; then',
        '  ccr start >>"$CCR_LOG" 2>&1 &',
        '  _ccr_wait=0',
        '  while [ "$_ccr_wait" -lt 50 ]; do',
        '    _ccr_running && break',
        '    _ccr_wait=$((_ccr_wait + 1))',
        '    sleep 0.2',
        '  done',
        "fi",
        'if ! _ccr_running; then echo "CCR service is not running. See $CCR_LOG" >&2; exit 127; fi',
        '_ccr_env_file="$VARIANT_ROOT/tmp/ccrouter-env.sh"',
        'python3 - "$CCR_CONFIG" >"$_ccr_env_file" <<\'PY\'',
        "import json",
        "import shlex",
        "import sys",
        "",
        "with open(sys.argv[1], encoding=\"utf-8\") as handle:",
        "    config = json.load(handle)",
        "if not isinstance(config, dict):",
        "    raise SystemExit(\"CCR config must be a JSON object\")",
        "port = int(config.get(\"PORT\") or 3456)",
        "if port < 1 or port > 65535:",
        "    raise SystemExit(\"CCR PORT must be between 1 and 65535\")",
        "env = {",
        "    \"ANTHROPIC_BASE_URL\": f\"http://127.0.0.1:{port}\",",
        "    \"ANTHROPIC_AUTH_TOKEN\": str(config.get(\"APIKEY\") or \"ccrouter-proxy\"),",
        "    \"NO_PROXY\": \"127.0.0.1\",",
        "    \"DISABLE_TELEMETRY\": \"true\",",
        "    \"DISABLE_COST_WARNINGS\": \"true\",",
        "    \"API_TIMEOUT_MS\": str(config.get(\"API_TIMEOUT_MS\") or \"600000\"),",
        "}",
        "for key, value in env.items():",
        "    print(f\"export {key}={shlex.quote(value)}\")",
        "PY",
        '. "$_ccr_env_file"',
    ]


def _model_proxy_runtime_lines(manifest: Dict, config: Dict) -> list:
    source = require_env_name(config.get("credentialEnv"), label="model proxy credential env")
    port = str(config.get("port") or "auto")
    if port == "0":
        port = "auto"
    python = shlex.quote(str(config.get("pythonExecutable") or "python3"))
    auth_lines = (
        ["unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN"]
        if config.get("mode") == "architect"
        else ['export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-unused}"', "unset ANTHROPIC_API_KEY"]
    )
    return [
        'MODEL_PROXY_PID=""',
        "cleanup_model_proxy() {",
        '  if [ -n "${MODEL_PROXY_PID:-}" ] && kill -0 "$MODEL_PROXY_PID" 2>/dev/null; then',
        '    kill "$MODEL_PROXY_PID" 2>/dev/null || true',
        '    wait "$MODEL_PROXY_PID" 2>/dev/null || true',
        "  fi",
        "}",
        "trap cleanup_model_proxy EXIT INT TERM",
        f"MODEL_PROXY_CONFIG={shlex.quote(str(config['runtimeConfigPath']))}",
        f"MODEL_PROXY_PORT_FILE={shlex.quote(str(config['portFilePath']))}",
        f"MODEL_PROXY_LOG={shlex.quote(str(config['logPath']))}",
        'mkdir -p "$(dirname "$MODEL_PROXY_PORT_FILE")" "$(dirname "$MODEL_PROXY_LOG")"',
        'rm -f "$MODEL_PROXY_PORT_FILE"',
        f": ${{{source}:?Set {source} for variant {manifest['id']}}}",
        f'MODEL_PROXY_AUTH_NONCE="$({python} -c \'import secrets; print(secrets.token_urlsafe(24))\')"',
        'if [ -z "$MODEL_PROXY_AUTH_NONCE" ]; then echo "Model proxy auth nonce generation failed." >&2; exit 127; fi',
        f'CCSILO_MODEL_PROXY_API_KEY="${{{source}}}"',
        'CCSILO_MODEL_PROXY_AUTH_NONCE="$MODEL_PROXY_AUTH_NONCE"',
        "export CCSILO_MODEL_PROXY_API_KEY",
        "export CCSILO_MODEL_PROXY_AUTH_NONCE",
        (
            f"{python} -m ccsilo.model_proxy "
            f'--config "$MODEL_PROXY_CONFIG" --port {shlex.quote(port)} --port-file "$MODEL_PROXY_PORT_FILE" '
            '>>"$MODEL_PROXY_LOG" 2>&1 &'
        ),
        "MODEL_PROXY_PID=$!",
        "unset CCSILO_MODEL_PROXY_API_KEY CCSILO_MODEL_PROXY_AUTH_NONCE",
        f"unset {source}",
        "_model_proxy_wait=0",
        'while [ "$_model_proxy_wait" -lt 50 ]; do',
        '  [ -s "$MODEL_PROXY_PORT_FILE" ] && break',
        '  if ! kill -0 "$MODEL_PROXY_PID" 2>/dev/null; then echo "Model proxy exited early. See $MODEL_PROXY_LOG" >&2; exit 127; fi',
        '  _model_proxy_wait=$((_model_proxy_wait + 1))',
        "  sleep 0.2",
        "done",
        'if [ ! -s "$MODEL_PROXY_PORT_FILE" ]; then echo "Model proxy did not start. See $MODEL_PROXY_LOG" >&2; exit 127; fi',
        'MODEL_PROXY_ACTUAL_PORT="$(cat "$MODEL_PROXY_PORT_FILE")"',
        'export ANTHROPIC_BASE_URL="http://127.0.0.1:$MODEL_PROXY_ACTUAL_PORT/$MODEL_PROXY_AUTH_NONCE"',
        *auth_lines,
        'case "${NO_PROXY:-}" in *127.0.0.1*) ;; "") export NO_PROXY=127.0.0.1,localhost ;; *) export NO_PROXY="127.0.0.1,localhost,$NO_PROXY" ;; esac',
    ]


def _local_proxy_runtime_lines(manifest: Dict, config: Dict) -> list:
    binary = str(config.get("binary") or "").strip()
    resolved = find_anyllm_proxy_binary() or binary
    port = int(config.get("port") or 0)
    key = str(config.get("key") or "").strip()
    args = [str(a) for a in (config.get("args") or [])]
    log_path = str(config.get("logPath") or "").strip()
    # If the proxy is already listening on the port, reuse it instead of launching a second copy.
    port_probe = (
        "python3 -c "
        '"import socket,sys; s=socket.socket(); s.settimeout(0.3); '
        f"s.connect(('127.0.0.1', {port})); s.close(); sys.exit(0)\" 2>/dev/null"
    )
    proxy_args = " ".join(shlex.quote(a) for a in args)
    launch = (
        f"{shlex.quote(resolved)} {proxy_args} "
        f'>>"{shlex.quote(log_path)}" 2>&1 &' if log_path else f"{shlex.quote(resolved)} {proxy_args} &"
    )
    lines = [
        'LOCAL_PROXY_PID=""',
        "cleanup_local_proxy() {",
        '  if [ -n "${LOCAL_PROXY_PID:-}" ] && kill -0 "$LOCAL_PROXY_PID" 2>/dev/null; then',
        '    kill "$LOCAL_PROXY_PID" 2>/dev/null || true',
        '    wait "$LOCAL_PROXY_PID" 2>/dev/null || true',
        "  fi",
        "}",
        "trap cleanup_local_proxy EXIT INT TERM",
        f"export PROXY_API_KEYS={shlex.quote(key)}",
        f"export ANTHROPIC_AUTH_TOKEN={shlex.quote(key)}",
        f"case \"{key}\" in \"\") echo \"AnyLLM proxy key is missing from the variant manifest.\" >&2; exit 127 ;; esac",
    ]
    if log_path:
        lines.append(f"mkdir -p \"$(dirname {shlex.quote(log_path)})\"")
    lines += [
        f"if {port_probe}; then",
        '  echo "AnyLLM proxy already listening on 127.0.0.1:' + str(port) + '; reusing it."',
        "else",
        '  echo "Starting AnyLLM proxy (admin UI: ' + str(config.get("adminUrl") or "http://127.0.0.1:3001/admin/") + ')..."',
        "  " + launch,
        "  LOCAL_PROXY_PID=$!",
        "  _local_proxy_wait=0",
        '  while [ "$_local_proxy_wait" -lt 50 ]; do',
        f"    {port_probe} && break",
        '    if ! kill -0 "$LOCAL_PROXY_PID" 2>/dev/null; then echo "AnyLLM proxy exited early. See ' + shlex.quote(log_path) + '" >&2; exit 127; fi',
        '    _local_proxy_wait=$((_local_proxy_wait + 1))',
        "    sleep 0.2",
        "  done",
        '  if ! ' + port_probe + "; then echo \"AnyLLM proxy did not start on 127.0.0.1:" + str(port) + '. See ' + shlex.quote(log_path) + '" >&2; exit 127; fi',
        "fi",
        f"export ANTHROPIC_BASE_URL={shlex.quote(f'http://127.0.0.1:{port}')}",
        'case "${NO_PROXY:-}" in *127.0.0.1*) ;; "") export NO_PROXY=127.0.0.1,localhost ;; *) export NO_PROXY="127.0.0.1,localhost,$NO_PROXY" ;; esac',
    ]
    return lines


def _preserve_exit_launch_lines(command: str, cleanup_fn: str = "cleanup_model_proxy") -> list:
    return [
        "set +e",
        command,
        "_cc_status=$?",
        "set -e",
        cleanup_fn,
        'exit "$_cc_status"',
    ]


def _launch_args(manifest: Dict) -> str:
    args = []
    if "dangerously-skip-permissions" in (manifest.get("tweaks") or []):
        args.append("--dangerously-skip-permissions")
    if not args:
        return ""
    return " " + " ".join(shlex.quote(arg) for arg in args)


def _api_key_approval_bootstrap_lines():
    return [
        'if [ -n "${ANTHROPIC_API_KEY:-}" ] && command -v python3 >/dev/null 2>&1; then',
        '  python3 - "$CLAUDE_CONFIG_DIR/.claude.json" <<\'PY\' >/dev/null 2>&1 || true',
        "import json",
        "import os",
        "import pathlib",
        "import stat",
        "import sys",
        "",
        'key = os.environ.get("ANTHROPIC_API_KEY", "")',
        "suffix = key[-20:]",
        "if not suffix:",
        "    raise SystemExit(0)",
        "path = pathlib.Path(sys.argv[1])",
        "if path.exists() or path.is_symlink():",
        "    mode = path.lstat().st_mode",
        "    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):",
        "        raise SystemExit(0)",
        "    try:",
        "        data = json.loads(path.read_text(encoding=\"utf-8\"))",
        "    except Exception:",
        "        raise SystemExit(0)",
        "else:",
        "    data = {}",
        "responses = data.get(\"customApiKeyResponses\")",
        "if not isinstance(responses, dict):",
        "    responses = {}",
        "approved = responses.get(\"approved\")",
        "if not isinstance(approved, list):",
        "    approved = []",
        "rejected = responses.get(\"rejected\")",
        "if not isinstance(rejected, list):",
        "    rejected = []",
        "if suffix not in approved:",
        "    approved.append(suffix)",
        "responses[\"approved\"] = approved",
        "responses[\"rejected\"] = [item for item in rejected if item != suffix]",
        "data[\"customApiKeyResponses\"] = responses",
        "path.parent.mkdir(parents=True, exist_ok=True)",
        "tmp = path.with_name(f\".{path.name}.ccsilo-auth.tmp\")",
        "if tmp.exists() or tmp.is_symlink():",
        "    tmp.unlink()",
        "tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + \"\\n\", encoding=\"utf-8\")",
        "os.replace(tmp, path)",
        "PY",
        "fi",
    ]


def write_secrets(path: Path, secret_env: Dict[str, str]) -> None:
    lines = [
        f"export {require_env_name(key, label='secret env key')}={shlex.quote(str(value))}"
        for key, value in sorted(secret_env.items())
    ]
    atomic_write_text_no_symlink(path, "\n".join(lines) + "\n", mode=SECRETS_FILE_MODE)

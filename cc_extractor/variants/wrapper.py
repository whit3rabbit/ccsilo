"""Variant wrapper script + secrets/config writers."""

import os
import shlex
import stat
from pathlib import Path
from typing import Dict, Optional

from .._utils import atomic_write_text_no_symlink, require_env_name, utc_now as _utc_now
from ..providers import (
    apply_provider_claude_config,
    get_provider,
    provider_auth_bootstrap_enabled,
    provider_patch_config,
)
from ..workspace import read_json, write_json
from .splash import shell_splash_lines

SECRETS_FILE = "secrets.env"
SECRETS_FILE_MODE = 0o600


def write_variant_config(manifest: Dict) -> None:
    paths = manifest["paths"]
    env = dict(manifest.get("env", {}))
    write_json(Path(paths["configDir"]) / "settings.json", {"env": env})
    apply_provider_claude_config(
        manifest["provider"]["key"],
        paths["configDir"],
        optional_mcp_ids=(manifest.get("mcp") or {}).get("selected", []),
        read_json=read_json,
        write_json=write_json,
    )
    tweak_config = provider_patch_config(manifest["provider"]["key"])
    tweak_config["ccInstallationPath"] = paths["binary"]
    tweak_config["lastModified"] = _utc_now()
    write_json(Path(paths["tweakccDir"]) / "config.json", tweak_config)


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
    for key, value in sorted(manifest.get("env", {}).items()):
        env_key = require_env_name(key, label="wrapper env key")
        lines.append(f"export {env_key}={shlex.quote(str(value))}")
    for key in manifest.get("envUnset") or []:
        env_key = require_env_name(key, label="wrapper unset env key")
        lines.append(f"unset {env_key}")
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
        for target in targets:
            lines.append(f"export {target}=\"${{{source}}}\"")
    if provider_auth_bootstrap_enabled(manifest["provider"]["key"]):
        lines.extend(_api_key_approval_bootstrap_lines())
    lines.extend(shell_splash_lines())
    launch_args = _launch_args(manifest)
    if manifest.get("runtime", "native") == "node":
        lines.extend(
            [
                'NODE_BIN="${NODE:-node}"',
                "_NODE_USING_PROBE='using x = { [Symbol.dispose]() {} };'",
                '_node_supports_using() { "$1" --input-type=module -e "$_NODE_USING_PROBE" >/dev/null 2>&1; }',
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
                f"ENTRY_PATH={shlex.quote(paths['entryPath'])}",
                'if [ ! -f "$ENTRY_PATH" ]; then echo "Variant entry is missing: $ENTRY_PATH" >&2; exit 127; fi',
                f'exec "$NODE_BIN" "$ENTRY_PATH"{launch_args} "$@"',
            ]
        )
    else:
        lines.append(f"exec {shlex.quote(paths['binary'])}{launch_args} \"$@\"")
    atomic_write_text_no_symlink(wrapper_path, "\n".join(lines) + "\n", mode=0o755)
    return wrapper_path


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
        "tmp = path.with_name(f\".{path.name}.cc-extractor-auth.tmp\")",
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

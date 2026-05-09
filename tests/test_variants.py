import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccsilo.binary_patcher.bun_compat import BUN_NODE_COMPAT_MARKER
from ccsilo.bun_extract import parse_bun_binary
from ccsilo.variants import (
    VariantBuildError,
    apply_variant,
    create_variant,
    default_install_dir,
    discover_install_candidates,
    doctor_variant,
    inspect_variant_command_install,
    install_variant_command,
    list_variant_providers,
    load_variant,
    preflight_variant_command_install,
    remove_variant,
    run_variant,
    scan_variants,
    uninstall_workspace,
    update_variants,
    update_variant_models,
)
from ccsilo.variants.model import Variant
from ccsilo.variants.ccrouter import (
    CCR_PACKAGE_DEFAULT,
)
from ccsilo.variants.builder import patch_entry_js
from ccsilo.variants.wrapper import write_wrapper
from ccsilo.variants.wrapper import write_secrets
from ccsilo.variant_tweaks import GATEWAY_MODEL_DISCOVERY_ENV, GATEWAY_MODEL_DISCOVERY_TWEAK_ID
from ccsilo.workspace import NativeArtifact
from tests.helpers.bun_fixture import build_bun_fixture


ENTRY_JS = "\n".join(
    [
        'function getNames(){return{"dark":"Dark mode","light":"Light mode"}}',
        'const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];',
        'function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}',
        'let WEBFETCH=`Fetches URLs.\\n- For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, gh issue view, gh api).`;',
        'const version=`${pkg.VERSION} (Claude Code)`;',
        ',R.createElement(B,{isBeforeFirstMessage:!1}),',
        'function inner(){return"\\u259B\\u2588\\u2588\\u2588\\u259C"}function wrapper(){return R.createElement(inner,{})}',
    ]
)


def write_source_artifact(tmp_path, version="2.1.0"):
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[{"name": "src/cli.js", "content": ENTRY_JS}],
        entry_point_id=0,
    )
    path = tmp_path / "claude"
    path.write_bytes(fixture["buf"])
    sha256 = hashlib.sha256(fixture["buf"]).hexdigest()
    return NativeArtifact(
        version=version,
        platform="linux-x64",
        sha256=sha256,
        path=path,
        metadata={},
    )


def write_macho_source_artifact(tmp_path, version="2.1.0"):
    fixture = build_bun_fixture(
        platform="macho",
        module_struct_size=52,
        modules=[{"name": "src/cli.js", "content": ENTRY_JS}],
        entry_point_id=0,
    )
    path = tmp_path / "claude-macho"
    path.write_bytes(fixture["buf"])
    sha256 = hashlib.sha256(fixture["buf"]).hexdigest()
    return NativeArtifact(
        version=version,
        platform="darwin-arm64",
        sha256=sha256,
        path=path,
        metadata={},
    )


def read_entry(binary_path):
    data = Path(binary_path).read_bytes()
    info = parse_bun_binary(data)
    entry = info.modules[info.entry_point_id]
    return data[info.data_start + entry.cont_off : info.data_start + entry.cont_off + entry.cont_len].decode("utf-8")


def stub_ccrouter_npm(monkeypatch):
    import ccsilo.variants.ccrouter as ccrouter_module

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "npm":
            runtime_dir = Path(command[command.index("--prefix") + 1])
            package_dir = runtime_dir / "node_modules" / "@musistudio" / "claude-code-router"
            package_dir.mkdir(parents=True, exist_ok=True)
            (package_dir / "package.json").write_text('{"version":"2.0.0"}\n', encoding="utf-8")
            bin_dir = runtime_dir / "node_modules" / ".bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            ccr = bin_dir / "ccr"
            ccr.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            ccr.chmod(0o755)
        if command[0] == "node":
            return SimpleNamespace(returncode=0, stdout="v20.0.0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ccrouter_module.subprocess, "run", fake_run)
    return calls


def run_in_pty(command):
    if os.name == "nt":
        pytest.skip("PTY capture is POSIX-only")
    import pty
    import select

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    chunks = []
    try:
        while True:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            if proc.poll() is not None and not ready:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)
        os.close(master_fd)
    proc.wait(timeout=2)
    return b"".join(chunks).decode("utf-8", "replace")


def wrapper_manifest(tmp_path, env):
    variant_root = tmp_path / "variant"
    binary = variant_root / "native" / "claude"
    wrapper = tmp_path / "bin" / "sample"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\nprintf 'RUN:%s\\n' \"$*\"\n", encoding="utf-8")
    os.chmod(binary, 0o755)
    return {
        "id": "sample",
        "provider": {"key": "mirror"},
        "env": env,
        "credential": {"mode": "none", "targets": []},
        "paths": {
            "root": str(variant_root),
            "wrapper": str(wrapper),
            "configDir": str(variant_root / "config"),
            "tweakccDir": str(variant_root / "tweakcc"),
            "tmpDir": str(variant_root / "tmp"),
            "binary": str(binary),
        },
    }


def install_test_variant(root, wrapper):
    variant_dir = root / "variants" / "demo"
    variant_dir.mkdir(parents=True, exist_ok=True)
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    manifest = {
        "schemaVersion": 1,
        "id": "demo",
        "name": "Demo",
        "provider": {"key": "mirror"},
        "source": {"version": "1.2.3"},
        "paths": {"wrapper": str(wrapper)},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    (variant_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Variant("demo", "Demo", variant_dir, manifest)


def test_install_candidate_detection_prefers_common_home_bins(tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    home_bin = home / "bin"
    tools_bin = home / "tools" / "bin"
    for path in (tools_bin, home_bin, local_bin):
        path.mkdir(parents=True)
    env = {
        "HOME": str(home),
        "PATH": os.pathsep.join([str(tools_bin), str(home_bin), "/usr/bin"]),
    }

    candidates = discover_install_candidates(env=env)

    assert [candidate.path for candidate in candidates] == [local_bin, home_bin, tools_bin]
    assert [candidate.on_path for candidate in candidates] == [False, True, True]
    assert default_install_dir(env=env) == local_bin


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_install_variant_command_records_symlink_and_refuses_unmanaged_target(tmp_path):
    root = tmp_path / ".ccsilo"
    install_dir = tmp_path / "home" / ".local" / "bin"
    install_dir.mkdir(parents=True)
    variant = install_test_variant(root, root / "bin" / "demo")

    result = install_variant_command(variant, bin_dir=install_dir)

    assert result.status == "installed"
    assert result.path == install_dir / "demo"
    assert result.path.is_symlink()
    assert result.path.resolve() == (root / "bin" / "demo").resolve()
    manifest = json.loads((variant.path / "variant.json").read_text(encoding="utf-8"))
    assert manifest["installs"][0]["alias"] == "demo"
    assert manifest["installs"][0]["managedBy"] == "ccsilo"

    second = install_variant_command(variant, bin_dir=install_dir)
    assert second.status == "already-installed"

    result.path.unlink()
    other = tmp_path / "other-wrapper"
    other.write_text("#!/bin/sh\n", encoding="utf-8")
    os.symlink(other, result.path)
    with pytest.raises(ValueError, match="pointing elsewhere"):
        install_variant_command(variant, bin_dir=install_dir)


def test_preflight_variant_command_install_refuses_blocked_command_without_creating_dir(tmp_path):
    install_dir = tmp_path / "home" / ".local" / "bin"
    install_dir.mkdir(parents=True)
    blocked = install_dir / "demo"
    blocked.write_text("#!/bin/sh\n", encoding="utf-8")
    target = tmp_path / ".ccsilo" / "bin" / "demo"

    with pytest.raises(ValueError, match="Refusing to overwrite non-symlink command"):
        preflight_variant_command_install("demo", target=target, bin_dir=install_dir)

    missing_dir = tmp_path / "home" / "new-bin"
    result = preflight_variant_command_install("demo", target=target, bin_dir=missing_dir, yes=True)

    assert result.status == "available"
    assert result.path == missing_dir / "demo"
    assert not missing_dir.exists()
    assert blocked.read_text(encoding="utf-8") == "#!/bin/sh\n"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_inspect_variant_command_install_classifies_existing_command_states(tmp_path):
    install_dir = tmp_path / "home" / ".local" / "bin"
    install_dir.mkdir(parents=True)
    target = tmp_path / ".ccsilo" / "bin" / "demo"

    available = inspect_variant_command_install("demo", target=target, bin_dir=install_dir)
    assert available.status == "available"

    command = install_dir / "demo"
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    blocked_file = inspect_variant_command_install("demo", target=target, bin_dir=install_dir)
    assert blocked_file.status == "blocked"
    assert "non-symlink command" in blocked_file.warning
    command.unlink()

    os.symlink(target, command)
    already_installed = inspect_variant_command_install("demo", target=target, bin_dir=install_dir)
    assert already_installed.status == "already-installed"
    command.unlink()

    other = tmp_path / "other-wrapper"
    os.symlink(other, command)
    blocked_symlink = inspect_variant_command_install("demo", target=target, bin_dir=install_dir)
    assert blocked_symlink.status == "blocked"
    assert "symlink pointing elsewhere" in blocked_symlink.warning


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_uninstall_workspace_removes_managed_symlinks_and_workspace(tmp_path):
    root = tmp_path / ".ccsilo"
    install_dir = tmp_path / "home" / ".local" / "bin"
    install_dir.mkdir(parents=True)
    variant = install_test_variant(root, root / "bin" / "demo")
    result = install_variant_command(variant, bin_dir=install_dir)

    with pytest.raises(ValueError, match="--yes"):
        uninstall_workspace(root=root)

    uninstall_result = uninstall_workspace(root=root, yes=True)

    assert uninstall_result.removed_workspace is True
    assert not root.exists()
    assert not result.path.exists()
    assert not result.path.is_symlink()
    assert uninstall_result.removed_symlinks[0].path == str(result.path)


def test_create_variant_writes_isolated_layout_wrapper_and_metadata(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    original = artifact.path.read_bytes()

    result = create_variant(
        name="Zai Test",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    assert artifact.path.read_bytes() == original
    assert result.variant.variant_id == "zai-test"
    assert result.binary_path == root / "variants" / "zai-test" / "native" / "claude"
    assert result.wrapper_path == root / "bin" / "zai-test"
    assert (root / "variants" / "zai-test" / "config" / "settings.json").exists()
    assert (root / "variants" / "zai-test" / "config" / ".claude.json").exists()
    assert (root / "variants" / "zai-test" / "tweakcc" / "config.json").exists()
    assert doctor_variant("zai-test", root=root)[0]["ok"] is True

    entry_js = read_entry(result.binary_path)
    assert "cc-mirror:provider-overlay start" in entry_js
    assert 'case"zai-variant"' in entry_js
    assert "isBeforeFirstMessage" not in entry_js

    wrapper = result.wrapper_path.read_text(encoding="utf-8")
    assert "CLAUDE_CONFIG_DIR" in wrapper
    assert "${Z_AI_API_KEY:?Set Z_AI_API_KEY for variant zai-test}" in wrapper
    assert "ANTHROPIC_API_KEY=\"${Z_AI_API_KEY}\"" in wrapper
    credential_export = 'export ANTHROPIC_API_KEY="${Z_AI_API_KEY}"'
    assert wrapper.index(credential_export) < wrapper.index("customApiKeyResponses") < wrapper.index("\nexec ")
    assert "++++++++" in wrapper
    assert result.variant.manifest["env"]["CCSILO_SPLASH"] == "1"
    assert result.variant.manifest["env"]["CCSILO_SPLASH_STYLE"] == "zai"
    assert result.variant.manifest["tweaks"] == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
        "suppress-native-installer-warning",
        "suppress-prompt-caching-warning",
        "suppress-model-launch-notice",
        "mcp-non-blocking",
        "mcp-batch-size",
        "rtk-shell-prefix",
        "dangerously-skip-permissions",
        "disable-telemetry",
        "disable-error-reporting",
        "disable-feedback-command",
        "disable-feedback-survey",
        "disable-prompt-caching",
    ]
    assert result.variant.manifest["env"]["MCP_SERVER_CONNECTION_BATCH_SIZE"] == "10"
    assert result.variant.manifest["env"]["DISABLE_TELEMETRY"] == "1"
    assert result.variant.manifest["env"]["DISABLE_PROMPT_CACHING"] == "1"
    assert scan_variants(root)[0].variant_id == "zai-test"
    stage_names = [stage.name for stage in result.stages]
    assert "prepare directories" in stage_names
    assert {"patch binary", "extract patch repack"} & set(stage_names)
    assert "write setup config" in stage_names
    assert all(stage.status == "ok" for stage in result.stages)

    settings = json.loads((root / "variants" / "zai-test" / "config" / "settings.json").read_text(encoding="utf-8"))
    claude_config = json.loads((root / "variants" / "zai-test" / "config" / ".claude.json").read_text(encoding="utf-8"))
    assert settings["forceLoginMethod"] == "console"
    assert "mcp__web_reader__webReader" in settings["permissions"]["deny"]
    assert sorted(claude_config["mcpServers"]) == ["web-reader", "web-search-prime", "zai-mcp-server", "zread"]
    assert claude_config["mcpServers"]["web-reader"]["headers"] == {"Authorization": "Bearer ${Z_AI_API_KEY}"}
    assert result.variant.manifest["mcp"]["selected"] == []


def test_create_variant_with_source_binary_imports_without_download(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    def fail_download(*_args, **_kwargs):
        raise AssertionError("source_binary should not download")

    monkeypatch.setattr(variants_module, "download_binary", fail_download)

    result = create_variant(
        name="Local Source",
        provider_key="mirror",
        claude_version="2.1.122",
        source_binary=artifact.path,
        source_platform="linux-x64",
        root=root,
        force=True,
    )

    source = result.variant.manifest["source"]
    stage_names = [stage.name for stage in result.stages]

    assert source["type"] == "local-binary"
    assert source["version"] == "2.1.122"
    assert source["platform"] == "linux-x64"
    assert source["importedFrom"] == str(artifact.path.resolve())
    assert Path(source["path"]).is_file()
    assert Path(source["path"]) != artifact.path
    assert artifact.path.exists()
    assert "download source" not in stage_names


def test_apply_variant_reuses_imported_source_binary_offline(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    result = create_variant(
        name="Offline Local",
        provider_key="mirror",
        claude_version="2.1.122",
        source_binary=artifact.path,
        source_platform="linux-x64",
        root=root,
        force=True,
    )
    artifact.path.unlink()

    def fail_download(*_args, **_kwargs):
        raise AssertionError("local-binary apply should not download")

    monkeypatch.setattr(variants_module, "_download_source_artifact", fail_download)

    reapplied = apply_variant("offline-local", root=root)

    assert reapplied.variant.manifest["source"]["path"] == result.variant.manifest["source"]["path"]
    assert reapplied.variant.manifest["source"]["type"] == "local-binary"


def test_apply_variant_reports_missing_or_changed_imported_source(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    result = create_variant(
        name="Missing Local",
        provider_key="mirror",
        claude_version="2.1.122",
        source_binary=artifact.path,
        source_platform="linux-x64",
        root=root,
        force=True,
    )
    managed_source = Path(result.variant.manifest["source"]["path"])
    managed_source.unlink()

    with pytest.raises(VariantBuildError, match="local source binary is missing"):
        apply_variant("missing-local", root=root)

    result = create_variant(
        name="Changed Local",
        provider_key="mirror",
        claude_version="2.1.122",
        source_binary=artifact.path,
        source_platform="linux-x64",
        root=root,
        force=True,
    )
    managed_source = Path(result.variant.manifest["source"]["path"])
    managed_source.write_bytes(b"changed")

    with pytest.raises(VariantBuildError, match="hash changed"):
        apply_variant("changed-local", root=root)


def test_update_variant_can_replace_local_source_binary(tmp_path):
    root = tmp_path / ".ccsilo"
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    first = write_source_artifact(first_dir)
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second_fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[{"name": "src/cli.js", "content": ENTRY_JS + "\nconsole.log('second');"}],
        entry_point_id=0,
    )
    second_path = second_dir / "claude"
    second_path.write_bytes(second_fixture["buf"])

    create_variant(
        name="Replace Local",
        provider_key="mirror",
        claude_version="2.1.121",
        source_binary=first.path,
        source_platform="linux-x64",
        root=root,
        force=True,
    )

    updated = update_variants(
        "replace-local",
        claude_version="2.1.122",
        source_binary=second_path,
        source_platform="linux-x64",
        root=root,
    )[0]

    source = updated.variant.manifest["source"]
    assert source["type"] == "local-binary"
    assert source["version"] == "2.1.122"
    assert source["importedFrom"] == str(second_path.resolve())
    assert Path(source["path"]).read_bytes() == second_path.read_bytes()


def test_update_all_rejects_source_binary(tmp_path):
    source = write_source_artifact(tmp_path).path

    with pytest.raises(ValueError, match="only be used when updating one variant"):
        update_variants(
            all_variants=True,
            claude_version="2.1.122",
            source_binary=source,
            root=tmp_path / ".ccsilo",
        )


def test_create_ccrouter_variant_prepares_managed_runtime_and_isolated_config(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    home = tmp_path / "home"
    global_config = home / ".claude-code-router" / "config.json"
    global_config.parent.mkdir(parents=True)
    global_config.write_text(
        json.dumps({"PORT": 3456, "APIKEY": "global-token", "API_TIMEOUT_MS": 12345, "Providers": [], "Router": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    npm_calls = stub_ccrouter_npm(monkeypatch)

    result = create_variant(
        name="CCR Test",
        provider_key="ccrouter",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    wrapper = result.wrapper_path.read_text(encoding="utf-8")
    manifest = result.variant.manifest
    ccrouter = manifest["ccrouter"]
    isolated_config = Path(ccrouter["configPath"])
    isolated_payload = json.loads(isolated_config.read_text(encoding="utf-8"))
    global_payload = json.loads(global_config.read_text(encoding="utf-8"))

    assert npm_calls and npm_calls[0][:4] == ["npm", "install", "--prefix", str(root / "variants" / "ccr-test" / "ccr-runtime")]
    assert ccrouter["mode"] == "managed"
    assert ccrouter["configMode"] == "copy-global"
    assert ccrouter["packageSpec"] == CCR_PACKAGE_DEFAULT
    assert ccrouter["installedVersion"] == "2.0.0"
    assert ccrouter["homeDir"] == str(root / "variants" / "ccr-test" / "ccr-home")
    assert ccrouter["tmpDir"] == str(root / "variants" / "ccr-test" / "tmp")
    assert isolated_payload["APIKEY"] == "global-token"
    assert isolated_payload["PORT"] == ccrouter["port"]
    assert global_payload["PORT"] == 3456
    assert manifest["env"]["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{ccrouter['port']}"
    assert manifest["env"]["ANTHROPIC_AUTH_TOKEN"] == "global-token"
    assert result.variant.manifest["envUnset"] == ["CLAUDE_CODE_USE_BEDROCK"]
    assert "unset CLAUDE_CODE_USE_BEDROCK" in wrapper
    assert f"export HOME={ccrouter['homeDir']}" in wrapper
    assert "ccr start" in wrapper
    assert "ccr code" not in wrapper
    assert "eval $(" not in wrapper
    assert 'python3 - "$CCR_CONFIG"' in wrapper
    assert wrapper.index("unset CLAUDE_CODE_USE_BEDROCK") < wrapper.index("ccr start") < wrapper.index("\nexec ")


def test_create_variant_persists_base_url_override(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="LM Local",
        provider_key="lmstudio",
        base_url="http://localhost:4567",
        model_overrides={"opus": "local-model", "sonnet": "local-model", "haiku": "local-model"},
        root=root,
        source_artifact=artifact,
        force=True,
    )

    wrapper = result.wrapper_path.read_text(encoding="utf-8")

    assert result.variant.manifest["env"]["ANTHROPIC_BASE_URL"] == "http://localhost:4567"
    assert "export ANTHROPIC_BASE_URL=http://localhost:4567" in wrapper


def test_variant_provider_payload_exposes_ccrouter_env_unset():
    providers = {provider["key"]: provider for provider in list_variant_providers()}

    assert providers["ccrouter"]["envUnset"] == ["CLAUDE_CODE_USE_BEDROCK"]
    assert providers["ccrouter"]["splashStyle"] == "ccrouter"
    assert "CC ROUTER" in providers["ccrouter"]["asciiArt"]
    assert "\033" not in providers["ccrouter"]["asciiArt"]
    assert providers["ccrouter"]["asciiArtQuoteBlock"].startswith("> +")


def test_variant_cli_provider_quote_blocks(monkeypatch, capsys):
    from ccsilo import __main__ as cli
    import sys

    monkeypatch.setattr(
        cli,
        "list_variant_providers",
        lambda: [
            {
                "key": "zai",
                "label": "Zai Cloud",
                "description": "Test provider",
                "asciiArt": "+===+\n| Z |",
                "asciiArtQuoteBlock": "> +===+\n> | Z |",
            }
        ],
    )

    old_argv = sys.argv
    sys.argv = ["ccsilo", "variant", "providers", "--quote-blocks"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    out = capsys.readouterr().out
    assert "zai: Zai Cloud" in out
    assert "> +===+" in out
    assert "> | Z |" in out


def test_create_and_reapply_variant_preserves_selected_optional_mcp(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="Mirror MCP",
        provider_key="mirror",
        mcp_ids=["github"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    config_path = root / "variants" / "mirror-mcp" / "config" / ".claude.json"
    claude_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert result.variant.manifest["mcp"]["selected"] == ["github"]
    assert sorted(claude_config["mcpServers"]) == ["github"]
    assert claude_config["mcpServers"]["github"]["headers"] == {
        "Authorization": "Bearer ${GITHUB_TOKEN}"
    }
    assert "notion" not in claude_config["mcpServers"]

    monkeypatch.setattr(variants_module, "_download_source_artifact", lambda version, root=None: artifact)
    apply_variant("mirror-mcp", root=root)
    update_variants("mirror-mcp", root=root)

    reapplied_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert sorted(reapplied_config["mcpServers"]) == ["github"]
    assert "notion" not in reapplied_config["mcpServers"]


def test_macos_grow_skip_uses_unpacked_node_runtime(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_macho_source_artifact(tmp_path)
    unpack_calls = []

    def fake_apply_patches(inputs):
        return SimpleNamespace(
            ok=True,
            skipped_reason="macho-grow-not-supported",
            missing_prompt_keys=[],
            resigned=False,
        )

    def fake_unpack_and_patch(**kwargs):
        unpack_calls.append(kwargs)
        unpacked_dir = Path(kwargs["unpacked_dir"])
        entry_path = unpacked_dir / "src" / "cli.js"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text('const version="2.1.123 (Claude Code)";', encoding="latin1")
        (unpacked_dir / "package.json").write_text("{}", encoding="utf-8")
        (unpacked_dir / "node_modules").mkdir()
        return SimpleNamespace(
            entry_path=str(entry_path),
            patch=SimpleNamespace(
                theme_replaced=2,
                prompt_replaced=["webfetch"],
                prompt_missing=[],
            ),
        )

    monkeypatch.setattr(variants_module, "apply_patches", fake_apply_patches)
    monkeypatch.setattr(variants_module, "unpack_and_patch", fake_unpack_and_patch)

    result = create_variant(
        name="Mac Zai",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        tweaks=["themes", "prompt-overlays"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    manifest = result.variant.manifest
    entry_path = Path(manifest["paths"]["entryPath"])
    wrapper = result.wrapper_path.read_text(encoding="utf-8")

    assert manifest["runtime"] == "node"
    assert manifest["paths"]["unpackedDir"] == str(root / "variants" / "mac-zai" / "unpacked")
    assert entry_path.read_text(encoding="latin1") == 'const version="2.1.123 (Claude Code)";'
    assert unpack_calls[0]["pristine_binary_path"] == str(artifact.path)
    assert "NODE_BIN=\"${NODE:-node}\"" in wrapper
    assert 'exec "$NODE_BIN" "$ENTRY_PATH" "$@"' in wrapper
    assert doctor_variant("mac-zai", root=root)[0]["ok"] is True
    assert manifest["patchResults"]["appliedTweaks"] == [
        "themes",
        "prompt-overlays",
    ]


def test_macos_startup_regex_tweaks_use_in_place_binary_patch(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_macho_source_artifact(tmp_path)
    patch_calls = []

    def fake_apply_patches(inputs):
        patch_calls.append(inputs)
        return SimpleNamespace(
            ok=True,
            skipped_reason=None,
            missing_prompt_keys=[],
            resigned=False,
            curated_applied=["hide-startup-banner", "hide-startup-clawd"],
            curated_skipped=[],
            curated_missed=[],
        )

    def fail_unpack_and_patch(**_kwargs):
        raise AssertionError("native-safe startup tweaks should not unpack")

    monkeypatch.setattr(variants_module, "apply_patches", fake_apply_patches)
    monkeypatch.setattr(variants_module, "unpack_and_patch", fail_unpack_and_patch)

    result = create_variant(
        name="Mac Banner",
        provider_key="ccrouter",
        tweaks=["hide-startup-banner", "hide-startup-clawd"],
        ccrouter_mode="external",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    stage_names = [stage.name for stage in result.stages]

    assert result.variant.manifest["runtime"] == "native"
    assert "patch binary" in stage_names
    assert "unpack node runtime" not in stage_names
    assert patch_calls[0].regex_tweaks == ["hide-startup-banner", "hide-startup-clawd"]
    assert result.variant.manifest["patchResults"]["appliedTweaks"] == [
        "hide-startup-banner",
        "hide-startup-clawd",
    ]


def test_macos_default_startup_tweaks_do_not_force_node_runtime(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_macho_source_artifact(tmp_path)
    patch_calls = []

    def fake_apply_patches(inputs):
        patch_calls.append(inputs)
        return SimpleNamespace(
            ok=True,
            skipped_reason=None,
            missing_prompt_keys=[],
            resigned=False,
            curated_applied=[
                "hide-startup-banner",
                "hide-startup-clawd",
                "suppress-native-installer-warning",
                "suppress-prompt-caching-warning",
                "suppress-model-launch-notice",
                "mcp-non-blocking",
            ],
            curated_skipped=[],
            curated_missed=[],
        )

    def fail_unpack_and_patch(**_kwargs):
        raise AssertionError("default native-safe tweaks should not unpack")

    monkeypatch.setattr(variants_module, "apply_patches", fake_apply_patches)
    monkeypatch.setattr(variants_module, "unpack_and_patch", fail_unpack_and_patch)

    result = create_variant(
        name="Mac Default",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    assert result.variant.manifest["runtime"] == "native"
    assert result.variant.manifest["tweaks"] == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
        "suppress-native-installer-warning",
        "suppress-prompt-caching-warning",
        "suppress-model-launch-notice",
        "mcp-non-blocking",
        "mcp-batch-size",
        "rtk-shell-prefix",
        "dangerously-skip-permissions",
        "disable-telemetry",
        "disable-error-reporting",
        "disable-feedback-command",
        "disable-feedback-survey",
        "disable-prompt-caching",
    ]
    assert result.variant.manifest["env"]["MCP_SERVER_CONNECTION_BATCH_SIZE"] == "10"
    assert result.variant.manifest["env"]["DISABLE_PROMPT_CACHING"] == "1"
    assert patch_calls[0].regex_tweaks == [
        "hide-startup-banner",
        "hide-startup-clawd",
        "suppress-native-installer-warning",
        "suppress-prompt-caching-warning",
        "suppress-model-launch-notice",
        "mcp-non-blocking",
    ]
    assert result.variant.manifest["patchResults"]["appliedTweaks"] == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
        "suppress-native-installer-warning",
        "suppress-prompt-caching-warning",
        "suppress-model-launch-notice",
        "mcp-non-blocking",
        "mcp-batch-size",
        "rtk-shell-prefix",
        "dangerously-skip-permissions",
    ]


def test_macos_non_native_regex_tweak_uses_unpacked_node_runtime_not_in_place_binary_patch(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_macho_source_artifact(tmp_path)
    unpack_calls = []

    def fail_apply_patches(_inputs):
        raise AssertionError("regex-only tweaks should not use in-place binary patching")

    def fake_unpack_and_patch(**kwargs):
        unpack_calls.append(kwargs)
        unpacked_dir = Path(kwargs["unpacked_dir"])
        entry_path = unpacked_dir / "src" / "cli.js"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(f"{BUN_NODE_COMPAT_MARKER}\n{ENTRY_JS}", encoding="latin1")
        (unpacked_dir / "package.json").write_text("{}", encoding="utf-8")
        (unpacked_dir / "node_modules").mkdir()
        return SimpleNamespace(
            entry_path=str(entry_path),
            patch=SimpleNamespace(
                theme_replaced=0,
                prompt_replaced=[],
                prompt_missing=[],
            ),
        )

    monkeypatch.setattr(variants_module, "apply_patches", fail_apply_patches)
    monkeypatch.setattr(variants_module, "unpack_and_patch", fake_unpack_and_patch)

    result = create_variant(
        name="Mac Patches Indication",
        provider_key="ccrouter",
        tweaks=["patches-applied-indication"],
        ccrouter_mode="external",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    entry_path = Path(result.variant.manifest["paths"]["entryPath"])
    entry_js = entry_path.read_text(encoding="latin1")
    stage_names = [stage.name for stage in result.stages]

    assert result.variant.manifest["runtime"] == "node"
    assert "unpack node runtime" in stage_names
    assert "patch binary" not in stage_names
    assert unpack_calls[0]["pristine_binary_path"] == str(artifact.path)
    assert entry_js.count(BUN_NODE_COMPAT_MARKER) == 1
    assert "(Claude Code, CC Router variant)" in entry_js
    assert result.variant.manifest["patchResults"]["appliedTweaks"] == ["patches-applied-indication"]


def test_create_variant_build_error_includes_stages(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_macho_source_artifact(tmp_path)

    def fake_apply_patches(_inputs):
        return SimpleNamespace(
            ok=False,
            reason="failed",
            detail="anchor missing",
            missing_prompt_keys=[],
            resigned=False,
        )

    monkeypatch.setattr(variants_module, "apply_patches", fake_apply_patches)

    with pytest.raises(VariantBuildError) as exc_info:
        create_variant(
            name="Broken Zai",
            provider_key="zai",
            credential_env="Z_AI_API_KEY",
            tweaks=["themes"],
            root=root,
            source_artifact=artifact,
            force=True,
        )

    err = exc_info.value
    assert err.stage == "patch binary"
    assert [stage.name for stage in err.stages] == ["prepare directories", "patch binary"]
    assert err.stages[-1].status == "failed"
    assert "anchor missing" in err.stages[-1].detail


def test_create_variant_stored_secret_is_not_in_metadata(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="Secret Zai",
        provider_key="zai",
        api_key="super-secret",
        store_secret=True,
        root=root,
        source_artifact=artifact,
        force=True,
    )

    variant_dir = root / "variants" / "secret-zai"
    metadata_text = (variant_dir / "variant.json").read_text(encoding="utf-8")
    settings_text = (variant_dir / "config" / "settings.json").read_text(encoding="utf-8")
    claude_config_text = (variant_dir / "config" / ".claude.json").read_text(encoding="utf-8")
    secrets_path = variant_dir / "secrets.env"

    assert "super-secret" not in metadata_text
    assert "super-secret" not in settings_text
    assert "super-secret" not in claude_config_text
    assert "${Z_AI_API_KEY}" in claude_config_text
    assert "super-secret" in secrets_path.read_text(encoding="utf-8")
    assert oct(secrets_path.stat().st_mode & 0o777) == "0o600"
    wrapper = result.wrapper_path.read_text(encoding="utf-8")
    assert 'SECRET_FILE="$VARIANT_ROOT/secrets.env"' in wrapper
    assert 'stat -f %Lp "$SECRET_FILE"' in wrapper
    assert result.variant.manifest["credential"]["mode"] == "stored"


def test_create_model_proxy_architect_variant_uses_oauth_safe_env(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="Deep Proxy",
        provider_key="deepseek",
        credential_env="DEEPSEEK_API_KEY",
        model_proxy="architect",
        model_proxy_port=4567,
        model_overrides={"opus": "claude-opus-4-6"},
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    manifest = result.variant.manifest
    model_proxy = manifest["modelProxy"]
    wrapper = result.wrapper_path.read_text(encoding="utf-8")
    settings = json.loads((root / "variants" / "deep-proxy" / "config" / "settings.json").read_text(encoding="utf-8"))
    proxy_config = json.loads(Path(model_proxy["runtimeConfigPath"]).read_text(encoding="utf-8"))
    doctor_checks = {check["name"]: check for check in doctor_variant("deep-proxy", root=root)[0]["checks"]}

    assert model_proxy["mode"] == "architect"
    assert model_proxy["port"] == 4567
    assert model_proxy["backendUrl"] == "https://api.deepseek.com/anthropic"
    assert model_proxy["backendAuth"] == "x-api-key"
    assert model_proxy["credentialEnv"] == "DEEPSEEK_API_KEY"
    assert model_proxy["timeoutMs"] == 3000000
    assert model_proxy["backendProviderKey"] == "deepseek"
    assert model_proxy["backendProviderLabel"] == "DeepSeek"
    assert "backendModelsUrl" not in model_proxy
    assert manifest["credential"] == {"mode": "env", "source": "DEEPSEEK_API_KEY", "targets": []}
    assert "ANTHROPIC_BASE_URL" not in manifest["env"]
    assert "ANTHROPIC_API_KEY" not in manifest["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in manifest["env"]
    assert manifest["env"][GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert manifest["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"
    assert manifest["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deepseek-v4-flash"
    assert manifest["env"]["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
    assert GATEWAY_MODEL_DISCOVERY_TWEAK_ID in manifest["tweaks"]
    assert "forceLoginMethod" not in settings
    assert proxy_config == {
        "anthropicUrl": "https://api.anthropic.com",
        "backendAuth": "x-api-key",
        "backendModels": ["deepseek-v4-flash"],
        "backendUrl": "https://api.deepseek.com/anthropic",
        "backendProviderKey": "deepseek",
        "backendProviderLabel": "DeepSeek",
        "anthropicModels": ["claude-opus-4-6"],
        "mode": "architect",
        "timeoutMs": 3000000,
    }
    assert "customApiKeyResponses" not in wrapper
    assert 'export ANTHROPIC_API_KEY="${DEEPSEEK_API_KEY}"' not in wrapper
    assert "ccsilo.model_proxy" in wrapper
    assert "MODEL_PROXY_AUTH_NONCE" in wrapper
    assert 'ANTHROPIC_BASE_URL="http://127.0.0.1:$MODEL_PROXY_ACTUAL_PORT/$MODEL_PROXY_AUTH_NONCE"' in wrapper
    assert "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN" in wrapper
    assert "cleanup_model_proxy" in wrapper
    assert "exec " not in wrapper.split('ccsilo.model_proxy', 1)[1]
    assert doctor_checks["model-proxy-config"]["ok"] is True
    assert doctor_checks["model-proxy-python"]["ok"] is True
    assert doctor_checks["model-proxy-nonce-wrapper"]["ok"] is True


def test_model_proxy_doctor_fails_when_wrapper_lacks_nonce(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="Broken Proxy",
        provider_key="deepseek",
        credential_env="DEEPSEEK_API_KEY",
        model_proxy="architect",
        model_overrides={"opus": "claude-opus-4-6"},
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )
    result.wrapper_path.write_text("#!/bin/sh\n", encoding="utf-8")

    checks = {check["name"]: check for check in doctor_variant("broken-proxy", root=root)[0]["checks"]}

    assert checks["model-proxy-nonce-wrapper"]["ok"] is False


def test_create_model_proxy_stores_only_backend_secret(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="Deep Proxy Secret",
        provider_key="deepseek",
        api_key="actual-secret-token",
        store_secret=True,
        model_proxy="architect",
        model_overrides={"opus": "claude-opus-4-6"},
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    variant_dir = root / "variants" / "deep-proxy-secret"
    metadata_text = (variant_dir / "variant.json").read_text(encoding="utf-8")
    proxy_config_text = (variant_dir / "config" / "model-proxy.json").read_text(encoding="utf-8")
    secrets_text = (variant_dir / "secrets.env").read_text(encoding="utf-8")

    assert "actual-secret-token" not in metadata_text
    assert "actual-secret-token" not in proxy_config_text
    assert "DEEPSEEK_API_KEY" in secrets_text
    assert "actual-secret-token" in secrets_text
    assert "ANTHROPIC_API_KEY" not in secrets_text
    assert result.variant.manifest["credential"]["mode"] == "stored"
    assert result.variant.manifest["credential"]["targets"] == ["DEEPSEEK_API_KEY"]


def test_create_model_proxy_openrouter_uses_bearer_backend_auth(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="OpenRouter Proxy",
        provider_key="openrouter",
        credential_env="OPENROUTER_API_KEY",
        model_proxy="architect",
        model_overrides={
        "opus": "claude-opus-4-6",
        "sonnet": "deepseek/deepseek-v4-pro",
        "haiku": "deepseek/deepseek-v4-pro",
        },
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    manifest = result.variant.manifest

    assert manifest["modelProxy"]["backendAuth"] == "bearer"
    assert manifest["modelProxy"]["credentialEnv"] == "OPENROUTER_API_KEY"
    assert manifest["modelProxy"]["timeoutMs"] == 3000000
    assert manifest["modelProxy"]["backendProviderKey"] == "openrouter"
    assert manifest["modelProxy"]["backendProviderLabel"] == "OpenRouter"
    assert manifest["modelProxy"]["backendModelsUrl"] == "https://openrouter.ai/api/v1/models"
    assert manifest["modelProxy"]["anthropicModels"] == ["claude-opus-4-6"]
    assert manifest["modelProxy"]["backendModels"] == ["deepseek/deepseek-v4-pro"]
    assert manifest["credential"] == {"mode": "env", "source": "OPENROUTER_API_KEY", "targets": []}
    assert manifest["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"
    assert manifest["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deepseek/deepseek-v4-pro"
    assert manifest["env"]["ANTHROPIC_MODEL"] == "deepseek/deepseek-v4-pro"
    assert manifest["env"][GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert GATEWAY_MODEL_DISCOVERY_TWEAK_ID in manifest["tweaks"]
    assert "ANTHROPIC_AUTH_TOKEN" not in manifest["env"]


def test_create_ccr_oauth_proxy_uses_managed_ccrouter_backend(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    stub_ccrouter_npm(monkeypatch)

    result = create_variant(
        name="CCR OAuth",
        provider_key="ccr-oauth",
        model_proxy="architect",
        model_overrides={
            "opus": "claude-opus-test",
            "sonnet": "ccr-worker",
            "haiku": "ccr-worker",
        },
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )

    manifest = result.variant.manifest
    model_proxy = manifest["modelProxy"]

    assert manifest["provider"]["key"] == "ccr-oauth"
    assert manifest["ccrouter"]["mode"] == "managed"
    assert model_proxy["mode"] == "architect"
    assert model_proxy["backendUrl"] == f"http://127.0.0.1:{manifest['ccrouter']['port']}"
    assert model_proxy["credentialEnv"] == "CCROUTER_AUTH_TOKEN"
    assert model_proxy["timeoutMs"] == 3000000
    assert model_proxy["backendProviderKey"] == "ccr-oauth"
    assert model_proxy["backendProviderLabel"] == "CCR OAuth Proxy"
    assert "backendModelsUrl" not in model_proxy
    assert model_proxy["anthropicModels"] == ["claude-opus-test"]
    assert model_proxy["backendModels"] == ["ccr-worker"]
    assert manifest["env"]["CCROUTER_AUTH_TOKEN"] == "ccrouter-proxy"
    assert manifest["env"][GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert GATEWAY_MODEL_DISCOVERY_TWEAK_ID in manifest["tweaks"]
    assert "ANTHROPIC_BASE_URL" not in manifest["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in manifest["env"]
    assert "ANTHROPIC_API_KEY" not in manifest["env"]


def test_write_secrets_rewrites_existing_file_with_private_mode(tmp_path):
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("old\n", encoding="utf-8")
    secrets_path.chmod(0o644)

    write_secrets(secrets_path, {"ANTHROPIC_API_KEY": "secret"})

    assert oct(secrets_path.stat().st_mode & 0o777) == "0o600"
    assert "secret" in secrets_path.read_text(encoding="utf-8")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_write_secrets_refuses_symlink_target(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("keep me\n", encoding="utf-8")
    secrets_path = tmp_path / "secrets.env"
    os.symlink(target, secrets_path)

    with pytest.raises(ValueError, match="symlink"):
        write_secrets(secrets_path, {"ANTHROPIC_API_KEY": "secret"})

    assert target.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_write_wrapper_refuses_symlink_target(tmp_path):
    target = tmp_path / "target-wrapper"
    target.write_text("keep me\n", encoding="utf-8")
    wrapper_path = tmp_path / "bin" / "unsafe"
    wrapper_path.parent.mkdir()
    os.symlink(target, wrapper_path)
    manifest = {
        "id": "unsafe",
        "provider": {"key": "mirror"},
        "env": {},
        "credential": {"mode": "none", "targets": []},
        "paths": {
            "root": str(tmp_path / "variant"),
            "wrapper": str(wrapper_path),
            "configDir": str(tmp_path / "variant" / "config"),
            "tweakccDir": str(tmp_path / "variant" / "tweakcc"),
            "tmpDir": str(tmp_path / "variant" / "tmp"),
            "binary": str(tmp_path / "variant" / "native" / "claude"),
        },
    }

    with pytest.raises(ValueError, match="symlink"):
        write_wrapper(manifest)

    assert target.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode check")
def test_doctor_variant_fails_stored_secret_with_unsafe_mode(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Secret Zai",
        provider_key="zai",
        api_key="super-secret",
        store_secret=True,
        root=root,
        source_artifact=artifact,
        force=True,
    )
    secrets_path = root / "variants" / "secret-zai" / "secrets.env"
    secrets_path.chmod(0o644)

    report = doctor_variant("secret-zai", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is False
    assert checks["secrets-mode"]["ok"] is False
    assert checks["secrets-safe"]["ok"] is False


def test_doctor_variant_passes_marked_node_bun_compat_entry(tmp_path):
    root = _write_node_variant(tmp_path, f"{BUN_NODE_COMPAT_MARKER}\nBun.stringWidth('abc');")

    report = doctor_variant("node-compat", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is True
    assert checks["node-bun-compat"]["ok"] is True


def test_doctor_variant_fails_unmarked_node_entry_with_bun_globals(tmp_path):
    root = _write_node_variant(tmp_path, "Bun.stringWidth('abc');")

    report = doctor_variant("node-compat", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is False
    assert checks["node-bun-compat"]["ok"] is False


def test_doctor_variant_reports_managed_ccrouter_running_and_missing_bin(tmp_path, monkeypatch):
    import ccsilo.variants.ccrouter as ccrouter_module

    monkeypatch.setattr(ccrouter_module, "node_version_ok", lambda: (True, "node 20.0.0"))
    root = _write_managed_ccrouter_variant(tmp_path, pid=os.getpid())

    report = doctor_variant("ccr-managed", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert checks["ccrouter-bin"]["ok"] is True
    assert checks["ccrouter-running"]["ok"] is True

    (root / "variants" / "ccr-managed" / "ccr-runtime" / "node_modules" / ".bin" / "ccr").unlink()
    report = doctor_variant("ccr-managed", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is False
    assert checks["ccrouter-bin"]["ok"] is False


def test_doctor_variant_reports_managed_ccrouter_stopped_and_bad_config(tmp_path, monkeypatch):
    import ccsilo.variants.ccrouter as ccrouter_module

    monkeypatch.setattr(ccrouter_module, "node_version_ok", lambda: (True, "node 20.0.0"))
    root = _write_managed_ccrouter_variant(tmp_path, config_text="{not json", pid=None)

    report = doctor_variant("ccr-managed", root=root)[0]
    checks = {check["name"]: check for check in report["checks"]}

    assert report["ok"] is False
    assert checks["ccrouter-config-valid"]["ok"] is False
    assert checks["ccrouter-running"]["ok"] is False


def _write_node_variant(tmp_path, entry_js):
    root = tmp_path / ".ccsilo"
    variant_dir = root / "variants" / "node-compat"
    entry_path = variant_dir / "unpacked" / "src" / "cli.js"
    wrapper = root / "bin" / "node-compat"
    config = variant_dir / "config" / "settings.json"
    binary = variant_dir / "native" / "claude"
    package_json = variant_dir / "unpacked" / "package.json"
    node_modules = variant_dir / "unpacked" / "node_modules"
    for path in (entry_path.parent, wrapper.parent, config.parent, binary.parent, node_modules):
        path.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(entry_js, encoding="latin1")
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    config.write_text("{}\n", encoding="utf-8")
    binary.write_text("binary\n", encoding="utf-8")
    package_json.write_text("{}\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "id": "node-compat",
        "name": "Node Compat",
        "provider": {"key": "mirror", "label": "Mirror"},
        "source": {"version": "2.1.128"},
        "runtime": "node",
        "paths": {
            "root": str(variant_dir),
            "wrapper": str(wrapper),
            "configDir": str(config.parent),
            "binary": str(binary),
            "entryPath": str(entry_path),
            "unpackedDir": str(variant_dir / "unpacked"),
        },
        "createdAt": "2026-05-04T00:00:00Z",
        "updatedAt": "2026-05-04T00:00:00Z",
    }
    (variant_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _write_managed_ccrouter_variant(tmp_path, *, config_text=None, pid=None):
    root = tmp_path / ".ccsilo"
    variant_dir = root / "variants" / "ccr-managed"
    wrapper = root / "bin" / "ccr-managed"
    settings = variant_dir / "config" / "settings.json"
    binary = variant_dir / "native" / "claude"
    home_dir = variant_dir / "ccr-home"
    config_dir = home_dir / ".claude-code-router"
    runtime_bin = variant_dir / "ccr-runtime" / "node_modules" / ".bin"
    for path in (wrapper.parent, settings.parent, binary.parent, config_dir, runtime_bin):
        path.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    settings.write_text("{}\n", encoding="utf-8")
    binary.write_text("binary\n", encoding="utf-8")
    ccr = runtime_bin / "ccr"
    ccr.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ccr.chmod(0o755)
    config_path = config_dir / "config.json"
    config_path.write_text(config_text or json.dumps({"PORT": 4567, "Providers": [], "Router": {}}), encoding="utf-8")
    if pid is not None:
        (config_dir / ".claude-code-router.pid").write_text(str(pid), encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "id": "ccr-managed",
        "name": "CCR Managed",
        "provider": {"key": "ccrouter", "label": "CC Router"},
        "source": {"version": "2.1.128"},
        "runtime": "native",
        "paths": {
            "root": str(variant_dir),
            "wrapper": str(wrapper),
            "configDir": str(settings.parent),
            "binary": str(binary),
        },
        "ccrouter": {
            "mode": "managed",
            "packageSpec": CCR_PACKAGE_DEFAULT,
            "configMode": "empty",
            "autoStart": True,
            "port": 4567,
            "homeDir": str(home_dir),
            "runtimeDir": str(variant_dir / "ccr-runtime"),
            "tmpDir": str(variant_dir / "tmp"),
            "configPath": str(config_path),
            "binPath": str(ccr),
        },
        "createdAt": "2026-05-04T00:00:00Z",
        "updatedAt": "2026-05-04T00:00:00Z",
    }
    (variant_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_write_wrapper_rejects_unsafe_env_key(tmp_path):
    manifest = {
        "id": "unsafe",
        "provider": {"key": "mirror"},
        "env": {"X; touch /tmp/pwn": "1"},
        "credential": {"mode": "none", "targets": []},
        "paths": {
            "root": str(tmp_path / "variant"),
            "wrapper": str(tmp_path / "bin" / "unsafe"),
            "configDir": str(tmp_path / "variant" / "config"),
            "tweakccDir": str(tmp_path / "variant" / "tweakcc"),
            "tmpDir": str(tmp_path / "variant" / "tmp"),
            "binary": str(tmp_path / "variant" / "native" / "claude"),
        },
    }

    with pytest.raises(ValueError, match="wrapper env key"):
        write_wrapper(manifest)


def test_write_wrapper_rejects_unsafe_env_unset_key(tmp_path):
    manifest = wrapper_manifest(tmp_path, {})
    manifest["envUnset"] = ["X; touch /tmp/pwn"]

    with pytest.raises(ValueError, match="wrapper unset env key"):
        write_wrapper(manifest)


def test_write_wrapper_unsets_env_before_launch(tmp_path):
    manifest = wrapper_manifest(tmp_path, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"})
    manifest["envUnset"] = ["CLAUDE_CODE_USE_BEDROCK"]

    wrapper = write_wrapper(manifest).read_text(encoding="utf-8")

    assert wrapper.index("export ANTHROPIC_BASE_URL=http://127.0.0.1:3456") < wrapper.index("unset CLAUDE_CODE_USE_BEDROCK") < wrapper.index("\nexec ")


def test_write_wrapper_can_force_dangerous_skip_permissions(tmp_path):
    manifest = wrapper_manifest(tmp_path, {})
    manifest["tweaks"] = ["dangerously-skip-permissions"]

    wrapper = write_wrapper(manifest)
    wrapper_text = wrapper.read_text(encoding="utf-8")
    proc = subprocess.run([str(wrapper), "--print"], capture_output=True, text=True, check=True)

    assert f"exec {manifest['paths']['binary']} --dangerously-skip-permissions \"$@\"" in wrapper_text
    assert "RUN:--dangerously-skip-permissions --print" in proc.stdout


def test_write_wrapper_bootstraps_api_key_approval_for_non_mirror(tmp_path):
    manifest = wrapper_manifest(tmp_path, {})
    manifest["provider"]["key"] = "minimax"
    manifest["credential"] = {
        "mode": "env",
        "source": "MINIMAX_API_KEY",
        "targets": ["ANTHROPIC_API_KEY", "MINIMAX_API_KEY"],
    }

    wrapper = write_wrapper(manifest).read_text(encoding="utf-8")

    credential_export = 'export ANTHROPIC_API_KEY="${MINIMAX_API_KEY}"'
    assert "customApiKeyResponses" in wrapper
    assert "key[-20:]" in wrapper
    assert credential_export in wrapper
    assert wrapper.index(credential_export) < wrapper.index("customApiKeyResponses") < wrapper.index("\nexec ")


def test_write_wrapper_skips_api_key_approval_bootstrap_for_mirror(tmp_path):
    manifest = wrapper_manifest(tmp_path, {"ANTHROPIC_API_KEY": "already-present"})

    wrapper = write_wrapper(manifest).read_text(encoding="utf-8")

    assert "customApiKeyResponses" not in wrapper
    assert "key[-20:]" not in wrapper


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper execution")
def test_write_wrapper_approves_api_key_suffix_without_storing_key(tmp_path):
    manifest = wrapper_manifest(tmp_path, {})
    manifest["provider"]["key"] = "minimax"
    manifest["credential"] = {
        "mode": "env",
        "source": "MINIMAX_API_KEY",
        "targets": ["ANTHROPIC_API_KEY", "MINIMAX_API_KEY"],
    }
    wrapper = write_wrapper(manifest)
    api_key = "mini-key-value-1234567890abcdef"

    result = subprocess.run(
        [str(wrapper)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MINIMAX_API_KEY": api_key},
    )

    assert result.returncode == 0
    config_path = Path(manifest["paths"]["configDir"]) / ".claude.json"
    raw_config = config_path.read_text(encoding="utf-8")
    config = json.loads(raw_config)
    assert config["customApiKeyResponses"]["approved"] == [api_key[-20:]]
    assert config["customApiKeyResponses"]["rejected"] == []
    assert api_key not in raw_config


def test_write_wrapper_splash_tty_and_machine_output_controls(tmp_path):
    manifest = wrapper_manifest(
        tmp_path,
        {
            "CCSILO_SPLASH": "1",
            "CCSILO_SPLASH_STYLE": "zai",
            "CCSILO_PROVIDER_LABEL": "Zai Cloud",
        },
    )
    wrapper = write_wrapper(manifest)

    non_tty = subprocess.run([str(wrapper)], capture_output=True, text=True, check=False)
    assert non_tty.returncode == 0
    assert "++++++++" not in non_tty.stdout
    assert "RUN:" in non_tty.stdout

    tty_output = run_in_pty([str(wrapper)])
    assert "++++++++" in tty_output
    assert "\x1b[38;5;220m" in tty_output
    assert "RUN:" in tty_output

    machine_output = run_in_pty([str(wrapper), "--output-format", "json"])
    assert "++++++++" not in machine_output
    assert "RUN:--output-format json" in machine_output


def test_write_wrapper_splash_disable_and_fallback_style(tmp_path):
    disabled = wrapper_manifest(
        tmp_path / "disabled",
        {
            "CCSILO_SPLASH": "0",
            "CCSILO_SPLASH_STYLE": "zai",
            "CCSILO_PROVIDER_LABEL": "Zai Cloud",
        },
    )
    disabled_output = run_in_pty([str(write_wrapper(disabled))])
    assert "++++++++" not in disabled_output
    assert "RUN:" in disabled_output

    fallback = wrapper_manifest(
        tmp_path / "fallback",
        {
            "CCSILO_SPLASH": "1",
            "CCSILO_SPLASH_STYLE": "unknown",
            "CCSILO_PROVIDER_LABEL": "Mystery Provider",
        },
    )
    fallback_output = run_in_pty([str(write_wrapper(fallback))])
    assert "CCSILO" in fallback_output
    assert "Mystery Provider" in fallback_output
    assert "RUN:" in fallback_output


def test_apply_variant_rebuilds_from_saved_metadata(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Zai Test",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )
    variant = load_variant("zai-test", root=root)
    Path(variant.manifest["paths"]["binary"]).write_bytes(b"broken")
    evil_bin = tmp_path / "evil-bin"
    variant.manifest["paths"]["binDir"] = str(evil_bin)
    variant.manifest["paths"]["wrapper"] = str(evil_bin / "zai-test")
    (variant.path / "variant.json").write_text(json.dumps(variant.manifest), encoding="utf-8")

    monkeypatch.setattr(variants_module, "_download_source_artifact", lambda version, root=None: artifact)
    rebuilt = apply_variant("zai-test", root=root)

    assert rebuilt.binary_path.read_bytes() != b"broken"
    assert rebuilt.wrapper_path == root / "bin" / "zai-test"
    assert not (evil_bin / "zai-test").exists()
    assert 'case"zai-variant"' in read_entry(rebuilt.binary_path)


def test_apply_variant_removes_unchecked_default_tweak_env(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Remove Defaults",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )
    variant = load_variant("remove-defaults", root=root)
    manifest = dict(variant.manifest)
    manifest["tweaks"] = [
        tweak_id
        for tweak_id in manifest["tweaks"]
        if tweak_id not in {"mcp-batch-size", "rtk-shell-prefix"}
    ]
    (variant.path / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(variants_module, "_download_source_artifact", lambda version, root=None: artifact)
    rebuilt = apply_variant("remove-defaults", root=root)

    assert "mcp-batch-size" not in rebuilt.variant.manifest["tweaks"]
    assert "rtk-shell-prefix" not in rebuilt.variant.manifest["tweaks"]
    assert "MCP_SERVER_CONNECTION_BATCH_SIZE" not in rebuilt.variant.manifest["env"]
    assert "MCP_SERVER_CONNECTION_BATCH_SIZE" not in rebuilt.wrapper_path.read_text(encoding="utf-8")
    assert "mcp-batch-size" not in rebuilt.variant.manifest["patchResults"]["appliedTweaks"]
    assert "rtk-shell-prefix" not in rebuilt.variant.manifest["patchResults"]["appliedTweaks"]


def test_apply_variant_backfills_gateway_discovery_for_model_proxy(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Deep Proxy Backfill",
        provider_key="deepseek",
        credential_env="DEEPSEEK_API_KEY",
        model_proxy="architect",
        model_overrides={"opus": "claude-opus-4-6"},
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )
    variant = load_variant("deep-proxy-backfill", root=root)
    manifest = dict(variant.manifest)
    manifest["tweaks"] = [
        tweak_id
        for tweak_id in manifest["tweaks"]
        if tweak_id != GATEWAY_MODEL_DISCOVERY_TWEAK_ID
    ]
    manifest["env"] = dict(manifest["env"])
    manifest["env"].pop(GATEWAY_MODEL_DISCOVERY_ENV, None)
    (variant.path / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(variants_module, "_download_source_artifact", lambda version, root=None: artifact)
    rebuilt = apply_variant("deep-proxy-backfill", root=root)

    assert GATEWAY_MODEL_DISCOVERY_TWEAK_ID in rebuilt.variant.manifest["tweaks"]
    assert rebuilt.variant.manifest["env"][GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert GATEWAY_MODEL_DISCOVERY_ENV in rebuilt.wrapper_path.read_text(encoding="utf-8")


def test_update_variant_models_rewrites_manifest_and_wrapper_without_rebuild(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="LM Local",
        provider_key="lmstudio",
        model_overrides={"opus": "old-model", "sonnet": "old-model", "haiku": "old-model"},
        root=root,
        source_artifact=artifact,
        force=True,
    )
    monkeypatch.setattr(
        variants_module,
        "_download_source_artifact",
        lambda version, root=None: (_ for _ in ()).throw(AssertionError("should not rebuild")),
    )

    updated = update_variant_models(
        "lm-local",
        {
            "opus": "new-model",
            "sonnet": "new-model",
            "haiku": "new-model",
            "default": "new-model",
            "small_fast": "",
        },
        root=root,
    )

    wrapper = Path(updated.manifest["paths"]["wrapper"]).read_text(encoding="utf-8")

    assert updated.manifest["modelOverrides"] == {
        "opus": "new-model",
        "sonnet": "new-model",
        "haiku": "new-model",
        "default": "new-model",
    }
    assert updated.manifest["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "new-model"
    assert updated.manifest["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "new-model"
    assert updated.manifest["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "new-model"
    assert updated.manifest["env"]["ANTHROPIC_MODEL"] == "new-model"
    assert "export ANTHROPIC_DEFAULT_OPUS_MODEL=new-model" in wrapper
    assert "old-model" not in wrapper


def test_update_variant_models_backfills_gateway_discovery_for_model_proxy(tmp_path, monkeypatch):
    import ccsilo.variants as variants_module

    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Deep Proxy Update",
        provider_key="deepseek",
        credential_env="DEEPSEEK_API_KEY",
        model_proxy="architect",
        model_overrides={"opus": "claude-opus-4-6"},
        tweaks=["themes"],
        root=root,
        source_artifact=artifact,
        force=True,
    )
    variant = load_variant("deep-proxy-update", root=root)
    manifest = dict(variant.manifest)
    manifest["tweaks"] = [
        tweak_id
        for tweak_id in manifest["tweaks"]
        if tweak_id != GATEWAY_MODEL_DISCOVERY_TWEAK_ID
    ]
    manifest["env"] = dict(manifest["env"])
    manifest["env"].pop(GATEWAY_MODEL_DISCOVERY_ENV, None)
    (variant.path / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        variants_module,
        "_download_source_artifact",
        lambda version, root=None: (_ for _ in ()).throw(AssertionError("should not rebuild")),
    )

    updated = update_variant_models(
        "deep-proxy-update",
        {
            "opus": "claude-opus-4-6",
            "sonnet": "deepseek-v4-flash",
            "haiku": "deepseek-v4-flash",
        },
        root=root,
    )

    wrapper = Path(updated.manifest["paths"]["wrapper"]).read_text(encoding="utf-8")

    assert GATEWAY_MODEL_DISCOVERY_TWEAK_ID in updated.manifest["tweaks"]
    assert updated.manifest["env"][GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert GATEWAY_MODEL_DISCOVERY_ENV in wrapper


def test_update_variant_models_blocks_missing_required_core_aliases(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="LM Local",
        provider_key="lmstudio",
        model_overrides={"opus": "old-model", "sonnet": "old-model", "haiku": "old-model"},
        root=root,
        source_artifact=artifact,
        force=True,
    )

    with pytest.raises(ValueError, match="requires model mapping"):
        update_variant_models("lm-local", {}, root=root)


def test_patch_entry_js_rejects_tampered_entrypoint(tmp_path):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    outside = tmp_path / "outside.js"
    outside.write_text(ENTRY_JS, encoding="utf-8")

    with pytest.raises(ValueError, match="entryPoint"):
        patch_entry_js(
            extract_dir,
            {"entryPoint": "../outside.js"},
            provider_key="mirror",
            tweak_ids=[],
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_remove_variant_requires_confirmation_and_removes_wrapper(tmp_path):
    root = tmp_path / ".ccsilo"
    artifact = write_source_artifact(tmp_path)
    result = create_variant(
        name="Zai Test",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    with pytest.raises(ValueError, match="--yes"):
        remove_variant("zai-test", root=root)

    install_dir = tmp_path / "home" / ".local" / "bin"
    install_dir.mkdir(parents=True)
    install_result = install_variant_command(result.variant, bin_dir=install_dir)
    assert install_result.path.is_symlink()

    assert remove_variant("zai-test", yes=True, root=root) is True
    assert not result.wrapper_path.exists()
    assert not install_result.path.exists()
    assert not install_result.path.is_symlink()
    assert scan_variants(root) == []


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink not supported")
def test_remove_variant_removes_unrecorded_symlink_to_wrapper(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    install_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    artifact = write_source_artifact(tmp_path)
    result = create_variant(
        name="Zai Test",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )
    orphan = install_dir / "zai-test"
    os.symlink(result.wrapper_path, orphan)
    manifest = json.loads((result.variant.path / "variant.json").read_text(encoding="utf-8"))
    assert "installs" not in manifest

    assert remove_variant("zai-test", yes=True, root=root) is True

    assert not orphan.exists()
    assert not orphan.is_symlink()
    assert scan_variants(root) == []


def test_remove_variant_preserves_unrecorded_non_symlink_command(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    install_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    artifact = write_source_artifact(tmp_path)
    create_variant(
        name="Zai Test",
        provider_key="zai",
        credential_env="Z_AI_API_KEY",
        root=root,
        source_artifact=artifact,
        force=True,
    )
    command = install_dir / "zai-test"
    command.write_text("#!/bin/sh\n", encoding="utf-8")

    assert remove_variant("zai-test", yes=True, root=root) is True

    assert command.read_text(encoding="utf-8") == "#!/bin/sh\n"
    assert scan_variants(root) == []


def test_remove_variant_ignores_tampered_manifest_wrapper(tmp_path):
    root = tmp_path / ".ccsilo"
    variant_dir = root / "variants" / "fake"
    canonical_wrapper = root / "bin" / "fake"
    outside_wrapper = tmp_path / "outside-wrapper"
    variant_dir.mkdir(parents=True)
    canonical_wrapper.parent.mkdir(parents=True)
    canonical_wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    outside_wrapper.write_text("do not delete\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "id": "fake",
        "name": "Fake",
        "provider": {"key": "mirror"},
        "source": {"version": "1.2.3"},
        "paths": {"wrapper": str(outside_wrapper)},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    (variant_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert remove_variant("fake", yes=True, root=root) is True

    assert not canonical_wrapper.exists()
    assert outside_wrapper.exists()
    assert not variant_dir.exists()


def test_run_variant_ignores_tampered_manifest_wrapper(tmp_path):
    root = tmp_path / ".ccsilo"
    variant_dir = root / "variants" / "fake"
    canonical_wrapper = root / "bin" / "fake"
    outside_wrapper = tmp_path / "outside-wrapper"
    output = tmp_path / "output.txt"
    variant_dir.mkdir(parents=True)
    canonical_wrapper.parent.mkdir(parents=True)
    canonical_wrapper.write_text(f"#!/bin/sh\necho canonical > {output}\n", encoding="utf-8")
    outside_wrapper.write_text(f"#!/bin/sh\necho tampered > {output}\n", encoding="utf-8")
    canonical_wrapper.chmod(0o755)
    outside_wrapper.chmod(0o755)
    manifest = {
        "schemaVersion": 1,
        "id": "fake",
        "name": "Fake",
        "provider": {"key": "mirror"},
        "source": {"version": "1.2.3"},
        "paths": {"wrapper": str(outside_wrapper)},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    (variant_dir / "variant.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert run_variant("fake", root=root) == 0

    assert output.read_text(encoding="utf-8") == "canonical\n"


def test_variant_cli_list_and_show_json(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    class FakeVariant:
        manifest = {
            "schemaVersion": 1,
            "id": "fake",
            "name": "Fake",
            "provider": {"key": "mirror"},
            "source": {"version": "1.2.3"},
            "paths": {"wrapper": "/tmp/fake"},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        variant_id = "fake"

    monkeypatch.setattr(cli, "scan_variants", lambda: [FakeVariant()])
    old_argv = sys.argv
    sys.argv = ["ccsilo", "variant", "list", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "fake"


def test_variant_cli_create_show_doctor_and_remove(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    calls = []

    class FakeVariant:
        manifest = {
            "schemaVersion": 1,
            "id": "fake",
            "name": "Fake",
            "provider": {"key": "zai"},
            "source": {"version": "1.2.3"},
            "paths": {"wrapper": str(tmp_path / "fake")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        variant_id = "fake"

    class FakeResult:
        variant = FakeVariant()
        binary_path = tmp_path / "claude"
        wrapper_path = tmp_path / "fake"
        output_sha256 = "a" * 64
        applied_tweaks = ["themes"]
        skipped_tweaks = []
        missing_prompt_keys = []

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return FakeResult()

    install_calls = []

    def fake_install_variant_command(variant, alias=None, bin_dir=None, yes=False):
        install_calls.append((variant, alias, bin_dir, yes))
        return SimpleNamespace(
            alias=alias or "fake",
            path=tmp_path / "home" / "bin" / (alias or "fake"),
            target=tmp_path / "fake",
            status="installed",
            on_path=True,
            warning="",
        )

    monkeypatch.setattr(cli, "create_variant", fake_create_variant)
    monkeypatch.setattr(cli, "load_variant", lambda name: FakeVariant())
    monkeypatch.setattr(cli, "doctor_variant", lambda name=None, all_variants=False: [{"id": "fake", "name": "Fake", "ok": True, "checks": []}])
    monkeypatch.setattr(cli, "install_variant_command", fake_install_variant_command)
    monkeypatch.setattr(cli, "remove_variant", lambda name, yes=False: yes)
    monkeypatch.setattr(cli, "workspace_managed_install_records", lambda: [])
    monkeypatch.setattr(
        cli,
        "uninstall_workspace",
        lambda yes=False: SimpleNamespace(
            workspace=tmp_path / ".ccsilo",
            removed_workspace=True,
            removed_symlinks=[],
            skipped_symlinks=[],
        ),
    )

    old_argv = sys.argv
    try:
        sys.argv = ["ccsilo", "variant", "mcp", "--provider", "zai", "--json"]
        cli.main()
        mcp_payload = json.loads(capsys.readouterr().out)
        assert "github" in [item["id"] for item in mcp_payload["optionalMcpServers"]]
        assert "web-reader" in [item["id"] for item in mcp_payload["providerMcpServers"]]

        sys.argv = [
            "ccsilo",
            "variant",
            "create",
            "--name",
            "Fake",
            "--provider",
            "zai",
            "--base-url",
            "https://example.test/anthropic",
            "--credential-env",
            "Z_AI_API_KEY",
            "--tweak",
            "themes",
            "--mcp",
            "github",
            "--model-proxy",
            "architect",
            "--model-proxy-port",
            "4321",
            "--json",
        ]
        cli.main()
        create_payload = json.loads(capsys.readouterr().out)
        assert create_payload["id"] == "fake"
        assert calls[0]["provider_key"] == "zai"
        assert calls[0]["base_url"] == "https://example.test/anthropic"
        assert calls[0]["tweaks"] == ["themes"]
        assert calls[0]["mcp_ids"] == ["github"]
        assert calls[0]["model_proxy"] == "architect"
        assert calls[0]["model_proxy_port"] == "4321"

        sys.argv = [
            "ccsilo",
            "variant",
            "create",
            "--name",
            "Local",
            "--provider",
            "mirror",
            "--claude-version",
            "2.1.123",
            "--source-binary",
            str(tmp_path / "claude"),
            "--source-platform",
            "linux-x64",
            "--json",
        ]
        cli.main()
        json.loads(capsys.readouterr().out)
        assert calls[-1]["source_binary"] == str(tmp_path / "claude")
        assert calls[-1]["source_platform"] == "linux-x64"

        sys.argv = [
            "ccsilo",
            "variant",
            "create",
            "--name",
            "CCR",
            "--provider",
            "ccrouter",
            "--ccrouter-mode",
            "managed",
            "--ccrouter-config",
            "empty",
            "--ccrouter-package",
            "@musistudio/claude-code-router@2.0.0",
            "--ccrouter-port",
            "4567",
            "--no-ccrouter-autostart",
            "--json",
        ]
        cli.main()
        json.loads(capsys.readouterr().out)
        assert calls[-1]["provider_key"] == "ccrouter"
        assert calls[-1]["ccrouter_mode"] == "managed"
        assert calls[-1]["ccrouter_config"] == "empty"
        assert calls[-1]["ccrouter_package"] == "@musistudio/claude-code-router@2.0.0"
        assert calls[-1]["ccrouter_port"] == "4567"
        assert calls[-1]["ccrouter_autostart"] is False

        sys.argv = [
            "ccsilo",
            "variant",
            "create",
            "--name",
            "Fake",
            "--provider",
            "zai",
            "--install",
            "--json",
        ]
        cli.main()
        installed_create_payload = json.loads(capsys.readouterr().out)
        assert installed_create_payload["install"]["path"].endswith("/home/bin/fake")
        assert install_calls[-1][1:] == (None, None, False)

        sys.argv = [
            "ccsilo",
            "variant",
            "install",
            "Fake",
            "--bin-dir",
            str(tmp_path / "home" / "bin"),
            "--alias",
            "cc-fake",
            "--yes",
            "--json",
        ]
        cli.main()
        install_payload = json.loads(capsys.readouterr().out)
        assert install_payload["alias"] == "cc-fake"
        assert install_calls[-1][1:] == ("cc-fake", str(tmp_path / "home" / "bin"), True)

        sys.argv = ["ccsilo", "variant", "show", "fake", "--json"]
        cli.main()
        assert json.loads(capsys.readouterr().out)["id"] == "fake"

        sys.argv = ["ccsilo", "variant", "doctor", "fake", "--json"]
        cli.main()
        assert json.loads(capsys.readouterr().out)[0]["ok"] is True

        sys.argv = ["ccsilo", "variant", "remove", "fake", "--yes"]
        cli.main()
        assert "Removed variant" in capsys.readouterr().out

        sys.argv = ["ccsilo", "uninstall", "--yes", "--json"]
        cli.main()
        uninstall_payload = json.loads(capsys.readouterr().out)
        assert uninstall_payload["removedWorkspace"] is True
    finally:
        sys.argv = old_argv


def test_variant_cli_create_install_reports_blocked_existing_command(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    root = tmp_path / ".ccsilo"
    home = tmp_path / "home"
    install_dir = home / ".local" / "bin"
    install_dir.mkdir(parents=True)
    blocked = install_dir / "zai"
    blocked.write_text("#!/bin/sh\n", encoding="utf-8")
    calls = []

    class FakeVariant:
        variant_id = "zai"
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

    class FakeResult:
        variant = FakeVariant()
        binary_path = tmp_path / "claude"
        wrapper_path = root / "bin" / "zai"
        output_sha256 = "a" * 64
        applied_tweaks = []
        skipped_tweaks = []
        missing_prompt_keys = []
        stages = []

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return FakeResult()

    def fake_install_variant_command(*_args, **_kwargs):
        raise ValueError(f"Refusing to overwrite non-symlink command: {blocked}")

    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cli, "create_variant", fake_create_variant)
    monkeypatch.setattr(cli, "install_variant_command", fake_install_variant_command)

    old_argv = sys.argv
    sys.argv = ["ccsilo", "variant", "create", "--name", "zai", "--provider", "zai", "--install", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    assert payload["install"]["status"] == "blocked"
    assert payload["install"]["path"] == str(blocked)
    assert "Refusing to overwrite non-symlink command" in payload["install"]["warning"]
    assert blocked.read_text(encoding="utf-8") == "#!/bin/sh\n"


def test_variant_cli_update_passes_source_binary_args(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    calls = []

    class FakeVariant:
        manifest = {
            "schemaVersion": 1,
            "id": "fake",
            "name": "Fake",
            "provider": {"key": "mirror"},
            "source": {"version": "1.2.3"},
            "paths": {"wrapper": str(tmp_path / "fake")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        variant_id = "fake"

    class FakeResult:
        variant = FakeVariant()
        binary_path = tmp_path / "claude"
        wrapper_path = tmp_path / "fake"
        output_sha256 = "a" * 64
        applied_tweaks = []
        skipped_tweaks = []
        missing_prompt_keys = []

    def fake_update_variants(*args, **kwargs):
        calls.append((args, kwargs))
        return [FakeResult()]

    monkeypatch.setattr(cli, "update_variants", fake_update_variants)
    old_argv = sys.argv
    sys.argv = [
        "ccsilo",
        "variant",
        "update",
        "Fake",
        "--claude-version",
        "2.1.123",
        "--source-binary",
        str(tmp_path / "claude"),
        "--source-platform",
        "linux-x64",
        "--json",
    ]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "fake"
    assert calls[0][0] == ("Fake",)
    assert calls[0][1]["claude_version"] == "2.1.123"
    assert calls[0][1]["source_binary"] == str(tmp_path / "claude")
    assert calls[0][1]["source_platform"] == "linux-x64"


def test_provider_shortcut_install_creates_missing_setup(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    monkeypatch.setenv("CCSILO_WORKSPACE", str(tmp_path / ".ccsilo"))
    calls = []

    class FakeVariant:
        variant_id = "zai"
        name = "zai"
        path = tmp_path / ".ccsilo" / "variants" / "zai"
        manifest = {
            "schemaVersion": 1,
            "id": "zai",
            "name": "zai",
            "provider": {"key": "zai", "label": "Zai Cloud"},
            "source": {"version": "latest"},
            "paths": {
                "root": str(path),
                "wrapper": str(tmp_path / ".ccsilo" / "bin" / "zai"),
                "configDir": str(path / "config"),
            },
            "credential": {"mode": "env", "source": "Z_AI_API_KEY", "targets": ["ANTHROPIC_API_KEY", "Z_AI_API_KEY"]},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    class FakeResult:
        variant = FakeVariant()
        binary_path = tmp_path / "claude"
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "zai"
        output_sha256 = "a" * 64
        applied_tweaks = []
        skipped_tweaks = []
        missing_prompt_keys = []

    def fake_create_variant(**kwargs):
        calls.append(kwargs)
        return FakeResult()

    install_calls = []

    def fake_install_variant_command(variant, alias=None, bin_dir=None, yes=False):
        install_calls.append((variant.variant_id, alias, bin_dir, yes))
        return SimpleNamespace(
            alias=alias,
            path=tmp_path / "home" / "bin" / alias,
            target=Path(variant.manifest["paths"]["wrapper"]),
            status="installed",
            on_path=True,
            warning="",
        )

    monkeypatch.setattr(cli, "load_variant", lambda name: (_ for _ in ()).throw(ValueError("missing")))
    monkeypatch.setattr(cli, "scan_variants", lambda: [])
    monkeypatch.setattr(cli, "create_variant", fake_create_variant)
    monkeypatch.setattr(cli, "install_variant_command", fake_install_variant_command)

    old_argv = sys.argv
    sys.argv = ["ccsilo", "--provider", "zai", "install", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "zai"
    assert payload["install"]["alias"] == "zai"
    assert payload["nextSteps"]["command"] == "zai"
    assert payload["nextSteps"]["workspace"] == str(tmp_path / ".ccsilo")
    assert payload["nextSteps"]["doctor"] == "ccsilo variant doctor zai"
    assert payload["nextSteps"]["credentialEnv"] == ["ANTHROPIC_API_KEY", "Z_AI_API_KEY"]
    assert calls[0]["provider_key"] == "zai"
    assert calls[0]["claude_version"] == "latest"
    assert install_calls == [("zai", "zai", None, False)]


def test_provider_shortcut_install_repairs_existing_setup(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    monkeypatch.setenv("CCSILO_WORKSPACE", str(tmp_path / ".ccsilo"))

    class FakeVariant:
        variant_id = "zai"
        name = "zai"
        path = tmp_path / ".ccsilo" / "variants" / "zai"
        manifest = {
            "schemaVersion": 1,
            "id": "zai",
            "name": "zai",
            "provider": {"key": "zai", "label": "Zai Cloud"},
            "source": {"version": "2.1.0"},
            "paths": {"wrapper": str(tmp_path / ".ccsilo" / "bin" / "zai")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    create_calls = []
    install_calls = []

    monkeypatch.setattr(cli, "load_variant", lambda name: FakeVariant())
    monkeypatch.setattr(cli, "create_variant", lambda **kwargs: create_calls.append(kwargs))
    monkeypatch.setattr(
        cli,
        "install_variant_command",
        lambda variant, alias=None, bin_dir=None, yes=False: install_calls.append((variant.variant_id, alias, bin_dir, yes))
        or SimpleNamespace(
            alias=alias,
            path=tmp_path / "home" / "bin" / alias,
            target=Path(variant.manifest["paths"]["wrapper"]),
            status="already-installed",
            on_path=False,
            warning="Install directory is not on PATH: /tmp/bin. Add it to PATH to run the command by name.",
        ),
    )

    old_argv = sys.argv
    sys.argv = ["ccsilo", "install", "--provider", "zai", "--bin-dir", str(tmp_path / "home" / "bin"), "--yes", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload["install"]["status"] == "already-installed"
    assert payload["nextSteps"]["warnings"]
    assert create_calls == []
    assert install_calls == [("zai", "zai", str(tmp_path / "home" / "bin"), True)]


def test_provider_shortcut_update_defaults_latest_and_reinstalls(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    class FakeVariant:
        variant_id = "zai"
        name = "zai"
        path = tmp_path / ".ccsilo" / "variants" / "zai"
        manifest = {
            "schemaVersion": 1,
            "id": "zai",
            "name": "zai",
            "provider": {"key": "zai", "label": "Zai Cloud"},
            "source": {"version": "latest"},
            "paths": {"wrapper": str(tmp_path / ".ccsilo" / "bin" / "zai")},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    class FakeResult:
        variant = FakeVariant()
        binary_path = tmp_path / "claude"
        wrapper_path = tmp_path / ".ccsilo" / "bin" / "zai"
        output_sha256 = "a" * 64
        applied_tweaks = []
        skipped_tweaks = []
        missing_prompt_keys = []

    update_calls = []

    monkeypatch.setattr(cli, "load_variant", lambda name: FakeVariant())
    monkeypatch.setattr(cli, "update_variants", lambda *args, **kwargs: update_calls.append((args, kwargs)) or [FakeResult()])
    monkeypatch.setattr(
        cli,
        "install_variant_command",
        lambda variant, alias=None, bin_dir=None, yes=False: SimpleNamespace(
            alias=alias,
            path=tmp_path / "home" / "bin" / alias,
            target=Path(variant.manifest["paths"]["wrapper"]),
            status="installed",
            on_path=True,
            warning="",
        ),
    )

    old_argv = sys.argv
    sys.argv = ["ccsilo", "--provider", "zai", "update", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload["install"]["alias"] == "zai"
    assert update_calls == [(("zai",), {"claude_version": "latest"})]


def test_provider_shortcut_uninstall_removes_only_provider_setup(monkeypatch, capsys):
    from ccsilo import __main__ as cli
    import sys

    class FakeVariant:
        variant_id = "zai"
        name = "zai"
        manifest = {"provider": {"key": "zai"}}

    remove_calls = []
    workspace_calls = []

    monkeypatch.setattr(cli, "load_variant", lambda name: FakeVariant())
    monkeypatch.setattr(cli, "remove_variant", lambda name, yes=False: remove_calls.append((name, yes)) or True)
    monkeypatch.setattr(cli, "uninstall_workspace", lambda yes=False: workspace_calls.append(yes))

    old_argv = sys.argv
    sys.argv = ["ccsilo", "--provider", "zai", "uninstall", "--yes", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"provider": "zai", "removed": True, "variant": "zai"}
    assert remove_calls == [("zai", True)]
    assert workspace_calls == []


def test_provider_shortcut_bare_provider_prints_help_without_mutation(monkeypatch, capsys):
    from ccsilo import __main__ as cli
    import sys

    monkeypatch.setattr(cli, "create_variant", lambda **kwargs: pytest.fail("bare provider mutated state"))
    old_argv = sys.argv
    sys.argv = ["ccsilo", "--provider", "zai"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    output = capsys.readouterr().out
    assert "Provider shortcut commands" in output
    assert "ccsilo --provider zai install" in output


def test_paths_command_reports_workspace_override(monkeypatch, tmp_path, capsys):
    from ccsilo import __main__ as cli
    import sys

    monkeypatch.setenv("CCSILO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setattr(cli, "which", lambda _name: "")
    command_path = tmp_path / "venv" / "bin" / "ccsilo"
    old_argv = sys.argv
    sys.argv = [str(command_path), "paths", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == str(command_path)
    assert payload["workspace"] == str(tmp_path / "workspace")
    assert payload["workspaceOverride"] is True
    assert payload["workspaceOverrideEnv"] == "CCSILO_WORKSPACE"


def test_provider_shortcut_multiple_matching_setups_errors(monkeypatch):
    from ccsilo import __main__ as cli

    variants = [
        SimpleNamespace(name="One", variant_id="one", manifest={"provider": {"key": "zai"}}),
        SimpleNamespace(name="Two", variant_id="two", manifest={"provider": {"key": "zai"}}),
    ]
    monkeypatch.setattr(cli, "load_variant", lambda name: (_ for _ in ()).throw(ValueError("missing")))
    monkeypatch.setattr(cli, "scan_variants", lambda: variants)

    with pytest.raises(ValueError, match="Multiple setups use provider zai"):
        cli._resolve_provider_variant("zai", required=True)


def test_provider_shortcut_resolves_single_matching_setup_from_workspace(monkeypatch, tmp_path):
    from ccsilo import __main__ as cli
    from ccsilo.workspace import write_json

    root = tmp_path / ".ccsilo"
    variant_dir = root / "variants" / "custom-zai"
    variant_dir.mkdir(parents=True)
    write_json(
        variant_dir / "variant.json",
        {
            "schemaVersion": 1,
            "id": "custom-zai",
            "name": "Custom Zai",
            "provider": {"key": "zai", "label": "Zai Cloud"},
            "source": {"version": "2.1.0"},
            "paths": {},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        },
    )
    monkeypatch.setenv("CCSILO_WORKSPACE", str(root))

    resolved = cli._resolve_provider_variant("zai", required=True)

    assert resolved.variant_id == "custom-zai"

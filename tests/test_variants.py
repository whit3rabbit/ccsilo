import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cc_extractor.binary_patcher.bun_compat import BUN_NODE_COMPAT_MARKER
from cc_extractor.bun_extract import parse_bun_binary
from cc_extractor.variants import (
    VariantBuildError,
    apply_variant,
    create_variant,
    doctor_variant,
    list_variant_providers,
    load_variant,
    remove_variant,
    run_variant,
    scan_variants,
    update_variants,
    update_variant_models,
)
from cc_extractor.variants.builder import patch_entry_js
from cc_extractor.variants.wrapper import write_wrapper
from cc_extractor.variants.wrapper import write_secrets
from cc_extractor.workspace import NativeArtifact
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


def test_create_variant_writes_isolated_layout_wrapper_and_metadata(tmp_path):
    root = tmp_path / ".cc-extractor"
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
    assert "ZAI CLOUD" in wrapper
    assert result.variant.manifest["env"]["CC_EXTRACTOR_SPLASH"] == "1"
    assert result.variant.manifest["env"]["CC_EXTRACTOR_SPLASH_STYLE"] == "zai"
    assert result.variant.manifest["tweaks"] == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
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


def test_create_ccrouter_variant_persists_env_unset_and_wrapper_unsets_bedrock(tmp_path):
    root = tmp_path / ".cc-extractor"
    artifact = write_source_artifact(tmp_path)

    result = create_variant(
        name="CCR Test",
        provider_key="ccrouter",
        root=root,
        source_artifact=artifact,
        force=True,
    )

    wrapper = result.wrapper_path.read_text(encoding="utf-8")

    assert result.variant.manifest["envUnset"] == ["CLAUDE_CODE_USE_BEDROCK"]
    assert "unset CLAUDE_CODE_USE_BEDROCK" in wrapper
    assert wrapper.index("export ANTHROPIC_BASE_URL=http://127.0.0.1:3456") < wrapper.index("unset CLAUDE_CODE_USE_BEDROCK") < wrapper.index("\nexec ")


def test_create_variant_persists_base_url_override(tmp_path):
    root = tmp_path / ".cc-extractor"
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


def test_create_and_reapply_variant_preserves_selected_optional_mcp(tmp_path, monkeypatch):
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
    artifact = write_macho_source_artifact(tmp_path)
    patch_calls = []

    def fake_apply_patches(inputs):
        patch_calls.append(inputs)
        return SimpleNamespace(
            ok=True,
            skipped_reason=None,
            missing_prompt_keys=[],
            resigned=False,
            curated_applied=["hide-startup-banner", "hide-startup-clawd", "mcp-non-blocking"],
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
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
    artifact = write_macho_source_artifact(tmp_path)
    patch_calls = []

    def fake_apply_patches(inputs):
        patch_calls.append(inputs)
        return SimpleNamespace(
            ok=True,
            skipped_reason=None,
            missing_prompt_keys=[],
            resigned=False,
            curated_applied=["hide-startup-banner", "hide-startup-clawd", "mcp-non-blocking"],
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
        "mcp-non-blocking",
    ]
    assert result.variant.manifest["patchResults"]["appliedTweaks"] == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
        "mcp-non-blocking",
        "mcp-batch-size",
        "rtk-shell-prefix",
        "dangerously-skip-permissions",
    ]


def test_macos_non_native_regex_tweak_uses_unpacked_node_runtime_not_in_place_binary_patch(tmp_path, monkeypatch):
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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
    root = tmp_path / ".cc-extractor"
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
    root = tmp_path / ".cc-extractor"
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


def _write_node_variant(tmp_path, entry_js):
    root = tmp_path / ".cc-extractor"
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
            "CC_EXTRACTOR_SPLASH": "1",
            "CC_EXTRACTOR_SPLASH_STYLE": "zai",
            "CC_EXTRACTOR_PROVIDER_LABEL": "Zai Cloud",
        },
    )
    wrapper = write_wrapper(manifest)

    non_tty = subprocess.run([str(wrapper)], capture_output=True, text=True, check=False)
    assert non_tty.returncode == 0
    assert "ZAI CLOUD" not in non_tty.stdout
    assert "RUN:" in non_tty.stdout

    tty_output = run_in_pty([str(wrapper)])
    assert "ZAI CLOUD" in tty_output
    assert "RUN:" in tty_output

    machine_output = run_in_pty([str(wrapper), "--output-format", "json"])
    assert "ZAI CLOUD" not in machine_output
    assert "RUN:--output-format json" in machine_output


def test_write_wrapper_splash_disable_and_fallback_style(tmp_path):
    disabled = wrapper_manifest(
        tmp_path / "disabled",
        {
            "CC_EXTRACTOR_SPLASH": "0",
            "CC_EXTRACTOR_SPLASH_STYLE": "zai",
            "CC_EXTRACTOR_PROVIDER_LABEL": "Zai Cloud",
        },
    )
    disabled_output = run_in_pty([str(write_wrapper(disabled))])
    assert "ZAI CLOUD" not in disabled_output
    assert "RUN:" in disabled_output

    fallback = wrapper_manifest(
        tmp_path / "fallback",
        {
            "CC_EXTRACTOR_SPLASH": "1",
            "CC_EXTRACTOR_SPLASH_STYLE": "unknown",
            "CC_EXTRACTOR_PROVIDER_LABEL": "Mystery Provider",
        },
    )
    fallback_output = run_in_pty([str(write_wrapper(fallback))])
    assert "CC EXTRACTOR" in fallback_output
    assert "Mystery Provider" in fallback_output
    assert "RUN:" in fallback_output


def test_apply_variant_rebuilds_from_saved_metadata(tmp_path, monkeypatch):
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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


def test_update_variant_models_rewrites_manifest_and_wrapper_without_rebuild(tmp_path, monkeypatch):
    import cc_extractor.variants as variants_module

    root = tmp_path / ".cc-extractor"
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


def test_update_variant_models_blocks_missing_required_core_aliases(tmp_path):
    root = tmp_path / ".cc-extractor"
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


def test_remove_variant_requires_confirmation_and_removes_wrapper(tmp_path):
    root = tmp_path / ".cc-extractor"
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

    assert remove_variant("zai-test", yes=True, root=root) is True
    assert not result.wrapper_path.exists()
    assert scan_variants(root) == []


def test_remove_variant_ignores_tampered_manifest_wrapper(tmp_path):
    root = tmp_path / ".cc-extractor"
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
    root = tmp_path / ".cc-extractor"
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
    from cc_extractor import __main__ as cli
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
    sys.argv = ["cc-extractor", "variant", "list", "--json"]
    try:
        cli.main()
    finally:
        sys.argv = old_argv

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "fake"


def test_variant_cli_create_show_doctor_and_remove(monkeypatch, tmp_path, capsys):
    from cc_extractor import __main__ as cli
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

    monkeypatch.setattr(cli, "create_variant", fake_create_variant)
    monkeypatch.setattr(cli, "load_variant", lambda name: FakeVariant())
    monkeypatch.setattr(cli, "doctor_variant", lambda name=None, all_variants=False: [{"id": "fake", "name": "Fake", "ok": True, "checks": []}])
    monkeypatch.setattr(cli, "remove_variant", lambda name, yes=False: yes)

    old_argv = sys.argv
    try:
        sys.argv = ["cc-extractor", "variant", "mcp", "--provider", "zai", "--json"]
        cli.main()
        mcp_payload = json.loads(capsys.readouterr().out)
        assert "github" in [item["id"] for item in mcp_payload["optionalMcpServers"]]
        assert "web-reader" in [item["id"] for item in mcp_payload["providerMcpServers"]]

        sys.argv = [
            "cc-extractor",
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
            "--json",
        ]
        cli.main()
        create_payload = json.loads(capsys.readouterr().out)
        assert create_payload["id"] == "fake"
        assert calls[0]["provider_key"] == "zai"
        assert calls[0]["base_url"] == "https://example.test/anthropic"
        assert calls[0]["tweaks"] == ["themes"]
        assert calls[0]["mcp_ids"] == ["github"]

        sys.argv = ["cc-extractor", "variant", "show", "fake", "--json"]
        cli.main()
        assert json.loads(capsys.readouterr().out)["id"] == "fake"

        sys.argv = ["cc-extractor", "variant", "doctor", "fake", "--json"]
        cli.main()
        assert json.loads(capsys.readouterr().out)[0]["ok"] is True

        sys.argv = ["cc-extractor", "variant", "remove", "fake", "--yes"]
        cli.main()
        assert "Removed variant" in capsys.readouterr().out
    finally:
        sys.argv = old_argv

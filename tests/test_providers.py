import json
from pathlib import Path
from urllib.error import URLError

import pytest

import ccsilo.providers.model_discovery as model_discovery
from ccsilo.providers.loader import REGISTRY_DIR
from ccsilo.providers import (
    apply_provider_claude_config,
    build_provider_env,
    fetch_provider_models,
    get_provider,
    list_mcp_catalog,
    list_providers,
    parse_model_ids,
    provider_patch_config,
    provider_models_url,
    provider_prompt_overlays,
)
from ccsilo.providers.proxy import proxy_provider_for_key
from ccsilo.providers.schema import ProviderSchemaError, provider_from_json
from ccsilo.variants import list_variant_providers
from ccsilo.variants.splash import has_style, splash_ascii_art, splash_lines, splash_quote_block


def _minimal_provider_payload(mcp_servers):
    return {
        "schemaVersion": 1,
        "key": "test",
        "label": "Test",
        "description": "Test provider",
        "displayOrder": 999,
        "baseUrl": "",
        "auth": {
            "mode": "none",
            "credentialEnv": "",
        },
        "models": {
            "default": "",
            "smallFast": "",
            "opus": "",
            "sonnet": "",
            "haiku": "",
            "subagent": "",
            "requiresModelMapping": False,
        },
        "env": {},
        "variant": {
            "splashStyle": "",
            "theme": {},
            "noPromptPack": True,
            "promptOverlays": {},
        },
        "claudeConfig": {
            "settingsPermissionsDeny": [],
            "mcpServers": mcp_servers,
        },
        "tui": {
            "headline": "",
            "features": [],
            "setupLinks": {},
            "setupNote": "",
        },
    }


def test_provider_list_includes_cc_mirror_parity_presets():
    keys = [provider.key for provider in list_providers()]

    assert keys.count("ccrouter") == 1
    assert keys.count("ccr-oauth") == 1
    assert keys == [
        "kimi",
        "minimax",
        "minimax-cn",
        "zai",
        "deepseek",
        "alibaba",
        "poe",
        "openrouter",
        "litellm",
        "vercel",
        "ollama",
        "nanogpt",
        "9router",
        "ccrouter",
        "ccr-oauth",
        "cerebras",
        "mirror",
        "anthropic",
        "gatewayz",
        "custom",
        "llamacpp",
        "lmstudio",
        "omlx",
        "local-custom",
    ]


def test_provider_registry_uses_nested_provider_manifests():
    assert (REGISTRY_DIR / "litellm" / "provider.json").is_file()
    assert not (REGISTRY_DIR / "litellm.json").exists()
    assert get_provider("litellm").key == "litellm"


def test_zai_defaults_to_env_ref_without_storing_secret():
    result = build_provider_env("zai")

    assert result.credential == {
        "mode": "env",
        "source": "Z_AI_API_KEY",
        "targets": ["ANTHROPIC_API_KEY", "Z_AI_API_KEY"],
    }
    assert result.secret_env == {}
    assert result.env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert result.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.1"
    assert result.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "glm-5-turbo"
    assert result.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-4.5-air"
    assert "ANTHROPIC_API_KEY" not in result.env


def test_stored_secret_is_separate_from_safe_env():
    result = build_provider_env("zai", api_key="secret-value", store_secret=True)

    assert result.credential["mode"] == "stored"
    assert result.secret_env == {
        "ANTHROPIC_API_KEY": "secret-value",
        "Z_AI_API_KEY": "secret-value",
    }
    assert "secret-value" not in json.dumps(result.env)


def test_api_key_requires_store_secret():
    with pytest.raises(ValueError, match="--store-secret"):
        build_provider_env("zai", api_key="secret-value")


def test_extra_env_rejects_unsafe_shell_key():
    with pytest.raises(ValueError, match=r"--extra-env key"):
        build_provider_env("zai", extra_env=["X; touch /tmp/pwn=1"])


def test_credential_env_rejects_unsafe_shell_key():
    with pytest.raises(ValueError, match="credential env"):
        build_provider_env("zai", credential_env="X; touch /tmp/pwn")


def test_provider_schema_rejects_unsafe_registry_env_keys():
    payload = {
        "schemaVersion": 1,
        "key": "unsafe",
        "label": "Unsafe",
        "description": "Unsafe provider",
        "displayOrder": 999,
        "baseUrl": "",
        "auth": {
            "mode": "none",
            "credentialEnv": "",
        },
        "models": {
            "default": "",
            "smallFast": "",
            "opus": "",
            "sonnet": "",
            "haiku": "",
            "subagent": "",
            "requiresModelMapping": False,
        },
        "env": {"X; touch /tmp/pwn": "1"},
        "variant": {
            "splashStyle": "",
            "theme": {},
            "noPromptPack": True,
            "promptOverlays": {},
        },
        "claudeConfig": {
            "settingsPermissionsDeny": [],
            "mcpServers": {},
        },
        "tui": {
            "headline": "",
            "features": [],
            "setupLinks": {},
            "setupNote": "",
        },
    }

    with pytest.raises(ProviderSchemaError, match="unsafe.env key"):
        provider_from_json(payload)


def test_provider_schema_rejects_unsafe_env_unset_keys():
    payload = _minimal_provider_payload({})
    payload["envUnset"] = ["X; touch /tmp/pwn"]

    with pytest.raises(ProviderSchemaError, match="test.envUnset item"):
        provider_from_json(payload)


def test_provider_schema_rejects_malformed_mcp_servers():
    with pytest.raises(ProviderSchemaError, match=r"bad\.type must be http, stdio, or sse"):
        provider_from_json(_minimal_provider_payload({"bad": {"url": "https://example.com/mcp"}}))

    with pytest.raises(ProviderSchemaError, match=r"bad\.headers must be an object of strings"):
        provider_from_json(_minimal_provider_payload({
            "bad": {
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": ["Authorization: Bearer token"],
            }
        }))

    with pytest.raises(ProviderSchemaError, match=r"bad\.args must be a list of strings"):
        provider_from_json(_minimal_provider_payload({
            "bad": {
                "type": "stdio",
                "command": "node",
                "args": "server.js",
            }
        }))


def test_provider_schema_model_discovery_sets_gateway_env_unless_explicit():
    payload = _minimal_provider_payload({})
    payload["tui"]["modelDiscovery"] = {"enabled": True}

    provider = provider_from_json(payload)

    assert provider.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    payload["env"]["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "0"
    provider = provider_from_json(payload)

    assert provider.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "0"


def test_model_discovery_providers_export_gateway_env():
    providers = [
        provider
        for provider in list_providers()
        if (provider.tui.get("modelDiscovery") or {}).get("enabled")
    ]

    assert {provider.key for provider in providers} == {
        "llamacpp",
        "lmstudio",
        "local-custom",
        "ollama",
        "omlx",
        "openrouter",
        "litellm",
    }
    assert all(
        provider.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
        for provider in providers
    )


def test_model_mapping_providers_require_core_model_overrides():
    with pytest.raises(ValueError, match="requires model mapping"):
        build_provider_env("openrouter")
    with pytest.raises(ValueError, match="requires model mapping"):
        build_provider_env("litellm")
    with pytest.raises(ValueError, match="requires model mapping"):
        build_provider_env("9router")
    with pytest.raises(ValueError, match="requires model mapping"):
        build_provider_env("llamacpp")

    result = build_provider_env(
        "openrouter",
        model_overrides={
            "sonnet": "anthropic/claude-sonnet-4",
            "opus": "anthropic/claude-opus-4",
            "haiku": "anthropic/claude-haiku-4",
        },
    )

    assert result.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "anthropic/claude-sonnet-4"
    assert result.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    litellm = build_provider_env(
        "litellm",
        model_overrides={
            "sonnet": "anthropic/claude-sonnet-4",
            "opus": "anthropic/claude-opus-4",
            "haiku": "openai/gpt-4.1-mini",
        },
    )

    assert litellm.credential == {
        "mode": "env",
        "source": "LITELLM_API_KEY",
        "targets": ["ANTHROPIC_AUTH_TOKEN"],
    }
    assert litellm.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"
    assert litellm.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "openai/gpt-4.1-mini"
    assert litellm.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    router = build_provider_env(
        "9router",
        model_overrides={
            "sonnet": "kr/claude-sonnet-4.5",
            "opus": "cc/claude-opus-4-7",
            "haiku": "oc/kimi-k2.5",
        },
    )

    assert router.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "kr/claude-sonnet-4.5"
    assert router.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "cc/claude-opus-4-7"
    assert router.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "oc/kimi-k2.5"


def test_provider_patch_assets_are_safe_and_prompt_pack_skips_mirror():
    config = provider_patch_config("zai")
    zai_overlays = provider_prompt_overlays("zai")
    minimax_overlays = provider_prompt_overlays("minimax")
    minimax_cn_overlays = provider_prompt_overlays("minimax-cn")

    assert config["settings"]["themes"][0]["id"] == "zai-variant"
    assert provider_prompt_overlays("mirror") == {}
    assert provider_prompt_overlays("deepseek") == {}
    assert set(zai_overlays) == {"webfetch", "explore", "planEnhanced"}
    assert "ZAI MCP tools" in zai_overlays["webfetch"]
    assert "GLM models" in zai_overlays["explore"]
    assert "Do not assume first-party Claude model names" in zai_overlays["planEnhanced"]
    assert set(minimax_overlays) == {"webfetch", "explore", "planEnhanced"}
    assert "MiniMax MCP server" in minimax_overlays["webfetch"]
    assert "MiniMax-M2.7" in minimax_overlays["explore"]
    assert "Do not assume first-party Claude model names" in minimax_overlays["planEnhanced"]
    assert set(minimax_cn_overlays) == {"webfetch", "explore", "planEnhanced"}
    assert "MiniMax China docs" in minimax_cn_overlays["webfetch"]
    assert "China MiniMax Anthropic-compatible endpoint" in minimax_cn_overlays["explore"]
    assert "Do not assume first-party Claude model names" in minimax_cn_overlays["planEnhanced"]


def test_provider_splash_metadata_matches_art_registry():
    for provider in list_providers():
        assert provider.env["CCSILO_SPLASH"] == "1"
        assert provider.env["CCSILO_PROVIDER_LABEL"] == provider.label
        assert has_style(provider.env["CCSILO_SPLASH_STYLE"])


def test_provider_ascii_art_is_unique_plain_and_quoteable():
    art_by_key = {}
    for provider in list_providers():
        style = provider.env["CCSILO_SPLASH_STYLE"]
        art = splash_ascii_art(style)
        quote_block = splash_quote_block(style)

        assert art
        assert "\033" not in art
        assert all(line.startswith("> ") for line in quote_block.splitlines())
        assert [line[2:] for line in quote_block.splitlines()] == art.splitlines()
        art_by_key[provider.key] = art

    assert len(set(art_by_key.values())) == len(art_by_key)


def test_zai_ascii_art_loads_from_text_file_and_keeps_palette():
    art_path = Path(__file__).parents[1] / "ccsilo" / "variants" / "ascii" / "zai.txt"
    expected = art_path.read_text(encoding="utf-8").strip("\n")

    art = splash_ascii_art("zai")
    colored = "\n".join(splash_lines("zai"))

    assert art == expected
    assert "ZAI CLOUD" not in art
    assert "\033" not in art
    assert "++++++++" in colored
    assert r"\033[38;5;220m" in colored
    assert r"\033[38;5;214m" in colored
    assert r"\033[38;5;208m" in colored


def test_ported_provider_defaults_match_cc_mirror_update():
    minimax = build_provider_env("minimax")
    assert minimax.env["ANTHROPIC_MODEL"] == "MiniMax-M2.7"
    assert minimax.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "MiniMax-M2.7"

    minimax_cn = build_provider_env("minimax-cn")
    assert minimax_cn.credential == {
        "mode": "env",
        "source": "MINIMAX_CN_API_KEY",
        "targets": ["ANTHROPIC_API_KEY", "MINIMAX_CN_API_KEY"],
    }
    assert minimax_cn.env["ANTHROPIC_BASE_URL"] == "https://api.minimaxi.com/anthropic"
    assert minimax_cn.env["ANTHROPIC_MODEL"] == "MiniMax-M2.7"

    deepseek = build_provider_env("deepseek")
    assert deepseek.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert deepseek.env["ANTHROPIC_MODEL"] == "deepseek-v4-pro"
    assert deepseek.env["ANTHROPIC_SMALL_FAST_MODEL"] == "deepseek-v4-flash"

    alibaba = build_provider_env("alibaba")
    assert alibaba.env["ANTHROPIC_BASE_URL"] == "https://coding-intl.dashscope.aliyuncs.com/apps/anthropic"
    assert alibaba.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "qwen3-coder-plus"
    assert alibaba.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "qwen3.5-plus"
    assert alibaba.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3-coder-next"

    poe = build_provider_env("poe")
    assert poe.credential["source"] == "POE_API_KEY"
    assert poe.credential["targets"] == ["ANTHROPIC_AUTH_TOKEN"]
    assert poe.env["ANTHROPIC_BASE_URL"] == "https://api.poe.com"

    anthropic = build_provider_env("anthropic")
    assert anthropic.credential == {
        "mode": "env",
        "source": "ANTHROPIC_API_KEY",
        "targets": ["ANTHROPIC_API_KEY"],
    }
    assert anthropic.env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert "ANTHROPIC_MODEL" not in anthropic.env

    router = build_provider_env(
        "9router",
        credential_env="ROUTER_API_KEY",
        model_overrides={
            "sonnet": "kr/claude-sonnet-4.5",
            "opus": "premium-coding",
            "haiku": "oc/kimi-k2.5",
        },
    )
    assert router.credential == {
        "mode": "env",
        "source": "ROUTER_API_KEY",
        "targets": ["ANTHROPIC_API_KEY", "NINEROUTER_API_KEY"],
    }
    assert router.env["ANTHROPIC_BASE_URL"] == "http://localhost:20128/v1"
    assert router.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "premium-coding"


def test_ccrouter_and_cerebras_use_optional_router_fallbacks():
    ccrouter = build_provider_env("ccrouter")
    assert ccrouter.credential == {"mode": "none", "targets": []}
    assert ccrouter.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:3456"
    assert ccrouter.env["ANTHROPIC_AUTH_TOKEN"] == "ccrouter-proxy"
    assert ccrouter.env["NO_PROXY"] == "127.0.0.1"
    assert ccrouter.env["DISABLE_TELEMETRY"] == "true"
    assert ccrouter.env["DISABLE_COST_WARNINGS"] == "true"
    assert ccrouter.env_unset == ["CLAUDE_CODE_USE_BEDROCK"]

    ccr_oauth = build_provider_env(
        "ccr-oauth",
        model_overrides={
            "opus": "claude-opus-test",
            "sonnet": "ccr-worker",
            "haiku": "ccr-worker",
        },
    )
    assert ccr_oauth.credential == {"mode": "none", "targets": []}
    assert ccr_oauth.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:3456"
    assert ccr_oauth.env["ANTHROPIC_AUTH_TOKEN"] == "ccrouter-proxy"
    assert ccr_oauth.env["CCROUTER_AUTH_TOKEN"] == "ccrouter-proxy"
    assert ccr_oauth.env["NO_PROXY"] == "127.0.0.1"

    cerebras = build_provider_env("cerebras")
    assert cerebras.credential == {"mode": "none", "targets": []}
    assert cerebras.env["ANTHROPIC_AUTH_TOKEN"] == "cerebras-proxy"
    assert cerebras.env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "zai-glm-4.7"
    assert cerebras.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "gpt-oss-120b"


def test_local_llm_provider_defaults_and_endpoint_override():
    model_overrides = {"opus": "local-model", "sonnet": "local-model", "haiku": "local-model"}
    ollama = build_provider_env("ollama")
    assert ollama.env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert ollama.env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert ollama.env["ANTHROPIC_API_KEY"] == "ollama"
    assert ollama.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    llamacpp = build_provider_env("llamacpp", model_overrides=model_overrides)
    assert llamacpp.credential == {"mode": "none", "targets": []}
    assert llamacpp.env["ANTHROPIC_BASE_URL"] == "http://localhost:8080"
    assert llamacpp.env["ANTHROPIC_AUTH_TOKEN"] == "llamacpp"
    assert llamacpp.env["ANTHROPIC_API_KEY"] == "llamacpp"
    assert llamacpp.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    lmstudio = build_provider_env("lmstudio", model_overrides=model_overrides)
    assert lmstudio.credential == {"mode": "none", "targets": []}
    assert lmstudio.env["ANTHROPIC_BASE_URL"] == "http://localhost:1234"
    assert lmstudio.env["ANTHROPIC_AUTH_TOKEN"] == "lmstudio"
    assert lmstudio.env["ANTHROPIC_API_KEY"] == "lmstudio"
    assert lmstudio.env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"

    omlx = build_provider_env("omlx", model_overrides=model_overrides)
    assert omlx.env["ANTHROPIC_BASE_URL"] == "http://localhost:8000"
    assert omlx.env["ANTHROPIC_AUTH_TOKEN"] == "omlx"
    assert omlx.env["ANTHROPIC_API_KEY"] == "omlx"

    custom = build_provider_env("local-custom", base_url="http://localhost:8787", model_overrides=model_overrides)
    assert custom.env["ANTHROPIC_BASE_URL"] == "http://localhost:8787"
    assert custom.env["ANTHROPIC_AUTH_TOKEN"] == "local-llm"


def test_local_llm_stored_secret_targets_anthropic_envs():
    result = build_provider_env(
        "lmstudio",
        api_key="secret-value",
        store_secret=True,
        model_overrides={"opus": "local-model", "sonnet": "local-model", "haiku": "local-model"},
    )

    assert result.credential == {
        "mode": "stored",
        "targets": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"],
    }
    assert result.secret_env == {
        "ANTHROPIC_AUTH_TOKEN": "secret-value",
        "ANTHROPIC_API_KEY": "secret-value",
    }


def test_provider_payload_exposes_sections_and_model_discovery():
    providers = {provider["key"]: provider for provider in list_variant_providers()}

    assert providers["mirror"]["section"] == "pinned"
    assert providers["ccrouter"]["section"] == "pinned"
    assert providers["ccr-oauth"]["section"] == "pinned"
    assert "Claude Code OAuth" in providers["ccr-oauth"]["description"]
    assert providers["openrouter"]["modelDiscovery"] == {"enabled": True}
    assert providers["litellm"]["modelDiscovery"] == {"enabled": True}
    assert providers["litellm"]["baseUrl"] == "http://127.0.0.1:4000"
    assert providers["llamacpp"]["section"] == "local"
    assert providers["llamacpp"]["baseUrl"] == "http://localhost:8080"
    assert providers["llamacpp"]["defaultVariantName"] == "ccllamacpp"
    assert providers["llamacpp"]["modelDiscovery"] == {"enabled": True}
    assert providers["lmstudio"]["section"] == "local"
    assert providers["lmstudio"]["modelDiscovery"] == {"enabled": True}
    assert providers["zai"]["section"] == "cloud"


def test_model_discovery_url_and_payload_parsing():
    assert provider_models_url("http://localhost:1234") == "http://localhost:1234/v1/models"
    assert provider_models_url("http://localhost:1234/v1") == "http://localhost:1234/v1/models"
    assert provider_models_url("http://localhost:8080") == "http://localhost:8080/v1/models"
    assert parse_model_ids({"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]}) == ["a", "b"]
    assert parse_model_ids({"models": [{"key": "lmstudio-model"}, {"name": "fallback-name"}]}) == [
        "lmstudio-model",
        "fallback-name",
    ]
    assert parse_model_ids({"data": []}) == []


def test_proxy_provider_model_parsers():
    openrouter = proxy_provider_for_key("openrouter")
    litellm = proxy_provider_for_key("litellm")

    assert openrouter.parse_model_ids(
        {
            "data": [
                {"id": "tool-model", "supported_parameters": ["tools"]},
                {"id": "plain-model", "supported_parameters": ["temperature"]},
                {"id": "choice-model", "supported_parameters": ["tool_choice"]},
            ]
        }
    ) == ("tool-model", "choice-model")
    assert litellm.parse_model_ids({"data": [{"id": "anthropic/claude-sonnet"}]}) == ("anthropic/claude-sonnet",)


def test_fetch_provider_models_success_and_errors(monkeypatch):
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    calls = []

    def ok_urlopen(request, timeout):
        calls.append((request.full_url, request.headers.get("Authorization"), timeout))
        return Response(b'{"data":[{"id":"model-a"}]}')

    monkeypatch.setattr(model_discovery, "urlopen", ok_urlopen)
    assert fetch_provider_models("http://localhost:1234", api_key="secret", timeout=1.5) == ["model-a"]
    assert calls == [("http://localhost:1234/v1/models", "Bearer secret", 1.5)]

    monkeypatch.setattr(model_discovery, "urlopen", lambda _request, timeout: Response(b"{"))
    with pytest.raises(RuntimeError, match="Malformed model list"):
        fetch_provider_models("http://localhost:1234")

    monkeypatch.setattr(model_discovery, "urlopen", lambda _request, timeout: Response(b'{"unexpected":[]}'))
    with pytest.raises(RuntimeError, match="did not contain"):
        fetch_provider_models("http://localhost:1234")

    def fail_urlopen(_request, timeout):
        raise URLError("refused")

    monkeypatch.setattr(model_discovery, "urlopen", fail_urlopen)
    with pytest.raises(RuntimeError, match="Failed to refresh models"):
        fetch_provider_models("http://localhost:1234")


def test_provider_schema_exposes_tui_and_config_metadata():
    provider = get_provider("zai")

    assert provider.tui["headline"] == "Z.ai Coding Plan"
    assert provider.settings_permissions_deny == [
        "mcp__4_5v_mcp__analyze_image",
        "mcp__milk_tea_server__claim_milk_tea_coupon",
        "mcp__web_reader__webReader",
    ]
    assert sorted(provider.mcp_servers) == ["web-reader", "web-search-prime", "zai-mcp-server", "zread"]


def test_mcp_catalog_lists_provider_optional_and_plugin_recommendations():
    catalog = list_mcp_catalog(provider_key="zai")

    assert sorted(item["id"] for item in catalog["providerMcpServers"]) == [
        "web-reader",
        "web-search-prime",
        "zai-mcp-server",
        "zread",
    ]
    assert sorted(item["id"] for item in catalog["optionalMcpServers"]) == [
        "dbhub-postgres",
        "github",
        "notion",
        "sentry",
    ]
    assert "github" in catalog["pluginRecommendations"]


def test_provider_config_writer_merges_zai_mcp_and_denies(tmp_path):
    result = apply_provider_claude_config("zai", tmp_path, credential_value="zai-secret")

    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))

    assert result.settings_changed is True
    assert result.claude_config_changed is True
    assert settings["forceLoginMethod"] == "console"
    assert "mcp__web_reader__webReader" in settings["permissions"]["deny"]
    assert sorted(config["mcpServers"]) == ["web-reader", "web-search-prime", "zai-mcp-server", "zread"]
    assert config["mcpServers"]["web-reader"]["headers"] == {
        "Authorization": "Bearer ${Z_AI_API_KEY}"
    }
    assert config["mcpServers"]["zai-mcp-server"]["env"]["Z_AI_API_KEY"] == "${Z_AI_API_KEY}"
    assert "zai-secret" not in json.dumps(config)

    second = apply_provider_claude_config("zai", tmp_path, credential_value="zai-secret")
    assert second.settings_changed is False
    assert second.claude_config_changed is False


def test_provider_config_writer_preserves_existing_mcp_and_uses_env_refs(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"env": {"EXISTING": "1"}, "theme": "dark", "forceLoginMethod": "claudeai"}),
        encoding="utf-8",
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"user-mcp": {"command": "node", "args": ["server.js"]}}}),
        encoding="utf-8",
    )

    apply_provider_claude_config("zai", tmp_path)
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))

    assert settings["env"] == {"EXISTING": "1"}
    assert settings["theme"] == "dark"
    assert settings["forceLoginMethod"] == "console"
    assert config["mcpServers"]["user-mcp"] == {"command": "node", "args": ["server.js"]}
    assert config["mcpServers"]["web-search-prime"]["headers"] == {
        "Authorization": "Bearer ${Z_AI_API_KEY}"
    }


def test_provider_config_writer_adds_minimax_mcp(tmp_path):
    apply_provider_claude_config("minimax", tmp_path, credential_value="mini-secret")

    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))

    assert settings["permissions"]["deny"] == ["WebSearch"]
    assert settings["forceLoginMethod"] == "console"
    assert config["mcpServers"]["MiniMax"]["command"] == "uvx"
    assert config["mcpServers"]["MiniMax"]["env"]["MINIMAX_API_KEY"] == "${MINIMAX_API_KEY}"
    assert "mini-secret" not in json.dumps(config)


def test_provider_config_writer_adds_selected_optional_mcp(tmp_path):
    apply_provider_claude_config("mirror", tmp_path, optional_mcp_ids=["github"])

    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))

    assert not (tmp_path / "settings.json").exists()
    assert sorted(config["mcpServers"]) == ["github"]
    assert config["mcpServers"]["github"]["type"] == "http"
    assert config["mcpServers"]["github"]["headers"] == {
        "Authorization": "Bearer ${GITHUB_TOKEN}"
    }

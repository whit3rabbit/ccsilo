"""Setup creation and model-edit option helpers."""

from ..providers import PLUGIN_RECOMMENDATIONS, list_optional_mcp_entries
from ..variant_tweaks import CURATED_TWEAK_IDS, default_tweak_ids_for_provider
from ._const import MenuOption, SOURCE_LATEST, VARIANT_MODEL_FIELDS, VARIANT_STEPS
from .options_tweaks import _tweak_display_name

def variant_options(state):
    if state.variant_step == 0:
        options = []
        if state.variants and state.mode not in {"variants", "first-run-setup"}:
            options.append(MenuOption("section", "Existing setups"))
            for variant in state.variants:
                paths = variant.manifest.get("paths", {})
                options.append(MenuOption(
                    "variant-status",
                    f"{variant.variant_id}: {paths.get('wrapper', '(no command)')}",
                    variant.variant_id,
                ))
        if state.variant_providers and state.mode not in {"variants", "first-run-setup"}:
            options.append(MenuOption("section", "Create setup provider"))
        options.extend(_variant_provider_options(state))
        return options
    if state.variant_step == 1:
        name = state.variant_name or "(type a setup name)"
        return [
            MenuOption("variant-name", f"Name: {name}"),
            MenuOption("variant-name-continue", "Continue to credentials"),
            MenuOption("section", "Claude Code version"),
            *_variant_version_options(state),
        ]
    if state.variant_step == 2:
        provider = selected_variant_provider(state)
        if provider is None:
            credential = state.variant_credential_env or "(none)"
            return [
                MenuOption("variant-credential-env", f"Credential env: {credential}"),
                MenuOption("variant-credentials-continue", "Continue to models"),
            ]
        if provider.get("authMode") == "none":
            return [
                MenuOption("section", "Credentials: not required"),
                MenuOption("variant-credentials-continue", "Continue to models"),
            ]
        endpoint = state.variant_base_url or str(provider.get("baseUrl") or "")
        credential = state.variant_credential_env or "(none)"
        store_marker = "[x]" if state.variant_store_secret else "[ ]"
        options = [
            MenuOption("variant-endpoint", f"Endpoint: {endpoint or '(set endpoint)'}"),
            MenuOption("variant-credential-env", f"Credential env: {credential}"),
            MenuOption("variant-store-secret", f"{store_marker} Store API key locally"),
        ]
        if state.variant_store_secret:
            options.append(MenuOption("variant-api-key", f"API key: {_masked_secret(state.variant_api_key)}"))
        options.append(MenuOption("variant-credentials-continue", "Continue to models"))
        return options
    if state.variant_step == 3:
        provider = selected_variant_provider(state)
        options = []
        provider_mcp = list(provider.get("mcpServers") or []) if provider else []
        if provider_mcp:
            credential_env = str(provider.get("credentialEnv") or "").strip() if provider else ""
            env_note = f" env:{credential_env}" if credential_env else ""
            for name in provider_mcp:
                options.append(
                    MenuOption(
                        "variant-mcp-auto",
                        f"[x] {name}  auto-enabled for this provider{env_note}",
                        name,
                    )
                )
        else:
            options.append(MenuOption("section", "Provider MCP servers: none"))
        for entry in list_optional_mcp_entries():
            marker = "[x]" if entry.id in state.selected_variant_mcp_ids else "[ ]"
            env = ", ".join(entry.required_env)
            auth = f" env:{env}" if env else (" oauth" if entry.auth == "oauth" else "")
            options.append(MenuOption("variant-mcp", f"{marker} {entry.name}  ({entry.id}){auth}", entry.id))
        options.append(MenuOption("section", f"Plugin recommendations: {', '.join(PLUGIN_RECOMMENDATIONS)}"))
        next_label = "Continue to models" if provider and provider.get("requiresModelMapping") else "Continue to tweaks"
        options.append(MenuOption("variant-mcp-continue", next_label))
        return options
    if state.variant_step == 4:
        provider = selected_variant_provider(state)
        if provider and not provider.get("requiresModelMapping"):
            return [
                MenuOption("variant-models-default", "Using provider default models"),
                MenuOption("variant-models-continue", "Continue to tweaks"),
            ]
        options = []
        if _provider_model_discovery_enabled(provider):
            options.append(MenuOption("variant-model-refresh", "Refresh model list"))
            if state.variant_model_choices:
                for model_id in state.variant_model_choices:
                    selected = _model_choice_selected(state, model_id)
                    marker = "*" if selected else " "
                    options.append(MenuOption("variant-model-choice", f"{marker} {model_id}", model_id))
            else:
                options.append(MenuOption("section", "No models loaded"))
        for key, label in VARIANT_MODEL_FIELDS:
            value = variant_model_display_value(state, provider, key)
            source = "override" if state.variant_model_overrides.get(key, "").strip() else "default"
            options.append(MenuOption("variant-model", f"{label}: {value or '(not set)'} ({source})", key))
        options.append(MenuOption("variant-models-continue", "Continue to tweaks"))
        return options
    if state.variant_step == 5:
        options = []
        provider = selected_variant_provider(state)
        recommended_ids = default_tweak_ids_for_provider(provider.get("key") if provider else None)
        tweak_ids = recommended_ids if state.tweak_filter == "recommended" else list(CURATED_TWEAK_IDS)
        for tweak_id in tweak_ids:
            marker = "[x]" if tweak_id in state.selected_variant_tweaks else "[ ]"
            options.append(MenuOption("variant-tweak", f"{marker} {_tweak_display_name(tweak_id)}  ({tweak_id})", tweak_id))
        if state.tweak_filter == "recommended":
            options.append(MenuOption("variant-tweak-view", "Show advanced tweaks", "all"))
        else:
            options.append(MenuOption("variant-tweak-view", "Show recommended tweaks", "recommended"))
        options.append(MenuOption("variant-tweaks-continue", "Continue to review"))
        return options
    return [
        MenuOption("variant-create", "Preview setup create"),
        MenuOption("variant-review-back", "Back to tweaks"),
        MenuOption("variant-reset", "Reset setup wizard"),
    ]

def _variant_provider_options(state):
    options = []
    for provider in _providers_for_section(state, "pinned"):
        options.append(_variant_provider_option(state, provider))
    cloud = _providers_for_section(state, "cloud")
    if cloud:
        options.append(MenuOption("section", "Cloud Providers"))
        options.extend(_variant_provider_option(state, provider) for provider in cloud)
    local = _providers_for_section(state, "local")
    if local:
        options.append(MenuOption("section", "Local LLMs"))
        options.extend(_variant_provider_option(state, provider) for provider in local)
    return options

def _variant_version_options(state):
    selected = state.variant_claude_version or SOURCE_LATEST
    latest = (state.download_index.get("binary") or {}).get("latest")
    latest_label = "Claude Code: latest native binary"
    if latest:
        latest_label = f"{latest_label} ({latest})"
    options = [
        MenuOption(
            "variant-version-latest",
            _variant_version_label(selected == SOURCE_LATEST, latest_label),
            SOURCE_LATEST,
        ),
        MenuOption("variant-version-refresh", "Refresh version list"),
    ]
    for version in state.download_versions:
        suffix = " (latest)" if version == latest else ""
        label = f"Claude Code: {version}{suffix}"
        options.append(
            MenuOption(
                "variant-version",
                _variant_version_label(selected == version, label),
                version,
            )
        )
    return options

def _variant_version_label(selected, label):
    return f"* {label}" if selected else f"  {label}"

def _providers_for_section(state, section):
    providers = [
        (index, provider)
        for index, provider in enumerate(state.variant_providers)
        if str(provider.get("section") or _default_provider_section(provider.get("key"))) == section
    ]
    if section == "pinned":
        order = {"mirror": 0, "ccrouter": 1}
        providers.sort(key=lambda item: (order.get(item[1].get("key"), 99), item[1].get("label", "")))
    return providers

def _default_provider_section(provider_key):
    if provider_key in {"mirror", "ccrouter"}:
        return "pinned"
    if provider_key in {"ollama", "lmstudio", "omlx", "local-custom"}:
        return "local"
    return "cloud"

def _variant_provider_option(state, item):
    index, provider = item
    return MenuOption(
        "variant-provider",
        f"{provider['key']}  {provider['label']} - {provider.get('description', '')} {_provider_markers(provider)}",
        index,
    )

def variant_provider_selector_labels(state):
    labels = []
    for option in variant_options(state):
        if option.kind == "variant-provider":
            labels.append(_variant_provider_row_label(_provider_by_index(state, option.value)))
        else:
            labels.append(option.label)
    return labels

def variant_provider_detail_lines(state):
    provider = _highlighted_variant_provider(state)
    if provider is None:
        return ["No provider selected."]

    tui = provider.get("tui") or {}
    headline = str(tui.get("headline") or provider.get("label") or provider.get("key") or "Provider")
    description = str(provider.get("description") or "No description.")
    lines = [
        headline,
        "",
        description,
        "",
        "Configuration",
        f"Provider key: {provider.get('key') or '?'}",
        f"Section: {provider.get('section') or _default_provider_section(provider.get('key'))}",
        f"Auth: {provider.get('authMode') or 'apiKey'}",
        f"Credential env: {provider.get('credentialEnv') or 'not required'}",
        f"Endpoint: {provider.get('baseUrl') or 'provider default'}",
        f"Model mapping: {'required' if provider.get('requiresModelMapping') else 'provider defaults'}",
        f"Model discovery: {'enabled' if _provider_model_discovery_enabled(provider) else 'not available'}",
        "",
        "Enabled by default",
        f"Prompt pack: {'off' if provider.get('noPromptPack') else 'on'}",
        f"MCP servers: {_list_or_none(provider.get('mcpServers'))}",
        f"Settings deny: {_list_or_none(provider.get('settingsPermissionsDeny'))}",
        f"Env unset: {_list_or_none(provider.get('envUnset'))}",
    ]

    model_lines = _provider_model_lines(provider)
    if model_lines:
        lines.extend(["", "Models", *model_lines])

    features = _string_list(tui.get("features"))
    if features:
        lines.extend(["", "Features", *[f"- {feature}" for feature in features]])

    setup_note = str(tui.get("setupNote") or "").strip()
    if setup_note:
        lines.extend(["", "Setup note", setup_note])

    links = tui.get("setupLinks") or {}
    if isinstance(links, dict) and links:
        lines.extend(["", "Setup links"])
        for key, value in sorted(links.items()):
            lines.append(f"{key}: {value}")

    return lines

def _variant_provider_row_label(provider):
    if not provider:
        return "unknown provider"
    key = str(provider.get("key") or "?")
    label = str(provider.get("label") or key)
    markers = []
    auth_mode = provider.get("authMode") or "apiKey"
    if auth_mode == "none":
        markers.append("no-auth")
    else:
        markers.append(str(auth_mode))
    if provider.get("requiresModelMapping"):
        markers.append("model-map")
    if provider.get("mcpServers"):
        markers.append("mcp")
    if provider.get("section") == "local" or provider.get("baseUrl", "").startswith(("http://127.0.0.1", "http://localhost")):
        markers.append("local")
    return f"{key}  {label} [{', '.join(markers)}]"

def _highlighted_variant_provider(state):
    option = selected_variant_option(state)
    if option is not None and option.kind == "variant-provider":
        return _provider_by_index(state, option.value)
    return selected_variant_provider(state)

def _provider_by_index(state, value):
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(state.variant_providers):
        return None
    return state.variant_providers[index]

def _list_or_none(values):
    values = [str(value) for value in (values or []) if str(value)]
    return ", ".join(values) if values else "none"

def _provider_model_lines(provider):
    models = provider.get("models") or {}
    if not isinstance(models, dict) or not models:
        return []
    return [
        f"{key}: {value}"
        for key, value in sorted(models.items())
        if str(value).strip()
    ]

def _string_list(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]

def _masked_secret(value):
    return "set" if str(value or "").strip() else "not set"

def _provider_model_discovery_enabled(provider):
    discovery = (provider or {}).get("modelDiscovery") or {}
    return bool(discovery.get("enabled"))

def _model_choice_selected(state, model_id):
    overrides = state.variant_model_overrides or {}
    return bool(overrides) and all(overrides.get(key) == model_id for key, _label in VARIANT_MODEL_FIELDS)

def _provider_markers(provider):
    markers = []
    auth_mode = provider.get("authMode") or "apiKey"
    markers.append(f"auth:{auth_mode}")
    if provider.get("credentialOptional"):
        markers.append("credential:optional")
    if provider.get("requiresModelMapping"):
        markers.append("model-map:required")
    if provider.get("section") == "local" or provider.get("baseUrl", "").startswith(("http://127.0.0.1", "http://localhost")):
        markers.append("local")
    if _provider_model_discovery_enabled(provider):
        markers.append("models:refresh")
    markers.append("prompt-pack:off" if provider.get("noPromptPack") else "prompt-pack:on")
    if provider.get("mcpServers"):
        markers.append("mcp")
    return "[" + ", ".join(markers) + "]"

def variant_model_display_value(state, provider, key):
    override = state.variant_model_overrides.get(key, "").strip()
    if override:
        return override
    if not provider:
        return ""
    return str(provider.get("models", {}).get(key) or "")

def selected_variant_option(state):
    options = variant_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def selected_variant_provider(state):
    if not state.variant_providers:
        return None
    index = max(0, min(state.variant_provider_index, len(state.variant_providers) - 1))
    return state.variant_providers[index]

def provider_for_setup(state, variant):
    provider_key = str(((variant.manifest or {}).get("provider") or {}).get("key") or "")
    for provider in state.variant_providers:
        if provider.get("key") == provider_key:
            return provider
    return {
        "key": provider_key,
        "label": provider_key or "?",
        "models": {},
        "modelDiscovery": {},
        "requiresModelMapping": bool((variant.manifest or {}).get("modelOverrides")),
    }

def models_edit_options(state):
    variant = models_edit_variant(state)
    if variant is None:
        return [MenuOption("models-back", "Back to setup")]
    provider = provider_for_setup(state, variant)
    options = []
    if _provider_model_discovery_enabled(provider):
        options.append(MenuOption("models-refresh", "Refresh model list"))
        if state.models_choices:
            for model_id in state.models_choices:
                marker = "*" if _models_choice_selected(state, model_id) else " "
                options.append(MenuOption("models-choice", f"{marker} {model_id}", model_id))
        else:
            options.append(MenuOption("section", "No models loaded"))
    for key, label in VARIANT_MODEL_FIELDS:
        value = models_display_value(state, provider, key)
        source = "override" if state.models_pending.get(key, "").strip() else "default"
        options.append(MenuOption("models-field", f"{label}: {value or '(not set)'} ({source})", key))
    options.append(MenuOption("models-apply", "Apply model changes"))
    options.append(MenuOption("models-discard", "Discard model changes"))
    return options

def models_edit_variant(state):
    if not state.models_variant_id:
        return None
    for variant in state.variants:
        if variant.variant_id == state.models_variant_id:
            return variant
    return None

def selected_models_edit_option(state):
    options = models_edit_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def models_display_value(state, provider, key):
    override = state.models_pending.get(key, "").strip()
    if override:
        return override
    return str((provider or {}).get("models", {}).get(key) or "")

def models_pending_diff(state):
    baseline = {
        key: value
        for key, value in (state.models_baseline or {}).items()
        if str(value or "").strip()
    }
    pending = {
        key: value
        for key, value in (state.models_pending or {}).items()
        if str(value or "").strip()
    }
    return {
        "changed": sorted(key for key in set(baseline) | set(pending) if baseline.get(key) != pending.get(key)),
        "pending": pending,
    }

def _models_choice_selected(state, model_id):
    pending = state.models_pending or {}
    return bool(pending) and all(pending.get(key) == model_id for key, _label in VARIANT_MODEL_FIELDS)

def variant_title(state):
    return f"Create setup: {VARIANT_STEPS[state.variant_step]}"

def variant_steps(state):
    labels = []
    for index, step in enumerate(VARIANT_STEPS):
        if index == state.variant_step:
            labels.append(f"[{step}]")
        elif index < state.variant_step:
            labels.append(f"{step}*")
        else:
            labels.append(step)
    return "Setup steps: " + " > ".join(labels)

def variant_summary(state):
    provider = selected_variant_provider(state)
    name = state.variant_name or (provider.get("defaultVariantName") if provider else "")
    credential = state.variant_credential_env or "none"
    model_count = len([value for value in state.variant_model_overrides.values() if value.strip()])
    return (
        f"Provider: {provider.get('key') if provider else 'none'}  "
        f"Name: {name or 'none'}  "
        f"Credential env: {credential}  "
        f"Model overrides: {model_count}  "
        f"Tweaks: {len(state.selected_variant_tweaks)}"
    )

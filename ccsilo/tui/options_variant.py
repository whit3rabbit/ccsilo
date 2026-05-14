"""Setup creation and model-edit option helpers."""

from ..providers import PLUGIN_RECOMMENDATIONS, list_optional_mcp_entries
from ..variants import CCR_PROVIDER_KEYS
from ..variant_tweaks import (
    CURATED_TWEAK_IDS,
)
from ._const import (
    ARCHITECT_MODE_TWEAK_ID,
    MenuOption,
    SOURCE_LATEST,
    VARIANT_MODEL_FIELDS,
    VARIANT_STEPS,
    next_action_label,
)
from .options_variant_provider_detail import variant_model_proxy_supported, variant_provider_detail_lines  # noqa: F401
from .options_variant_provider import (  # noqa: F401
    _default_provider_section,
    _provider_markers,
    _provider_search_text,
    _provider_section,
    _providers_for_section,
    _variant_provider_groups,
    _variant_provider_options,
    variant_provider_control_summary,
    variant_provider_selected_label_index,
    variant_provider_selector_labels,
)
from .options_variant_models import (  # noqa: F401
    models_display_value,
    models_edit_options,
    models_edit_variant,
    models_pending_diff,
    provider_for_setup,
    selected_models_edit_option,
)
from .options_variant_state import _provider_model_discovery_enabled, selected_variant_provider, variant_model_display_value
from .options_variant_tweaks import (  # noqa: F401
    group_setup_tweak_ids,
    variant_setup_tweak_ids,
    variant_tweak_groups,
    variant_tweak_ids,
    variant_tweak_selected_label_index,
    variant_tweak_selector_labels,
    variant_tweak_selector_rows,
)
from .options_tweaks import _tweak_display_name


def variant_options(state):
    if state.variant_step == 0:
        options = []
        if state.variants and state.mode not in {"variants", "first-run-setup"}:
            for variant in state.variants:
                paths = variant.manifest.get("paths", {})
                options.append(MenuOption(
                    "variant-status",
                    f"{variant.variant_id}: {paths.get('wrapper', '(no command)')}",
                    variant.variant_id,
                ))
        options.extend(_variant_provider_options(state))
        return options
    if state.variant_step == 1:
        name = state.variant_name or "(type a setup name)"
        return [
            MenuOption("variant-name", f"Name: {name}"),
            MenuOption("variant-name-continue", next_action_label("Continue to credentials")),
            MenuOption("section", "Claude Code version"),
            *_variant_version_options(state),
        ]
    if state.variant_step == 2:
        provider = selected_variant_provider(state)
        if provider is None:
            credential = state.variant_credential_env or "(none)"
            return [
                MenuOption("variant-credential-env", f"Credential env: {credential}"),
                MenuOption("variant-credentials-continue", next_action_label("Continue to MCP")),
            ]
        if provider.get("authMode") == "none":
            return [
                MenuOption("section", "Credentials: not required"),
                MenuOption("variant-credentials-continue", next_action_label("Continue to MCP")),
            ]
        endpoint = state.variant_base_url or str(provider.get("baseUrl") or "")
        credential = state.variant_credential_env or "(none)"
        store_marker = "[x]" if state.variant_store_secret else "[ ]"
        options = [
            MenuOption("variant-endpoint", f"Endpoint: {endpoint or '(set endpoint)'}"),
            MenuOption("variant-credential-env", f"Credential env: {credential}"),
            MenuOption("variant-store-secret", f"{store_marker} Store API key locally"),
        ]
        if provider.get("key") in CCR_PROVIDER_KEYS:
            options.extend(_ccrouter_credential_options(state))
        if state.variant_store_secret:
            options.append(MenuOption("variant-api-key", f"API key: {_masked_secret(state.variant_api_key)}"))
        options.append(MenuOption("variant-credentials-continue", next_action_label("Continue to MCP")))
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
        options.append(MenuOption("variant-mcp-continue", next_action_label(next_label)))
        return options
    if state.variant_step == 4:
        provider = selected_variant_provider(state)
        if provider and not provider.get("requiresModelMapping"):
            return [
                MenuOption("variant-models-default", "Using provider default models"),
                MenuOption("variant-models-continue", next_action_label("Continue to tweaks")),
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
        options.append(MenuOption("variant-models-continue", next_action_label("Continue to tweaks")))
        return options
    if state.variant_step == 5:
        options = []
        provider = selected_variant_provider(state)
        if ARCHITECT_MODE_TWEAK_ID in CURATED_TWEAK_IDS:
            marker = "[x]" if ARCHITECT_MODE_TWEAK_ID in state.selected_variant_tweaks else "[ ]"
            options.append(
                MenuOption(
                    "variant-architect-mode",
                    f"{marker} Architect Mode  (model picker alias, no Claude OAuth)",
                    ARCHITECT_MODE_TWEAK_ID,
                )
            )
        if variant_model_proxy_supported(provider):
            marker = "[x]" if state.variant_model_proxy == "architect" else "[ ]"
            options.extend(
                [
                    MenuOption(
                        "variant-model-proxy",
                        f"{marker} OAuth architect proxy  (requires Claude Code account)",
                        "architect",
                    ),
                ]
            )
            if state.variant_model_proxy == "architect":
                options.append(
                    MenuOption(
                        "variant-model-proxy-port",
                        f"Model proxy port: {state.variant_model_proxy_port or 'auto'}",
                    )
                )
        for _group, tweak_ids in variant_tweak_groups(state):
            for tweak_id in tweak_ids:
                marker = "[x]" if tweak_id in state.selected_variant_tweaks else "[ ]"
                options.append(MenuOption("variant-tweak", f"{marker} {_tweak_display_name(tweak_id)}  ({tweak_id})", tweak_id))
        if state.tweak_filter == "recommended":
            options.append(MenuOption("variant-tweak-view", "Show advanced tweaks", "all"))
        else:
            options.append(MenuOption("variant-tweak-view", "Show recommended tweaks", "recommended"))
        options.append(MenuOption("variant-tweaks-continue", next_action_label("Continue to review")))
        return options
    return [
        MenuOption("variant-create", next_action_label("Preview setup create")),
        MenuOption("variant-review-back", "Back to tweaks"),
        MenuOption("variant-reset", "Reset setup wizard"),
    ]


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


def _ccrouter_credential_options(state):
    options = [
        MenuOption("section", "Managed CCR"),
        MenuOption("variant-ccrouter-mode", f"Mode: {state.variant_ccrouter_mode}"),
    ]
    if state.variant_ccrouter_mode == "managed":
        auto_marker = "[x]" if state.variant_ccrouter_autostart else "[ ]"
        options.extend(
            [
                MenuOption("variant-ccrouter-config", f"Config source: {state.variant_ccrouter_config}"),
                MenuOption("variant-ccrouter-package", f"NPM package: {state.variant_ccrouter_package or '(set package)'}"),
                MenuOption("variant-ccrouter-port", f"Port: {state.variant_ccrouter_port or 'auto'}"),
                MenuOption("variant-ccrouter-autostart", f"{auto_marker} Auto-start CCR"),
            ]
        )
    return options


def _masked_secret(value):
    return "set" if str(value or "").strip() else "not set"


def _model_choice_selected(state, model_id):
    overrides = state.variant_model_overrides or {}
    return bool(overrides) and all(overrides.get(key) == model_id for key, _label in VARIANT_MODEL_FIELDS)


def selected_variant_option(state):
    options = variant_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]


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

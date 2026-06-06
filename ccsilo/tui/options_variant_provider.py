"""Provider selector and detail helpers for setup creation."""

from ..variants import CCR_PROVIDER_KEYS
from ._const import MenuOption
from .options_variant_state import _provider_model_discovery_enabled, selected_variant_provider

PROVIDER_FILTER_LABELS = {
    "all": "All",
    "recommended": "Recommended",
    "cloud": "Cloud",
    "local": "Local",
    "model-map": "Needs model map",
    "mcp": "MCP",
}
PROVIDER_GROUPS = [
    ("pinned", "Recommended defaults"),
    ("cloud-direct", "Direct model APIs"),
    ("cloud-gateway", "Gateways, routers, and custom endpoints"),
    ("local", "Local endpoints"),
]
PINNED_PROVIDER_ORDER = {"mirror": 0, "ccrouter": 1, "ccr-oauth": 2}
DIRECT_MODEL_API_PROVIDER_KEYS = {
    "alibaba",
    "anthropic",
    "deepseek",
    "kimi",
    "minimax",
    "minimax-cn",
    "zai",
}
GATEWAY_PROVIDER_KEYS = {
    "9router",
    "cerebras",
    "custom",
    "gatewayz",
    "litellm",
    "nanogpt",
    "opencode-go",
    "opencode-zen",
    "openrouter",
    "poe",
    "vercel",
}

__all__ = [
    "_variant_provider_options",
    "_providers_for_section",
    "_variant_provider_groups",
    "_provider_group_key",
    "_provider_matches_controls",
    "_provider_matches_filter",
    "_provider_matches_search",
    "_provider_search_text",
    "_provider_section",
    "_default_provider_section",
    "_variant_provider_option",
    "variant_provider_selector_labels",
    "variant_provider_selected_label_index",
    "variant_provider_control_summary",
    "_variant_provider_selector_rows",
    "_variant_provider_row_label",
    "_highlighted_variant_provider",
    "_provider_by_index",
    "_string_list",
    "_provider_markers",
]

def _variant_provider_options(state):
    options = []
    for _group_key, _group_label, providers in _variant_provider_groups(state):
        options.extend(_variant_provider_option(state, provider) for provider in providers)
    return options

def _providers_for_section(state, section):
    providers = [
        (index, provider)
        for index, provider in enumerate(state.variant_providers)
        if _provider_section(provider) == section
    ]
    providers.sort(key=lambda item: _provider_sort_key("pinned" if section == "pinned" else "", item))
    return providers

def _variant_provider_groups(state):
    candidates = [
        (index, provider)
        for index, provider in enumerate(state.variant_providers)
        if _provider_matches_controls(state, provider)
    ]
    groups = []
    for group_key, label in PROVIDER_GROUPS:
        providers = [
            (index, provider)
            for index, provider in candidates
            if _provider_group_key(provider) == group_key
        ]
        providers.sort(key=lambda item: _provider_sort_key(group_key, item))
        if providers:
            groups.append((group_key, label, providers))
    return groups

def _provider_group_key(provider):
    section = _provider_section(provider)
    if section == "pinned":
        return "pinned"
    if section == "local":
        return "local"
    key = str(provider.get("key") or "")
    if key in DIRECT_MODEL_API_PROVIDER_KEYS:
        return "cloud-direct"
    if provider.get("requiresModelMapping") or key in GATEWAY_PROVIDER_KEYS:
        return "cloud-gateway"
    return "cloud-direct"

def _provider_sort_key(group_key, item):
    _index, provider = item
    key = str(provider.get("key") or "").lower()
    label = str(provider.get("label") or "").lower()
    if group_key == "pinned":
        return (PINNED_PROVIDER_ORDER.get(key, 99), key, label)
    return (key, label)

def _provider_matches_controls(state, provider):
    return _provider_matches_filter(state, provider) and _provider_matches_search(state, provider)

def _provider_matches_filter(state, provider):
    filter_key = getattr(state, "variant_provider_filter", "all") or "all"
    if filter_key == "all":
        return True
    section = _provider_section(provider)
    if filter_key == "recommended":
        return section == "pinned" or (section == "cloud" and not provider.get("requiresModelMapping"))
    if filter_key == "cloud":
        return section == "cloud"
    if filter_key == "local":
        return section == "local"
    if filter_key == "model-map":
        return bool(provider.get("requiresModelMapping"))
    if filter_key == "mcp":
        return bool(provider.get("mcpServers"))
    return True

def _provider_matches_search(state, provider):
    query = (getattr(state, "variant_provider_search_text", "") or "").strip().lower()
    if not query:
        return True
    return query in _provider_search_text(provider)

def _provider_search_text(provider):
    parts = [
        provider.get("key"),
        provider.get("label"),
        provider.get("description"),
        provider.get("authMode"),
        provider.get("credentialEnv"),
        provider.get("baseUrl"),
        _provider_section(provider),
    ]
    parts.extend(_string_list(provider.get("mcpServers")))
    parts.extend(_string_list(provider.get("settingsPermissionsDeny")))
    parts.extend(_string_list(provider.get("envUnset")))
    tui = provider.get("tui") or {}
    if isinstance(tui, dict):
        parts.extend([tui.get("headline"), tui.get("setupNote")])
        parts.extend(_string_list(tui.get("features")))
        links = tui.get("setupLinks") or {}
        if isinstance(links, dict):
            parts.extend(str(key) for key in links)
            parts.extend(str(value) for value in links.values())
    return " ".join(str(part).lower() for part in parts if str(part or "").strip())

def _provider_section(provider):
    return str(provider.get("section") or _default_provider_section(provider.get("key")))

def _default_provider_section(provider_key):
    if provider_key in {"mirror", *CCR_PROVIDER_KEYS}:
        return "pinned"
    if provider_key in {"ollama", "lmstudio", "omlx", "local-custom"}:
        return "local"
    return "cloud"

def _variant_provider_option(state, item):
    index, provider = item
    return MenuOption(
        "variant-provider",
        _variant_provider_row_label(provider),
        index,
    )

def variant_provider_selector_labels(state):
    return [label for label, _option_index in _variant_provider_selector_rows(state)]

def variant_provider_selected_label_index(state):
    rows = _variant_provider_selector_rows(state)
    if not rows:
        return 0
    for row_index, (_label, option_index) in enumerate(rows):
        if option_index == state.selected_index:
            return row_index
    return 0

def variant_provider_control_summary(state):
    search = (getattr(state, "variant_provider_search_text", "") or "").strip()
    search_label = search if search else "none"
    if getattr(state, "variant_provider_search_active", False):
        search_label = f"{search_label} (typing)"
    filter_key = getattr(state, "variant_provider_filter", "all") or "all"
    filter_label = PROVIDER_FILTER_LABELS.get(filter_key, filter_key)
    shown = sum(len(providers) for _group_key, _label, providers in _variant_provider_groups(state))
    total = len(state.variant_providers)
    return f"Search: {search_label} | Filter: {filter_label} | Showing: {shown}/{total}"

def _variant_provider_selector_rows(state):
    from .options_variant import variant_options

    options = variant_options(state)
    rows = [(variant_provider_control_summary(state), None)]
    option_index = 0

    if state.variants and state.mode not in {"variants", "first-run-setup"}:
        rows.append((f"Existing setups ({len(state.variants)})", None))
        for _variant in state.variants:
            if option_index < len(options):
                rows.append((options[option_index].label, option_index))
                option_index += 1

    provider_option_count = len(options) - option_index
    if provider_option_count:
        if state.variants and state.mode not in {"variants", "first-run-setup"}:
            rows.append((f"Create setup providers ({provider_option_count})", None))
        for _group_key, label, providers in _variant_provider_groups(state):
            rows.append((f"{label} ({len(providers)})", None))
            for _item in providers:
                if option_index < len(options):
                    rows.append((options[option_index].label, option_index))
                    option_index += 1
    elif state.variant_providers:
        rows.append(("No providers match current search/filter", None))

    return rows


def _variant_provider_row_label(provider):
    if not provider:
        return "unknown provider"
    key = str(provider.get("key") or "?")
    label = str(provider.get("label") or key)
    markers = []
    auth_mode = provider.get("authMode") or "apiKey"
    if auth_mode == "none":
        markers.append("no-auth")
    elif auth_mode == "apiKey":
        markers.append("key")
    elif auth_mode == "authToken":
        markers.append("token")
    else:
        markers.append(str(auth_mode))
    if provider.get("requiresModelMapping"):
        markers.append("model-map")
    if provider.get("mcpServers"):
        markers.append("mcp")
    if _provider_section(provider) == "local" or provider.get("baseUrl", "").startswith(("http://127.0.0.1", "http://localhost")):
        markers.append("local")
    if _provider_model_discovery_enabled(provider):
        markers.append("refresh")
    return f"{key}  {label} [{', '.join(markers)}]"

def _highlighted_variant_provider(state):
    from .options_variant import selected_variant_option

    option = selected_variant_option(state)
    if option is not None and option.kind == "variant-provider":
        return _provider_by_index(state, option.value)
    if state.mode in {"variants", "first-run-setup"} and state.variant_step == 0:
        return None
    return selected_variant_provider(state)

def _provider_by_index(state, value):
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(state.variant_providers):
        return None
    return state.variant_providers[index]


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]

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

"""Setup manager option and selection helpers."""

from pathlib import Path

from ..variants import CCR_PROVIDER_KEYS
from .._utils import version_sort_key
from ._const import MenuOption

def setup_manager_options(state):
    options = [MenuOption("setup-action-new", "Create new setup")]
    for variant in setup_manager_variants(state):
        options.append(MenuOption("setup-row", setup_row_label(state, variant), variant.variant_id))
    return options

def setup_provider_keys(state):
    return sorted({
        str((variant.manifest.get("provider") or {}).get("key") or "?")
        for variant in state.variants
        if variant.manifest
    })

def setup_manager_variants(state):
    variants = list(state.variants)
    provider_filter = getattr(state, "setup_provider_filter", "all") or "all"
    if provider_filter != "all":
        variants = [
            variant for variant in variants
            if _setup_provider(variant) == provider_filter
        ]

    query = (getattr(state, "setup_search_text", "") or "").strip().lower()
    if query:
        variants = [
            variant for variant in variants
            if query in _setup_search_text(variant)
        ]

    return sorted(variants, key=lambda variant: _setup_sort_value(state, variant))

def setup_manager_empty_label(state):
    if not state.variants:
        return "No setups found."
    if len(setup_manager_variants(state)) == 0:
        return "No setups match current search/filter."
    return ""

def setup_manager_control_summary(state):
    search = getattr(state, "setup_search_text", "") or ""
    search_label = search if search else "none"
    if getattr(state, "setup_search_active", False):
        search_label = f"{search_label} (typing)"
    provider = getattr(state, "setup_provider_filter", "all") or "all"
    sort_key = getattr(state, "setup_sort_key", "name") or "name"
    return f"Search: {search_label} | Provider: {provider} | Sort: {sort_key}"

def _setup_sort_value(state, variant):
    sort_key = getattr(state, "setup_sort_key", "name") or "name"
    if sort_key == "provider":
        return (_setup_provider(variant), variant.variant_id)
    if sort_key == "health":
        return (_setup_health_rank(setup_health_status(state, variant.variant_id)), variant.variant_id)
    if sort_key == "updated":
        return (_setup_updated(variant), variant.variant_id)
    if sort_key == "version":
        return (version_sort_key(_setup_version(variant)), variant.variant_id)
    return (variant.variant_id, )

def _setup_search_text(variant):
    manifest = variant.manifest or {}
    paths = manifest.get("paths") or {}
    wrapper = str(paths.get("wrapper") or "")
    parts = [
        variant.variant_id,
        str(manifest.get("name") or ""),
        _setup_provider(variant),
        _setup_version(variant),
        wrapper,
        Path(wrapper).name if wrapper else "",
    ]
    return " ".join(parts).lower()

def _setup_provider(variant):
    manifest = variant.manifest or {}
    return str((manifest.get("provider") or {}).get("key") or "?")

def _setup_version(variant):
    manifest = variant.manifest or {}
    return str((manifest.get("source") or {}).get("version") or "?")

def _setup_updated(variant):
    manifest = variant.manifest or {}
    return str(manifest.get("updatedAt") or "")

def _setup_health_rank(status):
    return {
        "broken": 0,
        "warning": 1,
        "unknown": 2,
        "never": 3,
        "healthy": 4,
    }.get(str(status), 2)

def setup_upgrade_action_label(state, variant):
    status = setup_upgrade_status(state, variant)
    current = status["current"]
    latest = status["latest"]
    if status["state"] == "available":
        return f"Upgrade Claude Code ({current} -> {latest})"
    if status["state"] == "current":
        return f"Upgrade Claude Code (up to date: {current})"
    if status["state"] == "ahead":
        return f"Upgrade Claude Code (current {current}; latest {latest})"
    if latest:
        return f"Upgrade Claude Code (latest: {latest})"
    return "Upgrade Claude Code (latest unknown)"

def setup_upgrade_status(state, variant):
    current = _setup_version(variant) if variant is not None else "?"
    latest = str(((getattr(state, "download_index", {}) or {}).get("binary") or {}).get("latest") or "")
    if not latest:
        return {
            "state": "unknown",
            "current": current,
            "latest": "",
        }
    if current in {"", "?", "latest"}:
        return {
            "state": "latest-known",
            "current": current,
            "latest": latest,
        }
    latest_key = version_sort_key(latest)
    current_key = version_sort_key(current)
    if latest_key > current_key:
        state_name = "available"
    elif latest_key == current_key:
        state_name = "current"
    else:
        state_name = "ahead"
    return {
        "state": state_name,
        "current": current,
        "latest": latest,
    }

def setup_detail_options(state):
    setup_id = selected_setup_id(state)
    if setup_id is None:
        return [MenuOption("setup-action-new", "Create new setup")]
    variant = selected_setup_variant(state)
    options = [
        MenuOption("setup-action-run", "Run Claude", setup_id),
        MenuOption("setup-action-health", "Run health check", setup_id),
        MenuOption("setup-action-upgrade", setup_upgrade_action_label(state, variant), setup_id),
        MenuOption("setup-action-models", "Edit models", setup_id),
        MenuOption("setup-action-tweaks", "Edit tweaks", setup_id),
        MenuOption("setup-action-add-tweaks", "Add tweaks", setup_id),
    ]
    if _managed_ccrouter(variant):
        options.extend(
            [
                MenuOption("setup-action-ccrouter-status", "CCR status", setup_id),
                MenuOption("setup-action-ccrouter-start", "Start CCR", setup_id),
                MenuOption("setup-action-ccrouter-stop", "Stop CCR", setup_id),
                MenuOption("setup-action-ccrouter-restart", "Restart CCR", setup_id),
                MenuOption("setup-action-ccrouter-ui", "Open CCR UI", setup_id),
                MenuOption("setup-action-ccrouter-copy-config", "Copy CCR config path", setup_id),
            ]
        )
    options.extend([
        MenuOption("setup-action-delete", "Delete setup", setup_id),
        MenuOption("setup-action-new", "Create new setup"),
    ])
    return options

def setup_row_label(state, variant):
    manifest = variant.manifest or {}
    provider = (manifest.get("provider") or {}).get("key") or "?"
    version = (manifest.get("source") or {}).get("version") or "?"
    health = setup_health_status(state, variant.variant_id)
    return f"{variant.variant_id:<20} {provider:<12} {version:<12} {health:<8} {setup_command_label(variant)}"

def setup_command_label(variant):
    wrapper = (variant.manifest.get("paths") or {}).get("wrapper") if variant.manifest else ""
    if not wrapper:
        return "(no command)"
    return Path(str(wrapper)).name or str(wrapper)

def setup_health_status(state, setup_id):
    summary = state.setup_health.get(setup_id)
    if not summary:
        return "never"
    return str(summary.get("status") or "unknown")

def selected_setup_option(state):
    options = setup_detail_options(state) if state.mode == "setup-detail" else setup_manager_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def selected_setup_id(state):
    if state.selected_setup_id:
        return state.selected_setup_id
    if state.variants:
        return state.variants[0].variant_id
    return None

def selected_setup_variant(state):
    setup_id = selected_setup_id(state)
    if setup_id is None:
        return None
    for variant in state.variants:
        if variant.variant_id == setup_id:
            return variant
    return None

def setup_detail_lines(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return ["No setup selected."]
    manifest = variant.manifest or {}
    paths = manifest.get("paths") or {}
    provider = (manifest.get("provider") or {}).get("key") or "?"
    version = (manifest.get("source") or {}).get("version") or "?"
    tweak_count = len(manifest.get("tweaks", []) or [])
    lines = [
        f"Setup: {variant.variant_id}",
        f"Provider: {provider}",
        f"Claude Code: {version}",
        f"Health: {setup_health_status(state, variant.variant_id)}",
        f"Command: {paths.get('wrapper') or '(no command)'}",
        f"Setup config: {variant.path / 'variant.json'}",
        f"Enabled tweaks: {tweak_count}",
    ]
    ccrouter = manifest.get("ccrouter") if provider in CCR_PROVIDER_KEYS else None
    if isinstance(ccrouter, dict):
        lines.extend([
            f"CCR mode: {ccrouter.get('mode') or 'external'}",
            f"CCR config: {ccrouter.get('configPath') or '(external)'}",
            f"CCR package: {ccrouter.get('installedVersion') or ccrouter.get('packageSpec') or '(external)'}",
        ])
    model_proxy = manifest.get("modelProxy")
    if isinstance(model_proxy, dict):
        if model_proxy.get("mode") == "openai":
            lines.extend([
                "Model proxy: OpenAI-compatible backend proxy (CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1)",
                "Model proxy routing: Anthropic Messages requests are converted to OpenAI chat completions",
                f"Model proxy backend: {model_proxy.get('backendUrl') or '(not set)'}",
            ])
        else:
            lines.extend([
                "Model proxy: OAuth architect proxy (CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1)",
                "Model proxy requirement: Requires Claude Code account/login",
                "Model proxy account: claude-* requests use Claude Code OAuth/session",
                "Model proxy routing: non-Claude model aliases use the provider backend",
                f"Model proxy backend: {model_proxy.get('backendUrl') or '(not set)'}",
            ])
    return lines


def _managed_ccrouter(variant):
    manifest = variant.manifest if variant is not None else {}
    ccrouter = manifest.get("ccrouter") if isinstance(manifest, dict) else None
    return isinstance(ccrouter, dict) and ccrouter.get("mode") == "managed"

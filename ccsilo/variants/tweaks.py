"""Registry-delegating shim for variant tweaks. All tweaks are registered in patches._registry."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from ..patches import PatchContext as _PatchCtx, apply_patches as _apply_patches, PatchAnchorMissError
from ..patches._registry import REGISTRY as _PATCH_REGISTRY
from ..patches.model_customizations import CUSTOM_MODELS  # noqa: F401 (legacy re-export)


DEFAULT_TWEAK_IDS = [
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
NON_MIRROR_DEFAULT_TWEAK_IDS = [
    "disable-telemetry",
    "disable-error-reporting",
    "disable-feedback-command",
    "disable-feedback-survey",
    "disable-prompt-caching",
]
VALUE_ENV_TWEAK_IDS = ["context-limit", "file-read-limit", "subagent-model", "compact-window"]
GATEWAY_MODEL_DISCOVERY_TWEAK_ID = "gateway-model-discovery"
GATEWAY_MODEL_DISCOVERY_ENV = "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"
OPENCODE_GATEWAY_DISCOVERY_TWEAK_ID = "opencode-gateway-discovery"
MID_CONVERSATION_SYSTEM_FALLBACK_TWEAK_ID = "mid-conversation-system-422-fallback"
ANTHROPIC_SSE_ERROR_SURFACING_TWEAK_ID = "anthropic-sse-error-surfacing"
BOOLEAN_ENV_TWEAKS = {
    GATEWAY_MODEL_DISCOVERY_TWEAK_ID: {
        "name": "Gateway model discovery",
        "env": GATEWAY_MODEL_DISCOVERY_ENV,
        "value": "1",
        "description": (
            "Enables Claude Code gateway model discovery. Required for OAuth architect proxy model ids; "
            "unchecking this disables the proxy."
        ),
    },
    "disable-telemetry": {
        "name": "Disable telemetry",
        "env": "DISABLE_TELEMETRY",
        "value": "1",
        "description": "Opts out of Statsig telemetry.",
    },
    "disable-error-reporting": {
        "name": "Disable error reporting",
        "env": "DISABLE_ERROR_REPORTING",
        "value": "1",
        "description": "Disables Sentry error reporting.",
    },
    "disable-feedback-command": {
        "name": "Disable feedback command",
        "env": "DISABLE_FEEDBACK_COMMAND",
        "value": "1",
        "description": "Hides the feedback command.",
    },
    "disable-feedback-survey": {
        "name": "Disable feedback survey",
        "env": "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
        "value": "1",
        "description": "Disables session quality surveys.",
    },
    "disable-prompt-caching": {
        "name": "Disable prompt caching",
        "env": "DISABLE_PROMPT_CACHING",
        "value": "1",
        "description": "Disables prompt caching for all models.",
    },
    "disable-auto-compact": {
        "name": "Disable auto compact",
        "env": "DISABLE_AUTO_COMPACT",
        "value": "1",
        "description": "Disables automatic compaction while leaving manual compact available.",
    },
    "disable-all-compact": {
        "name": "Disable all compact",
        "env": "DISABLE_COMPACT",
        "value": "1",
        "description": "Disables automatic and manual compaction.",
    },
    "disable-growthbook": {
        "name": "Disable GrowthBook",
        "env": "DISABLE_GROWTHBOOK",
        "value": "1",
        "description": "Disables GrowthBook feature flag fetching.",
    },
    "disable-nonessential-traffic": {
        "name": "Disable nonessential traffic",
        "env": "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        "value": "1",
        "description": "Disables updater, feedback, error reporting, and telemetry traffic.",
    },
    "skip-prompt-history": {
        "name": "Skip prompt history",
        "env": "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
        "value": "1",
        "description": "Skips writing prompt history and session transcripts.",
    },
    "disable-auto-memory": {
        "name": "Disable auto memory",
        "env": "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
        "value": "1",
        "description": "Disables Claude Code auto memory.",
    },
    "disable-cron": {
        "name": "Disable scheduled tasks",
        "env": "CLAUDE_CODE_DISABLE_CRON",
        "value": "1",
        "description": "Disables scheduled tasks and cron tools.",
    },
    "subprocess-env-scrub": {
        "name": "Scrub subprocess env",
        "env": "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
        "value": "1",
        "description": "Strips provider credentials from subprocess environments.",
    },
    "mcp-allowlist-env": {
        "name": "MCP allowlist env",
        "env": "CLAUDE_CODE_MCP_ALLOWLIST_ENV",
        "value": "1",
        "description": "Starts stdio MCP servers with only a safe baseline environment plus configured env.",
    },
    "disable-experimental-betas": {
        "name": "Disable experimental betas",
        "env": "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
        "value": "1",
        "description": "Strips Anthropic beta headers and beta tool-schema fields from API requests.",
    },
}
BOOLEAN_ENV_TWEAK_IDS = list(BOOLEAN_ENV_TWEAKS)
ENV_TWEAK_IDS = [*VALUE_ENV_TWEAK_IDS, *BOOLEAN_ENV_TWEAK_IDS]
PROMPT_ONLY_TWEAK_IDS = ["rtk-shell-prefix"]
YET_ANOTHER_STATUSLINE_TWEAK_ID = "yet-another-statusline"
SETUP_CONFIG_TWEAK_IDS = [YET_ANOTHER_STATUSLINE_TWEAK_ID]
SETUP_ENV_ONLY_TWEAK_IDS = ["mcp-batch-size", "dangerously-skip-permissions"]
SETUP_ONLY_TWEAK_IDS = [*SETUP_ENV_ONLY_TWEAK_IDS, *SETUP_CONFIG_TWEAK_IDS]
CURATED_TWEAK_IDS = [
    "themes",
    "prompt-overlays",
    "show-more-items-in-select-menus",
    "model-customizations",
    "hide-startup-banner",
    "hide-startup-clawd",
    "hide-ctrl-g-to-edit",
    "suppress-line-numbers",
    "suppress-model-launch-notice",
    ANTHROPIC_SSE_ERROR_SURFACING_TWEAK_ID,
    MID_CONVERSATION_SYSTEM_FALLBACK_TWEAK_ID,
    "suppress-native-installer-warning",
    "suppress-prompt-caching-warning",
    "suppress-rate-limit-options",
    "thinking-visibility",
    "input-box-border",
    "filter-scroll-escape-sequences",
    "agents-md",
    "session-memory",
    "remember-skill",
    OPENCODE_GATEWAY_DISCOVERY_TWEAK_ID,
    "opusplan1m",
    "mcp-non-blocking",
    "mcp-batch-size",
    "rtk-shell-prefix",
    "dangerously-skip-permissions",
    "token-count-rounding",
    "statusline-update-throttle",
    YET_ANOTHER_STATUSLINE_TWEAK_ID,
    "auto-accept-plan-mode",
    "allow-custom-agent-models",
    "patches-applied-indication",
    *ENV_TWEAK_IDS,
]
DASHBOARD_EXCLUDED_TWEAK_IDS = {
    "themes",
    "prompt-overlays",
    ANTHROPIC_SSE_ERROR_SURFACING_TWEAK_ID,
    MID_CONVERSATION_SYSTEM_FALLBACK_TWEAK_ID,
    OPENCODE_GATEWAY_DISCOVERY_TWEAK_ID,
    "remember-skill",
    "rtk-shell-prefix",
    *ENV_TWEAK_IDS,
    "dangerously-skip-permissions",
    *SETUP_CONFIG_TWEAK_IDS,
}
DASHBOARD_TWEAK_IDS = [
    tweak_id for tweak_id in CURATED_TWEAK_IDS
    if tweak_id not in DASHBOARD_EXCLUDED_TWEAK_IDS
]


@dataclass
class TweakResult:
    js: str
    applied: List[str]
    skipped: List[str]
    missing: List[str]


class TweakPatchError(ValueError):
    def __init__(self, tweak_id: str, detail: str):
        self.tweak_id = tweak_id
        self.detail = detail
        super().__init__(f"{tweak_id}: {detail}")


RTK_SHELL_PREFIX_TEXT = (
    "When running shell commands through Bash, prefix each command with `rtk` "
    "unless the user explicitly asks otherwise or `rtk` is unavailable."
)
RTK_PROMPT_TARGETS = ("explore", "planEnhanced")
MCP_BATCH_SIZE_ENV = "MCP_SERVER_CONNECTION_BATCH_SIZE"
MCP_BATCH_SIZE_DEFAULT = "10"
MANAGED_TWEAK_ENV_KEYS = (
    "CLAUDE_CODE_CONTEXT_LIMIT",
    "DISABLE_COMPACT",
    "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    MCP_BATCH_SIZE_ENV,
    *(str(meta["env"]) for meta in BOOLEAN_ENV_TWEAKS.values()),
)


def default_tweak_ids_for_provider(provider_key: Optional[str]) -> List[str]:
    defaults = list(DEFAULT_TWEAK_IDS)
    if provider_key == "ccr-oauth":
        defaults.append("opusplan1m")
    if provider_key in ("opencode-go", "opencode-zen"):
        defaults.append(OPENCODE_GATEWAY_DISCOVERY_TWEAK_ID)
        defaults.append("gateway-model-discovery")
    if provider_key == "zai":
        defaults.insert(
            defaults.index("suppress-model-launch-notice") + 1,
            MID_CONVERSATION_SYSTEM_FALLBACK_TWEAK_ID,
        )
    if provider_key and provider_key != "mirror":
        defaults.insert(
            defaults.index("suppress-model-launch-notice") + 1,
            ANTHROPIC_SSE_ERROR_SURFACING_TWEAK_ID,
        )
        defaults.extend(NON_MIRROR_DEFAULT_TWEAK_IDS)
    return _unique_ordered(defaults)


def compose_prompt_overlays(
    base_overlays: Optional[Dict[str, str]],
    tweak_ids: Iterable[str],
) -> Dict[str, str]:
    overlays = dict(base_overlays or {})
    ids = set(tweak_ids)
    if "rtk-shell-prefix" in ids:
        for key in RTK_PROMPT_TARGETS:
            overlays[key] = _append_overlay(overlays.get(key), RTK_SHELL_PREFIX_TEXT)
    return overlays


def _append_overlay(existing: Optional[str], addition: str) -> str:
    existing_text = str(existing or "").strip()
    if not existing_text:
        return addition
    if addition in existing_text:
        return existing_text
    return f"{existing_text}\n\n{addition}"


def normalize_tweak_ids(tweak_ids: Optional[Iterable[str]]) -> List[str]:
    ids = list(tweak_ids or DEFAULT_TWEAK_IDS)
    result = []
    for tweak_id in ids:
        if tweak_id not in CURATED_TWEAK_IDS:
            raise ValueError(f"Unknown tweak: {tweak_id}")
        if tweak_id not in result:
            result.append(tweak_id)
    return result


def _unique_ordered(tweak_ids: Iterable[str]) -> List[str]:
    result = []
    for tweak_id in tweak_ids:
        if tweak_id not in result:
            result.append(tweak_id)
    return result


def available_tweaks() -> List[Dict[str, object]]:
    return [
        {
            "id": tweak_id,
            "envBacked": tweak_id in ENV_TWEAK_IDS,
            "booleanEnv": tweak_id in BOOLEAN_ENV_TWEAK_IDS,
            "promptOnly": tweak_id in PROMPT_ONLY_TWEAK_IDS,
            "setupOnly": tweak_id in SETUP_ONLY_TWEAK_IDS,
            "setupConfig": tweak_id in SETUP_CONFIG_TWEAK_IDS,
        }
        for tweak_id in CURATED_TWEAK_IDS
    ]


def env_for_tweaks(tweak_ids: Iterable[str], options: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    options = options or {}
    env = {}
    ids = set(tweak_ids)
    if "context-limit" in ids and options.get("context_limit"):
        env["CLAUDE_CODE_CONTEXT_LIMIT"] = str(options["context_limit"])
        env["DISABLE_COMPACT"] = env.get("DISABLE_COMPACT", "1")
    if "file-read-limit" in ids and options.get("file_read_limit"):
        env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] = str(options["file_read_limit"])
    if "subagent-model" in ids and options.get("subagent_model"):
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = str(options["subagent_model"])
    if "compact-window" in ids and options.get("compact_window"):
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(options["compact_window"])
    if "mcp-batch-size" in ids:
        env[MCP_BATCH_SIZE_ENV] = str(options.get("mcp_batch_size") or MCP_BATCH_SIZE_DEFAULT)
    for tweak_id, meta in BOOLEAN_ENV_TWEAKS.items():
        if tweak_id in ids:
            env[str(meta["env"])] = str(meta["value"])
    return env


def sync_tweak_env(
    env: Optional[Dict[str, str]],
    tweak_ids: Iterable[str],
    options: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    synced = dict(env or {})
    for key in MANAGED_TWEAK_ENV_KEYS:
        synced.pop(key, None)
    synced.update(env_for_tweaks(tweak_ids, options))
    return synced


def apply_variant_tweaks(
    js: str,
    *,
    tweak_ids: Iterable[str],
    config: Optional[Dict] = None,
    overlays: Optional[Dict[str, str]] = None,
    provider_label: str = "ccsilo",
    claude_version: Optional[str] = None,
    force: bool = False,
) -> TweakResult:
    config = config or {}
    overlays = overlays or {}
    applied: List[str] = []
    skipped: List[str] = []
    missing: List[str] = []
    prompt_overlay_done = False

    for tweak_id in normalize_tweak_ids(tweak_ids):
        if tweak_id in ENV_TWEAK_IDS or (tweak_id in SETUP_ONLY_TWEAK_IDS and tweak_id not in _PATCH_REGISTRY):
            skipped.append(tweak_id)
            continue
        if tweak_id in PROMPT_ONLY_TWEAK_IDS:
            if not overlays:
                skipped.append(tweak_id)
                continue
            if not prompt_overlay_done:
                sub = _apply_patches(
                    js,
                    ["prompt-overlays"],
                    _PatchCtx(
                        claude_version=claude_version,
                        provider_label=provider_label,
                        config=config,
                        overlays=overlays,
                        force=force,
                    ),
                    registry=_PATCH_REGISTRY,
                )
                js = sub.js
                prompt_overlay_done = bool(sub.applied)
                for note in sub.notes:
                    if note.startswith("prompt overlay miss: "):
                        missing.append(note[len("prompt overlay miss: "):])
            (applied if prompt_overlay_done else skipped).append(tweak_id)
            continue
        if tweak_id not in _PATCH_REGISTRY:
            raise TweakPatchError(tweak_id, "unknown tweak (not registered)")
        try:
            sub = _apply_patches(
                js,
                [tweak_id],
                _PatchCtx(
                    claude_version=claude_version,
                    provider_label=provider_label,
                    config=config,
                    overlays=overlays,
                    force=force,
                ),
                registry=_PATCH_REGISTRY,
            )
        except PatchAnchorMissError as e:
            detail = "failed to find anchor"
            if e.detail:
                detail = f"{detail}: {e.detail}"
            raise TweakPatchError(tweak_id, detail) from e
        js = sub.js
        if sub.applied:
            applied.append(tweak_id)
        else:
            skipped.append(tweak_id)
        if tweak_id == "prompt-overlays":
            prompt_overlay_done = bool(sub.applied)
        # Forward prompt-overlay miss notes to the legacy `missing` list
        for note in sub.notes:
            if note.startswith("prompt overlay miss: "):
                missing.append(note[len("prompt overlay miss: "):])

    return TweakResult(js=js, applied=applied, skipped=skipped, missing=missing)

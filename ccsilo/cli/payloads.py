"""JSON payload helpers and shared argparse adders for variant subcommands."""

import json
from dataclasses import asdict, is_dataclass


def to_jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def variant_payload(variant):
    return dict(variant.manifest)


def variant_result_payload(result):
    payload = dict(result.variant.manifest)
    payload["build"] = {
        "binaryPath": str(result.binary_path),
        "wrapperPath": str(result.wrapper_path),
        "outputSha256": result.output_sha256,
        "appliedTweaks": result.applied_tweaks,
        "skippedTweaks": result.skipped_tweaks,
        "missingPromptKeys": result.missing_prompt_keys,
        "stages": [
            {
                "name": stage.name,
                "status": stage.status,
                "detail": stage.detail,
            }
            for stage in getattr(result, "stages", [])
        ],
    }
    return payload


def install_result_payload(result):
    return {
        "alias": result.alias,
        "path": str(result.path),
        "target": str(result.target),
        "status": result.status,
        "onPath": result.on_path,
        "warning": result.warning,
    }


def symlink_removal_payload(item):
    return {
        "path": item.path,
        "target": item.target,
        "status": item.status,
        "reason": item.reason,
    }


def uninstall_result_payload(result):
    return {
        "workspace": str(result.workspace),
        "removedWorkspace": result.removed_workspace,
        "removedSymlinks": [symlink_removal_payload(item) for item in result.removed_symlinks],
        "skippedSymlinks": [symlink_removal_payload(item) for item in result.skipped_symlinks],
    }


def model_overrides_from_args(args):
    return {
        "sonnet": getattr(args, "model_sonnet", None),
        "opus": getattr(args, "model_opus", None),
        "haiku": getattr(args, "model_haiku", None),
        "small_fast": getattr(args, "model_small_fast", None),
        "default": getattr(args, "model_default", None),
        "subagent": getattr(args, "subagent_model", None),
    }


def tweak_options_from_args(args):
    return {
        "context_limit": getattr(args, "context_limit", None),
        "file_read_limit": getattr(args, "file_read_limit", None),
        "subagent_model": getattr(args, "subagent_model", None),
        "compact_window": getattr(args, "compact_window", None),
    }


def add_variant_model_args(parser):
    parser.add_argument("--model-sonnet", help="Provider model mapped to Sonnet")
    parser.add_argument("--model-opus", help="Provider model mapped to Opus")
    parser.add_argument("--model-haiku", help="Provider model mapped to Haiku")
    parser.add_argument("--model-small-fast", help="Provider small/fast model")
    parser.add_argument("--model-default", help="Provider startup/default model")
    parser.add_argument("--subagent-model", help="Provider subagent model")


def add_variant_tweak_option_args(parser):
    parser.add_argument("--context-limit", help="CLAUDE_CODE_CONTEXT_LIMIT value for context-limit tweak")
    parser.add_argument("--file-read-limit", help="CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS value")
    parser.add_argument("--compact-window", help="CLAUDE_CODE_AUTO_COMPACT_WINDOW value")

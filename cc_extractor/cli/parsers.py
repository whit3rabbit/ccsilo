"""Argparse parser wiring for ``cc_extractor``.

Only the parser tree lives here; dispatching is done by ``cc_extractor.__main__``
so test fixtures can monkey-patch variant helpers (``create_variant``,
``load_variant``, etc.) on the ``__main__`` module and have those patches apply
to the variant CLI handlers.
"""

import argparse

from .payloads import add_variant_model_args, add_variant_tweak_option_args


def build_parser():
    parser = argparse.ArgumentParser(description="Bun standalone binary manager")
    parser.add_argument("--provider", help="Provider shortcut key for install, update, or uninstall")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    dl = subparsers.add_parser("download", help="Download binary or NPM bundle")
    dl.add_argument("version", nargs="?", help="Version to download")
    dl.add_argument("--latest", action="store_true", help="Download the latest version without prompting")
    dl.add_argument("--npm", action="store_true", help="Download NPM bundle instead of binary")
    dl.add_argument("--outdir", help="Output directory")

    ex = subparsers.add_parser("extract", help="Extract Bun bundle from binary")
    ex.add_argument("binary", help="Path to Bun standalone binary")
    ex.add_argument("outdir", nargs="?", help="Output directory")
    ex.add_argument("--source-version", help="Source Claude Code version for patch targeting")
    ex.add_argument("--include-sourcemaps", action="store_true", help="Write sourcemap files")
    ex.add_argument("--no-manifest", dest="manifest", action="store_false", help="Skip bundle manifest output")
    ex.set_defaults(manifest=True)

    unpack = subparsers.add_parser("unpack", help="Alias for extract with TypeScript-compatible naming")
    unpack.add_argument("binary", help="Path to Bun standalone binary")
    unpack.add_argument("--out", required=True, help="Output directory")
    unpack.add_argument("--source-version", help="Source Claude Code version for patch targeting")
    unpack.add_argument("--include-sourcemaps", action="store_true", help="Write sourcemap files")
    unpack.add_argument("--manifest", dest="manifest", action="store_true", default=True, help="Write bundle manifest")
    unpack.add_argument("--no-manifest", dest="manifest", action="store_false", help="Skip bundle manifest output")

    inspect = subparsers.add_parser("inspect", help="Inspect Bun binary metadata")
    inspect.add_argument("binary", help="Path to Bun standalone binary")
    inspect.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    replace_entry = subparsers.add_parser("replace-entry", help="Replace the entry JS module and repack")
    replace_entry.add_argument("binary", help="Path to Bun standalone binary")
    replace_entry.add_argument("entry_js", help="Path to replacement entry JS")
    replace_entry.add_argument("--out", required=True, help="Output binary path")

    apply_binary = subparsers.add_parser("apply-binary", help="Apply theme and prompt patches to a binary")
    apply_binary.add_argument("binary", help="Path to Bun standalone binary to patch in place")
    apply_binary.add_argument("--config", required=True, help="Config JSON containing settings.themes")
    apply_binary.add_argument("--overlays", help="Prompt overlay JSON")

    pk = subparsers.add_parser("pack", help="Pack directory back into binary")
    pk.add_argument("indir", help="Directory with extracted files and manifest")
    pk.add_argument("base_binary", help="Original binary to use as template")
    pk.add_argument("out_binary", help="Path for output binary")

    install = subparsers.add_parser("install", help="Install a default provider setup")
    install.add_argument("--provider", dest="command_provider", help="Provider shortcut key")
    install.add_argument("--claude-version", default="latest", help="Claude Code version, latest, or stable")
    install.add_argument("--credential-env", help="Environment variable containing provider credentials")
    install.add_argument("--api-key", help="Provider credential to store locally, requires --store-secret")
    install.add_argument("--store-secret", action="store_true", help="Store --api-key in setup-local secrets.env")
    install.add_argument("--bin-dir", help="Directory where the command symlink should be created")
    install.add_argument("--alias", help="Command name to install, defaults to the provider key")
    install.add_argument("--yes", action="store_true", help="Create fallback install directory if needed")
    install.add_argument("--ccrouter-mode", choices=["managed", "external"], help="ccrouter runtime mode")
    install.add_argument(
        "--ccrouter-config",
        choices=["copy-global", "empty", "shared-home"],
        help="ccrouter config source for managed mode",
    )
    install.add_argument("--ccrouter-package", help="NPM package spec for managed ccrouter")
    install.add_argument("--ccrouter-port", help="Managed ccrouter port or auto")
    install.add_argument(
        "--no-ccrouter-autostart",
        dest="ccrouter_autostart",
        action="store_false",
        default=None,
        help="Do not start managed ccrouter automatically in the wrapper",
    )
    install.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    update = subparsers.add_parser("update", help="Update a default provider setup")
    update.add_argument("--provider", dest="command_provider", help="Provider shortcut key")
    update.add_argument("--claude-version", default="latest", help="Claude Code version, latest, or stable")
    update.add_argument("--yes", action="store_true", help="Create fallback install directory if needed")
    update.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    uninstall = subparsers.add_parser("uninstall", help="Remove managed symlinks and the current workspace")
    uninstall.add_argument("--provider", dest="command_provider", help="Provider shortcut key")
    uninstall.add_argument("--yes", action="store_true", help="Confirm uninstall without prompting")
    uninstall.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    patch = subparsers.add_parser("patch", help="Create or apply text patches to extracted bundles")
    patch_subparsers = patch.add_subparsers(dest="patch_command", help="Patch commands")

    patch_init = patch_subparsers.add_parser("init", help="Create a patch scaffold")
    patch_init.add_argument("patch_dir", help="Directory where the patch scaffold will be created")

    patch_apply = patch_subparsers.add_parser("apply", help="Apply a patch to an extracted bundle")
    patch_apply.add_argument("patch_dir", help="Directory containing patch.json")
    patch_apply.add_argument("extract_dir", help="Directory containing extracted bundle files")
    patch_apply.add_argument("--check", action="store_true", help="Validate the patch without writing files")
    patch_apply.add_argument("--binary", help="Path to source binary to derive checksum override")
    patch_apply.add_argument("--source-version", help="Source version override for target validation")

    variant = subparsers.add_parser("variant", help="Create and manage isolated Claude Code variants")
    variant_subparsers = variant.add_subparsers(dest="variant_command", help="Variant commands")
    _build_variant_subcommands(variant_subparsers)

    return parser, patch, variant


def _build_variant_subcommands(subparsers):
    providers = subparsers.add_parser("providers", help="List provider presets")
    provider_formats = providers.add_mutually_exclusive_group()
    provider_formats.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    provider_formats.add_argument("--ascii-art", action="store_true", help="Print provider ASCII art")
    provider_formats.add_argument(
        "--quote-blocks",
        action="store_true",
        help="Print provider ASCII art as Markdown quote blocks",
    )

    mcp = subparsers.add_parser("mcp", help="List provider and optional MCP servers")
    mcp.add_argument("--provider", help="Provider key for provider-owned MCP servers")
    mcp.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    create = subparsers.add_parser("create", help="Create an isolated variant")
    create.add_argument("--name", required=True, help="Variant name, also used as wrapper command")
    create.add_argument("--provider", required=True, help="Provider preset key")
    create.add_argument("--claude-version", default="latest", help="Claude Code version, latest, or stable")
    create.add_argument("--source-binary", help="Advanced: import a local Claude Code native binary")
    create.add_argument("--source-platform", help="Advanced: platform key for --source-binary")
    create.add_argument("--patch-profile", help="Patch profile id to apply")
    create.add_argument("--tweak", action="append", help="Curated tweak id, repeatable")
    create.add_argument("--mcp", action="append", help="Optional MCP server id, repeatable")
    create.add_argument("--base-url", help="Override the provider endpoint URL")
    create.add_argument("--credential-env", help="Environment variable containing provider credentials")
    create.add_argument("--api-key", help="Provider credential to store locally, requires --store-secret")
    create.add_argument("--store-secret", action="store_true", help="Store --api-key in variant-local secrets.env")
    create.add_argument("--bin-dir", help="Wrapper output directory")
    create.add_argument("--install", action="store_true", help="Install the setup command into a home PATH directory")
    create.add_argument("--force", action="store_true", help="Overwrite an existing variant")
    create.add_argument("--extra-env", action="append", help="Additional KEY=VALUE env entry, repeatable")
    create.add_argument("--ccrouter-mode", choices=["managed", "external"], help="ccrouter runtime mode")
    create.add_argument(
        "--ccrouter-config",
        choices=["copy-global", "empty", "shared-home"],
        help="ccrouter config source for managed mode",
    )
    create.add_argument("--ccrouter-package", help="NPM package spec for managed ccrouter")
    create.add_argument("--ccrouter-port", help="Managed ccrouter port or auto")
    create.add_argument(
        "--no-ccrouter-autostart",
        dest="ccrouter_autostart",
        action="store_false",
        default=None,
        help="Do not start managed ccrouter automatically in the wrapper",
    )
    create.add_argument(
        "--model-proxy",
        choices=["architect"],
        help="Start the managed architect-only local model proxy; requires a Claude Code account",
    )
    create.add_argument("--model-proxy-port", default="auto", help="Managed model proxy port or auto")
    create.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    add_variant_model_args(create)
    add_variant_tweak_option_args(create)

    install = subparsers.add_parser("install", help="Install a setup command into a home PATH directory")
    install.add_argument("name", help="Variant name or id")
    install.add_argument("--bin-dir", help="Directory where the command symlink should be created")
    install.add_argument("--alias", help="Command name to install, defaults to the setup id")
    install.add_argument("--yes", action="store_true", help="Create fallback install directory if needed")
    install.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    list_cmd = subparsers.add_parser("list", help="List variants")
    list_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    show = subparsers.add_parser("show", help="Show variant metadata")
    show.add_argument("name", help="Variant name or id")
    show.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    apply_cmd = subparsers.add_parser("apply", help="Re-apply a variant using its saved settings")
    apply_cmd.add_argument("name", help="Variant name or id")
    apply_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    update = subparsers.add_parser("update", help="Update one or all variants")
    update.add_argument("name", nargs="?", help="Variant name or id")
    update.add_argument("--all", action="store_true", help="Update all variants")
    update.add_argument("--claude-version", help="Override Claude Code version")
    update.add_argument("--source-binary", help="Advanced: import a local Claude Code native binary")
    update.add_argument("--source-platform", help="Advanced: platform key for --source-binary")
    update.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    remove = subparsers.add_parser("remove", help="Remove a variant")
    remove.add_argument("name", help="Variant name or id")
    remove.add_argument("--yes", action="store_true", help="Confirm removal")

    doctor = subparsers.add_parser("doctor", help="Health check variants")
    doctor.add_argument("name", nargs="?", help="Variant name or id")
    doctor.add_argument("--all", action="store_true", help="Check all variants")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    run = subparsers.add_parser("run", help="Run a variant wrapper")
    run.add_argument("name", help="Variant name or id")
    run.add_argument("variant_args", nargs=argparse.REMAINDER, help="Arguments passed to Claude Code")

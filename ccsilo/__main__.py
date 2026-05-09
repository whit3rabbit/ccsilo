"""Top-level CLI entry point.

The argparse parser tree is built in :mod:`ccsilo.cli.parsers`; simple
non-variant subcommand handlers live in :mod:`ccsilo.cli.handlers`. The
variant subcommand dispatcher and the ``main`` entry point live here so test
fixtures can monkey-patch variant helpers (``create_variant``, ``load_variant``,
``doctor_variant``, ``remove_variant``, etc.) via ``ccsilo.__main__`` and
have those patches apply to the dispatch site.
"""

import os
import sys
from pathlib import Path
from shutil import which

from .cli import build_parser, inspect_binary  # noqa: F401, re-exported for test imports
from .cli import handlers as _handlers
from .providers import get_provider, list_mcp_catalog, provider_default_variant_name
from .cli.payloads import (
    install_result_payload,
    model_overrides_from_args,
    print_json,
    tweak_options_from_args,
    uninstall_result_payload,
    variant_payload,
    variant_result_payload,
)
from .variants import (
    apply_variant,
    create_variant,
    doctor_variant,
    inspect_variant_command_install,
    install_variant_command,
    list_variant_providers,
    load_variant,
    remove_variant,
    run_variant,
    scan_variants,
    uninstall_workspace,
    update_variants,
    variant_id_from_name,
    workspace_managed_install_records,
)
from .workspace import workspace_root


_SIMPLE_HANDLERS = {
    "download": _handlers.cmd_download,
    "extract": _handlers.cmd_extract,
    "unpack": _handlers.cmd_unpack,
    "inspect": _handlers.cmd_inspect,
    "replace-entry": _handlers.cmd_replace_entry,
    "apply-binary": _handlers.cmd_apply_binary,
    "pack": _handlers.cmd_pack,
}


def _provider_arg(args):
    return getattr(args, "command_provider", None) or getattr(args, "provider", None)


def _resolve_provider_variant(provider_key: str, *, required: bool):
    provider = get_provider(provider_key)
    default_name = provider_default_variant_name(provider.key)
    default_id = variant_id_from_name(default_name)
    try:
        return load_variant(default_id)
    except ValueError:
        pass
    matches = [
        variant
        for variant in scan_variants()
        if ((variant.manifest.get("provider") or {}).get("key") == provider.key)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(variant.name for variant in matches)
        raise ValueError(
            f"Multiple setups use provider {provider.key}: {names}. "
            "Use variant update/remove/install <name>."
        )
    if required:
        raise ValueError(f"No setup found for provider {provider.key}. Run ccsilo --provider {provider.key} install.")
    return None


def _provider_next_steps(variant, provider_key: str, install_result=None):
    provider = get_provider(provider_key)
    manifest = variant.manifest or {}
    paths = manifest.get("paths") or {}
    credential = manifest.get("credential") or {}
    credential_envs = []
    if credential.get("mode") == "env" and credential.get("source"):
        credential_envs.append(str(credential["source"]))
    credential_envs.extend(str(item) for item in credential.get("targets") or [] if item)
    if provider.credential_env:
        credential_envs.append(provider.credential_env)
    credential_envs = sorted(set(credential_envs))

    install_blocked = _install_result_blocked(install_result)
    fallback_run = paths.get("wrapper") or f"ccsilo variant run {variant.variant_id} --"
    next_steps = {
        "command": fallback_run if install_blocked else getattr(install_result, "alias", None) or provider.key,
        "workspace": str(workspace_root()),
        "setupRoot": paths.get("root") or str(getattr(variant, "path", "")),
        "wrapper": paths.get("wrapper") or "",
        "configDir": paths.get("configDir") or "",
        "credentialEnv": credential_envs,
        "providerMcpServers": sorted(provider.mcp_servers),
        "run": fallback_run if install_blocked else getattr(install_result, "alias", None) or fallback_run,
        "doctor": f"ccsilo variant doctor {variant.variant_id}",
        "warnings": [],
    }
    if install_result is not None:
        next_steps["installPath"] = str(install_result.path)
        next_steps["installTarget"] = str(install_result.target)
        next_steps["installOnPath"] = bool(install_result.on_path)
        if install_result.warning:
            next_steps["warnings"].append(install_result.warning)
        if install_blocked:
            next_steps["installSkipped"] = True
    ccrouter = manifest.get("ccrouter")
    if isinstance(ccrouter, dict):
        next_steps["ccrouter"] = {
            "configPath": str(ccrouter.get("configPath") or ""),
            "homeDir": str(ccrouter.get("homeDir") or ""),
            "runtimeDir": str(ccrouter.get("runtimeDir") or ""),
        }
    return next_steps


def _provider_payload(variant, provider_key: str, *, install_result=None):
    payload = variant_payload(variant)
    if install_result is not None:
        payload["install"] = install_result_payload(install_result)
    payload["nextSteps"] = _provider_next_steps(variant, provider_key, install_result)
    return payload


def _print_provider_summary(action: str, variant, provider_key: str, *, install_result=None):
    provider = get_provider(provider_key)
    steps = _provider_next_steps(variant, provider.key, install_result)
    print(f"[+] Provider setup {action}: {variant.variant_id}")
    install_blocked = _install_result_blocked(install_result)
    if install_result is not None and install_blocked:
        print(f"    command install skipped: {install_result.path}")
        print(f"    reason: {install_result.warning}")
    elif install_result is not None:
        print(f"    command: {install_result.alias}")
        print(f"    installed: {install_result.path}")
        print(f"    target: {install_result.target}")
        print(f"    status: {install_result.status}")
        print(f"    on PATH: {'yes' if install_result.on_path else 'no'}")
    print(f"    setup: {steps['setupRoot']}")
    print(f"    workspace: {steps['workspace']}")
    print(f"    wrapper: {steps['wrapper']}")
    print(f"    config: {steps['configDir']}")
    if steps["credentialEnv"]:
        print(f"    credential env: {', '.join(steps['credentialEnv'])}")
    if steps["providerMcpServers"]:
        print(f"    provider MCP: {', '.join(steps['providerMcpServers'])} auto-configured")
    ccrouter = steps.get("ccrouter")
    if ccrouter:
        if ccrouter.get("configPath"):
            print(f"    ccrouter config: {ccrouter['configPath']}")
        if ccrouter.get("homeDir"):
            print(f"    ccrouter home: {ccrouter['homeDir']}")
        if ccrouter.get("runtimeDir"):
            print(f"    ccrouter runtime: {ccrouter['runtimeDir']}")
    if install_result is not None and not install_blocked:
        print(f"    run: {install_result.alias}")
        print(f"    doctor: {steps['doctor']}")
        if install_result.warning:
            print(f"    warning: {install_result.warning}")
    elif install_result is not None:
        print(f"    run: {steps['run']}")
        print(f"    doctor: {steps['doctor']}")


def _install_result_blocked(install_result) -> bool:
    return getattr(install_result, "status", "") == "blocked"


def _install_variant_command_or_skip(variant, *, alias=None, bin_dir=None, yes=False):
    try:
        return install_variant_command(variant, alias=alias, bin_dir=bin_dir, yes=yes)
    except ValueError as exc:
        if not str(exc).startswith("Refusing to overwrite"):
            raise
        manifest = variant.manifest or {}
        target = (manifest.get("paths") or {}).get("wrapper") or ""
        plan = inspect_variant_command_install(
            variant.variant_id,
            target=Path(target),
            alias=alias,
            bin_dir=bin_dir,
            yes=yes,
        )
        if plan.status == "blocked" and plan.warning.startswith("Refusing to overwrite"):
            return plan
        raise


def _print_provider_help(args):
    provider_key = _provider_arg(args)
    if not provider_key:
        return False
    provider = get_provider(provider_key)
    print(f"{provider.key}: {provider.label}")
    print("Provider shortcut commands:")
    print(f"    ccsilo --provider {provider.key} install")
    print(f"    ccsilo --provider {provider.key} update")
    print(f"    ccsilo --provider {provider.key} uninstall --yes")
    if provider.credential_env:
        print(f"Credential env: {provider.credential_env}")
    return True


def cmd_provider_install(args):
    provider_key = _provider_arg(args)
    if not provider_key:
        raise ValueError("Pass --provider for the provider shortcut install command")
    provider = get_provider(provider_key)
    variant = _resolve_provider_variant(provider.key, required=False)
    created = False
    if variant is None:
        result = create_variant(
            name=provider_default_variant_name(provider.key),
            provider_key=provider.key,
            claude_version=args.claude_version,
            credential_env=args.credential_env,
            api_key=args.api_key,
            store_secret=args.store_secret,
            ccrouter_mode=args.ccrouter_mode,
            ccrouter_config=args.ccrouter_config,
            ccrouter_package=args.ccrouter_package,
            ccrouter_port=args.ccrouter_port,
            ccrouter_autostart=args.ccrouter_autostart,
        )
        variant = result.variant
        created = True
    install_result = _install_variant_command_or_skip(
        variant,
        alias=args.alias or provider.key,
        bin_dir=args.bin_dir,
        yes=args.yes,
    )
    if args.json:
        print_json(_provider_payload(variant, provider.key, install_result=install_result))
    else:
        _print_provider_summary("created" if created else "installed", variant, provider.key, install_result=install_result)


def cmd_provider_update(args):
    provider_key = _provider_arg(args)
    if not provider_key:
        raise ValueError("Pass --provider for the provider shortcut update command")
    provider = get_provider(provider_key)
    variant = _resolve_provider_variant(provider.key, required=True)
    result = update_variants(variant.name, claude_version=args.claude_version)[0]
    install_result = _install_variant_command_or_skip(result.variant, alias=provider.key, yes=args.yes)
    if args.json:
        print_json(_provider_payload(result.variant, provider.key, install_result=install_result))
    else:
        _print_provider_summary("updated", result.variant, provider.key, install_result=install_result)


def cmd_provider_uninstall(args):
    provider_key = _provider_arg(args)
    if not provider_key:
        raise ValueError("Pass --provider for the provider shortcut uninstall command")
    provider = get_provider(provider_key)
    variant = _resolve_provider_variant(provider.key, required=True)
    removed = remove_variant(variant.name, yes=args.yes)
    if args.json:
        print_json({"provider": provider.key, "variant": variant.variant_id, "removed": removed})
    else:
        print(f"[+] Removed provider setup: {variant.variant_id}" if removed else f"[*] No setup found: {variant.variant_id}")


def cmd_variant(args, variant_parser):
    """Dispatch ``variant <subcommand>`` against the variant helpers above.

    Names like ``create_variant`` are looked up via this module's globals so
    test fixtures that ``monkeypatch.setattr(cli, "create_variant", fake)``
    take effect.
    """
    sub = args.variant_command
    if sub == "providers":
        providers = list_variant_providers()
        if args.json:
            print_json(providers)
        elif args.ascii_art or args.quote_blocks:
            art_key = "asciiArtQuoteBlock" if args.quote_blocks else "asciiArt"
            for index, provider in enumerate(providers):
                if index:
                    print()
                print(f"{provider['key']}: {provider['label']}")
                print(provider.get(art_key) or "")
        else:
            for provider in providers:
                print(f"{provider['key']}: {provider['label']} - {provider['description']}")
    elif sub == "mcp":
        catalog = list_mcp_catalog(provider_key=args.provider or "")
        if args.json:
            print_json(catalog)
        else:
            print("Provider MCP servers:")
            for item in catalog["providerMcpServers"]:
                provider = item.get("providerKey") or "?"
                print(f"    {provider}:{item['id']} auto-enabled")
            print("Optional MCP servers:")
            for item in catalog["optionalMcpServers"]:
                env = ", ".join(item.get("requiredEnv") or [])
                suffix = f" env:{env}" if env else ""
                print(f"    {item['id']}: {item['name']}{suffix}")
            print("Plugin recommendations:")
            print("    " + ", ".join(catalog["pluginRecommendations"]))
    elif sub == "create":
        result = create_variant(
            name=args.name,
            provider_key=args.provider,
            claude_version=args.claude_version,
            patch_profile_id=args.patch_profile,
            tweaks=args.tweak,
            base_url=args.base_url,
            credential_env=args.credential_env,
            api_key=args.api_key,
            store_secret=args.store_secret,
            bin_dir=args.bin_dir,
            force=args.force,
            model_overrides=model_overrides_from_args(args),
            extra_env=args.extra_env,
            tweak_options=tweak_options_from_args(args),
            mcp_ids=args.mcp,
            ccrouter_mode=args.ccrouter_mode,
            ccrouter_config=args.ccrouter_config,
            ccrouter_package=args.ccrouter_package,
            ccrouter_port=args.ccrouter_port,
            ccrouter_autostart=args.ccrouter_autostart,
            model_proxy=args.model_proxy,
            model_proxy_port=args.model_proxy_port,
            source_binary=args.source_binary,
            source_platform=args.source_platform,
        )
        install_result = None
        if args.install:
            install_result = _install_variant_command_or_skip(result.variant)
        if args.json:
            payload = variant_result_payload(result)
            if install_result is not None:
                payload["install"] = install_result_payload(install_result)
            print_json(payload)
        else:
            print(f"[+] Variant created: {result.variant.variant_id}")
            print(f"    binary: {result.binary_path}")
            print(f"    workspace: {workspace_root()}")
            print(f"    wrapper: {result.wrapper_path}")
            print(f"    run: ccsilo variant run {result.variant.variant_id} --")
            print(f"    doctor: ccsilo variant doctor {result.variant.variant_id}")
            if install_result is not None:
                if _install_result_blocked(install_result):
                    print(f"    install skipped: {install_result.path}")
                    print(f"    reason: {install_result.warning}")
                else:
                    print(f"    installed: {install_result.path}")
                    print(f"    run installed command: {install_result.alias}")
                    if install_result.warning:
                        print(f"    warning: {install_result.warning}")
    elif sub == "install":
        variant = load_variant(variant_id_from_name(args.name))
        result = install_variant_command(
            variant,
            alias=args.alias,
            bin_dir=args.bin_dir,
            yes=args.yes,
        )
        if args.json:
            print_json(install_result_payload(result))
        else:
            print(f"[+] Installed command: {result.path}")
            print(f"    target: {result.target}")
            print(f"    status: {result.status}")
            print(f"    run: {result.alias}")
            print(f"    doctor: ccsilo variant doctor {variant.variant_id}")
            if result.warning:
                print(f"    warning: {result.warning}")
    elif sub == "list":
        variants = scan_variants()
        if args.json:
            print_json([variant_payload(variant) for variant in variants])
        else:
            for variant in variants:
                source = variant.manifest.get("source", {})
                provider = variant.manifest.get("provider", {})
                print(
                    f"{variant.variant_id}: {provider.get('key')} {source.get('version')} "
                    f"-> {variant.manifest.get('paths', {}).get('wrapper')}"
                )
    elif sub == "show":
        variant = load_variant(args.name)
        print_json(variant_payload(variant))
    elif sub == "apply":
        result = apply_variant(args.name)
        if args.json:
            print_json(variant_result_payload(result))
        else:
            print(f"[+] Variant applied: {result.variant.variant_id}")
            print(f"    wrapper: {result.wrapper_path}")
    elif sub == "update":
        results = update_variants(
            args.name,
            all_variants=args.all,
            claude_version=args.claude_version,
            source_binary=args.source_binary,
            source_platform=args.source_platform,
        )
        if args.json:
            print_json([variant_result_payload(result) for result in results])
        else:
            for result in results:
                print(f"[+] Variant updated: {result.variant.variant_id}")
    elif sub == "remove":
        removed = remove_variant(args.name, yes=args.yes)
        print(f"[+] Removed variant: {args.name}" if removed else f"[*] No variant found: {args.name}")
    elif sub == "doctor":
        report = doctor_variant(args.name, all_variants=args.all)
        if args.json:
            print_json(report)
        else:
            for item in report:
                status = "ok" if item["ok"] else "failed"
                print(f"{item['id']}: {status}")
                for check in item["checks"]:
                    mark = "ok" if check["ok"] else "missing"
                    print(f"    {check['name']}: {mark} {check['path']}")
    elif sub == "run":
        variant_args = list(args.variant_args or [])
        if variant_args and variant_args[0] == "--":
            variant_args = variant_args[1:]
        sys.exit(run_variant(args.name, variant_args))
    else:
        variant_parser.print_help()


def cmd_uninstall(args):
    workspace = workspace_root()
    planned = workspace_managed_install_records()
    if not args.yes:
        print("This will remove:")
        for item in planned:
            print(f"    symlink: {item.path} -> {item.target}")
        print(f"    workspace: {workspace}")
        response = input("Type uninstall to continue: ")
        if response != "uninstall":
            print("[*] Uninstall cancelled.")
            return
    result = uninstall_workspace(yes=True)
    if args.json:
        print_json(uninstall_result_payload(result))
    else:
        print(f"[+] Removed workspace: {result.workspace}" if result.removed_workspace else f"[*] Workspace already absent: {result.workspace}")
        for item in result.removed_symlinks:
            print(f"[+] Removed symlink: {item.path}")
        for item in result.skipped_symlinks:
            print(f"[*] Skipped symlink: {item.path} ({item.reason})")


def cmd_paths(args):
    command_path = which("ccsilo") or ""
    if not command_path and sys.argv:
        invoked = Path(sys.argv[0]).expanduser()
        if invoked.name == "ccsilo" and (
            invoked.is_absolute() or invoked.parent != Path(".")
        ):
            command_path = str(invoked)
    payload = {
        "command": command_path,
        "workspace": str(workspace_root()),
        "workspaceOverride": bool(os.environ.get("CCSILO_WORKSPACE")),
        "workspaceOverrideEnv": "CCSILO_WORKSPACE",
    }
    if args.json:
        print_json(payload)
        return
    print(f"command: {command_path or 'not found on PATH'}")
    print(f"workspace: {payload['workspace']}")
    if payload["workspaceOverride"]:
        print("workspace source: CCSILO_WORKSPACE")
    else:
        print("workspace source: platform user data directory")
    print("override: set CCSILO_WORKSPACE=/path/to/workspace")


def main():
    parser, patch_parser, variant_parser = build_parser()

    if len(sys.argv) == 1:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_tui

            try:
                run_tui()
            except Exception as exc:
                print(f"[!] Error: {exc}")
                sys.exit(1)
            return
        parser.print_help()
        return

    args = parser.parse_args()

    try:
        if args.command in _SIMPLE_HANDLERS:
            _SIMPLE_HANDLERS[args.command](args)
        elif args.command == "install":
            cmd_provider_install(args)
        elif args.command == "update":
            cmd_provider_update(args)
        elif args.command == "patch":
            _handlers.cmd_patch(args, patch_parser)
        elif args.command == "variant":
            cmd_variant(args, variant_parser)
        elif args.command == "uninstall" and _provider_arg(args):
            cmd_provider_uninstall(args)
        elif args.command == "uninstall":
            cmd_uninstall(args)
        elif args.command == "paths":
            cmd_paths(args)
        elif _print_provider_help(args):
            return
        else:
            parser.print_help()
    except Exception as exc:
        print(f"[!] Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

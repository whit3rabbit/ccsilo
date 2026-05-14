"""Dashboard option, profile, and artifact helpers."""

from ..patches._registry import REGISTRY as PATCH_REGISTRY
from ..variant_tweaks import DASHBOARD_TWEAK_IDS
from ..workspace import short_sha
from ._const import DASHBOARD_STEPS, MenuOption, SOURCE_ARTIFACT, SOURCE_LATEST, SOURCE_VERSION, next_action_label

def dashboard_options(state):
    if state.dashboard_step == 0:
        return _dashboard_source_options(state)
    if state.dashboard_step == 1:
        return _dashboard_patch_options(state)
    if state.dashboard_step == 2:
        return _dashboard_profile_options(state)
    return _dashboard_review_options(state)

def _dashboard_source_options(state):
    options = [
        MenuOption("source-latest", _selected_label(state, SOURCE_LATEST, None, "Latest native binary")),
        MenuOption("refresh-index", "Refresh version list"),
    ]
    latest = state.download_index.get("binary", {}).get("latest")
    for version in state.download_versions:
        suffix = " (latest)" if version == latest else ""
        label = f"Native {version}{suffix}"
        options.append(MenuOption("source-version", _selected_label(state, SOURCE_VERSION, version, label), version))
    if state.native_artifacts:
        options.append(MenuOption("section", "Downloaded native artifacts"))
    for index, artifact in enumerate(state.native_artifacts):
        label = f"Downloaded {format_native_artifact(artifact)}"
        options.append(MenuOption("source-artifact", _selected_label(state, SOURCE_ARTIFACT, index, label), index))
    return options

def _dashboard_patch_options(state):
    options = []
    for tweak_id in dashboard_tweak_ids():
        patch = PATCH_REGISTRY[tweak_id]
        marker = "[x]" if tweak_id in state.selected_dashboard_tweak_ids else "[ ]"
        options.append(MenuOption("dashboard-tweak-toggle", f"{marker} {patch.id}  {patch.name}", tweak_id))

    if state.dashboard_tweak_profiles:
        options.append(MenuOption("section", "Saved profiles"))
    for profile in state.dashboard_tweak_profiles:
        missing = dashboard_tweak_profile_missing_ids(state, profile)
        if missing:
            label = f"Load profile: {profile.name} (invalid, missing {', '.join(missing)})"
        else:
            label = f"Load profile: {profile.name} ({len(profile.tweak_ids)} tweaks)"
        options.append(MenuOption("profile-load", label, profile.profile_id))

    if selected_dashboard_tweaks(state):
        options.append(MenuOption("patch-continue", next_action_label("Continue to profile management")))
    return options

def _dashboard_profile_options(state):
    name = state.dashboard_profile_name or "(type a profile name)"
    options = [
        MenuOption("profile-name", f"Name: {name}"),
        MenuOption("profile-create", "Create new profile from selected tweaks"),
        MenuOption("review-continue", next_action_label("Continue to review")),
    ]
    for profile in state.dashboard_tweak_profiles:
        suffix = " [loaded]" if profile.profile_id == state.dashboard_loaded_profile_id else ""
        options.extend([
            MenuOption("profile-load", f"Load profile: {profile.name}{suffix}", profile.profile_id),
            MenuOption("profile-rename", f"Rename profile to typed name: {profile.name}", profile.profile_id),
            MenuOption("profile-overwrite", f"Overwrite profile with selected tweaks: {profile.name}", profile.profile_id),
            MenuOption("profile-delete", _delete_label(state, profile), profile.profile_id),
        ])
    return options

def _dashboard_review_options(state):
    return [
        MenuOption("review-run", "Run dashboard build"),
        MenuOption("review-back", "Back to profile management"),
        MenuOption("review-reset", "Reset dashboard wizard"),
    ]

def _selected_label(state, kind, value, label):
    selected = False
    if state.dashboard_source_kind == kind:
        if kind == SOURCE_LATEST:
            selected = True
        elif kind == SOURCE_VERSION:
            selected = state.dashboard_source_version == value
        elif kind == SOURCE_ARTIFACT:
            selected = state.dashboard_source_artifact_index == value
    return f"* {label}" if selected else f"  {label}"

def _delete_label(state, profile):
    if state.dashboard_delete_confirm_id == profile.profile_id:
        return f"Confirm delete profile: {profile.name}"
    return f"Delete profile: {profile.name}"

def selected_dashboard_option(state):
    options = dashboard_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def dashboard_source_artifact(state):
    if not state.native_artifacts:
        return None
    index = max(0, min(state.dashboard_source_artifact_index, len(state.native_artifacts) - 1))
    return state.native_artifacts[index]

def profile_refs_by_key(state):
    return {
        (package.patch_id, package.version): index
        for index, package in enumerate(state.patch_packages)
    }

def profile_missing_refs(state, profile):
    available = profile_refs_by_key(state)
    missing = []
    for ref in profile.patches:
        key = (ref["id"], ref["version"])
        if key not in available:
            missing.append(f"{ref['id']}@{ref['version']}")
    return missing

def profile_by_id(state, profile_id):
    for profile in state.patch_profiles:
        if profile.profile_id == profile_id:
            return profile
    return None

def dashboard_tweak_profile_by_id(state, profile_id):
    for profile in state.dashboard_tweak_profiles:
        if profile.profile_id == profile_id:
            return profile
    return None

def loaded_profile(state):
    if not state.dashboard_loaded_profile_id:
        return None
    profile = dashboard_tweak_profile_by_id(state, state.dashboard_loaded_profile_id)
    if profile is not None:
        return profile
    return profile_by_id(state, state.dashboard_loaded_profile_id)

def dashboard_tweak_ids():
    return [tweak_id for tweak_id in DASHBOARD_TWEAK_IDS if tweak_id in PATCH_REGISTRY]

def dashboard_tweak_profile_missing_ids(state, profile):
    if not hasattr(profile, "tweak_ids"):
        return [f"{profile.profile_id} is not a dashboard tweak profile"]
    available = set(dashboard_tweak_ids())
    return [tweak_id for tweak_id in profile.tweak_ids if tweak_id not in available]

def selected_dashboard_tweaks(state):
    available = set(dashboard_tweak_ids())
    return [
        tweak_id for tweak_id in state.selected_dashboard_tweak_ids
        if tweak_id in available
    ]

def selected_dashboard_packages(state):
    return [
        state.patch_packages[index]
        for index in state.selected_patch_indexes
        if 0 <= index < len(state.patch_packages)
    ]

def selected_patch_refs(state):
    return [
        {"id": package.patch_id, "version": package.version}
        for package in selected_dashboard_packages(state)
    ]

def dashboard_title(state):
    return f"Dashboard: {DASHBOARD_STEPS[state.dashboard_step]}"

def dashboard_steps(state):
    labels = []
    for index, step in enumerate(DASHBOARD_STEPS):
        if index == state.dashboard_step:
            labels.append(f"[{step}]")
        elif index < state.dashboard_step:
            labels.append(f"{step}*")
        else:
            labels.append(step)
    return "Steps: " + " > ".join(labels)

def dashboard_summary(state):
    profile = loaded_profile(state)
    profile_label = profile.name if profile else "none"
    return (
        f"Source: {dashboard_source_label(state)}  "
        f"Patches: {len(selected_dashboard_tweaks(state))}  "
        f"Profile: {profile_label}"
    )

def dashboard_source_label(state):
    if state.dashboard_source_kind == SOURCE_VERSION:
        return f"native {state.dashboard_source_version}"
    if state.dashboard_source_kind == SOURCE_ARTIFACT:
        artifact = dashboard_source_artifact(state)
        if artifact is None:
            return "downloaded artifact unavailable"
        return f"downloaded {artifact.version} {artifact.platform} {short_sha(artifact.sha256)}"
    return "latest native"

def format_native_artifact(artifact):
    return f"{artifact.version}  {artifact.platform}  {short_sha(artifact.sha256)}  {_format_size(artifact)}  {artifact.path}"

def _format_size(artifact):
    size = getattr(artifact, "size", 0)
    if not size:
        return "unknown"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"

"""Collect addon health for the settings status dialog."""

from __future__ import annotations

import os
from dataclasses import dataclass

import xbmcaddon
import xbmcvfs

from pillow_installer import pillow_is_available
from skin_profiles import active_profile, current_skin_id, snippet_spec_for_skin_id
from skin_snippet_installer import (
    OVERLAY_REVISION,
    current_skin_overlay_installed,
    find_skin_xml_paths,
    overlay_already_installed,
    overlay_needs_refresh,
)


@dataclass(frozen=True)
class AddonHealth:
    skin_id: str
    skin_name: str
    profile_label: str
    snippet_file: str
    target_xml: str
    snippet_state: str  # missing | installed | stale | no_target
    pillow_ok: bool
    ffmpeg: str
    overlay_revision: int


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _skin_display_name(skin_id: str) -> str:
    if not skin_id:
        return "(unknown)"
    try:
        return xbmcaddon.Addon(skin_id).getAddonInfo("name") or skin_id
    except RuntimeError:
        return skin_id


def _skin_root(skin_id: str) -> str:
    if not skin_id:
        return ""
    try:
        path = xbmcaddon.Addon(skin_id).getAddonInfo("path")
    except RuntimeError:
        return ""
    local = _local_path(path) if path else ""
    return local if local and os.path.isdir(local) else ""


def _ffmpeg_status() -> str:
    try:
        from ffmpeg_tools import resolve_generator_ffmpeg_tools
        from generator_settings import read_generator_settings

        custom = read_generator_settings().ffmpeg_path
        ffmpeg, _, _ = resolve_generator_ffmpeg_tools(custom)
        return ffmpeg or "(not found)"
    except Exception:
        return "(not found)"


def collect_addon_health() -> AddonHealth:
    skin_id = current_skin_id() or ""
    profile = active_profile()
    spec = snippet_spec_for_skin_id(skin_id) if skin_id else None
    snippet_file = spec.filename if spec else "(none)"
    target_xml = spec.target_xml if spec else "DialogSeekBar.xml"
    root = _skin_root(skin_id)

    snippet_state = "no_target"
    if skin_id and spec and root:
        paths = find_skin_xml_paths(root, target_xml)
        if not paths:
            snippet_state = "no_target"
        elif any(
            overlay_already_installed(p) and not overlay_needs_refresh(p, spec.filename)
            for p in paths
        ):
            snippet_state = "installed"
        elif any(overlay_already_installed(p) for p in paths):
            snippet_state = "stale"
        else:
            snippet_state = "missing"
    elif skin_id and spec:
        snippet_state = "no_target"

    return AddonHealth(
        skin_id=skin_id or "(none)",
        skin_name=_skin_display_name(skin_id),
        profile_label=profile.label if profile else "(unknown)",
        snippet_file=snippet_file,
        target_xml=target_xml,
        snippet_state=snippet_state,
        pillow_ok=pillow_is_available(),
        ffmpeg=_ffmpeg_status(),
        overlay_revision=OVERLAY_REVISION,
    )


def format_health_report(health: AddonHealth) -> str:
    state_labels = {
        "installed": "OK (up to date)",
        "stale": "Installed but STALE — reinstall snippet",
        "missing": "Not installed",
        "no_target": f"Target {health.target_xml} not found",
    }
    snippet_line = state_labels.get(health.snippet_state, health.snippet_state)
    pillow_line = "OK" if health.pillow_ok else "Missing — Install Pillow"
    return (
        f"Active skin: {health.skin_name}\n"
        f"  ({health.skin_id})\n"
        f"Skin profile: {health.profile_label}\n"
        f"Snippet: {health.snippet_file}\n"
        f"Target: {health.target_xml}\n"
        f"Snippet status: {snippet_line}\n"
        f"Expected overlay rev: {health.overlay_revision}\n"
        f"Pillow: {pillow_line}\n"
        f"ffmpeg: {health.ffmpeg}"
    )


def current_skin_snippet_is_current() -> bool:
    """True when the active skin has a non-stale trickplay overlay."""
    return current_skin_overlay_installed()

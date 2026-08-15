"""Addon status, cache, validation, and generator diagnostics dialogs."""

from __future__ import annotations

import os

import xbmcgui

from script_common import _ADDON, _dialog_yesno, _is_valid_library_root, _log
from generator_settings import read_generator_settings
from trickplay_validation import repair_invalid, validate_library


def run_addon_status_dialog() -> None:
    _log("run_addon_status_dialog started")
    from addon_health import collect_addon_health, format_health_report
    from script_skin import run_install_skin_dialog
    from skin_snippet_installer import InstallScope
    from snippet_nudge import prompt_message_for_snippet, snippet_needs_attention

    health = collect_addon_health()
    report = format_health_report(health)
    if snippet_needs_attention(health):
        body = report + "\n\n" + prompt_message_for_snippet(health)
        if xbmcgui.Dialog().yesno(
            _ADDON.getLocalizedString(32211),
            body,
            yeslabel=_ADDON.getLocalizedString(32164),
            nolabel=_ADDON.getLocalizedString(32100),
        ):
            run_install_skin_dialog(InstallScope.CURRENT)
        return
    xbmcgui.Dialog().ok(_ADDON.getLocalizedString(32211), report)

def _format_cache_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"

def run_clear_preview_cache_dialog() -> None:
    _log("run_clear_preview_cache_dialog started")
    title = _ADDON.getLocalizedString(32218)
    if not xbmcgui.Dialog().yesno(
        title,
        _ADDON.getLocalizedString(32220),
        yeslabel=_ADDON.getLocalizedString(32164),
        nolabel=_ADDON.getLocalizedString(32100),
    ):
        _log("Clear preview cache cancelled")
        return

    from thumb_cropper import clear_preview_cache

    result = clear_preview_cache()
    if result.total_files <= 0:
        message = _ADDON.getLocalizedString(32222)
    else:
        message = _ADDON.getLocalizedString(32221) % (
            result.thumb_files,
            _format_cache_bytes(result.thumb_bytes),
            result.tile_files,
            _format_cache_bytes(result.tile_bytes),
        )
    _log(f"Clear preview cache result: {message}")
    xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO, 5000)

def run_validation_repair_dialog() -> None:
    """Validate the configured sidecar profile and optionally repair it."""
    settings = read_generator_settings()
    title = _ADDON.getLocalizedString(32233)
    if not settings.library_path or not _is_valid_library_root(settings.library_path):
        xbmcgui.Dialog().ok(title, _ADDON.getLocalizedString(32088))
        return

    report = validate_library(
        settings.library_path,
        tile_width=settings.tile_width,
        grid=settings.grid,
        interval_ms=settings.interval_ms,
        debug=settings.debug,
    )
    valid_count = len(report.items) - len(report.invalid)
    lines = [
        f"Checked: {len(report.items)}",
        f"Valid: {valid_count}",
        f"Needs repair: {len(report.invalid)}",
    ]
    for item in report.invalid[:20]:
        lines.append(f"- {os.path.basename(item.media_path)}: {item.reason}")
    if len(report.invalid) > 20:
        lines.append(f"…and {len(report.invalid) - 20} more")
    body = "\n".join(lines)
    _log(f"Validation report:\n{body}")
    if report.cancelled or not report.invalid:
        xbmcgui.Dialog().ok(title, body)
        return
    if not _dialog_yesno(
        title,
        body + "\n\n" + _ADDON.getLocalizedString(32235),
        yeslabel=_ADDON.getLocalizedString(32236),
        nolabel=_ADDON.getLocalizedString(32224),
        default_yes=True,
    ):
        return
    results = repair_invalid(report.invalid, settings)
    repaired = sum(bool(result) for result in results)
    failed = len(results) - repaired
    xbmcgui.Dialog().ok(
        title,
        body + f"\n\nRepaired: {repaired}\nFailed: {failed}",
    )

def run_generator_diagnostics_dialog() -> None:
    """Show non-destructive ffmpeg and hardware capability diagnostics."""
    import sys as _sys
    from ffmpeg_tools import (
        identify_ffmpeg_build,
        probe_ffmpeg_hwaccels_summary,
        resolve_generator_ffmpeg_tools,
    )
    from hdr_tone_map import probe_ffmpeg_has_cuda, probe_vulkan_available

    settings = read_generator_settings()
    ffmpeg, _ffprobe, env = resolve_generator_ffmpeg_tools(settings.ffmpeg_path)
    vendor, version = identify_ffmpeg_build(ffmpeg or "", env)
    hwaccels = probe_ffmpeg_hwaccels_summary(ffmpeg or "", env) or "none reported"
    os_release = ""
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            os_release = handle.read().lower()
    except OSError:
        pass
    coreelec = "coreelec" in os_release
    cuda = probe_ffmpeg_has_cuda(ffmpeg or "", env)
    vulkan = probe_vulkan_available(ffmpeg or "", env)
    if coreelec:
        selected = "software/per-frame fast seek (CoreELEC policy)"
        platform_detail = "CoreELEC detected; rkmpp, CUDA, and Vulkan are not selected"
    elif _sys.platform.startswith("win"):
        selected = "D3D11VA when eligible, CUDA when the probe succeeds"
        platform_detail = "Windows hardware paths are selected per media and successful probe"
    elif _sys.platform.startswith("linux"):
        selected = "VA-API/Vulkan when eligible, otherwise software"
        platform_detail = "Linux hardware paths are selected per media and successful probe"
    else:
        selected = "software"
        platform_detail = "No supported hardware backend for this platform"
    body = (
        f"ffmpeg: {ffmpeg or 'not found'}\n"
        f"Build: {vendor} — {version or 'unknown version'}\n"
        f"Hardware accelerators: {hwaccels}\n"
        f"Runtime CUDA probe: {'available' if cuda else 'unavailable'}\n"
        f"Runtime Vulkan probe: {'available' if vulkan else 'unavailable'}\n"
        f"Platform policy: {platform_detail}\n"
        f"Addon decode selection: {selected}\n\n"
        "rkmpp/opencl/drm are not selected by this addon because its supported "
        "thumbnail paths require CUDA, D3D11VA, or VA-API (optionally Vulkan). "
        "Generation falls back to software when probes fail."
    )
    _log(f"Generator diagnostics:\n{body}")
    xbmcgui.Dialog().ok(_ADDON.getLocalizedString(32237), body)


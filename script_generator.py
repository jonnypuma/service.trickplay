"""Manual library batch trickplay generation."""

from __future__ import annotations

import os
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

_ADDON = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

from generator_settings import GeneratorSettings, read_generator_settings, save_generator_library_path
from hdr_ffmpeg_installer import prompt_and_install_generator_tools
from library_path_browse import browse_library_folder
from trickplay_generator import collect_generation_candidates, generate_trickplay_for_media


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator.batch] {message}", level)


def _is_valid_library_root(path: str) -> bool:
    if not path or path.startswith(("special://", "plugin://", "http://", "https://")):
        return False
    try:
        return xbmcvfs.exists(path) and xbmcvfs.isdir(path)
    except (OSError, RuntimeError, ValueError):
        return False


def _browse_library_path(current: str) -> str | None:
    _log(f"Browse library folder (start={current or 'full browser'})")
    folder = browse_library_folder(_ADDON.getLocalizedString(32061), current)
    if not folder:
        _log("Library folder browse cancelled")
        return None
    if not _is_valid_library_root(folder):
        _log(f"Invalid library folder selected: {folder!r}", xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(
            _ADDON.getLocalizedString(32063),
            _ADDON.getLocalizedString(32088),
        )
        return None
    _log(f"Library folder selected: {folder}")
    save_generator_library_path(folder)
    _log("Library folder saved to addon settings")
    return folder


def _run_batch_generation(
    candidates: list[str],
    settings: GeneratorSettings,
    *,
    progress: xbmcgui.DialogProgress | None = None,
    monitor: xbmc.Monitor | None = None,
) -> tuple[int, int, bool]:
    """Generate trickplay for each candidate. Returns (ok_count, fail_count, cancelled)."""
    ok_count = 0
    fail_count = 0
    cancelled = False
    total = len(candidates)

    if monitor is None:
        monitor = xbmc.Monitor()

    def _should_cancel() -> bool:
        nonlocal cancelled
        if monitor.abortRequested():
            cancelled = True
            return True
        if progress is not None and progress.iscanceled():
            cancelled = True
            return True
        return False

    for index, media_path in enumerate(candidates):
        if _should_cancel():
            _log(
                f"Batch stopped early at {index + 1}/{total}",
                xbmc.LOGWARNING,
            )
            break

        label = os.path.basename(media_path)
        status = _ADDON.getLocalizedString(32070) % (index + 1, total)
        if progress is not None:
            # Kodi v19+ DialogProgress.update() accepts only percent + one message line.
            progress.update(
                int((index * 100) / max(total, 1)),
                f"{status} — {label}",
            )
        else:
            _log(f"{status}: {label}")

        _log(f"Generating {index + 1}/{total}: {media_path}")
        if generate_trickplay_for_media(
            media_path,
            settings,
            should_cancel=_should_cancel,
        ):
            ok_count += 1
        elif cancelled:
            break
        else:
            fail_count += 1
            _log(f"Generation failed: {media_path}", xbmc.LOGWARNING)
            if settings.stop_on_failure:
                _log("Stopping batch (stop on first failure enabled)", xbmc.LOGWARNING)
                break

    return ok_count, fail_count, cancelled


def run_batch_dialog() -> None:
    _log("run_batch_dialog started")
    settings = read_generator_settings()
    _log(
        "Generator settings: "
        f"enabled={settings.enabled} library_path={settings.library_path!r} "
        f"overwrite={settings.overwrite_existing} extract_mode={settings.extract_mode} "
        f"hdr_tone_map={settings.hdr_tone_map} "
        f"hdr_dovi_tool_fallback={settings.hdr_dovi_tool_fallback} "
        f"ffmpeg_path={settings.ffmpeg_path!r} "
        f"stop_on_failure={settings.stop_on_failure} "
        f"batch_background={settings.batch_background} "
        f"tile_width={settings.tile_width} "
        f"grid={settings.grid} interval_ms={settings.interval_ms}"
    )
    if not settings.enabled:
        _log("Generator disabled; showing enable prompt", xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(
            _ADDON.getLocalizedString(32040),
            _ADDON.getLocalizedString(32062),
        )
        return

    folder = settings.library_path
    if not folder or not xbmcvfs.exists(folder):
        _log(
            f"Library path missing or not found ({folder!r}); opening browse dialog",
            xbmc.LOGWARNING,
        )
        folder = _browse_library_path(folder)
        if not folder:
            return
    else:
        _log(f"Confirming library path: {folder}")
        choice = xbmcgui.Dialog().yesno(
            _ADDON.getLocalizedString(32063),
            _ADDON.getLocalizedString(32064) % folder,
            yeslabel=_ADDON.getLocalizedString(32065),
            nolabel=_ADDON.getLocalizedString(32066),
        )
        if not choice:
            folder = _browse_library_path(folder)
            if not folder:
                return

    _log(f"Collecting generation candidates under {folder}")
    plan = collect_generation_candidates(folder, settings)
    candidates = plan.candidates
    _log(
        f"Found {len(candidates)} candidate(s) "
        f"({plan.skipped_existing} skipped existing, "
        f"{plan.skipped_dv_profile_5} skipped DV Profile 5, "
        f"{plan.total_videos} total)"
    )
    if not candidates:
        _log("No candidates; showing notification", xbmc.LOGINFO)
        xbmcgui.Dialog().notification(
            _ADDON.getLocalizedString(32063),
            _ADDON.getLocalizedString(32067),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return

    if not prompt_and_install_generator_tools(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
        title=_ADDON.getLocalizedString(32063),
        ffmpeg_prompt_yes=_ADDON.getLocalizedString(32099),
        dovi_prompt_yes=_ADDON.getLocalizedString(32106),
        prompt_no=_ADDON.getLocalizedString(32100),
        download_yes=_ADDON.getLocalizedString(32105),
        ffmpeg_progress_title=_ADDON.getLocalizedString(32101),
        dovi_progress_title=_ADDON.getLocalizedString(32107),
        ffmpeg_unsupported_message=_ADDON.getLocalizedString(32102),
        dovi_unsupported_message=_ADDON.getLocalizedString(32108),
        ffmpeg_failed_message=_ADDON.getLocalizedString(32103),
        dovi_failed_message=_ADDON.getLocalizedString(32109),
        ffmpeg_success_message=_ADDON.getLocalizedString(32104),
        dovi_success_message=_ADDON.getLocalizedString(32110),
        vulkan_prompt_yes=_ADDON.getLocalizedString(32118),
        vulkan_success_message=_ADDON.getLocalizedString(32119),
    ):
        _log("Batch aborted after HDR ffmpeg install prompt")
        return

    if plan.skipped_existing > 0 and plan.skipped_dv_profile_5 > 0:
        confirm = _ADDON.getLocalizedString(32116) % (
            len(candidates),
            plan.total_videos,
            plan.skipped_existing,
            plan.skipped_dv_profile_5,
        )
    elif plan.skipped_existing > 0:
        confirm = _ADDON.getLocalizedString(32083) % (
            len(candidates),
            plan.total_videos,
            plan.skipped_existing,
        )
    elif plan.skipped_dv_profile_5 > 0:
        confirm = _ADDON.getLocalizedString(32117) % (
            len(candidates),
            plan.total_videos,
            plan.skipped_dv_profile_5,
        )
    else:
        confirm = _ADDON.getLocalizedString(32068) % len(candidates)

    if not xbmcgui.Dialog().yesno(
        _ADDON.getLocalizedString(32063),
        confirm,
    ):
        _log("Batch run cancelled at confirmation prompt")
        return

    _log(f"Starting batch generation for {len(candidates)} file(s)")
    monitor = xbmc.Monitor()

    if settings.batch_background:
        xbmcgui.Dialog().notification(
            _ADDON.getLocalizedString(32063),
            _ADDON.getLocalizedString(32113) % len(candidates),
            xbmcgui.NOTIFICATION_INFO,
            5000,
        )
        ok_count, fail_count, cancelled = _run_batch_generation(
            candidates,
            settings,
            monitor=monitor,
        )
        if cancelled:
            _log(f"Batch cancelled (ok={ok_count} fail={fail_count})")
            return
        _log(f"Batch complete: ok={ok_count} fail={fail_count}")
        xbmcgui.Dialog().notification(
            _ADDON.getLocalizedString(32063),
            _ADDON.getLocalizedString(32071) % (ok_count, fail_count),
            xbmcgui.NOTIFICATION_INFO,
            8000,
        )
        return

    progress = xbmcgui.DialogProgress()
    progress.create(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32069),
    )
    try:
        ok_count, fail_count, cancelled = _run_batch_generation(
            candidates,
            settings,
            progress=progress,
            monitor=monitor,
        )
    finally:
        progress.close()

    if cancelled:
        _log(f"Batch cancelled by user (ok={ok_count} fail={fail_count})")
        return

    _log(f"Batch complete: ok={ok_count} fail={fail_count}")
    xbmcgui.Dialog().ok(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32071) % (ok_count, fail_count),
    )


def _resolve_mode(argv: list[str]) -> str:
    """Return script mode from RunScript argv (addon id + optional args)."""
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("batch", "run_batch"):
            return "batch"
        if normalized.endswith(".py"):
            continue
        if normalized:
            _log(f"Unknown script argument {arg!r}; defaulting to batch", xbmc.LOGWARNING)
            break
    return "batch"


if __name__ == "__main__":
    _log(f"script_generator invoked argv={sys.argv!r}")
    mode = _resolve_mode(sys.argv)
    _log(f"Resolved mode={mode!r}")
    if mode == "batch":
        run_batch_dialog()
    else:
        _log(f"Unsupported mode {mode!r}; no action taken", xbmc.LOGERROR)

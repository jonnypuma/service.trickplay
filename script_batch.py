"""Manual library batch trickplay generation."""

from __future__ import annotations

import os
import threading

import xbmc
import xbmcgui
import xbmcvfs

from script_common import (
    _ADDON,
    _dialog_yesno,
    _is_valid_library_root,
    _log,
    _yield_ui,
)
from generator_settings import GeneratorSettings, read_generator_settings, save_generator_library_path
from hdr_ffmpeg_installer import prompt_and_install_generator_tools
from library_path_browse import browse_library_folder
from trickplay_generator import (
    GenerationBatchPlan,
    GenerationResult,
    collect_generation_candidates,
    generate_trickplay_for_media,
)
from generation_state import begin_or_update, clear as clear_generation_state, load_completed
from generation_preflight import warnings_for_batch


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
    root: str = "",
    progress: xbmcgui.DialogProgress | None = None,
    monitor: xbmc.Monitor | None = None,
) -> tuple[int, int, bool, list[str], list[GenerationResult]]:
    """Generate candidates and return counts, failed paths, and detailed results."""
    ok_count = 0
    fail_count = 0
    failed_paths: list[str] = []
    results: list[GenerationResult] = []
    cancelled = False
    root = root or settings.library_path
    completed = load_completed(root, settings)
    pending = [path for path in candidates if path not in completed]
    if len(pending) != len(candidates):
        _log(
            f"Resuming batch: skipping {len(candidates) - len(pending)} "
            f"completed file(s) from {root}"
        )
    begin_or_update(root, settings, completed)
    total = len(pending)

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

    for index, media_path in enumerate(pending):
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
        raw_result = generate_trickplay_for_media(
            media_path,
            settings,
            should_cancel=_should_cancel,
        )
        result = (
            raw_result
            if isinstance(raw_result, GenerationResult)
            else GenerationResult(media_path=media_path, success=bool(raw_result))
        )
        results.append(result)
        if result:
            ok_count += 1
            completed.add(media_path)
            begin_or_update(root, settings, completed)
        elif cancelled:
            break
        else:
            fail_count += 1
            failed_paths.append(media_path)
            _log(f"Generation failed: {media_path}", xbmc.LOGWARNING)
            if settings.stop_on_failure:
                _log("Stopping batch (stop on first failure enabled)", xbmc.LOGWARNING)
                break

    if not cancelled and all(path in completed for path in candidates):
        clear_generation_state()
    return ok_count, fail_count, cancelled, failed_paths, results

def _format_batch_summary(
    results: list[GenerationResult],
    *,
    cancelled: bool,
) -> str:
    elapsed = sum(result.elapsed_seconds for result in results)
    tiles = sum(result.tiles_written for result in results)
    fallbacks = sum(result.fallback_count for result in results)
    failed_count = sum(not bool(result) and not result.cancelled for result in results)
    cancelled_count = sum(result.cancelled for result in results)
    status = "cancelled" if cancelled else "complete"
    summary = (
        f"Batch {status}: {len(results)} file(s), "
        f"{sum(bool(result) for result in results)} succeeded, "
        f"{failed_count} failed, {cancelled_count} cancelled, "
        f"{tiles} tile(s), {fallbacks} fallback(s), "
        f"{elapsed:.0f}s worker time"
    )
    failed = [
        f"{os.path.basename(result.media_path)}"
        + (f" — {result.failure_reason}" if result.failure_reason else "")
        for result in results
        if not bool(result) and not result.cancelled
    ]
    if failed:
        summary += "\nFailed files:\n- " + "\n- ".join(failed[:20])
        if len(failed) > 20:
            summary += f"\n- … and {len(failed) - 20} more"
    return summary

def _offer_batch_retry(failed_paths: list[str], settings: GeneratorSettings) -> None:
    if not failed_paths:
        return
    if not xbmcgui.Dialog().yesno(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32182) % len(failed_paths),
        yeslabel=_ADDON.getLocalizedString(32223),
        nolabel=_ADDON.getLocalizedString(32224),
    ):
        return
    _log(f"Retrying {len(failed_paths)} failed file(s)")
    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32183),
    )
    try:
        ok_count, fail_count, cancelled, still_failed, results = _run_batch_generation(
            failed_paths,
            settings,
            root=settings.library_path,
            progress=progress,
            monitor=monitor,
        )
    finally:
        progress.close()
    if cancelled:
        _log(_format_batch_summary(results, cancelled=True))
        return
    _log(_format_batch_summary(results, cancelled=False))
    xbmcgui.Dialog().ok(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32184) % (ok_count, fail_count),
    )
    if still_failed:
        _offer_batch_retry(still_failed, settings)

def _collect_candidates_with_progress(
    folder: str,
    settings: GeneratorSettings,
) -> GenerationBatchPlan | None:
    """Scan library for generation candidates with a cancellable progress dialog."""
    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create(
        _ADDON.getLocalizedString(32132),
        _ADDON.getLocalizedString(32133),
    )

    scan_line = _ADDON.getLocalizedString(32135)
    check_line = _ADDON.getLocalizedString(32134)
    state_lock = threading.Lock()
    state = {"phase": "scan", "checked": 0, "total": 0, "found": 0, "done": False}
    result: GenerationBatchPlan | None = None
    worker_error: BaseException | None = None

    def should_cancel() -> bool:
        return monitor.abortRequested() or progress.iscanceled()

    def on_progress(checked: int, total: int) -> None:
        with state_lock:
            if total <= 0:
                state["phase"] = "scan"
                state["found"] = checked
            else:
                state["phase"] = "check"
                state["checked"] = checked
                state["total"] = total

    def worker() -> None:
        nonlocal result, worker_error
        try:
            result = collect_generation_candidates(
                folder,
                settings,
                should_cancel=should_cancel,
                on_progress=on_progress,
            )
        except BaseException as exc:
            worker_error = exc
        finally:
            with state_lock:
                state["done"] = True

    thread = threading.Thread(target=worker, daemon=True, name="trickplay-batch-scan")
    thread.start()

    try:
        while thread.is_alive():
            with state_lock:
                phase = state["phase"]
                checked = state["checked"]
                total = state["total"]
                found = state["found"]

            if phase == "check" and total > 0:
                progress.update(
                    int((checked * 100) / total),
                    check_line % (checked, total),
                )
            elif found > 0:
                progress.update(0, scan_line % found)
            else:
                progress.update(0, scan_line % 0)

            if should_cancel():
                break
            if monitor.waitForAbort(0.1):
                break

        thread.join(timeout=30.0)
    finally:
        progress.close()
        _yield_ui()

    if worker_error is not None:
        _log(f"Candidate scan failed: {worker_error}", xbmc.LOGERROR)
        raise worker_error

    if result is None:
        _log("Candidate scan produced no result", xbmc.LOGWARNING)
        return None

    if should_cancel() or result.cancelled:
        _log("Candidate scan cancelled by user")
        return None

    return result

def run_batch_dialog() -> None:
    _log("run_batch_dialog started")
    settings = read_generator_settings()
    _log(
        "Generator settings: "
        f"enabled={settings.enabled} library_path={settings.library_path!r} "
        f"overwrite={settings.overwrite_existing} extract_mode={settings.extract_mode} "
        f"fps_batch_timeout_cap={settings.fps_batch_timeout_cap_sec} "
        f"hdr_tone_map={settings.hdr_tone_map} "
        f"hdr_dovi_tool_fallback={settings.hdr_dovi_tool_fallback} "
        f"hw_decode={settings.hw_decode} hw_decode_cuda={settings.hw_decode_cuda} "
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
    plan = _collect_candidates_with_progress(folder, settings)
    if plan is None:
        return
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
        base_ffmpeg_prompt_yes=_ADDON.getLocalizedString(32125),
        hdr_ffmpeg_prompt_yes=_ADDON.getLocalizedString(32099),
        dovi_prompt_yes=_ADDON.getLocalizedString(32106),
        prompt_no=_ADDON.getLocalizedString(32100),
        download_yes=_ADDON.getLocalizedString(32105),
        base_ffmpeg_progress_title=_ADDON.getLocalizedString(32126),
        hdr_ffmpeg_progress_title=_ADDON.getLocalizedString(32101),
        dovi_progress_title=_ADDON.getLocalizedString(32107),
        ffmpeg_unsupported_message=_ADDON.getLocalizedString(32102),
        dovi_unsupported_message=_ADDON.getLocalizedString(32108),
        base_ffmpeg_failed_message=_ADDON.getLocalizedString(32127),
        hdr_ffmpeg_failed_message=_ADDON.getLocalizedString(32103),
        dovi_failed_message=_ADDON.getLocalizedString(32109),
        base_ffmpeg_success_message=_ADDON.getLocalizedString(32128),
        hdr_ffmpeg_success_message=_ADDON.getLocalizedString(32104),
        dovi_success_message=_ADDON.getLocalizedString(32110),
        vulkan_prompt_yes=_ADDON.getLocalizedString(32118),
        vulkan_success_message=_ADDON.getLocalizedString(32119),
        jellyfin_upgrade_prompt_yes=_ADDON.getLocalizedString(32225),
        jellyfin_upgrade_success_message=_ADDON.getLocalizedString(32226),
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

    preflight_warnings = warnings_for_batch(folder, candidates)
    if preflight_warnings:
        for warning in preflight_warnings:
            _log(f"Batch preflight warning: {warning}", xbmc.LOGWARNING)
        confirm += "\n\nWarnings:\n- " + "\n- ".join(preflight_warnings)

    _log(f"Showing batch confirmation ({len(candidates)} candidate(s))")
    if not _dialog_yesno(
        _ADDON.getLocalizedString(32063),
        confirm,
        yeslabel=_ADDON.getLocalizedString(32229),
        nolabel=_ADDON.getLocalizedString(32224),
        default_yes=True,
    ):
        _log(
            "Batch run cancelled at confirmation prompt "
            "(No/Cancel, or dialog dismissed — Yes was not chosen)",
            xbmc.LOGINFO,
        )
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
        ok_count, fail_count, cancelled, failed_paths, results = _run_batch_generation(
            candidates,
            settings,
            root=folder,
            monitor=monitor,
        )
        if cancelled:
            _log(_format_batch_summary(results, cancelled=True))
            return
        summary = _format_batch_summary(results, cancelled=False)
        _log(summary)
        xbmcgui.Dialog().notification(
            _ADDON.getLocalizedString(32063),
            f"{_ADDON.getLocalizedString(32071) % (ok_count, fail_count)}\n\n{summary}",
            xbmcgui.NOTIFICATION_INFO,
            8000,
        )
        _offer_batch_retry(failed_paths, settings)
        return

    progress = xbmcgui.DialogProgress()
    progress.create(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32069),
    )
    try:
        ok_count, fail_count, cancelled, failed_paths, results = _run_batch_generation(
            candidates,
            settings,
            root=folder,
            progress=progress,
            monitor=monitor,
        )
    finally:
        progress.close()

    if cancelled:
        _log(f"Batch cancelled by user (ok={ok_count} fail={fail_count})")
        return

    summary = _format_batch_summary(results, cancelled=False)
    _log(summary)
    xbmcgui.Dialog().ok(
        _ADDON.getLocalizedString(32063),
        f"{_ADDON.getLocalizedString(32071) % (ok_count, fail_count)}\n\n{summary}",
    )
    _offer_batch_retry(failed_paths, settings)


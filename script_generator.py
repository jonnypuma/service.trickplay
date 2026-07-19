"""Manual library batch trickplay generation."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

_ADDON = xbmcaddon.Addon("service.trickplay")
_ADDON_PATH = _ADDON.getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

from generator_settings import GeneratorSettings, read_generator_settings, save_generator_library_path
from vfs_paths import vfs_is_dir
from hdr_ffmpeg_installer import (
    generator_install_tools_needed,
    install_tools_needed,
    prompt_and_install_generator_tools,
)
from pillow_installer import prompt_and_install_pillow, should_offer_pillow_download
from skin_snippet_installer import (
    InstallScope,
    build_install_plan,
    build_restore_plan,
    execute_install_plan,
    execute_restore_plan,
    format_plan_summary,
    format_restore_plan_summary,
    inactive_skin_install_note,
    plan_has_installable_targets,
    plan_has_restore_targets,
    summarize_outcomes,
)
from library_path_browse import browse_library_folder
from trickplay_generator import (
    GenerationBatchPlan,
    collect_generation_candidates,
    generate_trickplay_for_media,
)


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator.batch] {message}", level)


def _is_valid_library_root(path: str) -> bool:
    if not path or path.startswith(("special://", "plugin://", "http://", "https://")):
        return False
    try:
        return vfs_is_dir(path)
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
) -> tuple[int, int, bool, list[str]]:
    """Generate trickplay for each candidate. Returns (ok, fail, cancelled, failed_paths)."""
    ok_count = 0
    fail_count = 0
    failed_paths: list[str] = []
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
            failed_paths.append(media_path)
            _log(f"Generation failed: {media_path}", xbmc.LOGWARNING)
            if settings.stop_on_failure:
                _log("Stopping batch (stop on first failure enabled)", xbmc.LOGWARNING)
                break

    return ok_count, fail_count, cancelled, failed_paths


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
        ok_count, fail_count, cancelled, still_failed = _run_batch_generation(
            failed_paths,
            settings,
            progress=progress,
            monitor=monitor,
        )
    finally:
        progress.close()
    if cancelled:
        return
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
        ok_count, fail_count, cancelled, failed_paths = _run_batch_generation(
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
        _offer_batch_retry(failed_paths, settings)
        return

    progress = xbmcgui.DialogProgress()
    progress.create(
        _ADDON.getLocalizedString(32063),
        _ADDON.getLocalizedString(32069),
    )
    try:
        ok_count, fail_count, cancelled, failed_paths = _run_batch_generation(
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
    _offer_batch_retry(failed_paths, settings)


def _install_tools_strings(settings: GeneratorSettings) -> dict[str, str]:
    return {
        "title": _ADDON.getLocalizedString(32131),
        "pillow_prompt_yes": _ADDON.getLocalizedString(32149),
        "pillow_progress_title": _ADDON.getLocalizedString(32150),
        "pillow_unsupported_message": _ADDON.getLocalizedString(32151),
        "pillow_failed_message": _ADDON.getLocalizedString(32152),
        "pillow_success_message": _ADDON.getLocalizedString(32153),
        "base_ffmpeg_prompt_yes": _ADDON.getLocalizedString(32125),
        "hdr_ffmpeg_prompt_yes": _ADDON.getLocalizedString(32099),
        "dovi_prompt_yes": _ADDON.getLocalizedString(32106),
        "prompt_no": _ADDON.getLocalizedString(32100),
        "download_yes": _ADDON.getLocalizedString(32105),
        "base_ffmpeg_progress_title": _ADDON.getLocalizedString(32126),
        "hdr_ffmpeg_progress_title": _ADDON.getLocalizedString(32101),
        "dovi_progress_title": _ADDON.getLocalizedString(32107),
        "ffmpeg_unsupported_message": _ADDON.getLocalizedString(32102),
        "dovi_unsupported_message": _ADDON.getLocalizedString(32108),
        "base_ffmpeg_failed_message": _ADDON.getLocalizedString(32127),
        "hdr_ffmpeg_failed_message": _ADDON.getLocalizedString(32103),
        "dovi_failed_message": _ADDON.getLocalizedString(32109),
        "base_ffmpeg_success_message": _ADDON.getLocalizedString(32128),
        "hdr_ffmpeg_success_message": _ADDON.getLocalizedString(32104),
        "dovi_success_message": _ADDON.getLocalizedString(32110),
        "vulkan_prompt_yes": _ADDON.getLocalizedString(32118),
        "vulkan_success_message": _ADDON.getLocalizedString(32119),
        "already_installed": _ADDON.getLocalizedString(32129),
    }


def run_install_pillow_dialog() -> None:
    _log("run_install_pillow_dialog started")
    strings = _install_tools_strings(read_generator_settings())
    if not should_offer_pillow_download():
        xbmcgui.Dialog().notification(
            strings["title"],
            _ADDON.getLocalizedString(32185),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return
    prompt_and_install_pillow(
        title=strings["title"],
        prompt_yes=strings["pillow_prompt_yes"],
        prompt_no=strings["prompt_no"],
        download_yes=strings["download_yes"],
        progress_title=strings["pillow_progress_title"],
        unsupported_message=strings["pillow_unsupported_message"],
        failed_message=strings["pillow_failed_message"],
        success_message=strings["pillow_success_message"],
    )
    try:
        from pillow_installer import invalidate_pillow_cache

        invalidate_pillow_cache()
    except ImportError:
        pass


def run_install_generator_tools_dialog() -> None:
    _log("run_install_generator_tools_dialog started")
    settings = read_generator_settings()
    strings = _install_tools_strings(settings)
    if not generator_install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
    ):
        xbmcgui.Dialog().notification(
            strings["title"],
            _ADDON.getLocalizedString(32186),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return
    prompt_and_install_generator_tools(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
        title=strings["title"],
        base_ffmpeg_prompt_yes=strings["base_ffmpeg_prompt_yes"],
        hdr_ffmpeg_prompt_yes=strings["hdr_ffmpeg_prompt_yes"],
        dovi_prompt_yes=strings["dovi_prompt_yes"],
        prompt_no=strings["prompt_no"],
        download_yes=strings["download_yes"],
        base_ffmpeg_progress_title=strings["base_ffmpeg_progress_title"],
        hdr_ffmpeg_progress_title=strings["hdr_ffmpeg_progress_title"],
        dovi_progress_title=strings["dovi_progress_title"],
        ffmpeg_unsupported_message=strings["ffmpeg_unsupported_message"],
        dovi_unsupported_message=strings["dovi_unsupported_message"],
        base_ffmpeg_failed_message=strings["base_ffmpeg_failed_message"],
        hdr_ffmpeg_failed_message=strings["hdr_ffmpeg_failed_message"],
        dovi_failed_message=strings["dovi_failed_message"],
        base_ffmpeg_success_message=strings["base_ffmpeg_success_message"],
        hdr_ffmpeg_success_message=strings["hdr_ffmpeg_success_message"],
        dovi_success_message=strings["dovi_success_message"],
        vulkan_prompt_yes=strings["vulkan_prompt_yes"],
        vulkan_success_message=strings["vulkan_success_message"],
    )
    try:
        from thumb_cropper import invalidate_playback_ffmpeg_cache

        invalidate_playback_ffmpeg_cache()
    except ImportError:
        pass


def run_install_tools_dialog(*, from_playback_prompt: bool = False) -> None:
    _log(
        "run_install_tools_dialog started "
        f"(from_playback_prompt={from_playback_prompt})"
    )
    settings = read_generator_settings()
    strings = _install_tools_strings(settings)
    include_generator = settings.enabled or settings.hdr_tone_map
    if not install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
        include_generator_tools=include_generator,
    ):
        _log("Install tools: nothing needed")
        if not from_playback_prompt:
            xbmcgui.Dialog().notification(
                strings["title"],
                strings["already_installed"],
                xbmcgui.NOTIFICATION_INFO,
                4000,
            )
        return

    if should_offer_pillow_download():
        prompt_and_install_pillow(
            title=strings["title"],
            prompt_yes=strings["pillow_prompt_yes"],
            prompt_no=strings["prompt_no"],
            download_yes=strings["download_yes"],
            progress_title=strings["pillow_progress_title"],
            unsupported_message=strings["pillow_unsupported_message"],
            failed_message=strings["pillow_failed_message"],
            success_message=strings["pillow_success_message"],
        )

    if include_generator and generator_install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
    ):
        prompt_and_install_generator_tools(
            hdr_tone_map_enabled=settings.hdr_tone_map,
            hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
            custom_ffmpeg_path=settings.ffmpeg_path,
            title=strings["title"],
            base_ffmpeg_prompt_yes=strings["base_ffmpeg_prompt_yes"],
            hdr_ffmpeg_prompt_yes=strings["hdr_ffmpeg_prompt_yes"],
            dovi_prompt_yes=strings["dovi_prompt_yes"],
            prompt_no=strings["prompt_no"],
            download_yes=strings["download_yes"],
            base_ffmpeg_progress_title=strings["base_ffmpeg_progress_title"],
            hdr_ffmpeg_progress_title=strings["hdr_ffmpeg_progress_title"],
            dovi_progress_title=strings["dovi_progress_title"],
            ffmpeg_unsupported_message=strings["ffmpeg_unsupported_message"],
            dovi_unsupported_message=strings["dovi_unsupported_message"],
            base_ffmpeg_failed_message=strings["base_ffmpeg_failed_message"],
            hdr_ffmpeg_failed_message=strings["hdr_ffmpeg_failed_message"],
            dovi_failed_message=strings["dovi_failed_message"],
            base_ffmpeg_success_message=strings["base_ffmpeg_success_message"],
            hdr_ffmpeg_success_message=strings["hdr_ffmpeg_success_message"],
            dovi_success_message=strings["dovi_success_message"],
            vulkan_prompt_yes=strings["vulkan_prompt_yes"],
            vulkan_success_message=strings["vulkan_success_message"],
        )
    try:
        from pillow_installer import invalidate_pillow_cache
        from thumb_cropper import invalidate_playback_ffmpeg_cache

        invalidate_pillow_cache()
        invalidate_playback_ffmpeg_cache()
    except ImportError:
        pass


def _install_skin_error_message(code: str) -> str:
    mapping = {
        "dialog_seekbar_not_found": 32161,
        "not_writable": 32165,
        "skin_addon_path_unavailable": 32166,
        "snippet_file_missing": 32167,
        "backup_not_found": 32187,
        "already_installed": 32188,
        "dialog_seekbar_stub": 32209,
        "snippet_target_not_found": 32210,
        "stale_overlay": 32213,
    }
    string_id = mapping.get(code, 32161)
    return _ADDON.getLocalizedString(string_id)


def _format_skin_outcome_lines(outcomes: list) -> list[str]:
    result_lines: list[str] = []
    for item in outcomes:
        if item.skipped:
            rel = os.path.basename(os.path.dirname(item.seekbar_path))
            if item.message == "dialog_seekbar_stub":
                detail = _install_skin_error_message("dialog_seekbar_stub")
            else:
                detail = _install_skin_error_message("already_installed")
            result_lines.append(
                f"• {item.skin_name}: .../{rel}/{os.path.basename(item.seekbar_path)} "
                f"— {detail}"
            )
            continue
        if item.success:
            detail = item.message
            if detail == "ok_backup_kept":
                detail = _ADDON.getLocalizedString(32170)
            elif detail == "ok":
                detail = _ADDON.getLocalizedString(32171)
            elif detail == "restored":
                detail = _ADDON.getLocalizedString(32189)
            rel = os.path.basename(os.path.dirname(item.seekbar_path))
            result_lines.append(
                f"• {item.skin_name}: .../{rel}/{os.path.basename(item.seekbar_path)} — {detail}"
            )
        else:
            msg = _install_skin_error_message(item.message.split(":")[0])
            if item.message.startswith("backup_failed:"):
                msg = _ADDON.getLocalizedString(32168) % item.message.split(":", 1)[1]
            elif not item.seekbar_path:
                msg = _install_skin_error_message(item.message)
            result_lines.append(f"• {item.skin_name}: {msg}")
    return result_lines


def _build_skin_summary_body(outcomes: list, scope: InstallScope) -> str:
    ok_count, fail_count, skipped_count, skin_count = summarize_outcomes(outcomes)
    result_lines = _format_skin_outcome_lines(outcomes)
    summary_body = _ADDON.getLocalizedString(32180) % (
        ok_count,
        fail_count,
        skipped_count,
        skin_count,
    )
    if result_lines:
        summary_body = summary_body + "\n\n" + "\n".join(result_lines)
    if inactive_skin_install_note(outcomes, scope):
        summary_body = summary_body + "\n\n" + _ADDON.getLocalizedString(32181)
    return summary_body


def _execute_skin_plan_with_progress(
    work_count: int,
    title: str,
    execute: Callable[
        [Callable[[int, str], None] | None],
        tuple[list, bool],
    ],
) -> tuple[list, bool]:
    if work_count <= 1:
        return execute(None)

    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create(title, _ADDON.getLocalizedString(32190))

    def _progress(percent: int, line: str) -> None:
        if monitor.abortRequested() or progress.iscanceled():
            return
        progress.update(percent, line)

    try:
        return execute(_progress)
    finally:
        progress.close()


def run_install_skin_dialog(scope: InstallScope, *, force: bool = False) -> None:
    _log(f"run_install_skin_dialog started (scope={scope.value}, force={force})")
    plans = build_install_plan(scope, _ADDON_PATH, force=force)
    title = (
        _ADDON.getLocalizedString(32214)
        if force
        else _ADDON.getLocalizedString(32158)
    )
    if not plans:
        xbmcgui.Dialog().ok(
            title,
            _ADDON.getLocalizedString(32163),
        )
        return

    summary = format_plan_summary(plans)
    for plan in plans:
        if plan.error:
            err_text = _install_skin_error_message(plan.error)
            summary = summary.replace(f"[{plan.error}]", f"[{err_text}]")

    if not plan_has_installable_targets(plans):
        xbmcgui.Dialog().ok(
            title,
            _ADDON.getLocalizedString(32159) % summary,
        )
        return

    prompt = _ADDON.getLocalizedString(32159) % summary
    if not xbmcgui.Dialog().yesno(
        title,
        prompt,
        yeslabel=_ADDON.getLocalizedString(32164),
        nolabel=_ADDON.getLocalizedString(32100),
    ):
        _log("Skin snippet install cancelled")
        return

    work_count = sum(
        1
        for plan in plans
        for path_plan in plan.paths
        if path_plan.writable and not path_plan.already_installed and not path_plan.stub_seekbar
    )

    def _run(progress):
        # schedule_reload=True (default): same path that used to show the result
        # modal. ReloadSkin may still race OK — preferred over no modal at all.
        return execute_install_plan(plans, _ADDON_PATH, progress=progress)

    outcomes, _needs_reload = _execute_skin_plan_with_progress(work_count, title, _run)
    summary_body = _build_skin_summary_body(outcomes, scope)
    _log(f"Skin install result:\n{summary_body}")
    xbmcgui.Dialog().ok(title, summary_body)


def run_addon_status_dialog() -> None:
    _log("run_addon_status_dialog started")
    from addon_health import collect_addon_health, format_health_report

    report = format_health_report(collect_addon_health())
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


def run_restore_skin_dialog(scope: InstallScope) -> None:
    _log(f"run_restore_skin_dialog started (scope={scope.value})")
    plans = build_restore_plan(scope)
    if not plans:
        xbmcgui.Dialog().ok(
            _ADDON.getLocalizedString(32191),
            _ADDON.getLocalizedString(32163),
        )
        return

    summary = format_restore_plan_summary(plans)
    for plan in plans:
        if plan.error:
            err_text = _install_skin_error_message(plan.error)
            summary = summary.replace(f"[{plan.error}]", f"[{err_text}]")

    if not plan_has_restore_targets(plans):
        xbmcgui.Dialog().ok(
            _ADDON.getLocalizedString(32191),
            _ADDON.getLocalizedString(32192) % summary,
        )
        return

    prompt = _ADDON.getLocalizedString(32193) % summary
    if not xbmcgui.Dialog().yesno(
        _ADDON.getLocalizedString(32191),
        prompt,
        yeslabel=_ADDON.getLocalizedString(32164),
        nolabel=_ADDON.getLocalizedString(32100),
    ):
        _log("Skin restore cancelled")
        return

    work_count = sum(
        1 for plan in plans for path_plan in plan.paths if path_plan.writable
    )
    title = _ADDON.getLocalizedString(32191)

    def _run(progress):
        return execute_restore_plan(plans, progress=progress)

    outcomes, _needs_reload = _execute_skin_plan_with_progress(work_count, title, _run)
    summary_body = _build_skin_summary_body(outcomes, scope)
    _log(f"Skin restore result:\n{summary_body}")
    xbmcgui.Dialog().ok(title, summary_body)


def _resolve_skin_scope(argv: list[str], action: str) -> InstallScope | None:
    args = [(arg or "").strip().lower() for arg in argv[1:] if (arg or "").strip()]
    if action in args or f"{action}_snippet" in args:
        if "all" in args:
            return InstallScope.ALL
        return InstallScope.CURRENT
    for arg in args:
        if arg in (f"{action}_all", f"{action}_snippet_all"):
            return InstallScope.ALL
        if arg in (f"{action}_current", f"{action}_snippet_current"):
            return InstallScope.CURRENT
    return None


def _resolve_install_skin_scope(argv: list[str]) -> InstallScope | None:
    return _resolve_skin_scope(argv, "install_skin")


def _resolve_install_skin_force(argv: list[str]) -> bool:
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("force", "install_skin_force", "force_install_skin"):
            return True
    return False


def _resolve_restore_skin_scope(argv: list[str]) -> InstallScope | None:
    return _resolve_skin_scope(argv, "restore_skin")


def _resolve_mode(argv: list[str]) -> str:
    """Return script mode from RunScript argv (addon id + optional args)."""
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("batch", "run_batch"):
            return "batch"
        if normalized in ("install_tools", "install"):
            return "install_tools"
        if normalized in ("install_skin", "install_skin_snippet"):
            return "install_skin"
        if normalized in (
            "install_skin_current",
            "install_skin_all",
            "install_skin_snippet_current",
            "install_skin_snippet_all",
            "install_skin_force",
            "force_install_skin",
        ):
            return "install_skin"
        if normalized in ("addon_status", "show_status", "status"):
            return "addon_status"
        if normalized in ("restore_skin", "restore_skin_snippet"):
            return "restore_skin"
        if normalized in (
            "restore_skin_current",
            "restore_skin_all",
            "restore_skin_snippet_current",
            "restore_skin_snippet_all",
        ):
            return "restore_skin"
        if normalized in ("install_pillow",):
            return "install_pillow"
        if normalized in ("install_generator_tools", "install_generator"):
            return "install_generator_tools"
        if normalized in ("clear_preview_cache", "clear_cache", "clear_thumb_cache"):
            return "clear_preview_cache"
        if normalized.endswith(".py"):
            continue
        if normalized:
            _log(f"Unknown script argument {arg!r}; defaulting to batch", xbmc.LOGWARNING)
            break
    return "batch"


def _from_playback_prompt(argv: list[str]) -> bool:
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("playback", "from_playback"):
            return True
    return False


if __name__ == "__main__":
    _log(f"script_generator invoked argv={sys.argv!r}")
    mode = _resolve_mode(sys.argv)
    _log(f"Resolved mode={mode!r}")
    if mode == "batch":
        run_batch_dialog()
    elif mode == "install_tools":
        run_install_tools_dialog(from_playback_prompt=_from_playback_prompt(sys.argv))
    elif mode == "install_skin":
        scope = _resolve_install_skin_scope(sys.argv) or InstallScope.CURRENT
        force = _resolve_install_skin_force(sys.argv)
        run_install_skin_dialog(scope, force=force)
    elif mode == "addon_status":
        run_addon_status_dialog()
    elif mode == "restore_skin":
        scope = _resolve_restore_skin_scope(sys.argv) or InstallScope.CURRENT
        run_restore_skin_dialog(scope)
    elif mode == "install_pillow":
        run_install_pillow_dialog()
    elif mode == "install_generator_tools":
        run_install_generator_tools_dialog()
    elif mode == "clear_preview_cache":
        run_clear_preview_cache_dialog()
    else:
        _log(f"Unsupported mode {mode!r}; no action taken", xbmc.LOGERROR)

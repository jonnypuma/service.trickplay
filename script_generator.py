"""Manual library batch trickplay generation."""

from __future__ import annotations

import os
import sys
import threading

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
    execute_install_plan,
    format_plan_summary,
    plan_has_installable_targets,
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
    }
    string_id = mapping.get(code, 32161)
    return _ADDON.getLocalizedString(string_id)


def run_install_skin_dialog(scope: InstallScope) -> None:
    _log(f"run_install_skin_dialog started (scope={scope.value})")
    plans = build_install_plan(scope, _ADDON_PATH)
    if not plans:
        xbmcgui.Dialog().ok(
            _ADDON.getLocalizedString(32158),
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
            _ADDON.getLocalizedString(32158),
            _ADDON.getLocalizedString(32159) % summary,
        )
        return

    prompt = _ADDON.getLocalizedString(32159) % summary
    if not xbmcgui.Dialog().yesno(
        _ADDON.getLocalizedString(32158),
        prompt,
        yeslabel=_ADDON.getLocalizedString(32164),
        nolabel=_ADDON.getLocalizedString(32100),
    ):
        _log("Skin snippet install cancelled")
        return

    outcomes = execute_install_plan(plans, _ADDON_PATH)
    ok_count, fail_count, skin_count = summarize_outcomes(outcomes)
    result_lines: list[str] = []
    for item in outcomes:
        if item.success:
            detail = item.message
            if detail == "ok_backup_kept":
                detail = _ADDON.getLocalizedString(32170)
            elif detail == "ok":
                detail = _ADDON.getLocalizedString(32171)
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

    summary_body = _ADDON.getLocalizedString(32162) % (ok_count, fail_count, skin_count)
    if result_lines:
        summary_body = summary_body + "\n\n" + "\n".join(result_lines)

    xbmcgui.Dialog().ok(_ADDON.getLocalizedString(32158), summary_body)


def _resolve_install_skin_scope(argv: list[str]) -> InstallScope | None:
    args = [(arg or "").strip().lower() for arg in argv[1:] if (arg or "").strip()]
    if "install_skin" in args or "install_skin_snippet" in args:
        if "all" in args:
            return InstallScope.ALL
        return InstallScope.CURRENT
    for arg in args:
        if arg in ("install_skin_all", "install_skin_snippet_all"):
            return InstallScope.ALL
        if arg in ("install_skin_current", "install_skin_snippet_current"):
            return InstallScope.CURRENT
    return None


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
        ):
            return "install_skin"
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
        run_install_skin_dialog(scope)
    else:
        _log(f"Unsupported mode {mode!r}; no action taken", xbmc.LOGERROR)

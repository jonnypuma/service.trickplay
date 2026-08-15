"""Install and restore trickplay skin snippets."""

from __future__ import annotations

import os
from collections.abc import Callable

import xbmc
import xbmcgui

from script_common import _ADDON, _ADDON_PATH, _log
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
    schedule_skin_reload,
    summarize_outcomes,
)


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

def _present_skin_result(
    title: str,
    outcomes: list,
    scope: InstallScope,
    *,
    needs_reload: bool,
    log_label: str,
) -> None:
    """Show install/restore outcome, then reload the skin after the modal is dismissed."""
    summary_body = _build_skin_summary_body(outcomes, scope)
    _log(f"{log_label}:\n{summary_body}")
    ok_count, fail_count, skipped_count, skin_count = summarize_outcomes(outcomes)
    toast = _ADDON.getLocalizedString(32180) % (
        ok_count,
        fail_count,
        skipped_count,
        skin_count,
    )
    icon = xbmcgui.NOTIFICATION_ERROR if fail_count else xbmcgui.NOTIFICATION_INFO
    try:
        xbmcgui.Dialog().notification(title, toast, icon, 8000)
    except (RuntimeError, TypeError, AttributeError):
        pass
    xbmcgui.Dialog().ok(title, summary_body)
    if needs_reload:
        schedule_skin_reload()

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
        return execute_install_plan(
            plans,
            _ADDON_PATH,
            progress=progress,
            schedule_reload=False,
        )

    try:
        outcomes, needs_reload = _execute_skin_plan_with_progress(
            work_count, title, _run,
        )
    except Exception as exc:
        _log(f"Skin snippet install failed: {exc}", xbmc.LOGERROR)
        xbmcgui.Dialog().ok(title, str(exc))
        return
    _present_skin_result(
        title,
        outcomes,
        scope,
        needs_reload=needs_reload,
        log_label="Skin install result",
    )

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
        return execute_restore_plan(
            plans,
            progress=progress,
            schedule_reload=False,
        )

    try:
        outcomes, needs_reload = _execute_skin_plan_with_progress(
            work_count, title, _run,
        )
    except Exception as exc:
        _log(f"Skin snippet restore failed: {exc}", xbmc.LOGERROR)
        xbmcgui.Dialog().ok(title, str(exc))
        return
    _present_skin_result(
        title,
        outcomes,
        scope,
        needs_reload=needs_reload,
        log_label="Skin restore result",
    )

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


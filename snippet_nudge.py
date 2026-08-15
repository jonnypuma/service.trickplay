"""First-run / stale skin-snippet prompts and update toasts."""

from __future__ import annotations

import xbmc
import xbmcaddon
import xbmcgui

from addon_health import AddonHealth, collect_addon_health

_ADDON = xbmcaddon.Addon("service.trickplay")

SNIPPET_ATTENTION_STATES = frozenset({"missing", "stale"})


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def snippet_needs_attention(health: AddonHealth | None = None) -> bool:
    report = health or collect_addon_health()
    return report.snippet_state in SNIPPET_ATTENTION_STATES


def notify_stale_or_missing_snippet(health: AddonHealth | None = None) -> bool:
    """Toast on service start when the active skin overlay is missing or stale."""
    report = health or collect_addon_health()
    if not snippet_needs_attention(report):
        return False
    title = _ADDON.getLocalizedString(32158)
    message = _ADDON.getLocalizedString(32239)
    try:
        xbmcgui.Dialog().notification(
            title,
            message,
            xbmcgui.NOTIFICATION_INFO,
            8000,
        )
    except (RuntimeError, TypeError, AttributeError):
        pass
    _log(
        f"Skin snippet {report.snippet_state} for {report.skin_id} "
        f"(overlay rev {report.overlay_revision})"
    )
    return True


def prompt_message_for_snippet(health: AddonHealth) -> str:
    if health.snippet_state == "stale":
        return _ADDON.getLocalizedString(32241)
    return _ADDON.getLocalizedString(32240)


def prompt_snippet_install(*, from_playback: bool = False, inline: bool = False) -> bool:
    """Yes/No install prompt. Returns True when the user accepted."""
    health = collect_addon_health()
    if not snippet_needs_attention(health):
        return False
    title = _ADDON.getLocalizedString(32158)
    message = prompt_message_for_snippet(health)
    accepted = bool(
        xbmcgui.Dialog().yesno(
            title,
            message,
            yeslabel=_ADDON.getLocalizedString(32164),
            nolabel=_ADDON.getLocalizedString(32100),
        )
    )
    if not accepted:
        _log(
            "Skin snippet install declined"
            + (" (playback prompt)" if from_playback else "")
        )
        return False
    _log(
        "Skin snippet install accepted"
        + (" (playback prompt)" if from_playback else "")
    )
    if inline:
        from skin_snippet_installer import InstallScope
        from script_skin import run_install_skin_dialog

        run_install_skin_dialog(InstallScope.CURRENT)
    else:
        xbmc.executebuiltin("RunScript(service.trickplay,install_skin,current)")
    return True

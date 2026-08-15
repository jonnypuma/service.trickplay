"""Shared helpers for RunScript dialogs."""

from __future__ import annotations

import sys

import xbmc
import xbmcaddon
import xbmcgui

_ADDON = xbmcaddon.Addon("service.trickplay")
_ADDON_PATH = _ADDON.getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

from vfs_paths import vfs_is_dir  # noqa: E402


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator.batch] {message}", level)


def _dialog_yesno(
    heading: str,
    message: str,
    *,
    yeslabel: str = "",
    nolabel: str = "",
    default_yes: bool = False,
) -> bool:
    """
    Show a yes/no dialog.

    Kodi defaults focus to No (``DLG_YESNO_NO_BTN``). For confirm-to-proceed
    actions set ``default_yes=True`` so Enter/OK starts the job. Explicit
    yes/nolabel avoid ambiguous default button text.
    """
    kwargs: dict[str, object] = {"heading": heading, "message": message}
    if yeslabel:
        kwargs["yeslabel"] = yeslabel
    if nolabel:
        kwargs["nolabel"] = nolabel
    if default_yes:
        yes_btn = getattr(xbmcgui, "DLG_YESNO_YES_BTN", None)
        if yes_btn is not None:
            kwargs["defaultbutton"] = yes_btn
    try:
        return bool(xbmcgui.Dialog().yesno(**kwargs))
    except TypeError:
        kwargs.pop("defaultbutton", None)
        return bool(xbmcgui.Dialog().yesno(**kwargs))


def _yield_ui(ms: int = 350) -> None:
    """Let a closed progress/dialog finish dismissing before the next modal."""
    xbmc.sleep(max(0, int(ms)))


def _is_valid_library_root(path: str) -> bool:
    if not path or path.startswith(("special://", "plugin://", "http://", "https://")):
        return False
    try:
        return vfs_is_dir(path)
    except (OSError, RuntimeError, ValueError):
        return False

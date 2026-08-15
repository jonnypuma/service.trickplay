"""Shared lightweight Kodi API stubs for tests running outside Kodi."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def install_kodi_stubs() -> tuple[object, object, object, object]:
    xbmc = sys.modules.get("xbmc")
    if xbmc is None:
        xbmc = MagicMock()
        sys.modules["xbmc"] = xbmc
    xbmc.LOGINFO = getattr(xbmc, "LOGINFO", 0)
    xbmc.LOGWARNING = getattr(xbmc, "LOGWARNING", 1)
    xbmc.LOGERROR = getattr(xbmc, "LOGERROR", 2)
    if not callable(getattr(xbmc, "executebuiltin", None)):
        xbmc.executebuiltin = MagicMock()

    xbmcvfs = sys.modules.get("xbmcvfs")
    if xbmcvfs is None:
        xbmcvfs = types.ModuleType("xbmcvfs")
        sys.modules["xbmcvfs"] = xbmcvfs
    if isinstance(xbmcvfs, types.ModuleType):
        class _StubFile:
            def __init__(self, *args, **kwargs):
                self.data = b""

            def readBytes(self):
                return self.data

            def read(self, size=-1):
                return self.data if size == -1 else self.data[:size]

            def write(self, data):
                self.data = data
                return len(data)

            def close(self):
                return None

        xbmcvfs.translatePath = lambda path: path
        xbmcvfs.exists = getattr(xbmcvfs, "exists", lambda path: False)
        xbmcvfs.listdir = getattr(xbmcvfs, "listdir", lambda path: ([], []))
        xbmcvfs.mkdirs = getattr(xbmcvfs, "mkdirs", lambda path: True)
        xbmcvfs.delete = getattr(xbmcvfs, "delete", lambda path: True)
        xbmcvfs.copy = getattr(xbmcvfs, "copy", lambda source, target: True)
        xbmcvfs.File = getattr(xbmcvfs, "File", _StubFile)
    else:
        xbmcvfs.translatePath = lambda path: path

    addon_stub = MagicMock(
        return_value=MagicMock(
            getAddonInfo=MagicMock(return_value=""),
            getLocalizedString=MagicMock(return_value=""),
            getSettingInt=MagicMock(return_value=0),
            getSettingString=MagicMock(return_value=""),
            getSettingBool=MagicMock(return_value=False),
        )
    )
    xbmcaddon = sys.modules.get("xbmcaddon")
    addon_ok = False
    try:
        addon_ok = xbmcaddon is not None and callable(getattr(xbmcaddon, "Addon", None))
    except AttributeError:
        addon_ok = False
    if not addon_ok:
        module = types.ModuleType("xbmcaddon")
        module.Addon = addon_stub
        sys.modules["xbmcaddon"] = module
        xbmcaddon = module
    xbmcgui = sys.modules.get("xbmcgui")
    if xbmcgui is None:
        xbmcgui = MagicMock()
        sys.modules["xbmcgui"] = xbmcgui
    try:
        dialog_ok = callable(getattr(xbmcgui, "Dialog", None))
    except AttributeError:
        dialog_ok = False
    if not dialog_ok:
        gui = types.ModuleType("xbmcgui")
        gui.Dialog = MagicMock()
        gui.Window = MagicMock()
        gui.NOTIFICATION_INFO = "info"
        gui.NOTIFICATION_ERROR = "error"
        sys.modules["xbmcgui"] = gui
        xbmcgui = gui
    return (
        xbmc,
        sys.modules["xbmcaddon"],
        xbmcvfs,
        sys.modules["xbmcgui"],
    )

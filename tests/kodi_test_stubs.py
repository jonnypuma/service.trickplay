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
        xbmcvfs.translatePath = lambda path: path
        xbmcvfs.exists = getattr(xbmcvfs, "exists", lambda path: False)
        xbmcvfs.listdir = getattr(xbmcvfs, "listdir", lambda path: ([], []))
        xbmcvfs.mkdirs = getattr(xbmcvfs, "mkdirs", lambda path: True)
        xbmcvfs.delete = getattr(xbmcvfs, "delete", lambda path: True)
    else:
        xbmcvfs.translatePath = lambda path: path

    for name in ("xbmcaddon", "xbmcgui"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
    return (
        xbmc,
        sys.modules["xbmcaddon"],
        xbmcvfs,
        sys.modules["xbmcgui"],
    )

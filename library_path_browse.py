"""Folder picker for generator library path (full Kodi file browser)."""

from __future__ import annotations

import os

import xbmcgui
import xbmcvfs


def browse_start_directory(current: str) -> str:
    if current and xbmcvfs.exists(current):
        return current
    for candidate in ("/storage/", "root://", "special://home"):
        if candidate.startswith("/"):
            if os.path.isdir(candidate):
                return candidate
        elif xbmcvfs.exists(candidate):
            return candidate
    return "root://"


def browse_library_folder(heading: str, current: str = "") -> str | None:
    """Open Kodi's full drive/network folder browser (not limited file shares)."""
    dialog = xbmcgui.Dialog()
    start = browse_start_directory(current)
    # Empty shares = local drives + network shares (same roots as File manager).
    browse_single = getattr(dialog, "browseSingle", None)
    if callable(browse_single):
        folder = browse_single(0, heading, "", "", False, False, start)
    else:
        folder = dialog.browse(0, heading, "", "", False, False, start)
    if not folder:
        return None
    return folder

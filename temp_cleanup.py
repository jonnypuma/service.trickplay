"""Remove orphaned generator temp workdirs left after crash or hard kill."""

from __future__ import annotations

import os
import shutil

import xbmc
import xbmcvfs

GENERATOR_TEMP_ROOT = xbmcvfs.translatePath("special://temp/service.trickplay/")
GENERATE_TEMP_ROOT = os.path.join(GENERATOR_TEMP_ROOT, "generate")
DOVI_TEMP_ROOT = os.path.join(GENERATOR_TEMP_ROOT, "dovi")


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _clear_work_root(root: str) -> int:
    """Delete all files and subdirectories under root (not root itself)."""
    local = _local_path(root)
    if not local or not os.path.isdir(local):
        return 0

    removed = 0
    try:
        names = os.listdir(local)
    except OSError:
        return 0

    for name in names:
        if name in (".", ".."):
            continue
        path = os.path.join(local, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.isfile(path):
                os.remove(path)
            else:
                continue
            removed += 1
        except OSError:
            continue
    return removed


def cleanup_orphaned_generator_temp() -> int:
    """
    Clear generator temp trees under special://temp/service.trickplay/.

    Anything present means a prior job did not finish normally (crash, kill, power loss).
    Playback sprite copies live in the parent folder and are not removed here.
    """
    removed = _clear_work_root(GENERATE_TEMP_ROOT) + _clear_work_root(DOVI_TEMP_ROOT)
    if removed:
        _log(
            f"Removed {removed} orphaned generator temp path(s) "
            f"under {GENERATOR_TEMP_ROOT}"
        )
    return removed

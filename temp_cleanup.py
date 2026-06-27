"""Remove orphaned generator temp workdirs left after crash or hard kill."""

from __future__ import annotations

import os
import shutil
import time

import xbmc
import xbmcvfs

GENERATOR_TEMP_ROOT = xbmcvfs.translatePath("special://temp/service.trickplay/")
GENERATE_TEMP_ROOT = os.path.join(GENERATOR_TEMP_ROOT, "generate")
DOVI_TEMP_ROOT = os.path.join(GENERATOR_TEMP_ROOT, "dovi")
GENERATION_LOCK_PATH = os.path.join(GENERATE_TEMP_ROOT, ".generation.lock")
ORPHAN_MIN_AGE_SEC = 3600
LOCK_MAX_AGE_SEC = 7200


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _generation_lock_fresh() -> bool:
    local = _local_path(GENERATION_LOCK_PATH)
    if not local or not os.path.isfile(local):
        return False
    try:
        age = time.time() - os.path.getmtime(local)
    except OSError:
        return False
    return age < LOCK_MAX_AGE_SEC


def mark_generation_active() -> None:
    """Mark an in-progress generation job so startup cleanup does not delete its temp dir."""
    local_root = _local_path(GENERATE_TEMP_ROOT)
    if not local_root:
        return
    os.makedirs(local_root, exist_ok=True)
    local_lock = _local_path(GENERATION_LOCK_PATH)
    try:
        with open(local_lock, "w", encoding="utf-8") as handle:
            handle.write(str(time.time()))
    except OSError:
        pass


def clear_generation_active() -> None:
    local_lock = _local_path(GENERATION_LOCK_PATH)
    if not local_lock:
        return
    try:
        os.remove(local_lock)
    except OSError:
        pass


def _entry_age_sec(path: str) -> float:
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return 0.0


def _clear_work_root(root: str) -> int:
    """Delete stale files and subdirectories under root (not root itself)."""
    local = _local_path(root)
    if not local or not os.path.isdir(local):
        return 0

    if root == GENERATE_TEMP_ROOT and _generation_lock_fresh():
        _log("Skipping generator temp cleanup — generation lock is active")
        return 0

    removed = 0
    try:
        names = os.listdir(local)
    except OSError:
        return 0

    for name in names:
        if name in (".", ".."):
            continue
        if name == ".generation.lock":
            continue
        path = os.path.join(local, name)
        if _entry_age_sec(path) < ORPHAN_MIN_AGE_SEC:
            continue
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
    Clear stale generator temp trees under special://temp/service.trickplay/.

    Skips entries newer than ORPHAN_MIN_AGE_SEC and skips generate/ entirely
    while a generation lock file is fresh (active batch or idle job).
    """
    removed = _clear_work_root(GENERATE_TEMP_ROOT) + _clear_work_root(DOVI_TEMP_ROOT)
    if removed:
        _log(
            f"Removed {removed} orphaned generator temp path(s) "
            f"older than {ORPHAN_MIN_AGE_SEC}s under {GENERATOR_TEMP_ROOT}"
        )
    return removed

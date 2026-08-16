"""Persistent batch-generation resume state."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import xbmcvfs
from vfs_paths import local_path

_STATE_PATH = "special://profile/addon_data/service.trickplay/generation-state.json"


def _local_state_path() -> str:
    return xbmcvfs.translatePath(_STATE_PATH)


def _profile(root: str, settings: Any) -> dict[str, object]:
    return {
        "root": root,
        "tile_width": settings.tile_width,
        "grid": settings.grid,
        "interval_ms": settings.interval_ms,
        "extract_mode": settings.extract_mode,
        "overwrite": bool(getattr(settings, "overwrite_existing", False)),
    }


def _media_identity(path: str) -> dict[str, int] | None:
    """Return cheap replacement-detection metadata for a media file."""
    try:
        stat = os.stat(local_path(path))
    except (OSError, TypeError, ValueError):
        return None
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def load_completed(root: str, settings: Any) -> set[str]:
    """Return media paths completed for this exact folder/profile."""
    path = _local_state_path()
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError, TypeError):
        return set()
    if state.get("profile") != _profile(root, settings):
        return set()
    completed = state.get("completed")
    if not isinstance(completed, list):
        return set()
    identities = state.get("identities")
    result: set[str] = set()
    for item in completed:
        media_path = str(item)
        stored = identities.get(media_path) if isinstance(identities, dict) else None
        current = _media_identity(media_path)
        # Legacy entries without identity remain usable; new entries with an
        # identity are rejected if the media was replaced or changed.
        if stored is not None and current != stored:
            continue
        result.add(media_path)
    return result


def begin_or_update(root: str, settings: Any, completed: set[str]) -> None:
    """Persist the current profile and completed paths atomically."""
    path = _local_state_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = {
        "version": 2,
        "profile": _profile(root, settings),
        "completed": sorted(completed),
        "identities": {
            media_path: _media_identity(media_path)
            for media_path in completed
        },
    }
    fd, temporary = tempfile.mkstemp(prefix=".generation-state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def mark_completed(root: str, settings: Any, media_path: str) -> None:
    """Record one successful generation for this folder/profile."""
    if not media_path:
        return
    completed = load_completed(root, settings)
    completed.add(media_path)
    begin_or_update(root, settings, completed)


def clear() -> None:
    try:
        os.remove(_local_state_path())
    except OSError:
        pass

"""Persistent batch-generation resume state."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import xbmcvfs

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
    }


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
    return {str(item) for item in completed} if isinstance(completed, list) else set()


def begin_or_update(root: str, settings: Any, completed: set[str]) -> None:
    """Persist the current profile and completed paths atomically."""
    path = _local_state_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = {
        "version": 1,
        "profile": _profile(root, settings),
        "completed": sorted(completed),
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


def clear() -> None:
    try:
        os.remove(_local_state_path())
    except OSError:
        pass

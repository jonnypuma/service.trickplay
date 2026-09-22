"""Persistent batch-generation resume state."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Iterable

import xbmcvfs
from vfs_paths import is_remote_vfs_url, local_path

_STATE_PATH = "special://profile/addon_data/service.trickplay/generation-state.json"
_STATE_VERSION = 3


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


def _path_is_missing(path: str) -> bool:
    """True only when a local file is known gone. Remote URLs are kept."""
    if not path or is_remote_vfs_url(path):
        return False
    try:
        local = local_path(path)
    except (OSError, TypeError, ValueError):
        return False
    if not local or is_remote_vfs_url(local) or "://" in str(local):
        return False
    try:
        return not os.path.isfile(local)
    except OSError:
        return False


def _load_state() -> dict[str, Any]:
    path = _local_state_path()
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    return state if isinstance(state, dict) else {}


def _dedupe_keep_order(paths: Iterable[str], *, skip: set[str] | None = None) -> list[str]:
    seen: set[str] = set(skip or ())
    ordered: list[str] = []
    for item in paths:
        media_path = str(item)
        if not media_path or media_path in seen:
            continue
        seen.add(media_path)
        ordered.append(media_path)
    return ordered


def load_completed(root: str, settings: Any) -> set[str]:
    """Return media paths completed for this exact folder/profile."""
    state = _load_state()
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


def load_remaining(
    root: str,
    settings: Any,
    *,
    completed: set[str] | None = None,
    check_exists: bool = False,
) -> list[str]:
    """Return unfinished media paths for this folder/profile, scan order preserved."""
    state = _load_state()
    if state.get("profile") != _profile(root, settings):
        return []
    remaining = state.get("remaining")
    if not isinstance(remaining, list):
        return []
    done = completed if completed is not None else load_completed(root, settings)
    kept: list[str] = []
    seen: set[str] = set()
    for item in remaining:
        media_path = str(item)
        if not media_path or media_path in done or media_path in seen:
            continue
        if check_exists and _path_is_missing(media_path):
            continue
        seen.add(media_path)
        kept.append(media_path)
    return kept


def begin_or_update(
    root: str,
    settings: Any,
    completed: set[str],
    remaining: list[str] | None = None,
) -> None:
    """Persist the current profile, completed paths, and remaining queue atomically."""
    path = _local_state_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    completed_set = {str(item) for item in completed if item}
    if remaining is None:
        remaining_list = load_remaining(
            root, settings, completed=completed_set, check_exists=False
        )
    else:
        remaining_list = _dedupe_keep_order(remaining, skip=completed_set)
    payload = {
        "version": _STATE_VERSION,
        "profile": _profile(root, settings),
        "completed": sorted(completed_set),
        "remaining": remaining_list,
        "identities": {
            media_path: _media_identity(media_path)
            for media_path in completed_set
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
    """Record one successful generation and drop it from the remaining queue."""
    if not media_path:
        return
    completed = load_completed(root, settings)
    completed.add(media_path)
    remaining = load_remaining(
        root, settings, completed=completed, check_exists=False
    )
    begin_or_update(root, settings, completed, remaining)


def clear() -> None:
    try:
        os.remove(_local_state_path())
    except OSError:
        pass

"""Recently-added library videos for idle generation filtering."""

from __future__ import annotations

import json
import os
import time

import xbmc

from vfs_paths import local_path, normalize_vfs_path, path_variants

_log_prefix = "[service.trickplay.generator.recent]"
_MAX_LIBRARY_ITEMS = 500


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"{_log_prefix} {message}", level)


def path_match_key(path: str) -> str:
    cleaned = (path or "").strip().replace("\\", "/")
    if "://" in cleaned:
        cleaned = normalize_vfs_path(cleaned)
    return os.path.normcase(os.path.normpath(cleaned))


def expand_path_keys(path: str) -> set[str]:
    keys: set[str] = set()
    for variant in path_variants(path) or (path,):
        key = path_match_key(variant)
        if key:
            keys.add(key)
    return keys


def filter_paths_by_recent(candidates: list[str], recent_paths: list[str]) -> list[str]:
    """Keep candidates that match any recently-added library file."""
    recent_keys: set[str] = set()
    for path in recent_paths:
        recent_keys.update(expand_path_keys(path))
    if not recent_keys:
        return []
    matched: list[str] = []
    for path in candidates:
        if expand_path_keys(path) & recent_keys:
            matched.append(path)
    return matched


def is_recent_by_mtime(path: str, days: int) -> bool:
    cutoff = time.time() - max(int(days), 1) * 86400
    try:
        return os.path.getmtime(local_path(path)) >= cutoff
    except (OSError, TypeError, ValueError):
        return False


def _jsonrpc(method: str, params: dict) -> dict | None:
    command = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(command)))
    except (RuntimeError, TypeError, ValueError):
        return None
    if not isinstance(response, dict) or "error" in response:
        return None
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def _dateadded_filter(days: int) -> dict[str, str]:
    return {
        "field": "dateadded",
        "operator": "inthelast",
        "value": str(max(int(days), 1)),
    }


def _collect_files(result: dict, key: str) -> list[str]:
    items = result.get(key)
    if not isinstance(items, list):
        return []
    paths: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file")
        if isinstance(file_path, str) and file_path:
            paths.append(file_path)
    return paths


def list_recent_library_files(days: int) -> list[str] | None:
    """Return library file paths added in the last ``days``, or None if RPC failed."""
    date_filter = _dateadded_filter(days)
    limits = {"start": 0, "end": _MAX_LIBRARY_ITEMS}
    movies = _jsonrpc(
        "VideoLibrary.GetMovies",
        {"properties": ["file"], "filter": date_filter, "limits": limits},
    )
    episodes = _jsonrpc(
        "VideoLibrary.GetEpisodes",
        {"properties": ["file"], "filter": date_filter, "limits": limits},
    )
    musicvideos = _jsonrpc(
        "VideoLibrary.GetMusicVideos",
        {"properties": ["file"], "filter": date_filter, "limits": limits},
    )
    if movies is None and episodes is None and musicvideos is None:
        return None

    paths: list[str] = []
    if movies:
        paths.extend(_collect_files(movies, "movies"))
    if episodes:
        paths.extend(_collect_files(episodes, "episodes"))
    if musicvideos:
        paths.extend(_collect_files(musicvideos, "musicvideos"))
    return paths


def apply_recent_idle_filter(
    candidates: list[str],
    days: int,
    *,
    recent_paths: list[str] | None = None,
) -> list[str]:
    """Filter idle candidates to recently added library items (mtime fallback)."""
    library_paths = (
        recent_paths if recent_paths is not None else list_recent_library_files(days)
    )
    if library_paths is not None:
        matched = filter_paths_by_recent(candidates, library_paths)
        _log(
            f"Idle recent filter: {len(matched)}/{len(candidates)} "
            f"matched {len(library_paths)} library item(s) from the last {days} day(s)"
        )
        return matched

    kept = [path for path in candidates if is_recent_by_mtime(path, days)]
    _log(
        f"Idle recent filter: library RPC unavailable; "
        f"{len(kept)}/{len(candidates)} kept by mtime ({days} day(s))"
    )
    return kept

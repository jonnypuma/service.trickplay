"""Batch trickplay generation for videos added during a library update."""

from __future__ import annotations

import json
import os
import threading

import xbmc

from generator_settings import GeneratorSettings, read_generator_settings
from generator_worker import GeneratorWorker
from trickplay_generator import has_generated_sidecar
from trickplay_resolver import resolve_media_path

_log_prefix = "[service.trickplay.generator.library]"


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"{_log_prefix} {message}", level)


def _parse_notification_data(data: str) -> dict | None:
    if not data:
        return None
    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _jsonrpc(method: str, params: dict) -> dict:
    command = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(command)))
    except (RuntimeError, TypeError, ValueError):
        return {}
    if "error" in response:
        return {}
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def _resolve_video_path(item_type: str, item_id: int) -> str | None:
    if item_type == "movie":
        details = _jsonrpc(
            "VideoLibrary.GetMovieDetails",
            {"movieid": item_id, "properties": ["file"]},
        ).get("moviedetails", {})
        file_path = details.get("file")
    elif item_type == "episode":
        details = _jsonrpc(
            "VideoLibrary.GetEpisodeDetails",
            {"episodeid": item_id, "properties": ["file"]},
        ).get("episodedetails", {})
        file_path = details.get("file")
    elif item_type == "musicvideo":
        details = _jsonrpc(
            "VideoLibrary.GetMusicVideoDetails",
            {"musicvideoid": item_id, "properties": ["file"]},
        ).get("musicvideodetails", {})
        file_path = details.get("file")
    else:
        return None

    if not file_path or not isinstance(file_path, str):
        return None
    return resolve_media_path(file_path) or file_path


def _path_under_library_root(path: str, library_root: str) -> bool:
    if not library_root:
        return True
    try:
        media = os.path.normcase(os.path.normpath(path))
        root = os.path.normcase(os.path.normpath(library_root.rstrip("/\\")))
    except (TypeError, ValueError):
        return False
    if media == root:
        return True
    prefix = root if root.endswith(os.sep) else root + os.sep
    return media.startswith(prefix)


def _filter_generation_candidates(
    paths: list[str],
    settings: GeneratorSettings,
) -> list[str]:
    candidates: list[str] = []
    skipped_existing = 0
    skipped_outside_root = 0

    for path in paths:
        resolved = resolve_media_path(path) or path
        if settings.library_path and not _path_under_library_root(
            resolved, settings.library_path
        ):
            skipped_outside_root += 1
            continue
        if (
            not settings.overwrite_existing
            and has_generated_sidecar(
                resolved,
                settings.tile_width,
                settings.grid,
                settings.interval_ms,
                debug=settings.debug,
            )
        ):
            skipped_existing += 1
            continue
        candidates.append(resolved)

    if settings.debug and (skipped_existing or skipped_outside_root):
        _log(
            f"Library update batch: {len(candidates)} to generate, "
            f"{skipped_existing} skipped (existing sidecar), "
            f"{skipped_outside_root} skipped (outside library folder)"
        )
    return candidates


class LibraryUpdateBatch:
    """Collect newly added library paths and enqueue them after a scan finishes."""

    def __init__(self, worker: GeneratorWorker) -> None:
        self._worker = worker
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._scan_in_progress = False
        self._awaiting_playback_idle = False

    def on_notification(self, sender: str, method: str, data: str) -> None:
        settings = read_generator_settings()
        if not settings.enabled or not settings.on_library_update:
            return

        if method == "VideoLibrary.OnScanStarted":
            with self._lock:
                self._pending.clear()
                self._scan_in_progress = True
                self._awaiting_playback_idle = False
            if settings.debug:
                _log("Library scan started; clearing pending trickplay batch")
            return

        if method == "VideoLibrary.OnScanFinished":
            with self._lock:
                self._scan_in_progress = False
            if settings.debug:
                _log("Library scan finished; flushing pending trickplay batch")
            self._try_flush(playback_idle=None)
            return

        if method == "VideoLibrary.OnAdd":
            payload = _parse_notification_data(data)
            if payload is None:
                return
            item_type = str(payload.get("type", ""))
            item_id = payload.get("id")
            if not item_type or item_id is None:
                return
            self._record_added_item(settings, item_type, int(item_id))
            return

        if method == "VideoLibrary.OnUpdate":
            payload = _parse_notification_data(data)
            if payload is None or not payload.get("added"):
                return
            item_type = str(payload.get("type", ""))
            item_id = payload.get("id")
            if not item_type or item_id is None:
                return
            self._record_added_item(settings, item_type, int(item_id))

    def maybe_flush(self, playback_idle: bool) -> None:
        self._try_flush(playback_idle=playback_idle)

    def _record_added_item(
        self,
        settings: GeneratorSettings,
        item_type: str,
        item_id: int,
    ) -> None:
        path = _resolve_video_path(item_type, item_id)
        if not path:
            if settings.debug:
                _log(
                    f"Could not resolve file path for {item_type} id={item_id}",
                    xbmc.LOGWARNING,
                )
            return

        with self._lock:
            self._pending.add(path)
            scan_active = self._scan_in_progress

        if settings.debug:
            _log(f"Queued library add for trickplay: {path}")

        if not scan_active:
            self._try_flush(playback_idle=None)

    def _try_flush(self, playback_idle: bool | None) -> None:
        settings = read_generator_settings()
        if not settings.enabled or not settings.on_library_update:
            return

        if settings.on_library_update_while_idle:
            if playback_idle is False:
                self._awaiting_playback_idle = True
                return
            if playback_idle is None:
                try:
                    if xbmc.Player().isPlayingVideo():
                        self._awaiting_playback_idle = True
                        return
                except RuntimeError:
                    pass

        with self._lock:
            if not self._pending:
                self._awaiting_playback_idle = False
                return
            paths = list(self._pending)
            self._pending.clear()
            self._awaiting_playback_idle = False

        candidates = _filter_generation_candidates(paths, settings)
        if not candidates:
            if settings.debug:
                _log("Library update batch: no new videos need trickplay generation")
            return

        added = self._worker.enqueue_paths(candidates)
        if added:
            _log(
                f"Library update: enqueued {added} new video(s) for trickplay generation"
            )

"""Background queue for trickplay generation while idle."""

from __future__ import annotations

import threading
import time
from collections import deque

import xbmc

from generator_settings import GeneratorSettings, read_generator_settings
from trickplay_generator import (
    collect_generation_candidates,
    generate_trickplay_for_media,
)

_log_prefix = "[service.trickplay.generator]"


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"{_log_prefix} {message}", level)


class GeneratorWorker:
    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = False
        self._paused = False
        self._current_path = ""
        self._last_idle_scan_at = 0.0
        self._idle_scan_cursor = 0
        self._idle_candidates: list[str] = []

    @property
    def busy(self) -> bool:
        with self._lock:
            if self._current_path:
                return True
            return self._thread is not None and self._thread.is_alive()

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def pause_for_playback(self) -> None:
        with self._lock:
            self._paused = True

    def resume_after_playback(self) -> None:
        with self._lock:
            self._paused = False
            has_queue = bool(self._queue)
        if has_queue:
            self._ensure_worker()

    def cancel(self) -> None:
        with self._lock:
            self._stop = True
            self._queue.clear()
            self._queued.clear()
            self._idle_candidates.clear()
            self._idle_scan_cursor = 0

    def enqueue_paths(self, paths: list[str]) -> int:
        added = 0
        with self._lock:
            for path in paths:
                if not path or path in self._queued:
                    continue
                self._queue.append(path)
                self._queued.add(path)
                added += 1
            self._stop = False
        if added:
            _log(f"Queued {added} file(s) for trickplay generation")
            self._ensure_worker()
        return added

    def maybe_idle_tick(self, playback_idle: bool) -> None:
        settings = read_generator_settings()
        if not settings.enabled or not settings.while_idle or not playback_idle:
            return
        if self.busy or self.queue_size > 0:
            return

        now = time.monotonic()
        if now - self._last_idle_scan_at < 30.0 and self._idle_candidates:
            pass
        else:
            self._refresh_idle_candidates(settings)
            self._last_idle_scan_at = now

        if not self._idle_candidates:
            return

        if self._idle_scan_cursor >= len(self._idle_candidates):
            self._idle_scan_cursor = 0

        path = self._idle_candidates[self._idle_scan_cursor]
        self._idle_scan_cursor += 1
        self.enqueue_paths([path])

    def _refresh_idle_candidates(self, settings: GeneratorSettings) -> None:
        root = settings.library_path
        if not root:
            self._idle_candidates = []
            return
        self._idle_candidates = collect_generation_candidates(root, settings).candidates
        self._idle_scan_cursor = 0
        if settings.debug and self._idle_candidates:
            _log(
                f"Idle scan found {len(self._idle_candidates)} candidate(s) under {root}"
            )

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = False
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="trickplay-generator",
            )
            self._thread.start()

    def _next_job(self) -> str | None:
        with self._lock:
            if self._stop or self._paused or not self._queue:
                return None
            path = self._queue.popleft()
            self._queued.discard(path)
            self._current_path = path
            return path

    def _finish_job(self) -> None:
        with self._lock:
            self._current_path = ""

    def _should_cancel(self) -> bool:
        with self._lock:
            return self._stop

    def _run(self) -> None:
        while True:
            path = self._next_job()
            if path is None:
                return

            settings = read_generator_settings()
            if not settings.enabled:
                _log("Generator disabled; stopping worker")
                with self._lock:
                    self._queue.clear()
                    self._queued.clear()
                self._finish_job()
                return

            try:
                generate_trickplay_for_media(
                    path,
                    settings,
                    should_cancel=self._should_cancel,
                )
            except Exception as exc:  # pragma: no cover
                _log(f"Unexpected generator error for {path}: {exc}", xbmc.LOGERROR)

            self._finish_job()

            with self._lock:
                if self._stop or not self._queue:
                    return

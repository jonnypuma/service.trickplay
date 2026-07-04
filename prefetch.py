"""Background prefetch of trickplay thumb crops around the active preview."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

import xbmc

from prefetch_settings import PrefetchSettings, read_prefetch_settings
from thumb_cropper import (
    ThumbCacheKey,
    get_cached_thumb_path,
    get_cropped_thumb_path,
    temp_tile_copy,
    thumb_cache_key,
)
from trickplay_resolver import (
    TrickplayLookup,
    TrickplayResolution,
    lookup_by_index,
    lookup_thumbnail,
)

MAX_TILE_ENQUEUE = 20
IDLE_TILE_MAX_ENQUEUE = 100


def _cache_key(lookup: TrickplayLookup) -> ThumbCacheKey:
    return thumb_cache_key(
        lookup.tile_path,
        lookup.col,
        lookup.row,
        lookup.thumb_width,
        lookup.thumb_height,
    )


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _max_thumb_index(resolution: TrickplayResolution) -> int:
    if resolution.thumbnail_count > 0:
        return resolution.thumbnail_count - 1
    return 0


def _tile_index_bounds(
    resolution: TrickplayResolution, thumb_index: int
) -> tuple[int, int]:
    thumbs_per_tile = resolution.thumbs_per_tile
    tile_start = (thumb_index // thumbs_per_tile) * thumbs_per_tile
    tile_end = tile_start + thumbs_per_tile
    if resolution.thumbnail_count > 0:
        tile_end = min(tile_end, resolution.thumbnail_count)
    return tile_start, tile_end


def _neighbor_indices(
    center_index: int,
    max_index: int,
    scrub_direction: int,
    settings: PrefetchSettings,
) -> list[int]:
    """Return thumb indices in prefetch priority order."""
    ordered: list[int] = []
    seen: set[int] = set()

    def add(index: int) -> None:
        if index < 0 or index > max_index or index in seen:
            return
        seen.add(index)
        ordered.append(index)

    radius_ahead = settings.radius_ahead
    radius_behind = settings.radius_behind
    radius_symmetric = settings.radius_symmetric

    if scrub_direction > 0:
        for distance in range(1, radius_ahead + 1):
            add(center_index + distance)
        for distance in range(1, radius_behind + 1):
            add(center_index - distance)
    elif scrub_direction < 0:
        for distance in range(1, radius_ahead + 1):
            add(center_index - distance)
        for distance in range(1, radius_behind + 1):
            add(center_index + distance)
    else:
        for distance in range(1, radius_symmetric + 1):
            add(center_index + distance)
            add(center_index - distance)

    return ordered


def _symmetric_window_indices(
    center_index: int,
    max_index: int,
    radius: int,
) -> list[int]:
    """Thumb indices within ±radius of center, center first."""
    ordered: list[int] = []
    seen: set[int] = set()

    def add(index: int) -> None:
        if index < 0 or index > max_index or index in seen:
            return
        seen.add(index)
        ordered.append(index)

    add(center_index)
    for distance in range(1, max(radius, 1) + 1):
        add(center_index + distance)
        add(center_index - distance)
    return ordered


def _follow_warm_indices(
    center_index: int,
    last_index: int,
    max_index: int,
    radius: int,
) -> list[int]:
    """Indices newly entering the ±radius window when the playhead moves."""
    if last_index < 0:
        return _symmetric_window_indices(center_index, max_index, radius)
    if center_index == last_index:
        return []

    indices = [center_index]
    old_lo = max(0, last_index - radius)
    old_hi = min(max_index, last_index + radius)
    new_lo = max(0, center_index - radius)
    new_hi = min(max_index, center_index + radius)
    for index in range(new_lo, new_hi + 1):
        if index < old_lo or index > old_hi:
            indices.append(index)
    return indices


@dataclass(frozen=True)
class _PrefetchItem:
    lookup: TrickplayLookup


class ThumbPrefetch:
    """Low-priority crop queue; foreground preview crops are unchanged."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: deque[_PrefetchItem] = deque()
        self._queued_keys: set[tuple[str, int, int, int, int]] = set()
        self._worker: threading.Thread | None = None
        self._generation = 0
        self._debug = False
        self._prepared_tile: str | None = None
        self._idle_tiles_done: set[str] = set()
        self._max_queue = 48
        self._last_playback_follow_index = -1
        self._last_playback_follow_at = 0.0

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            self._queue.clear()
            self._queued_keys.clear()
            self._prepared_tile = None
            self._idle_tiles_done.clear()
            self._last_playback_follow_index = -1
            self._last_playback_follow_at = 0.0

    def schedule_playhead_follow(
        self,
        resolution: TrickplayResolution,
        play_seconds: int,
        interval_ms: int,
        settings: PrefetchSettings | None = None,
        debug: bool = False,
        *,
        high_priority: bool = False,
        force: bool = False,
    ) -> None:
        """Keep ±radius thumb crops warm around the moving playhead during playback."""
        settings = settings or read_prefetch_settings()
        if not settings.enabled or not settings.during_playback or not resolution.is_usable:
            return
        lookup = lookup_thumbnail(resolution, play_seconds, interval_ms)
        if lookup is None:
            return

        center_index = lookup.thumb_index
        previous_index = self._last_playback_follow_index
        now = time.monotonic()
        retry_same_index = (
            not force
            and center_index == previous_index
            and now - self._last_playback_follow_at >= 5.0
        )
        if (
            not force
            and center_index == previous_index
            and not retry_same_index
        ):
            return

        warm_previous = -1 if force or previous_index < 0 or retry_same_index else previous_index
        self._last_playback_follow_index = center_index
        self._last_playback_follow_at = now
        self._warm_around_lookup(
            resolution,
            lookup,
            interval_ms,
            settings,
            debug=debug,
            high_priority=high_priority,
            whole_tile=False,
            previous_index=warm_previous,
        )

    def _warm_around_lookup(
        self,
        resolution: TrickplayResolution,
        center: TrickplayLookup,
        interval_ms: int,
        settings: PrefetchSettings,
        *,
        debug: bool,
        high_priority: bool,
        whole_tile: bool,
        previous_index: int,
    ) -> None:
        self._debug = debug
        self._max_queue = settings.max_queue
        max_index = _max_thumb_index(resolution)
        radius = settings.radius

        if previous_index < 0:
            indices = _symmetric_window_indices(
                center.thumb_index, max_index, radius
            )
        else:
            indices = _follow_warm_indices(
                center.thumb_index,
                previous_index,
                max_index,
                radius,
            )

        if debug and indices:
            _log(
                f"Prefetch playhead follow index {center.thumb_index} "
                f"±{radius} ({len(indices)} cell(s))"
            )

        self._schedule_indices(
            resolution,
            interval_ms,
            indices,
            high_priority=high_priority,
        )
        if whole_tile:
            self._schedule_tile_cells(
                resolution,
                center,
                interval_ms,
                skip_indices=set(indices),
                max_enqueue=MAX_TILE_ENQUEUE,
            )

    def schedule_playhead_warm(
        self,
        resolution: TrickplayResolution,
        center: TrickplayLookup,
        interval_ms: int,
        settings: PrefetchSettings | None = None,
        debug: bool = False,
    ) -> None:
        """Warm cache around the current playhead when trickplay loads."""
        settings = settings or read_prefetch_settings()
        if not settings.enabled or not settings.on_start or not resolution.is_usable:
            return

        self._last_playback_follow_index = center.thumb_index
        self._last_playback_follow_at = time.monotonic()
        self._warm_around_lookup(
            resolution,
            center,
            interval_ms,
            settings,
            debug=debug,
            high_priority=True,
            whole_tile=settings.whole_tile,
            previous_index=-1,
        )

    def schedule_neighbors(
        self,
        resolution: TrickplayResolution,
        center: TrickplayLookup,
        interval_ms: int,
        scrub_direction: int = 0,
        settings: PrefetchSettings | None = None,
        debug: bool = False,
    ) -> None:
        settings = settings or read_prefetch_settings()
        if not settings.enabled or not resolution.is_usable:
            return

        self._debug = debug
        self._max_queue = settings.max_queue
        indices = _neighbor_indices(
            center.thumb_index,
            _max_thumb_index(resolution),
            scrub_direction,
            settings,
        )
        self._schedule_indices(
            resolution,
            interval_ms,
            indices,
            high_priority=True,
        )
        if settings.whole_tile:
            self._schedule_tile_cells(
                resolution,
                center,
                interval_ms,
                skip_indices={center.thumb_index, *indices},
                max_enqueue=MAX_TILE_ENQUEUE,
            )

    def schedule_idle_tile(
        self,
        resolution: TrickplayResolution,
        center: TrickplayLookup,
        interval_ms: int,
        settings: PrefetchSettings | None = None,
        debug: bool = False,
    ) -> None:
        """Prefetch remaining cells in the current sprite tile while OSD is idle."""
        settings = settings or read_prefetch_settings()
        if not settings.enabled or not settings.idle_tile or not resolution.is_usable:
            return

        tile_path = center.tile_path
        if tile_path in self._idle_tiles_done:
            return

        self._debug = debug
        self._max_queue = settings.max_queue
        if debug:
            _log(f"Prefetch idle tile {tile_path}")

        enqueued = self._schedule_tile_cells(
            resolution,
            center,
            interval_ms,
            skip_indices=set(),
            max_enqueue=IDLE_TILE_MAX_ENQUEUE,
        )
        if enqueued > 0:
            self._idle_tiles_done.add(tile_path)

    def _schedule_indices(
        self,
        resolution: TrickplayResolution,
        interval_ms: int,
        indices: list[int],
        high_priority: bool,
    ) -> None:
        for index in indices:
            lookup = lookup_by_index(resolution, index, interval_ms)
            if lookup is None:
                continue
            self._enqueue(lookup, high_priority=high_priority)

    def _schedule_tile_cells(
        self,
        resolution: TrickplayResolution,
        center: TrickplayLookup,
        interval_ms: int,
        skip_indices: set[int],
        max_enqueue: int,
    ) -> int:
        tile_start, tile_end = _tile_index_bounds(resolution, center.thumb_index)
        enqueued = 0
        for index in range(tile_start, tile_end):
            if index in skip_indices:
                continue
            lookup = lookup_by_index(resolution, index, interval_ms)
            if lookup is None:
                continue
            if self._enqueue(lookup, high_priority=False):
                enqueued += 1
            if enqueued >= max_enqueue:
                break
        return enqueued

    def _enqueue(
        self, lookup: TrickplayLookup, *, high_priority: bool
    ) -> bool:
        if get_cached_thumb_path(
            lookup.tile_path,
            lookup.col,
            lookup.row,
            lookup.thumb_width,
            lookup.thumb_height,
        ):
            return False

        key = _cache_key(lookup)
        with self._lock:
            if key in self._queued_keys:
                return False
            if len(self._queue) >= self._max_queue:
                if not high_priority:
                    return False
                dropped = self._queue.pop()
                self._queued_keys.discard(_cache_key(dropped.lookup))
            self._queue.append(_PrefetchItem(lookup))
            self._queued_keys.add(key)

        self._ensure_worker()
        return True

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            generation = self._generation
            self._worker = threading.Thread(
                target=self._run,
                args=(generation,),
                daemon=True,
                name="trickplay-prefetch",
            )
            self._worker.start()

    def _run(self, generation: int) -> None:
        prepared_tile: str | None = None
        while True:
            with self._lock:
                if generation != self._generation:
                    return
                if not self._queue:
                    self._worker = None
                    self._prepared_tile = None
                    return
                item = self._queue.popleft()
                self._queued_keys.discard(_cache_key(item.lookup))
                lookup = item.lookup

            if get_cached_thumb_path(
                lookup.tile_path,
                lookup.col,
                lookup.row,
                lookup.thumb_width,
                lookup.thumb_height,
            ):
                continue

            if lookup.tile_path != prepared_tile:
                temp_tile_copy(lookup.tile_path)
                prepared_tile = lookup.tile_path
                with self._lock:
                    if generation == self._generation:
                        self._prepared_tile = prepared_tile

            if self._debug:
                _log(
                    f"Prefetch crop cell ({lookup.col},{lookup.row}) "
                    f"index {lookup.thumb_index}"
                )

            get_cropped_thumb_path(
                lookup.tile_path,
                lookup.col,
                lookup.row,
                lookup.thumb_width,
                lookup.thumb_height,
                debug=self._debug,
            )

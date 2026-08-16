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
    crop_tile_cells_batch,
    get_cached_thumb_path,
    get_cropped_thumb_path,
    temp_tile_copy,
    thumb_cache_key,
    warm_decoded_tile,
)
from trickplay_resolver import (
    TrickplayLookup,
    TrickplayResolution,
    lookup_by_index,
    lookup_thumbnail,
)

MAX_TILE_ENQUEUE = 20
# Cap idle whole-tile floods so NFS sprite copies do not starve scrub crops.
IDLE_TILE_MAX_ENQUEUE = 24
# Copy+decode the next sprite once playhead prefetch is this far through the
# current tile, so the first cell of 1.jpg is already in RAM.
UPCOMING_TILE_WARM_FRACTION = 0.80


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
    interval_ms: int,
) -> list[int]:
    """Return thumb indices in prefetch priority order."""
    ordered: list[int] = []
    seen: set[int] = set()

    def add(index: int) -> None:
        if index < 0 or index > max_index or index in seen:
            return
        seen.add(index)
        ordered.append(index)

    radius_ahead = settings.radius_ahead(interval_ms)
    radius_behind = settings.radius_behind(interval_ms)
    radius_symmetric = settings.radius_symmetric(interval_ms)

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


def tile_progress_fraction(
    resolution: TrickplayResolution, thumb_index: int
) -> float:
    """How far through the current sprite tile (0.0–1.0) by cell index."""
    tile_start, tile_end = _tile_index_bounds(resolution, thumb_index)
    length = tile_end - tile_start
    if length <= 0:
        return 0.0
    return (thumb_index - tile_start) / length


def adjacent_tile_path(
    resolution: TrickplayResolution,
    thumb_index: int,
    direction: int,
) -> str | None:
    """Sprite path one tile ahead (direction>=0) or behind (direction<0)."""
    if not resolution.tile_paths:
        return None
    thumbs_per_tile = resolution.thumbs_per_tile
    if thumbs_per_tile <= 0:
        return None
    tile_index = thumb_index // thumbs_per_tile
    next_index = tile_index + 1 if direction >= 0 else tile_index - 1
    if 0 <= next_index < len(resolution.tile_paths):
        return resolution.tile_paths[next_index]
    return None


def should_warm_upcoming_tile(
    resolution: TrickplayResolution,
    thumb_index: int,
    direction: int = 1,
    fraction: float = UPCOMING_TILE_WARM_FRACTION,
) -> bool:
    """True when the playhead is in the last (or first, reverse) 20% of a tile."""
    progress = tile_progress_fraction(resolution, thumb_index)
    if direction < 0:
        return progress <= (1.0 - fraction)
    return progress >= fraction


def upcoming_tile_to_warm(
    resolution: TrickplayResolution,
    thumb_index: int,
    direction: int = 1,
    fraction: float = UPCOMING_TILE_WARM_FRACTION,
) -> str | None:
    if not should_warm_upcoming_tile(
        resolution, thumb_index, direction=direction, fraction=fraction
    ):
        return None
    warm_direction = -1 if direction < 0 else 1
    return adjacent_tile_path(resolution, thumb_index, warm_direction)


@dataclass(frozen=True)
class _PrefetchItem:
    lookup: TrickplayLookup
    high_priority: bool = False


class ThumbPrefetch:
    """Background crop queue; scrub/foreground work preempts idle tile floods."""

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
        # Separate low-contention queue: copy sprite JPGs to local temp ASAP.
        self._copy_lock = threading.Lock()
        self._copy_queue: deque[str] = deque()
        self._copy_queued: set[str] = set()
        self._copy_done: set[str] = set()
        self._copy_worker: threading.Thread | None = None
        self._copy_generation = 0
        self._warmed_tiles: set[str] = set()

    def cancel(self, *, clear_copies: bool = True) -> None:
        with self._lock:
            self._generation += 1
            self._queue.clear()
            self._queued_keys.clear()
            self._prepared_tile = None
            self._idle_tiles_done.clear()
            self._last_playback_follow_index = -1
            self._last_playback_follow_at = 0.0
            if clear_copies:
                self._warmed_tiles.clear()
        if clear_copies:
            with self._copy_lock:
                self._copy_generation += 1
                self._copy_queue.clear()
                self._copy_queued.clear()
                self._copy_done.clear()

    def yield_for_scrub(self, preferred_tile: str | None = None) -> None:
        """Drop queued work that would contend with a scrub crop.

        Keeps high-priority items for ``preferred_tile`` (if set) so neighbor
        warm can continue; clears everything else so NFS bandwidth is free for
        the foreground crop worker.
        """
        with self._lock:
            if not self._queue:
                return
            kept: deque[_PrefetchItem] = deque()
            keys: set[tuple[str, int, int, int, int]] = set()
            for item in self._queue:
                if (
                    preferred_tile
                    and item.high_priority
                    and item.lookup.tile_path == preferred_tile
                ):
                    kept.append(item)
                    keys.add(_cache_key(item.lookup))
            dropped = len(self._queue) - len(kept)
            self._queue = kept
            self._queued_keys = keys
            if dropped and self._debug:
                _log(
                    f"Prefetch yield for scrub"
                    f"{f' tile={preferred_tile}' if preferred_tile else ''}"
                    f" dropped {dropped} queued cell(s)"
                )
        if preferred_tile:
            self.prioritize_tile_copy(preferred_tile)

    def schedule_all_tile_copies(
        self,
        tile_paths: tuple[str, ...] | list[str],
        *,
        prioritize: tuple[str, ...] | list[str] = (),
        debug: bool = False,
    ) -> None:
        """Copy every sprite JPG to local temp in the background (priority first)."""
        self._debug = debug
        ordered: list[str] = []
        seen: set[str] = set()
        for path in [*prioritize, *tile_paths]:
            if not path or path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        if not ordered:
            return

        with self._copy_lock:
            new_queue: deque[str] = deque()
            queued: set[str] = set()
            for path in ordered:
                if path in self._copy_done:
                    continue
                new_queue.append(path)
                queued.add(path)
            self._copy_queue = new_queue
            self._copy_queued = queued

        if debug:
            _log(
                f"Scheduled local copies for {len(ordered)} sprite tile(s) "
                f"(priority {len([p for p in prioritize if p])})"
            )
        self._ensure_copy_worker()

    def prioritize_tile_copy(self, tile_path: str) -> None:
        """Move a sprite tile to the front of the local-copy queue."""
        if not tile_path:
            return
        with self._copy_lock:
            if tile_path in self._copy_done:
                return
            if tile_path in self._copy_queued:
                try:
                    self._copy_queue.remove(tile_path)
                except ValueError:
                    pass
            else:
                self._copy_queued.add(tile_path)
            self._copy_queue.appendleft(tile_path)
        self._ensure_copy_worker()

    def _ensure_copy_worker(self) -> None:
        with self._copy_lock:
            if self._copy_worker is not None and self._copy_worker.is_alive():
                return
            generation = self._copy_generation
            self._copy_worker = threading.Thread(
                target=self._run_tile_copies,
                args=(generation,),
                daemon=True,
                name="trickplay-tile-copy",
            )
            self._copy_worker.start()

    def _run_tile_copies(self, generation: int) -> None:
        while True:
            with self._copy_lock:
                if generation != self._copy_generation:
                    return
                if not self._copy_queue:
                    self._copy_worker = None
                    return
                tile_path = self._copy_queue.popleft()
                self._copy_queued.discard(tile_path)

            if self._debug:
                _log(f"Prefetch local tile copy {os.path.basename(tile_path)}")
            local = temp_tile_copy(tile_path)
            with self._copy_lock:
                if generation != self._copy_generation:
                    return
                if local:
                    self._copy_done.add(tile_path)

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
        """Keep ±playback_warm_indices crops warm around the playhead during playback."""
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
        # Cap during-playback follow so a large scrub window does not flood the queue.
        self._warm_around_lookup(
            resolution,
            lookup,
            interval_ms,
            settings,
            debug=debug,
            high_priority=high_priority,
            whole_tile=False,
            previous_index=warm_previous,
            radius=settings.playback_warm_indices(interval_ms),
        )
        direction = 1
        if previous_index >= 0 and center_index < previous_index:
            direction = -1
        self.maybe_warm_upcoming_tile(
            resolution, lookup, direction=direction, debug=debug
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
        radius: int | None = None,
    ) -> None:
        self._debug = debug
        self._max_queue = settings.max_queue
        max_index = _max_thumb_index(resolution)
        if radius is None:
            radius = settings.radius_indices(interval_ms)

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
        self.maybe_warm_upcoming_tile(
            resolution, center, direction=1, debug=debug
        )

    def maybe_warm_upcoming_tile(
        self,
        resolution: TrickplayResolution,
        lookup: TrickplayLookup,
        *,
        direction: int = 1,
        debug: bool = False,
    ) -> str | None:
        """Copy and decode the next sprite when the playhead is in the last 20%."""
        tile_path = upcoming_tile_to_warm(
            resolution, lookup.thumb_index, direction=direction
        )
        if not tile_path:
            return None
        return self.schedule_tile_warm(tile_path, debug=debug)

    def schedule_tile_warm(self, tile_path: str, debug: bool = False) -> str | None:
        """Copy a sprite locally and decode it into RAM once per playback."""
        if not tile_path:
            return None
        with self._lock:
            if tile_path in self._warmed_tiles:
                return None
            self._warmed_tiles.add(tile_path)
        self._debug = debug or self._debug
        if self._debug:
            _log(f"Warm upcoming sprite {os.path.basename(tile_path)}")
        self.prioritize_tile_copy(tile_path)
        threading.Thread(
            target=self._decode_tile_warm,
            args=(tile_path,),
            daemon=True,
            name="trickplay-tile-warm",
        ).start()
        return tile_path

    def _decode_tile_warm(self, tile_path: str) -> None:
        try:
            ok = warm_decoded_tile(tile_path)
            if self._debug:
                _log(
                    f"Decoded sprite warm {os.path.basename(tile_path)} ok={ok}"
                )
        except (OSError, RuntimeError, ValueError) as exc:
            _log(
                f"Upcoming tile decode failed for {tile_path}: {exc}",
                xbmc.LOGWARNING,
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
            interval_ms,
        )
        self._schedule_indices(
            resolution,
            interval_ms,
            indices,
            high_priority=True,
        )
        self.maybe_warm_upcoming_tile(
            resolution, center, direction=scrub_direction, debug=debug
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
        # High-priority uses appendleft; enqueue in reverse so the first
        # index stays at the front of the queue.
        ordered = reversed(indices) if high_priority else indices
        for index in ordered:
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
                if not high_priority:
                    return False
                # Promote an already-queued low-priority cell to the front.
                for existing in self._queue:
                    if _cache_key(existing.lookup) == key:
                        self._queue.remove(existing)
                        self._queue.appendleft(
                            _PrefetchItem(lookup, high_priority=True)
                        )
                        return True
                return False
            if len(self._queue) >= self._max_queue:
                if not high_priority:
                    return False
                dropped = self._queue.pop()
                self._queued_keys.discard(_cache_key(dropped.lookup))
            item = _PrefetchItem(lookup, high_priority=high_priority)
            if high_priority:
                self._queue.appendleft(item)
            else:
                self._queue.append(item)
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
                batch = [item.lookup]
                tile_path = item.lookup.tile_path
                # Drain more queued cells from the same sprite so one decode
                # pass can warm many thumbs.
                remaining: deque[_PrefetchItem] = deque()
                while self._queue:
                    nxt = self._queue.popleft()
                    key = _cache_key(nxt.lookup)
                    self._queued_keys.discard(key)
                    if nxt.lookup.tile_path == tile_path:
                        batch.append(nxt.lookup)
                    else:
                        remaining.append(nxt)
                        self._queued_keys.add(key)
                if remaining:
                    self._queue.extendleft(reversed(remaining))

            cells: list[tuple[int, int, int, int]] = []
            seen_cells: set[tuple[int, int, int, int]] = set()
            for lookup in batch:
                if get_cached_thumb_path(
                    lookup.tile_path,
                    lookup.col,
                    lookup.row,
                    lookup.thumb_width,
                    lookup.thumb_height,
                ):
                    continue
                cell = (
                    lookup.col,
                    lookup.row,
                    lookup.thumb_width,
                    lookup.thumb_height,
                )
                if cell in seen_cells:
                    continue
                seen_cells.add(cell)
                cells.append(cell)

            if not cells:
                continue

            if tile_path != prepared_tile:
                temp_tile_copy(tile_path)
                prepared_tile = tile_path
                with self._lock:
                    if generation == self._generation:
                        self._prepared_tile = prepared_tile

            if self._debug:
                _log(
                    f"Prefetch batch crop {len(cells)} cell(s) from "
                    f"{os.path.basename(tile_path)}"
                )

            if len(cells) == 1:
                col, row, thumb_w, thumb_h = cells[0]
                get_cropped_thumb_path(
                    tile_path,
                    col,
                    row,
                    thumb_w,
                    thumb_h,
                    debug=self._debug,
                )
            else:
                crop_tile_cells_batch(tile_path, cells, debug=self._debug)

"""Resolve Jellyfin trickplay folders and map seek times to sprite tiles."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import xbmc
import xbmcvfs

from thumb_cropper import probe_image_dimensions

# Jellyfin stores tiles under:
# {basename}.trickplay/{width} - {tileW}x{tileH}/{index}.jpg
# {basename}.trickplay/{width} - {tileW}x{tileH} - {intervalMs}/{index}.jpg
DEFAULT_FOLDER_INTERVAL_MS = 10000
_RESOLUTION_DIR_RE = re.compile(
    r"^(?P<width>\d+)\s*-\s*(?P<tile_w>\d+)x(?P<tile_h>\d+)"
    r"(?:\s*-\s*(?P<interval_ms>\d+))?$",
    re.IGNORECASE,
)
_TILE_FILE_RE = re.compile(r"^\d+\.jpg$", re.IGNORECASE)
_TILE_GRID_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")
_MAX_TILE_GRID = 50
_MIN_TILE_GRID = 1


@dataclass(frozen=True)
class TrickplayResolution:
    width: int
    tile_width: int
    tile_height: int
    tiles_dir: str
    tile_paths: tuple[str, ...]
    interval_ms: int = DEFAULT_FOLDER_INTERVAL_MS
    thumb_width: int = 0
    thumb_height: int = 0
    tile_image_width: int = 0
    tile_image_height: int = 0
    thumbnail_count: int = 0

    @property
    def thumbs_per_tile(self) -> int:
        return self.tile_width * self.tile_height

    @property
    def is_usable(self) -> bool:
        return bool(self.tile_paths and self.thumb_width > 0 and self.thumb_height > 0)


@dataclass(frozen=True)
class TrickplayLookup:
    tile_path: str
    col: int
    row: int
    thumb_width: int
    thumb_height: int
    thumb_index: int
    target_second: int


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _log_debug(debug: bool, message: str) -> None:
    if debug:
        _log(message, xbmc.LOGINFO)


def _vfs_join(base: str, *parts: str) -> str:
    path = base
    for part in parts:
        path = os.path.join(path, part)
    return path


def resolve_media_path(playing_file: str) -> str | None:
    """Return a local filesystem path for the currently playing item."""
    if not playing_file:
        return None

    path = playing_file
    if path.lower().startswith(("plugin://", "http://", "https://")):
        return None

    if path.lower().endswith(".strm"):
        try:
            with xbmcvfs.File(path, "r") as handle:
                target = handle.read().strip()
        except OSError:
            return None
        if not target or target.lower().startswith(("plugin://", "http://", "https://")):
            return None
        path = target

    if path.startswith("special://"):
        path = xbmcvfs.translatePath(path)

    if not xbmcvfs.exists(path):
        return None

    return path


def trickplay_root_for_media(media_path: str) -> str:
    base, _ext = os.path.splitext(media_path)
    return f"{base}.trickplay"


def format_resolution_dir_name(
    width: int,
    tile_width: int,
    tile_height: int,
    interval_ms: int = DEFAULT_FOLDER_INTERVAL_MS,
) -> str:
    return f"{width} - {tile_width}x{tile_height} - {interval_ms}"


def parse_resolution_dir_name(name: str) -> tuple[int, int, int, int] | None:
    match = _RESOLUTION_DIR_RE.match(name)
    if not match:
        return None
    interval_raw = match.group("interval_ms")
    interval_ms = int(interval_raw) if interval_raw else DEFAULT_FOLDER_INTERVAL_MS
    return (
        int(match.group("width")),
        int(match.group("tile_w")),
        int(match.group("tile_h")),
        max(interval_ms, 1),
    )


def _list_resolution_dirs(trickplay_root: str, debug: bool = False) -> list[TrickplayResolution]:
    if not xbmcvfs.exists(trickplay_root):
        return []

    resolutions: list[TrickplayResolution] = []
    try:
        entries = xbmcvfs.listdir(trickplay_root)
    except OSError:
        return []

    subdirs = entries[0] if isinstance(entries, (list, tuple)) and len(entries) >= 1 else []
    if not subdirs and isinstance(entries, (list, tuple)) and len(entries) == 2:
        subdirs = entries[0]

    for name in subdirs:
        parsed = parse_resolution_dir_name(name)
        if parsed is None:
            continue

        width, tile_w, tile_h, interval_ms = parsed
        tiles_dir = _vfs_join(trickplay_root, name)
        tile_paths = _list_tile_paths(tiles_dir, debug=debug)
        if not tile_paths:
            _log_debug(debug, f"No tile JPGs found in {tiles_dir}")
            continue

        resolutions.append(
            TrickplayResolution(
                width=width,
                tile_width=tile_w,
                tile_height=tile_h,
                tiles_dir=tiles_dir,
                tile_paths=tile_paths,
                interval_ms=interval_ms,
            )
        )

    return resolutions


def _list_tile_paths(tiles_dir: str, debug: bool = False) -> tuple[str, ...]:
    try:
        entries = xbmcvfs.listdir(tiles_dir)
    except OSError:
        return ()

    dirs, files = entries if isinstance(entries, (list, tuple)) and len(entries) == 2 else ([], entries)
    names: list[str] = []
    for name in list(files) + list(dirs):
        if _TILE_FILE_RE.match(name):
            names.append(name)

    def _tile_index(filename: str) -> int:
        return int(os.path.splitext(filename)[0])

    names = sorted(set(names), key=_tile_index)
    paths = tuple(_vfs_join(tiles_dir, name) for name in names)
    _log_debug(debug, f"Found {len(paths)} tile file(s) in {tiles_dir}")
    return paths


def select_resolution(
    trickplay_root: str,
    preferred_width: int,
    preferred_interval_ms: int = DEFAULT_FOLDER_INTERVAL_MS,
    debug: bool = False,
) -> TrickplayResolution | None:
    resolutions = _list_resolution_dirs(trickplay_root, debug=debug)
    if not resolutions:
        _log_debug(debug, f"No trickplay resolutions under {trickplay_root}")
        return None

    exact = [
        res
        for res in resolutions
        if res.width == preferred_width and res.interval_ms == preferred_interval_ms
    ]
    if exact:
        chosen = exact[0]
        _log(
            f"Using preferred resolution {preferred_width}px / {preferred_interval_ms}ms "
            f"at {chosen.tiles_dir} ({len(chosen.tile_paths)} tile file(s))"
        )
        return chosen

    same_width = [res for res in resolutions if res.width == preferred_width]
    if same_width:
        chosen = min(
            same_width,
            key=lambda res: abs(res.interval_ms - preferred_interval_ms),
        )
        _log(
            f"Using resolution {chosen.width}px / {chosen.interval_ms}ms at "
            f"{chosen.tiles_dir} ({len(chosen.tile_paths)} tile file(s)); "
            f"preferred interval {preferred_interval_ms}ms not found"
        )
        return chosen

    chosen = sorted(resolutions, key=lambda res: res.width)[0]
    _log(
        f"Preferred width {preferred_width}px not found; using {chosen.width}px / "
        f"{chosen.interval_ms}ms at {chosen.tiles_dir} "
        f"({len(chosen.tile_paths)} tile file(s))"
    )
    return chosen


def _default_thumb_height(thumb_width: int) -> int:
    return max(int(round(thumb_width * 9 / 16)), 2)


def resolve_tile_grid(
    resolution: TrickplayResolution,
    auto_tile_grid: bool,
    manual_tile_grid: str,
    debug: bool = False,
) -> tuple[int, int]:
    """Return (columns, rows) for splitting each sprite JPG."""
    if auto_tile_grid:
        return resolution.tile_width, resolution.tile_height

    match = _TILE_GRID_RE.match((manual_tile_grid or "").strip())
    if not match:
        _log(
            f"Invalid manual tile grid {manual_tile_grid!r}; "
            f"using folder grid {resolution.tile_width}x{resolution.tile_height}",
            xbmc.LOGWARNING,
        )
        return resolution.tile_width, resolution.tile_height

    cols = max(min(int(match.group(1)), _MAX_TILE_GRID), _MIN_TILE_GRID)
    rows = max(min(int(match.group(2)), _MAX_TILE_GRID), _MIN_TILE_GRID)
    _log_debug(debug, f"Manual tile grid: {cols}x{rows}")
    return cols, rows


def parse_manual_tile_grid(manual_tile_grid: str) -> tuple[int, int] | None:
    """Parse a grid string like 10x10. Returns None if invalid."""
    match = _TILE_GRID_RE.match((manual_tile_grid or "").strip())
    if not match:
        return None
    cols = max(min(int(match.group(1)), _MAX_TILE_GRID), _MIN_TILE_GRID)
    rows = max(min(int(match.group(2)), _MAX_TILE_GRID), _MIN_TILE_GRID)
    return cols, rows


def _estimate_thumbnail_count(
    tile_count: int,
    thumbs_per_tile: int,
    duration_seconds: int,
    interval_ms: int,
) -> int:
    if tile_count <= 0:
        return 0

    from_files = max((tile_count - 1) * thumbs_per_tile + 1, 1)
    if duration_seconds > 0 and interval_ms > 0:
        interval_sec = max(interval_ms / 1000.0, 0.001)
        from_duration = int(duration_seconds / interval_sec) + 1
        return min(from_files, from_duration)
    return from_files


def enrich_resolution(
    resolution: TrickplayResolution,
    duration_seconds: int,
    interval_ms: int,
    auto_tile_grid: bool = True,
    manual_tile_grid: str = "10x10",
    debug: bool = False,
) -> TrickplayResolution:
    """Fill in thumb dimensions and total thumbnail count."""
    if not resolution.tile_paths:
        return resolution

    grid_cols, grid_rows = resolve_tile_grid(
        resolution,
        auto_tile_grid,
        manual_tile_grid,
        debug=debug,
    )

    tile_w, tile_h = probe_image_dimensions(resolution.tile_paths[0], debug=debug)
    if tile_w <= 0 or tile_h <= 0:
        thumb_width = resolution.width
        thumb_height = _default_thumb_height(thumb_width)
        _log(
            f"Could not read tile dimensions from {resolution.tile_paths[0]}; "
            f"using fallback {thumb_width}x{thumb_height}",
            xbmc.LOGWARNING,
        )
    else:
        thumb_width = max(tile_w // grid_cols, 1)
        thumb_height = max(tile_h // grid_rows, 1)
        grid_source = (
            f"{grid_cols}x{grid_rows} from folder"
            if auto_tile_grid
            else f"{grid_cols}x{grid_rows} manual"
        )
        _log(
            f"Sprite {os.path.basename(resolution.tile_paths[0])} is {tile_w}x{tile_h} "
            f"-> cell {thumb_width}x{thumb_height} ({grid_source})"
        )

    thumbs_per_tile = grid_cols * grid_rows
    full_tiles = max(len(resolution.tile_paths) - 1, 0)
    last_tile_thumbs = _count_thumbs_in_last_tile(
        resolution,
        thumb_width,
        thumb_height,
        full_tiles,
        grid_cols,
        grid_rows,
        debug=debug,
    )
    from_files = full_tiles * thumbs_per_tile + last_tile_thumbs
    if duration_seconds > 0 and interval_ms > 0:
        interval_sec = max(interval_ms / 1000.0, 0.001)
        from_duration = int(duration_seconds / interval_sec) + 1
        thumbnail_count = min(from_files, from_duration)
    else:
        thumbnail_count = from_files

    if thumbnail_count <= 0:
        thumbnail_count = _estimate_thumbnail_count(
            len(resolution.tile_paths),
            thumbs_per_tile,
            duration_seconds,
            interval_ms,
        )

    enriched = TrickplayResolution(
        width=resolution.width,
        tile_width=grid_cols,
        tile_height=grid_rows,
        tiles_dir=resolution.tiles_dir,
        tile_paths=resolution.tile_paths,
        interval_ms=resolution.interval_ms,
        thumb_width=thumb_width,
        thumb_height=thumb_height,
        tile_image_width=tile_w if tile_w > 0 else thumb_width * grid_cols,
        tile_image_height=tile_h if tile_h > 0 else thumb_height * grid_rows,
        thumbnail_count=thumbnail_count,
    )
    _log_debug(
        debug,
        f"Enriched trickplay: grid={grid_cols}x{grid_rows}, "
        f"interval={resolution.interval_ms}ms, "
        f"thumb={thumb_width}x{thumb_height}, "
        f"count={thumbnail_count}, tiles={len(resolution.tile_paths)}",
    )
    return enriched


def _count_thumbs_in_last_tile(
    resolution: TrickplayResolution,
    thumb_width: int,
    thumb_height: int,
    full_tiles: int,
    grid_cols: int,
    grid_rows: int,
    debug: bool = False,
) -> int:
    if not resolution.tile_paths:
        return 0

    last_path = resolution.tile_paths[-1]
    tile_w, tile_h = probe_image_dimensions(last_path, debug=debug)
    thumbs_per_tile = grid_cols * grid_rows
    if tile_w <= 0 or tile_h <= 0 or thumb_width <= 0 or thumb_height <= 0:
        if full_tiles == 0:
            return 1
        return thumbs_per_tile

    cols = min(max(tile_w // thumb_width, 1), grid_cols)
    rows = min(max(tile_h // thumb_height, 1), grid_rows)
    count = cols * rows
    return max(count, 1)


def lookup_thumbnail(
    resolution: TrickplayResolution,
    target_second: int,
    interval_ms: int,
) -> TrickplayLookup | None:
    if not resolution.is_usable:
        return None

    interval_sec = max(interval_ms / 1000.0, 0.001)
    thumb_index = max(int(target_second / interval_sec), 0)
    if resolution.thumbnail_count > 0:
        thumb_index = min(thumb_index, resolution.thumbnail_count - 1)

    thumbs_per_tile = resolution.thumbs_per_tile
    tile_index = thumb_index // thumbs_per_tile
    position_in_tile = thumb_index % thumbs_per_tile

    if tile_index >= len(resolution.tile_paths):
        tile_index = len(resolution.tile_paths) - 1
        position_in_tile = min(position_in_tile, thumbs_per_tile - 1)

    col = position_in_tile % resolution.tile_width
    row = position_in_tile // resolution.tile_width

    return TrickplayLookup(
        tile_path=resolution.tile_paths[tile_index],
        col=col,
        row=row,
        thumb_width=resolution.thumb_width,
        thumb_height=resolution.thumb_height,
        thumb_index=thumb_index,
        target_second=target_second,
    )


def lookup_by_index(
    resolution: TrickplayResolution,
    thumb_index: int,
    interval_ms: int,
) -> TrickplayLookup | None:
    if not resolution.is_usable or thumb_index < 0:
        return None
    if resolution.thumbnail_count > 0:
        thumb_index = min(thumb_index, resolution.thumbnail_count - 1)
    interval_sec = max(interval_ms / 1000.0, 0.001)
    target_second = int(thumb_index * interval_sec)
    return lookup_thumbnail(resolution, target_second, interval_ms)


def load_trickplay_for_file(
    playing_file: str,
    preferred_width: int,
    interval_ms: int,
    duration_seconds: int,
    auto_tile_grid: bool = True,
    manual_tile_grid: str = "10x10",
    debug: bool = False,
) -> TrickplayResolution | None:
    media_path = resolve_media_path(playing_file)
    if not media_path:
        _log_debug(debug, f"Could not resolve local media path from {playing_file!r}")
        return None

    trickplay_root = trickplay_root_for_media(media_path)
    resolution = select_resolution(
        trickplay_root,
        preferred_width,
        preferred_interval_ms=interval_ms,
        debug=debug,
    )
    if resolution is None:
        return None

    folder_interval_ms = resolution.interval_ms
    return enrich_resolution(
        resolution,
        duration_seconds,
        folder_interval_ms,
        auto_tile_grid=auto_tile_grid,
        manual_tile_grid=manual_tile_grid,
        debug=debug,
    )

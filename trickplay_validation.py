"""Validate and repair Jellyfin trickplay sidecars."""

from __future__ import annotations

import io
import json
import math
import os
from dataclasses import dataclass
from typing import Callable

import xbmcvfs

from grid_settings import grid_tuple
from pillow_installer import ensure_pillow_loaded
from trickplay_generator import (
    GenerationResult,
    generate_trickplay_for_media,
    iter_library_videos,
    probe_video_duration_seconds,
    sidecar_dir_for_grid,
)
from trickplay_resolver import find_matching_sidecar_resolution
from vfs_paths import vfs_join


@dataclass(frozen=True)
class SidecarValidation:
    media_path: str
    sidecar_dir: str
    expected_tiles: int
    present_tiles: int
    missing_tiles: tuple[int, ...] = ()
    corrupt_tiles: tuple[int, ...] = ()
    wrong_dimension_tiles: tuple[int, ...] = ()
    reason: str = ""

    @property
    def valid(self) -> bool:
        return not (
            self.missing_tiles
            or self.corrupt_tiles
            or self.wrong_dimension_tiles
            or self.present_tiles != self.expected_tiles
        )

    @property
    def repair_needed(self) -> bool:
        return not self.valid


@dataclass(frozen=True)
class ValidationReport:
    items: tuple[SidecarValidation, ...]
    cancelled: bool = False

    @property
    def invalid(self) -> tuple[SidecarValidation, ...]:
        return tuple(item for item in self.items if item.repair_needed)


def _read_image_size(path: str) -> tuple[int, int]:
    if not ensure_pillow_loaded():
        raise RuntimeError("Pillow is unavailable")
    from PIL import Image

    local = xbmcvfs.translatePath(path) if path.startswith("special://") else path
    if "://" not in local and os.path.isfile(local):
        with Image.open(local) as image:
            image.verify()
        with Image.open(local) as image:
            return image.size

    handle = xbmcvfs.File(path, "rb")
    try:
        data = handle.readBytes()
    finally:
        handle.close()
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def _tile_paths(directory: str) -> dict[int, str]:
    try:
        entries = xbmcvfs.listdir(directory)
    except (OSError, RuntimeError):
        return {}
    files = entries[1] if isinstance(entries, (list, tuple)) and len(entries) == 2 else entries
    result: dict[int, str] = {}
    for name in files or []:
        text = str(name)
        stem, extension = os.path.splitext(text)
        if extension.lower() != ".jpg" or not stem.isdigit():
            continue
        result[int(stem)] = vfs_join(directory, text)
    return result


def _valid_cache_path(directory: str) -> str | None:
    if "://" in directory:
        return None
    return os.path.join(directory, "valid.json")


def _file_signatures(paths: dict[int, str]) -> dict[str, dict[str, int]]:
    signatures: dict[str, dict[str, int]] = {}
    for index, path in paths.items():
        try:
            stat = os.stat(path)
        except OSError:
            return {}
        signatures[str(index)] = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    return signatures


def _load_valid_cache(
    directory: str,
    *,
    tile_width: int,
    grid: str,
    interval_ms: int,
    duration: int,
    expected_tiles: int,
    paths: dict[int, str],
) -> bool:
    cache_path = _valid_cache_path(directory)
    if not cache_path:
        return False
    try:
        with open(cache_path, encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    return (
        cache.get("version") == 1
        and cache.get("tile_width") == tile_width
        and cache.get("grid") == grid
        and cache.get("interval_ms") == interval_ms
        and cache.get("duration") == duration
        and cache.get("expected_tiles") == expected_tiles
        and cache.get("files") == _file_signatures(paths)
    )


def _write_valid_cache(
    directory: str,
    *,
    tile_width: int,
    grid: str,
    interval_ms: int,
    duration: int,
    expected_tiles: int,
    paths: dict[int, str],
) -> None:
    cache_path = _valid_cache_path(directory)
    signatures = _file_signatures(paths)
    if not cache_path or not signatures:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "tile_width": tile_width,
                    "grid": grid,
                    "interval_ms": interval_ms,
                    "duration": duration,
                    "expected_tiles": expected_tiles,
                    "files": signatures,
                },
                handle,
                indent=2,
            )
            handle.write("\n")
    except OSError:
        return


def validate_sidecar(
    media_path: str,
    *,
    tile_width: int,
    grid: str,
    interval_ms: int,
    debug: bool = False,
) -> SidecarValidation:
    cols, rows = grid_tuple(grid)
    matching = find_matching_sidecar_resolution(
        media_path,
        tile_width,
        grid,
        interval_ms,
        debug=debug,
    )
    sidecar_dir = (
        matching.tiles_dir
        if matching is not None
        else sidecar_dir_for_grid(media_path, tile_width, grid, interval_ms)
    )
    duration = probe_video_duration_seconds(
        media_path,
        debug=debug,
    )
    thumb_count = int(duration / max(interval_ms / 1000.0, 0.001)) + 1
    expected_tiles = max(1, math.ceil(thumb_count / (cols * rows)))
    paths = _tile_paths(sidecar_dir)
    if len(paths) == expected_tiles and _load_valid_cache(
        sidecar_dir,
        tile_width=tile_width,
        grid=grid,
        interval_ms=interval_ms,
        duration=duration,
        expected_tiles=expected_tiles,
        paths=paths,
    ):
        return SidecarValidation(
            media_path=media_path,
            sidecar_dir=sidecar_dir,
            expected_tiles=expected_tiles,
            present_tiles=len(paths),
            reason="validated cache",
        )
    missing = tuple(index for index in range(expected_tiles) if index not in paths)
    corrupt: list[int] = []
    wrong_dimensions: list[int] = []
    expected_width = tile_width * cols
    observed_height = 0
    for index, path in sorted(paths.items()):
        try:
            width, height = _read_image_size(path)
        except (OSError, RuntimeError, ValueError):
            corrupt.append(index)
            continue
        if width != expected_width:
            wrong_dimensions.append(index)
        if observed_height == 0:
            observed_height = height
        elif height != observed_height:
            wrong_dimensions.append(index)

    reasons: list[str] = []
    if missing:
        reasons.append(f"missing tile(s): {','.join(map(str, missing))}")
    if corrupt:
        reasons.append(f"corrupt tile(s): {','.join(map(str, corrupt))}")
    if wrong_dimensions:
        reasons.append(
            f"wrong dimensions tile(s): {','.join(map(str, sorted(set(wrong_dimensions))))}"
        )
    result = SidecarValidation(
        media_path=media_path,
        sidecar_dir=sidecar_dir,
        expected_tiles=expected_tiles,
        present_tiles=len(paths),
        missing_tiles=missing,
        corrupt_tiles=tuple(corrupt),
        wrong_dimension_tiles=tuple(sorted(set(wrong_dimensions))),
        reason="; ".join(reasons),
    )
    if result.valid:
        _write_valid_cache(
            sidecar_dir,
            tile_width=tile_width,
            grid=grid,
            interval_ms=interval_ms,
            duration=duration,
            expected_tiles=expected_tiles,
            paths=paths,
        )
    else:
        cache_path = _valid_cache_path(sidecar_dir)
        if cache_path:
            try:
                os.remove(cache_path)
            except OSError:
                pass
    return result


def validate_library(
    root: str,
    *,
    tile_width: int,
    grid: str,
    interval_ms: int,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> ValidationReport:
    items: list[SidecarValidation] = []
    for media_path in iter_library_videos(root, should_cancel=should_cancel):
        if should_cancel and should_cancel():
            return ValidationReport(tuple(items), cancelled=True)
        items.append(
            validate_sidecar(
                media_path,
                tile_width=tile_width,
                grid=grid,
                interval_ms=interval_ms,
                debug=debug,
            )
        )
    return ValidationReport(tuple(items))


def repair_invalid(
    items: tuple[SidecarValidation, ...],
    settings,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[GenerationResult, ...]:
    from dataclasses import replace

    repair_settings = replace(settings, overwrite_existing=True)
    results: list[GenerationResult] = []
    for item in items:
        if should_cancel and should_cancel():
            break
        results.append(
            generate_trickplay_for_media(
                item.media_path,
                repair_settings,
                should_cancel=should_cancel,
            )
        )
    return tuple(results)

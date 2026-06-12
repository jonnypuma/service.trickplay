"""Crop individual trickplay thumbs from Jellyfin sprite tiles into a local cache."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
import time

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
FFMPEG_TOOLS_ADDON_ID = "tools.ffmpeg-tools"
CACHE_VERSION = "v4"
CACHE_DIR = xbmcvfs.translatePath(
    "special://profile/addon_data/service.trickplay/thumbs/"
)
TEMP_DIR = xbmcvfs.translatePath("special://temp/service.trickplay/")

_FFMPEG_BIN: str | None = None
_FFPROBE_BIN: str | None = None
_FFMPEG_ENV: dict[str, str] | None = None
_PROBE_SIZE_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")

# Debounced cache pruning: avoid full directory scans after every crop.
_PRUNE_CROP_BATCH = 20
_PRUNE_MIN_INTERVAL_SEC = 30.0
_crops_since_prune = 0
_last_prune_at = 0.0
_estimated_cache_bytes = 0
_estimate_valid = False

ThumbCacheKey = tuple[str, int, int, int, int, float, int]

# In-memory cache index + in-flight crop deduplication.
_INFLIGHT_WAIT_SEC = 30.0
_memory_cache_keys: set[ThumbCacheKey] = set()
_inflight_lock = threading.Lock()
_inflight_crops: dict[ThumbCacheKey, threading.Event] = {}

# Shared local temp copies of sprite JPGs (thread-safe, source fingerprinted).
_prepared_temp_tiles: dict[str, tuple[str, float, int]] = {}
_prepared_temp_lock = threading.Lock()
_tile_copy_locks: dict[str, threading.Lock] = {}
_tile_copy_locks_guard = threading.Lock()

# Short-lived tile stat cache to avoid repeated VFS stats during prefetch/scrub.
_tile_fingerprint_cache: dict[str, tuple[float, int, float]] = {}
_TILE_FP_TTL_SEC = 2.0


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _ensure_dir(path: str) -> None:
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)


def _read_file_bytes(path: str, max_bytes: int | None = None) -> bytes:
    try:
        handle = xbmcvfs.File(path, "rb")
    except (OSError, RuntimeError, ValueError):
        return b""

    data = bytearray()
    try:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("latin-1", errors="ignore")
            data.extend(chunk)
            if max_bytes is not None and len(data) >= max_bytes:
                break
    except (OSError, RuntimeError, ValueError):
        return b""
    finally:
        try:
            handle.close()
        except (OSError, RuntimeError, ValueError):
            pass

    if max_bytes is not None and len(data) > max_bytes:
        return bytes(data[:max_bytes])
    return bytes(data)


def _write_file_bytes(path: str, payload: bytes) -> bool:
    try:
        handle = xbmcvfs.File(path, "wb")
        handle.write(payload)
        handle.close()
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _file_size(path: str) -> int:
    try:
        stat_obj = xbmcvfs.Stat(path)
        value = getattr(stat_obj, "st_size", None)
        if callable(value):
            return int(value())
        if value is not None:
            return int(value)
        value = getattr(stat_obj, "size", None)
        if callable(value):
            return int(value())
        if value is not None:
            return int(value)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    return 0


def _has_file_content(path: str) -> bool:
    return xbmcvfs.exists(path) and _file_size(path) > 0


def _touch_cached_file(path: str) -> None:
    local = _local_path(path)
    if not local or not os.path.exists(local):
        return
    try:
        os.utime(local, None)
    except OSError:
        pass


def prune_thumb_cache(max_mb: int) -> int:
    """Drop oldest cached thumbs until total size is under max_mb. 0 = unlimited."""
    if max_mb <= 0:
        return 0

    local_dir = _local_path(CACHE_DIR)
    if not local_dir or not os.path.isdir(local_dir):
        return 0

    entries: list[tuple[float, int, str]] = []
    try:
        names = os.listdir(local_dir)
    except OSError:
        return 0

    for name in names:
        if not name.endswith(".jpg"):
            continue
        path = os.path.join(local_dir, name)
        try:
            stat = os.stat(path)
            entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue

    if not entries:
        return 0

    entries.sort(key=lambda item: item[0])
    total = sum(size for _, size, _ in entries)
    limit = max_mb * 1024 * 1024
    removed = 0
    while entries and total > limit:
        _, size, path = entries.pop(0)
        try:
            os.remove(path)
            total -= size
            removed += 1
        except OSError:
            continue
    if removed:
        _clear_memory_cache_index()
    return removed


def _clear_memory_cache_index() -> None:
    _memory_cache_keys.clear()
    _tile_fingerprint_cache.clear()


def _cache_tile_fingerprint(tile_path: str, mtime: float, size: int) -> None:
    _tile_fingerprint_cache[tile_path] = (mtime, size, time.monotonic())


def _tile_fingerprint(tile_path: str) -> tuple[float, int]:
    now = time.monotonic()
    entry = _tile_fingerprint_cache.get(tile_path)
    if entry is not None:
        mtime, size, cached_at = entry
        if now - cached_at < _TILE_FP_TTL_SEC:
            return mtime, size
    mtime, size = _source_fingerprint(tile_path)
    _cache_tile_fingerprint(tile_path, mtime, size)
    return mtime, size


def thumb_cache_key(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
) -> ThumbCacheKey:
    mtime, size = _tile_fingerprint(tile_path)
    return (tile_path, col, row, thumb_w, thumb_h, mtime, size)


def _mark_thumb_cached(key: ThumbCacheKey, cached_path: str) -> None:
    _memory_cache_keys.add(key)
    note_thumb_cache_write(cached_path)


def _refresh_cache_size_estimate() -> int:
    """Scan cache dir and refresh the in-memory size estimate."""
    global _estimated_cache_bytes, _estimate_valid

    local_dir = _local_path(CACHE_DIR)
    if not local_dir or not os.path.isdir(local_dir):
        _estimated_cache_bytes = 0
        _estimate_valid = True
        return 0

    total = 0
    try:
        names = os.listdir(local_dir)
    except OSError:
        _estimated_cache_bytes = 0
        _estimate_valid = True
        return 0

    for name in names:
        if not name.endswith(".jpg"):
            continue
        path = os.path.join(local_dir, name)
        try:
            total += os.path.getsize(path)
        except OSError:
            continue

    _estimated_cache_bytes = total
    _estimate_valid = True
    return total


def note_thumb_cache_write(path: str) -> None:
    """Record a new cached thumb; used to debounce LRU pruning."""
    global _crops_since_prune, _estimated_cache_bytes, _estimate_valid

    _crops_since_prune += 1
    if not _estimate_valid:
        return
    _estimated_cache_bytes += _file_size(path)


def maybe_prune_thumb_cache(max_mb: int) -> int:
    """Prune only when enough crops elapsed, time passed, or estimate exceeds limit."""
    global _crops_since_prune, _last_prune_at

    if max_mb <= 0 or _crops_since_prune <= 0:
        return 0

    limit = max_mb * 1024 * 1024
    now = time.monotonic()

    if not _estimate_valid:
        _refresh_cache_size_estimate()

    over_limit = _estimated_cache_bytes > limit
    batch_ready = _crops_since_prune >= _PRUNE_CROP_BATCH
    interval_elapsed = now - _last_prune_at >= _PRUNE_MIN_INTERVAL_SEC

    if not over_limit and not batch_ready and not interval_elapsed:
        return 0

    removed = prune_thumb_cache(max_mb)
    _crops_since_prune = 0
    _last_prune_at = now
    _refresh_cache_size_estimate()
    return removed


def cell_crop_rect(
    col: int,
    row: int,
    cell_w: int,
    cell_h: int,
) -> tuple[int, int, int, int]:
    """Return (left, top, width, height) for one cell in a row-major 10x10 grid."""
    return col * cell_w, row * cell_h, cell_w, cell_h


def cache_path_for_thumb(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
) -> str:
    mtime, size = _tile_fingerprint(tile_path)
    digest = hashlib.sha1(
        f"{CACHE_VERSION}|{tile_path}|{col}|{row}|{thumb_w}|{thumb_h}|{mtime}|{size}".encode(
            "utf-8", errors="ignore"
        )
    ).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.jpg")


def _legacy_cache_path_for_thumb(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
) -> str:
    digest = hashlib.sha1(
        f"{CACHE_VERSION}|{tile_path}|{col}|{row}|{thumb_w}|{thumb_h}".encode(
            "utf-8", errors="ignore"
        )
    ).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.jpg")


def _migrate_cache_file(source_path: str, dest_path: str) -> bool:
    if not _has_file_content(source_path):
        return False
    if _has_file_content(dest_path):
        return True
    local_src = _local_path(source_path)
    local_dest = _local_path(dest_path)
    if not local_src or not local_dest:
        return False
    try:
        os.makedirs(os.path.dirname(local_dest), exist_ok=True)
        shutil.copy2(local_src, local_dest)
    except OSError:
        return False
    return _has_file_content(dest_path)


def _source_newer_than_cache(tile_path: str, cache_path: str) -> bool:
    src_mtime, _ = _source_fingerprint(tile_path)
    if src_mtime <= 0:
        return False
    local = _local_path(cache_path)
    if not local:
        return False
    try:
        cache_mtime = os.path.getmtime(local)
    except OSError:
        return False
    return src_mtime > cache_mtime + 1.0


def get_cached_thumb_path(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
) -> str | None:
    if not tile_path or thumb_w <= 0 or thumb_h <= 0:
        return None

    key = thumb_cache_key(tile_path, col, row, thumb_w, thumb_h)
    cached = cache_path_for_thumb(tile_path, col, row, thumb_w, thumb_h)

    if key in _memory_cache_keys:
        if _has_file_content(cached):
            _touch_cached_file(cached)
            return cached
        _memory_cache_keys.discard(key)

    if _has_file_content(cached):
        _memory_cache_keys.add(key)
        _touch_cached_file(cached)
        return cached

    legacy = _legacy_cache_path_for_thumb(tile_path, col, row, thumb_w, thumb_h)
    if _has_file_content(legacy) and not _source_newer_than_cache(tile_path, legacy):
        if _migrate_cache_file(legacy, cached):
            _memory_cache_keys.add(key)
            _touch_cached_file(cached)
            return cached
        _memory_cache_keys.add(key)
        _touch_cached_file(legacy)
        return legacy
    return None


def temp_tile_copy(tile_path: str) -> str | None:
    """Copy a sprite JPG to local temp storage for reliable probing and ffmpeg."""
    if not tile_path:
        return None

    _ensure_dir(TEMP_DIR)
    mtime, size = _source_fingerprint(tile_path)

    cached_local = _prepared_temp_hit(tile_path, mtime, size)
    if cached_local:
        return cached_local

    digest = hashlib.sha1(tile_path.encode("utf-8", errors="ignore")).hexdigest()
    temp_path = os.path.join(TEMP_DIR, f"{digest}.jpg")
    lock = _lock_for_temp_digest(digest)
    with lock:
        cached_local = _prepared_temp_hit(tile_path, mtime, size)
        if cached_local:
            return cached_local

        if _has_file_content(temp_path):
            local = _local_path(temp_path)
            _remember_prepared_temp(tile_path, local, mtime, size)
            return local

        try:
            xbmcvfs.copy(tile_path, temp_path)
            if _has_file_content(temp_path):
                local = _local_path(temp_path)
                _remember_prepared_temp(tile_path, local, mtime, size)
                return local
        except (OSError, RuntimeError, ValueError):
            pass

        tile_bytes = _read_file_bytes(tile_path)
        if tile_bytes and _write_file_bytes(temp_path, tile_bytes):
            local = _local_path(temp_path)
            _remember_prepared_temp(tile_path, local, mtime, size)
            return local

    return None


def _source_fingerprint(tile_path: str) -> tuple[float, int]:
    try:
        stat_obj = xbmcvfs.Stat(tile_path)
        mtime = getattr(stat_obj, "st_mtime", None)
        if callable(mtime):
            mtime = mtime()
        size = getattr(stat_obj, "st_size", None)
        if callable(size):
            size = size()
        if size is None:
            size = getattr(stat_obj, "size", None)
            if callable(size):
                size = size()
        return float(mtime or 0.0), int(size or 0)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0.0, 0


def _fingerprints_match(
    mtime: float,
    size: int,
    cached_mtime: float,
    cached_size: int,
) -> bool:
    if mtime <= 0 and size <= 0:
        return True
    return mtime == cached_mtime and size == cached_size


def _prepared_temp_hit(
    tile_path: str,
    mtime: float,
    size: int,
) -> str | None:
    with _prepared_temp_lock:
        entry = _prepared_temp_tiles.get(tile_path)
        if entry is None:
            return None
        local, cached_mtime, cached_size = entry
        if not _fingerprints_match(mtime, size, cached_mtime, cached_size):
            _prepared_temp_tiles.pop(tile_path, None)
            _tile_fingerprint_cache.pop(tile_path, None)
            return None

    if local and os.path.isfile(local) and os.path.getsize(local) > 0:
        return local

    with _prepared_temp_lock:
        _prepared_temp_tiles.pop(tile_path, None)
    return None


def _remember_prepared_temp(
    tile_path: str,
    local_path: str,
    mtime: float,
    size: int,
) -> None:
    with _prepared_temp_lock:
        _prepared_temp_tiles[tile_path] = (local_path, mtime, size)
    _cache_tile_fingerprint(tile_path, mtime, size)


def _lock_for_temp_digest(digest: str) -> threading.Lock:
    with _tile_copy_locks_guard:
        lock = _tile_copy_locks.get(digest)
        if lock is None:
            lock = threading.Lock()
            _tile_copy_locks[digest] = lock
        return lock


def _read_jpeg_dimensions_from_bytes(data: bytes) -> tuple[int, int]:
    if not data:
        return 0, 0

    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue

        marker = data[index + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = (data[index + 5] << 8) + data[index + 6]
            width = (data[index + 7] << 8) + data[index + 8]
            return width, height

        if marker in (0xD8, 0xD9):
            index += 2
            continue

        if index + 3 >= len(data):
            break
        segment_length = (data[index + 2] << 8) + data[index + 3]
        if segment_length < 2:
            break
        index += 2 + segment_length

    return 0, 0


def _resolve_ffmpeg_tools() -> tuple[str | None, str | None, dict[str, str]]:
    global _FFMPEG_BIN, _FFPROBE_BIN, _FFMPEG_ENV
    if _FFMPEG_BIN is not None:
        return _FFMPEG_BIN, _FFPROBE_BIN, _FFMPEG_ENV or os.environ.copy()

    env = os.environ.copy()
    ffmpeg_candidates: list[str] = []
    ffprobe_candidates: list[str] = []

    try:
        tools_addon = xbmcaddon.Addon(FFMPEG_TOOLS_ADDON_ID)
        addon_path = tools_addon.getAddonInfo("path")
        bin_dir = os.path.join(addon_path, "bin")
        lib_dir = os.path.join(addon_path, "lib")
        for name in ("ffmpeg", "ffmpeg.exe"):
            ffmpeg_candidates.append(os.path.join(bin_dir, name))
        for name in ("ffprobe", "ffprobe.exe"):
            ffprobe_candidates.append(os.path.join(bin_dir, name))
        if xbmcvfs.exists(lib_dir):
            lib_path = _local_path(lib_dir)
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = (
                f"{lib_path}:{existing}" if existing else lib_path
            )
    except RuntimeError:
        pass

    ffmpeg_candidates.extend(
        (
            "ffmpeg",
            "/usr/bin/ffmpeg",
            "/storage/.kodi/addons/tools.ffmpeg-tools/bin/ffmpeg",
        )
    )
    ffprobe_candidates.extend(
        (
            "ffprobe",
            "/usr/bin/ffprobe",
            "/storage/.kodi/addons/tools.ffmpeg-tools/bin/ffprobe",
        )
    )

    for candidate in ffmpeg_candidates:
        local = _local_path(candidate)
        if local and xbmcvfs.exists(local):
            _FFMPEG_BIN = local
            break
        found = shutil.which(candidate)
        if found and xbmcvfs.exists(found):
            _FFMPEG_BIN = _local_path(found)
            break

    for candidate in ffprobe_candidates:
        local = _local_path(candidate)
        if local and xbmcvfs.exists(local):
            _FFPROBE_BIN = local
            break
        found = shutil.which(candidate)
        if found and xbmcvfs.exists(found):
            _FFPROBE_BIN = _local_path(found)
            break

    _FFMPEG_ENV = env
    if _FFMPEG_BIN:
        _log(f"Using ffmpeg at {_FFMPEG_BIN}")
    return _FFMPEG_BIN, _FFPROBE_BIN, env


def _probe_dimensions_with_ffprobe(local_path: str, env: dict[str, str]) -> tuple[int, int]:
    _, ffprobe, _ = _resolve_ffmpeg_tools()
    if not ffprobe:
        return 0, 0

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        local_path,
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, 0

    if completed.returncode != 0:
        return 0, 0

    match = _PROBE_SIZE_RE.search((completed.stdout or "").strip())
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _probe_dimensions_with_ffmpeg(local_path: str, env: dict[str, str]) -> tuple[int, int]:
    ffmpeg, _, _ = _resolve_ffmpeg_tools()
    if not ffmpeg:
        return 0, 0

    cmd = [ffmpeg, "-hide_banner", "-i", local_path]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, 0

    match = _PROBE_SIZE_RE.search(completed.stderr or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def probe_image_dimensions(tile_path: str, debug: bool = False) -> tuple[int, int]:
    """Read sprite JPG width and height, copying to local temp storage if needed."""
    local = temp_tile_copy(tile_path)
    if not local:
        _log(f"Could not copy tile for dimension probe: {tile_path}", xbmc.LOGWARNING)
        return 0, 0

    header = _read_file_bytes(local, max_bytes=65536)
    size = _read_jpeg_dimensions_from_bytes(header)
    if size != (0, 0):
        if debug:
            _log(f"Sprite dimensions {size[0]}x{size[1]} from JPEG header ({local})")
        return size

    _, _, env = _resolve_ffmpeg_tools()
    size = _probe_dimensions_with_ffprobe(local, env)
    if size != (0, 0):
        if debug:
            _log(f"Sprite dimensions {size[0]}x{size[1]} via ffprobe ({local})")
        return size

    size = _probe_dimensions_with_ffmpeg(local, env)
    if size != (0, 0):
        if debug:
            _log(f"Sprite dimensions {size[0]}x{size[1]} via ffmpeg ({local})")
        return size

    _log(f"Could not probe sprite dimensions for {tile_path}", xbmc.LOGWARNING)
    return 0, 0


def _crop_with_ffmpeg(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
    output_path: str,
    debug: bool = False,
) -> bool:
    ffmpeg, _, env = _resolve_ffmpeg_tools()
    if not ffmpeg:
        return False

    source = temp_tile_copy(tile_path)
    if not source:
        _log(f"Could not copy sprite tile locally for ffmpeg: {tile_path}", xbmc.LOGWARNING)
        return False

    output_local = _local_path(output_path)
    _ensure_dir(os.path.dirname(output_local))

    left, top, crop_w, crop_h = cell_crop_rect(col, row, thumb_w, thumb_h)
    if debug:
        _log(
            f"Crop {crop_w}x{crop_h}:{left}:{top} from {os.path.basename(tile_path)} "
            f"cell ({col},{row})"
        )

    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        source,
        "-vf",
        f"crop={crop_w}:{crop_h}:{left}:{top}",
        "-frames:v",
        "1",
        output_local,
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"ffmpeg crop subprocess failed: {exc}", xbmc.LOGWARNING)
        return False

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        _log(f"ffmpeg crop failed ({completed.returncode}): {detail}", xbmc.LOGWARNING)
        return False

    return _has_file_content(output_path)


def _crop_thumb_to_cache(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
    cached: str,
    debug: bool = False,
) -> bool:
    if debug:
        left, top, crop_w, crop_h = cell_crop_rect(col, row, thumb_w, thumb_h)
        _log(
            f"Crop {crop_w}x{crop_h}:{left}:{top} from {os.path.basename(tile_path)} "
            f"cell ({col},{row})"
        )
    return _crop_with_ffmpeg(tile_path, col, row, thumb_w, thumb_h, cached, debug=debug)


def get_cropped_thumb_path(
    tile_path: str,
    col: int,
    row: int,
    thumb_w: int,
    thumb_h: int,
    debug: bool = False,
) -> str | None:
    """Return a cached local JPEG path for one sprite cell, or None if cropping failed."""
    if not tile_path or thumb_w <= 0 or thumb_h <= 0:
        return None

    _ensure_dir(CACHE_DIR)
    cached = get_cached_thumb_path(tile_path, col, row, thumb_w, thumb_h)
    if cached:
        return cached

    key = thumb_cache_key(tile_path, col, row, thumb_w, thumb_h)
    cached = cache_path_for_thumb(tile_path, col, row, thumb_w, thumb_h)

    with _inflight_lock:
        inflight = _inflight_crops.get(key)
        if inflight is not None:
            owner = False
            wait_event = inflight
        else:
            wait_event = threading.Event()
            _inflight_crops[key] = wait_event
            owner = True

    if not owner:
        wait_event.wait(_INFLIGHT_WAIT_SEC)
        return get_cached_thumb_path(tile_path, col, row, thumb_w, thumb_h)

    result: str | None = None
    try:
        if _crop_thumb_to_cache(
            tile_path, col, row, thumb_w, thumb_h, cached, debug=debug
        ):
            _mark_thumb_cached(key, cached)
            try:
                from prefetch_settings import read_prefetch_settings

                maybe_prune_thumb_cache(read_prefetch_settings().cache_max_mb)
            except ImportError:  # pragma: no cover
                pass
            result = cached
        else:
            ffmpeg, _, _ = _resolve_ffmpeg_tools()
            if ffmpeg:
                _log(
                    f"ffmpeg present but crop failed for {tile_path} cell ({col},{row})",
                    xbmc.LOGWARNING,
                )
            else:
                _log(
                    "No ffmpeg binary found; install tools.ffmpeg-tools",
                    xbmc.LOGWARNING,
                )
    finally:
        with _inflight_lock:
            _inflight_crops.pop(key, None)
        wait_event.set()

    return result


def resolve_ffmpeg_tools() -> tuple[str | None, str | None, dict[str, str]]:
    """Public wrapper for ffmpeg/ffprobe binary resolution."""
    return _resolve_ffmpeg_tools()

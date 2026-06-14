"""Generate Jellyfin-compatible trickplay sprite sidecars with ffmpeg."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import xbmc
import xbmcvfs

from ffmpeg_tools import resolve_generator_ffmpeg_tools, subprocess_hide_window_kwargs
from generator_extract_modes import (
    EXTRACT_MODE_ACCURATE,
    EXTRACT_MODE_EXPERIMENTAL,
    EXTRACT_MODE_FAST,
    extract_mode_log_label,
    normalize_extract_mode,
)
from generator_settings import GeneratorSettings
from experimental_extract import extract_tile_experimental
from ffmpeg_media import (
    elementary_hevc_input_args,
    extract_frames_from_local_file,
    extract_frames_via_pipe,
    is_elementary_hevc_path,
    probe_duration_via_pipe,
    resolve_ffmpeg_media_path,
)
from grid_settings import grid_tuple
from hdr_tone_map import (
    build_fps_batch_filter,
    is_dv_profile_5,
    prepare_dovi_zscale_media,
    resolve_thumb_filter_context,
)
from trickplay_resolver import (
    find_matching_sidecar_resolution,
    format_resolution_dir_name,
    has_matching_sidecar,
    resolve_media_path,
    trickplay_root_for_media,
)

GENERATE_TEMP_ROOT = xbmcvfs.translatePath("special://temp/service.trickplay/generate/")

_VIDEO_EXTENSIONS = frozenset(
    {
        ".mkv",
        ".mp4",
        ".avi",
        ".m4v",
        ".wmv",
        ".mpg",
        ".mpeg",
        ".ts",
        ".m2ts",
        ".webm",
        ".mov",
        ".flv",
    }
)

_ACCURATE_FRAME_TIMEOUT_BASE_SEC = 600.0
_ACCURATE_FRAME_TIMEOUT_PER_THUMB_SEC = 0.2
_FAST_FRAME_TIMEOUT_SEC = 120.0
_FAST_BATCH_FPS_MAX_INTERVAL_SEC = 5.0


def _accurate_frame_timeout_sec(thumb_index: int) -> float:
    return _ACCURATE_FRAME_TIMEOUT_BASE_SEC + max(thumb_index, 0) * _ACCURATE_FRAME_TIMEOUT_PER_THUMB_SEC


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def _debug(settings: GeneratorSettings, message: str) -> None:
    if settings.debug:
        _log(message, xbmc.LOGINFO)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _ensure_dir(path: str) -> None:
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)


def _ensure_local_dir(path: str) -> None:
    """Ensure a directory exists for local subprocess I/O (ffmpeg image sequences)."""
    local = _local_path(path)
    os.makedirs(local, exist_ok=True)


def _jpg_sort_key(path: str) -> int:
    base = os.path.splitext(os.path.basename(path))[0]
    try:
        return int(base)
    except ValueError:
        return 0


def _list_jpg_files(directory: str) -> list[str]:
    """List JPEGs in directory; prefer os.listdir for ffmpeg temp output."""
    if not directory:
        return []
    local = _local_path(directory)
    paths: list[str] = []
    if local and os.path.isdir(local):
        try:
            for name in os.listdir(local):
                if str(name).lower().endswith(".jpg"):
                    paths.append(os.path.join(local, name))
        except OSError:
            pass
    if not paths:
        if not xbmcvfs.exists(directory):
            return []
        try:
            entries = xbmcvfs.listdir(directory)
        except OSError:
            return []
        files = entries[1] if isinstance(entries, (list, tuple)) and len(entries) == 2 else entries
        for name in files:
            if str(name).lower().endswith(".jpg"):
                paths.append(os.path.join(directory, name))
    return sorted(paths, key=_jpg_sort_key)


def _list_jpg_tiles(directory: str) -> list[str]:
    return _list_jpg_files(directory)


def _path_exists(path: str) -> bool:
    if not path:
        return False
    local = _local_path(path)
    if local:
        if os.path.exists(local):
            return True
    try:
        return xbmcvfs.exists(path)
    except OSError:
        return False


def _list_immediate_entries(directory: str) -> tuple[list[str], list[str]]:
    """Return (subdir names, file names); prefer os.listdir on NFS/OS mounts."""
    dirs: list[str] = []
    files: list[str] = []
    local = _local_path(directory)
    if local and os.path.isdir(local):
        try:
            for entry in os.listdir(local):
                full = os.path.join(local, entry)
                if os.path.isdir(full):
                    dirs.append(str(entry))
                elif os.path.isfile(full):
                    files.append(str(entry))
        except OSError:
            pass
        if dirs or files:
            return dirs, files

    if not _path_exists(directory):
        return [], []

    try:
        entries = xbmcvfs.listdir(directory)
    except OSError:
        return [], []

    if isinstance(entries, (list, tuple)) and len(entries) == 2:
        return [str(name) for name in entries[0]], [str(name) for name in entries[1]]
    file_names = entries if isinstance(entries, list) else []
    return [], [str(name) for name in file_names]


def _delete_path(path: str) -> None:
    local = _local_path(path)
    if local and os.path.isfile(local):
        try:
            os.remove(local)
            return
        except OSError:
            pass
    if _path_exists(path):
        try:
            xbmcvfs.delete(path)
        except OSError:
            pass


def _remove_directory_tree(directory: str) -> None:
    if not directory:
        return
    local = _local_path(directory)
    if local and os.path.isdir(local):
        shutil.rmtree(local, ignore_errors=True)
        return
    if not _path_exists(directory):
        return

    subdirs, files = _list_immediate_entries(directory)
    for name in files:
        _delete_path(os.path.join(directory, name))
    for name in subdirs:
        _remove_directory_tree(os.path.join(directory, name))
    try:
        xbmcvfs.rmdir(directory)
    except OSError:
        pass


def _trickplay_root_for_sidecar_dir(sidecar_dir: str) -> str | None:
    parent = os.path.dirname(sidecar_dir.rstrip("/\\"))
    if parent.endswith(".trickplay"):
        return parent
    return None


def _remove_trickplay_root_if_empty(trickplay_root: str) -> None:
    if not trickplay_root or not trickplay_root.endswith(".trickplay"):
        return
    if not _path_exists(trickplay_root):
        return
    subdirs, files = _list_immediate_entries(trickplay_root)
    if subdirs or files:
        if subdirs:
            _log(
                f"Kept trickplay root ({len(subdirs)} resolution folder(s)): "
                f"{trickplay_root}"
            )
        return
    _remove_directory_tree(trickplay_root)
    _log(f"Removed empty trickplay root: {trickplay_root}")


def _clear_sidecar_tiles(directory: str) -> None:
    for path in _list_jpg_tiles(directory):
        _delete_path(path)


def _cleanup_cancelled_sidecar(directory: str) -> None:
    """Remove the in-progress resolution folder; drop parent .trickplay if alone."""
    if not directory:
        return
    trickplay_root = _trickplay_root_for_sidecar_dir(directory)
    if _path_exists(directory):
        _remove_directory_tree(directory)
        _log(f"Removed cancelled sidecar folder: {directory}")
    if trickplay_root:
        _remove_trickplay_root_if_empty(trickplay_root)


def _remove_empty_sidecar_dir(directory: str) -> None:
    """Remove a sidecar resolution folder when it contains no tile JPEGs."""
    if not directory or not _path_exists(directory):
        return
    if _has_jpg_tiles(directory):
        return
    subdirs, files = _list_immediate_entries(directory)
    if subdirs or files:
        return
    trickplay_root = _trickplay_root_for_sidecar_dir(directory)
    _remove_directory_tree(directory)
    _log(f"Removed empty sidecar folder: {directory}")
    if trickplay_root:
        _remove_trickplay_root_if_empty(trickplay_root)


def _has_jpg_tiles(directory: str) -> bool:
    return bool(_list_jpg_files(directory))


def sidecar_dir_for_grid(
    media_path: str,
    tile_width: int,
    grid: str,
    interval_ms: int,
) -> str:
    cols, rows = grid_tuple(grid)
    root = trickplay_root_for_media(media_path)
    folder = format_resolution_dir_name(tile_width, cols, rows, interval_ms)
    return os.path.join(root, folder)


def has_generated_sidecar(
    media_path: str,
    tile_width: int,
    grid: str,
    interval_ms: int,
    debug: bool = False,
) -> bool:
    """True when a compatible sidecar exists (including Jellyfin legacy folder names)."""
    return has_matching_sidecar(
        media_path,
        tile_width,
        grid,
        interval_ms,
        debug=debug,
    )


@dataclass(frozen=True)
class GenerationBatchPlan:
    candidates: list[str]
    skipped_existing: int
    skipped_dv_profile_5: int
    total_videos: int


def probe_video_duration_seconds(
    media_path: str,
    debug: bool = False,
    *,
    ffmpeg_path: str = "",
) -> int:
    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    _, ffprobe, env = resolve_generator_ffmpeg_tools(ffmpeg_path)

    if use_vfs_stream:
        if not ffprobe:
            _log(f"ffprobe unavailable for VFS duration probe: {media_path}", xbmc.LOGWARNING)
            return 0
        return probe_duration_via_pipe(media_path, ffprobe, env, debug=debug)

    local = ffmpeg_input
    if not ffprobe or not xbmcvfs.exists(media_path):
        _log(
            f"Duration probe skipped (ffprobe={bool(ffprobe)} exists={xbmcvfs.exists(media_path)}): {media_path}",
            xbmc.LOGWARNING,
        )
        return 0

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        local,
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env, **subprocess_hide_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"ffprobe duration failed for {media_path} (path={local!r}): {exc}", xbmc.LOGWARNING)
        return 0

    if completed.returncode == 0:
        try:
            duration = float((completed.stdout or "").strip())
            if duration > 0:
                if debug:
                    _log(f"Duration {int(duration)}s for {media_path} via ffprobe")
                return max(int(duration), 1)
        except ValueError:
            pass

    ffmpeg, _, env = resolve_generator_ffmpeg_tools(ffmpeg_path)
    if not ffmpeg:
        return 0
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", local],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env, **subprocess_hide_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"ffmpeg duration fallback failed for {media_path} (path={local!r}): {exc}", xbmc.LOGWARNING)
        return 0

    match = _DURATION_RE.search(completed.stderr or "")
    if not match:
        detail = (completed.stderr or completed.stdout or "").strip()
        _log(
            f"Could not parse duration for {media_path} (path={local!r}): {detail[:300]}",
            xbmc.LOGWARNING,
        )
        return 0
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if debug:
        _log(f"Duration {int(duration)}s for {media_path} via ffmpeg stderr")
    return max(int(duration), 1)


def _is_cancelled(should_cancel: Callable[[], bool] | None) -> bool:
    return bool(should_cancel and should_cancel())


def _run_subprocess_cancellable(
    cmd: list[str],
    env: dict[str, str],
    timeout: float,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int | None, str]:
    """Run a subprocess; return (returncode, detail). returncode None if cancelled."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env, **subprocess_hide_window_kwargs(),
        )
    except OSError as exc:
        return (-1, str(exc))

    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if _is_cancelled(should_cancel):
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return (None, "cancelled")
        if time.monotonic() >= deadline:
            proc.kill()
            try:
                _, detail = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                detail = "timeout"
            return (-1, detail or "timeout")
        time.sleep(0.15)

    _, detail = proc.communicate()
    return (proc.returncode, (detail or "").strip())


def _insert_before_output(cmd: list[str], extra: tuple[str, ...]) -> list[str]:
    if not extra:
        return cmd
    return [*cmd[:-1], *extra, cmd[-1]]


def _ffmpeg_cmd_prefix(ffmpeg: str, ffmpeg_input_args: tuple[str, ...] = ()) -> list[str]:
    return [ffmpeg, "-y", "-loglevel", "error", *ffmpeg_input_args]


def _extract_frame_accurate(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    timestamp: float,
    tile_width: int,
    output_path: str,
    thumb_vf: str,
    thumb_index: int = 0,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> bool:
    """Extract one thumbnail with seek after input (frame-accurate, slower)."""
    if _is_cancelled(should_cancel):
        return False

    local_out = _local_path(output_path)
    _ensure_local_dir(os.path.dirname(local_out))
    timeout = _accurate_frame_timeout_sec(thumb_index)
    cmd = [
        *_ffmpeg_cmd_prefix(ffmpeg, ffmpeg_input_args),
        "-i",
        ffmpeg_input,
        "-ss",
        f"{max(timestamp, 0.0):.3f}",
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-vf",
        thumb_vf,
        "-q:v",
        "2",
        local_out,
    ]
    cmd = _insert_before_output(cmd, output_color_args)
    returncode, detail = _run_subprocess_cancellable(cmd, env, timeout, should_cancel)
    if returncode is None:
        return False
    if returncode != 0:
        _log(f"Frame extract failed at {timestamp:.1f}s: {detail}", xbmc.LOGWARNING)
        return False

    if debug:
        _log(f"Extracted frame at {timestamp:.1f}s -> {output_path}")
    return os.path.isfile(local_out) or xbmcvfs.exists(output_path)


def _extract_frame_fast(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    timestamp: float,
    tile_width: int,
    output_path: str,
    thumb_vf: str,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> bool:
    """Extract one thumbnail with fast seek before input (keyframe-aligned)."""
    if _is_cancelled(should_cancel):
        return False

    local_out = _local_path(output_path)
    _ensure_local_dir(os.path.dirname(local_out))
    cmd = [
        *_ffmpeg_cmd_prefix(ffmpeg, ffmpeg_input_args),
        "-ss",
        f"{max(timestamp, 0.0):.3f}",
        "-i",
        ffmpeg_input,
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-vf",
        thumb_vf,
        "-q:v",
        "2",
        local_out,
    ]
    cmd = _insert_before_output(cmd, output_color_args)
    returncode, detail = _run_subprocess_cancellable(
        cmd, env, _FAST_FRAME_TIMEOUT_SEC, should_cancel
    )
    if returncode is None:
        return False
    if returncode != 0:
        _log(f"Fast frame extract failed at {timestamp:.1f}s: {detail}", xbmc.LOGWARNING)
        return False

    if not (os.path.isfile(local_out) or xbmcvfs.exists(output_path)):
        _log(
            f"Fast frame extract produced no output at {timestamp:.1f}s "
            f"(path={local_out!r})",
            xbmc.LOGWARNING,
        )
        return False

    if debug:
        _log(f"Fast extracted frame at {timestamp:.1f}s -> {output_path}")
    return os.path.isfile(local_out) or xbmcvfs.exists(output_path)


def _extract_tile_batch_fps(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    tile_start: float,
    frame_count: int,
    interval_sec: float,
    tile_width: int,
    output_dir: str,
    batch_vf: str,
    tile_index: int = 0,
    tile_count: int = 1,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    if _is_cancelled(should_cancel) or frame_count <= 0:
        return []

    _ensure_local_dir(output_dir)
    local_dir = _local_path(output_dir)
    duration = max(frame_count * interval_sec, interval_sec)
    timeout = max(120.0, duration * 3.0 + 60.0)
    pattern = os.path.join(local_dir, "%05d.jpg")

    _log(
        f"Tile {tile_index + 1}/{tile_count}: fps batch "
        f"{frame_count} frame(s) from {tile_start:.1f}s "
        f"(~{duration:.0f}s decode)"
    )

    cmd = [
        *_ffmpeg_cmd_prefix(ffmpeg, ffmpeg_input_args),
        "-ss",
        f"{max(tile_start, 0.0):.3f}",
        "-i",
        ffmpeg_input,
        "-t",
        f"{duration:.3f}",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        batch_vf,
        "-frames:v",
        str(frame_count),
        "-q:v",
        "2",
        pattern,
    ]
    cmd = _insert_before_output(cmd, output_color_args)
    returncode, detail = _run_subprocess_cancellable(cmd, env, timeout, should_cancel)
    if returncode is None:
        return []
    if returncode != 0:
        _log(
            f"Tile fps batch failed at {tile_start:.1f}s "
            f"({frame_count} frame(s)): {detail[:500]}",
            xbmc.LOGWARNING,
        )
        return []

    frame_paths = _list_jpg_files(output_dir)[:frame_count]
    if not frame_paths:
        _log(
            f"Tile fps batch produced no JPEGs at {tile_start:.1f}s "
            f"(dir={local_dir!r})",
            xbmc.LOGWARNING,
        )
        return []

    _log(
        f"Tile {tile_index + 1}/{tile_count}: fps batch extracted "
        f"{len(frame_paths)} frame(s)"
    )
    if debug:
        _log(f"Batch frames -> {output_dir}")
    return frame_paths


def _extract_tile_fast_seek(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    start_index: int,
    frame_count: int,
    interval_sec: float,
    tile_width: int,
    output_dir: str,
    thumb_vf: str,
    tile_index: int = 0,
    tile_count: int = 1,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    """Extract one frame per interval via fast seek (-ss before -i)."""
    if _is_cancelled(should_cancel) or frame_count <= 0:
        return []

    _ensure_local_dir(output_dir)
    tile_start = start_index * interval_sec
    _log(
        f"Tile {tile_index + 1}/{tile_count}: fast seek "
        f"{frame_count} frame(s) every {interval_sec:.1f}s from {tile_start:.1f}s"
    )

    frame_paths: list[str] = []
    for offset in range(frame_count):
        if _is_cancelled(should_cancel):
            return []
        thumb_index = start_index + offset
        timestamp = thumb_index * interval_sec
        frame_path = os.path.join(output_dir, f"{offset:05d}.jpg")
        if not _extract_frame_fast(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            frame_path,
            thumb_vf,
            debug=debug,
            should_cancel=should_cancel,
            output_color_args=output_color_args,
            ffmpeg_input_args=ffmpeg_input_args,
        ):
            return frame_paths
        frame_paths.append(frame_path)
        _log(
            f"Tile {tile_index + 1}/{tile_count}: thumb {offset + 1}/{frame_count} "
            f"at {timestamp:.1f}s"
        )

    _log(
        f"Tile {tile_index + 1}/{tile_count}: fast seek extracted "
        f"{len(frame_paths)} frame(s)"
    )
    return frame_paths


def _extract_tile_fast(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    start_index: int,
    frame_count: int,
    interval_sec: float,
    tile_width: int,
    output_dir: str,
    thumb_vf: str,
    batch_vf: str,
    tile_index: int = 0,
    tile_count: int = 1,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    tile_start = start_index * interval_sec
    if interval_sec <= _FAST_BATCH_FPS_MAX_INTERVAL_SEC:
        return _extract_tile_batch_fps(
            ffmpeg,
            env,
            ffmpeg_input,
            tile_start,
            frame_count,
            interval_sec,
            tile_width,
            output_dir,
            batch_vf,
            tile_index=tile_index,
            tile_count=tile_count,
            debug=debug,
            should_cancel=should_cancel,
            output_color_args=output_color_args,
            ffmpeg_input_args=ffmpeg_input_args,
        )
    return _extract_tile_fast_seek(
        ffmpeg,
        env,
        ffmpeg_input,
        start_index,
        frame_count,
        interval_sec,
        tile_width,
        output_dir,
        thumb_vf,
        tile_index=tile_index,
        tile_count=tile_count,
        debug=debug,
        should_cancel=should_cancel,
        output_color_args=output_color_args,
        ffmpeg_input_args=ffmpeg_input_args,
    )


def _tile_frames(
    ffmpeg: str,
    env: dict[str, str],
    frame_paths: list[str],
    cols: int,
    rows: int,
    output_path: str,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> bool:
    if _is_cancelled(should_cancel):
        return False

    if not frame_paths:
        return False

    local_out = _local_path(output_path)
    _ensure_dir(os.path.dirname(local_out))

    if len(frame_paths) == 1:
        try:
            xbmcvfs.copy(frame_paths[0], output_path)
            return xbmcvfs.exists(output_path)
        except (OSError, RuntimeError, ValueError):
            return False

    count = len(frame_paths)
    layout_cols = min(cols, count)
    layout_rows = (count + layout_cols - 1) // layout_cols

    parent = os.path.dirname(_local_path(frame_paths[0]))
    seq_dir = os.path.join(parent, f"seq_{uuid.uuid4().hex[:12]}")
    _ensure_local_dir(seq_dir)
    try:
        for index, path in enumerate(frame_paths):
            if _is_cancelled(should_cancel):
                return False
            shutil.copy2(_local_path(path), os.path.join(seq_dir, f"{index:05d}.jpg"))

        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-start_number",
            "0",
            "-i",
            os.path.join(seq_dir, "%05d.jpg"),
            "-frames:v",
            "1",
            "-filter_complex",
            f"tile={layout_cols}x{layout_rows}",
            "-q:v",
            "2",
            local_out,
        ]
        returncode, detail = _run_subprocess_cancellable(cmd, env, 180, should_cancel)
        if returncode is None:
            return False
        if returncode != 0:
            _log(f"Tile assembly failed: {detail}", xbmc.LOGWARNING)
            return False
    finally:
        _remove_tree(seq_dir)

    if debug:
        _log(
            f"Tiled {count} frame(s) as {layout_cols}x{layout_rows} -> {output_path}"
        )
    return xbmcvfs.exists(output_path)


def _remove_tree(path: str) -> None:
    local = _local_path(path)
    if os.path.isdir(local):
        shutil.rmtree(local, ignore_errors=True)


def generate_trickplay_for_media(
    media_path: str,
    settings: GeneratorSettings,
    should_cancel: Callable[[], bool] | None = None,
) -> bool:
    """Write Jellyfin-format trickplay sprites next to media_path."""
    if _is_cancelled(should_cancel):
        return False

    media_path = resolve_media_path(media_path) or media_path
    if not media_path or not xbmcvfs.exists(media_path):
        _log(f"Media not found: {media_path!r}", xbmc.LOGWARNING)
        return False

    cols, rows = grid_tuple(settings.grid)
    output_dir = sidecar_dir_for_grid(
        media_path,
        settings.tile_width,
        settings.grid,
        settings.interval_ms,
    )

    matching = find_matching_sidecar_resolution(
        media_path,
        settings.tile_width,
        settings.grid,
        settings.interval_ms,
        debug=settings.debug,
    )
    if matching is not None:
        if not settings.overwrite_existing:
            _debug(
                settings,
                f"Skipping existing sidecar: {matching.tiles_dir}",
            )
            return True
        _clear_sidecar_tiles(matching.tiles_dir)
        _log(f"Overwriting existing sidecar: {matching.tiles_dir}")
    elif _has_jpg_tiles(output_dir):
        if not settings.overwrite_existing:
            _debug(settings, f"Skipping existing sidecar: {output_dir}")
            return True
        _clear_sidecar_tiles(output_dir)
        _log(f"Overwriting existing sidecar: {output_dir}")

    ffmpeg, ffprobe, env = resolve_generator_ffmpeg_tools(settings.ffmpeg_path)
    if not ffmpeg:
        _log("ffmpeg not found; install tools.ffmpeg-tools", xbmc.LOGERROR)
        return False

    filter_ctx = resolve_thumb_filter_context(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback=settings.hdr_dovi_tool_fallback,
        tile_width=settings.tile_width,
        media_path=media_path,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe or "",
        env=env,
        debug=settings.debug,
    )
    batch_vf = build_fps_batch_filter(
        settings.tile_width,
        max(settings.interval_ms / 1000.0, 0.001),
        filter_ctx.apply_tonemap,
        filter_ctx.tonemap_mode,
        filter_ctx.hdr_transfer,
        dolby_vision=filter_ctx.dolby_vision,
    )
    output_color_args = filter_ctx.ffmpeg_color_args
    ffmpeg_input_args = filter_ctx.ffmpeg_input_args
    if settings.debug and filter_ctx.apply_tonemap:
        _log(f"HDR video filter: {filter_ctx.thumb_vf}")

    duration = probe_video_duration_seconds(
        media_path, debug=settings.debug, ffmpeg_path=settings.ffmpeg_path
    )
    if duration <= 0:
        _log(f"Could not determine duration for {media_path}", xbmc.LOGWARNING)
        return False

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    dovi_prep_dir: str | None = None
    if filter_ctx.use_dovi_tool_zscale_prep:
        if use_vfs_stream:
            _log(
                "Dolby Vision dovi_tool prep requires a local file path",
                xbmc.LOGERROR,
            )
            return False
        prepared_input, dovi_prep_dir = prepare_dovi_zscale_media(
            media_path,
            ffmpeg,
            ffprobe or "",
            env,
            duration_sec=duration,
            debug=settings.debug,
            should_cancel=should_cancel,
        )
        if not prepared_input:
            return False
        if dovi_prep_dir:
            ffmpeg_input = prepared_input
            use_vfs_stream = False
            _log(f"Using dovi_tool-prepared input for frame extraction: {ffmpeg_input}")

    is_elementary_hevc = not use_vfs_stream and is_elementary_hevc_path(ffmpeg_input or "")
    if is_elementary_hevc:
        ffmpeg_input_args = (
            *ffmpeg_input_args,
            *elementary_hevc_input_args(ffmpeg_input),
        )

    if use_vfs_stream:
        _log(f"Using VFS stream generation for {media_path}")

    interval_sec = max(settings.interval_ms / 1000.0, 0.001)
    thumb_count = int(duration / interval_sec) + 1
    thumbs_per_tile = cols * rows
    tile_count = (thumb_count + thumbs_per_tile - 1) // thumbs_per_tile

    _ensure_dir(output_dir)
    work_dir = os.path.join(GENERATE_TEMP_ROOT, uuid.uuid4().hex)
    _ensure_dir(work_dir)
    _ensure_local_dir(work_dir)

    extract_mode = "VFS stream" if use_vfs_stream else (
        "dovi HEVC sequential" if is_elementary_hevc else extract_mode_log_label(
            settings.extract_mode
        )
    )
    hdr_note = ", HDR tone map" if filter_ctx.apply_tonemap else ""
    _log(
        f"Generating trickplay for {os.path.basename(media_path)} "
        f"({thumb_count} thumbs, {tile_count} tile(s), {settings.grid}, "
        f"{settings.tile_width}px, {settings.interval_ms}ms, {extract_mode}{hdr_note}) "
        f"-> {output_dir}"
    )

    success = True
    cancelled = False
    try:
        if use_vfs_stream:
            frame_pattern = os.path.join(work_dir, "thumb_%06d.jpg")
            if not extract_frames_via_pipe(
                media_path,
                ffmpeg,
                env,
                _local_path(frame_pattern),
                batch_vf,
                debug=settings.debug,
                should_cancel=should_cancel,
                output_color_args=output_color_args,
                ffmpeg_input_args=ffmpeg_input_args,
            ):
                if _is_cancelled(should_cancel):
                    cancelled = True
                else:
                    success = False
            else:
                frame_paths = _list_jpg_files(work_dir)[:thumb_count]
                if not frame_paths:
                    success = False
                else:
                    for tile_index in range(tile_count):
                        if _is_cancelled(should_cancel):
                            cancelled = True
                            break
                        start_index = tile_index * thumbs_per_tile
                        chunk = frame_paths[start_index : start_index + thumbs_per_tile]
                        if not chunk:
                            break
                        tile_path = os.path.join(output_dir, f"{tile_index}.jpg")
                        if not _tile_frames(
                            ffmpeg,
                            env,
                            chunk,
                            cols,
                            rows,
                            tile_path,
                            debug=settings.debug,
                            should_cancel=should_cancel,
                        ):
                            if _is_cancelled(should_cancel):
                                cancelled = True
                            else:
                                success = False
                            break
        elif is_elementary_hevc:
            hevc_timeout = max(3600.0, duration * 2.0 + 300.0)
            frame_pattern = os.path.join(_local_path(work_dir), "thumb_%06d.jpg")
            _log(
                f"Dolby Vision HEVC: sequential extract of {thumb_count} frame(s) "
                f"(elementary stream has no seek index; timeout {int(hevc_timeout)}s)"
            )
            if not extract_frames_from_local_file(
                _local_path(ffmpeg_input) or ffmpeg_input,
                ffmpeg,
                env,
                frame_pattern,
                batch_vf,
                thumb_count,
                timeout_sec=hevc_timeout,
                debug=settings.debug,
                should_cancel=should_cancel,
                output_color_args=output_color_args,
                ffmpeg_input_args=ffmpeg_input_args,
            ):
                if _is_cancelled(should_cancel):
                    cancelled = True
                else:
                    success = False
            else:
                frame_paths = _list_jpg_files(work_dir)[:thumb_count]
                if not frame_paths:
                    _log(
                        "Dolby Vision HEVC extract produced no JPEGs",
                        xbmc.LOGWARNING,
                    )
                    success = False
                else:
                    _log(
                        f"Dolby Vision HEVC: extracted {len(frame_paths)} frame(s); "
                        f"assembling {tile_count} tile(s)"
                    )
                    for tile_index in range(tile_count):
                        if _is_cancelled(should_cancel):
                            cancelled = True
                            break
                        start_index = tile_index * thumbs_per_tile
                        chunk = frame_paths[start_index : start_index + thumbs_per_tile]
                        if not chunk:
                            break
                        tile_path = os.path.join(output_dir, f"{tile_index}.jpg")
                        if not _tile_frames(
                            ffmpeg,
                            env,
                            chunk,
                            cols,
                            rows,
                            tile_path,
                            debug=settings.debug,
                            should_cancel=should_cancel,
                        ):
                            if _is_cancelled(should_cancel):
                                cancelled = True
                            else:
                                success = False
                            break
        else:
            for tile_index in range(tile_count):
                if _is_cancelled(should_cancel):
                    cancelled = True
                    break
                start_index = tile_index * thumbs_per_tile
                end_index = min(start_index + thumbs_per_tile, thumb_count)
                chunk_count = end_index - start_index
                if chunk_count <= 0:
                    break

                tile_work_dir = os.path.join(work_dir, f"t{tile_index:04d}")
                _ensure_local_dir(tile_work_dir)

                if settings.extract_mode == EXTRACT_MODE_EXPERIMENTAL:
                    frame_paths = extract_tile_experimental(
                        ffmpeg,
                        env,
                        ffmpeg_input,
                        start_index,
                        chunk_count,
                        interval_sec,
                        settings.tile_width,
                        filter_ctx.thumb_vf,
                        tile_work_dir,
                        tile_index=tile_index,
                        tile_count=tile_count,
                        debug=settings.debug,
                        should_cancel=should_cancel,
                        run_subprocess=_run_subprocess_cancellable,
                        force_ffmpeg=filter_ctx.apply_tonemap,
                        output_color_args=output_color_args,
                        ffmpeg_input_args=ffmpeg_input_args,
                    )
                elif settings.extract_mode == EXTRACT_MODE_FAST:
                    frame_paths = _extract_tile_fast(
                        ffmpeg,
                        env,
                        ffmpeg_input,
                        start_index,
                        chunk_count,
                        interval_sec,
                        settings.tile_width,
                        tile_work_dir,
                        filter_ctx.thumb_vf,
                        batch_vf,
                        tile_index=tile_index,
                        tile_count=tile_count,
                        debug=settings.debug,
                        should_cancel=should_cancel,
                        output_color_args=output_color_args,
                        ffmpeg_input_args=ffmpeg_input_args,
                    )
                elif settings.extract_mode == EXTRACT_MODE_ACCURATE:
                    frame_paths = []
                    for thumb_index in range(start_index, end_index):
                        if _is_cancelled(should_cancel):
                            cancelled = True
                            break
                        timestamp = thumb_index * interval_sec
                        frame_path = os.path.join(
                            tile_work_dir, f"f{thumb_index:05d}.jpg"
                        )
                        if not _extract_frame_accurate(
                            ffmpeg,
                            env,
                            ffmpeg_input,
                            timestamp,
                            settings.tile_width,
                            frame_path,
                            filter_ctx.thumb_vf,
                            thumb_index=thumb_index,
                            debug=settings.debug,
                            should_cancel=should_cancel,
                            output_color_args=output_color_args,
                            ffmpeg_input_args=ffmpeg_input_args,
                        ):
                            if _is_cancelled(should_cancel):
                                cancelled = True
                            else:
                                success = False
                            break
                        frame_paths.append(frame_path)
                else:
                    _log(
                        f"Unknown extract mode {settings.extract_mode!r}; "
                        f"using fast",
                        xbmc.LOGWARNING,
                    )
                    frame_paths = _extract_tile_fast(
                        ffmpeg,
                        env,
                        ffmpeg_input,
                        start_index,
                        chunk_count,
                        interval_sec,
                        settings.tile_width,
                        tile_work_dir,
                        filter_ctx.thumb_vf,
                        batch_vf,
                        tile_index=tile_index,
                        tile_count=tile_count,
                        debug=settings.debug,
                        should_cancel=should_cancel,
                        output_color_args=output_color_args,
                        ffmpeg_input_args=ffmpeg_input_args,
                    )

                if cancelled or _is_cancelled(should_cancel):
                    cancelled = True
                    break
                if not success or not frame_paths:
                    if not cancelled and not frame_paths:
                        _log(
                            f"Tile {tile_index + 1}/{tile_count}: no frames extracted",
                            xbmc.LOGWARNING,
                        )
                        success = False
                    break
                if len(frame_paths) < chunk_count:
                    _log(
                        f"Tile {tile_index + 1}: expected {chunk_count} frame(s), "
                        f"got {len(frame_paths)} (using partial tile)",
                        xbmc.LOGWARNING,
                    )

                tile_path = os.path.join(output_dir, f"{tile_index}.jpg")
                if not _tile_frames(
                    ffmpeg,
                    env,
                    frame_paths,
                    cols,
                    rows,
                    tile_path,
                    debug=settings.debug,
                    should_cancel=should_cancel,
                ):
                    if _is_cancelled(should_cancel):
                        cancelled = True
                    else:
                        success = False
                    break

                _log(f"Tile {tile_index + 1}/{tile_count}: wrote {tile_path}")
                _remove_tree(tile_work_dir)

        was_cancelled = cancelled or _is_cancelled(should_cancel)
        if was_cancelled:
            _log(
                f"Generation cancelled for {os.path.basename(media_path)}",
                xbmc.LOGINFO,
            )
        elif success:
            _log(
                f"Generated {tile_count} tile(s) for {os.path.basename(media_path)}"
            )
        else:
            _log(
                f"Generation failed for {os.path.basename(media_path)}",
                xbmc.LOGWARNING,
            )
            _remove_empty_sidecar_dir(output_dir)
    finally:
        if cancelled or _is_cancelled(should_cancel):
            _cleanup_cancelled_sidecar(output_dir)
        _remove_tree(work_dir)
        if dovi_prep_dir:
            _remove_tree(dovi_prep_dir)

    if cancelled or _is_cancelled(should_cancel):
        return False

    return success


def iter_library_videos(root: str) -> list[str]:
    """Recursively list local video files under root."""
    root = (root or "").strip()
    if not root or not xbmcvfs.exists(root):
        return []

    results: list[str] = []
    stack = [_local_path(root) if root.startswith("special://") else root]

    while stack:
        current = stack.pop()
        try:
            entries = xbmcvfs.listdir(current)
        except OSError:
            continue

        if isinstance(entries, (list, tuple)) and len(entries) == 2:
            dirs, files = entries
        else:
            dirs, files = [], entries if isinstance(entries, list) else []

        for name in files:
            ext = os.path.splitext(str(name))[1].lower()
            if ext not in _VIDEO_EXTENSIONS:
                continue
            results.append(os.path.join(current, name))

        for name in dirs:
            if str(name) in (".", ".."):
                continue
            stack.append(os.path.join(current, name))

    return sorted(results)


def collect_generation_candidates(
    root: str,
    settings: GeneratorSettings,
) -> GenerationBatchPlan:
    """Return media paths under root that still need trickplay sidecars."""
    videos = iter_library_videos(root)
    _log(f"Scanned {len(videos)} video(s) under {root!r}")
    candidates: list[str] = []
    skipped = 0
    skipped_dv_p5 = 0
    skip_dv_p5 = settings.skip_dv_profile_5 and settings.hdr_tone_map
    ffmpeg = ffprobe = None
    env: dict[str, str] | None = None
    if skip_dv_p5:
        ffmpeg, ffprobe, env = resolve_generator_ffmpeg_tools(settings.ffmpeg_path)
        if not ffprobe:
            _log(
                "Skip DV Profile 5 enabled but ffprobe unavailable; "
                "profile scan disabled",
                xbmc.LOGWARNING,
            )
            skip_dv_p5 = False
    for media_path in videos:
        if (
            not settings.overwrite_existing
            and has_generated_sidecar(
                media_path,
                settings.tile_width,
                settings.grid,
                settings.interval_ms,
                debug=settings.debug,
            )
        ):
            skipped += 1
            _log(f"Skipping existing sidecar: {os.path.basename(media_path)}")
            continue
        if skip_dv_p5 and is_dv_profile_5(
            media_path,
            ffprobe,
            env,
            ffmpeg=ffmpeg,
            debug=settings.debug,
        ):
            skipped_dv_p5 += 1
            _log(f"Skipping DV Profile 5 (setting): {os.path.basename(media_path)}")
            continue
        candidates.append(media_path)
    _log(
        f"Candidates: {len(candidates)} need generation, {skipped} skipped "
        f"(existing sidecar), {skipped_dv_p5} skipped (DV Profile 5), "
        f"overwrite={settings.overwrite_existing}"
    )
    return GenerationBatchPlan(
        candidates=candidates,
        skipped_existing=skipped,
        skipped_dv_profile_5=skipped_dv_p5,
        total_videos=len(videos),
    )

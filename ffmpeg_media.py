"""Resolve Kodi VFS media paths for ffmpeg/ffprobe subprocesses."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable

import xbmc
import xbmcvfs

from ffmpeg_tools import subprocess_hide_window_kwargs
from vfs_paths import vfs_is_file

_NETWORK_URL_RE = re.compile(r"^(nfs|smb|smb2|smb3)://([^/]+)/(.+)$", re.IGNORECASE)
_MOUNT_CACHE_TTL_SEC = 60.0
_mount_cache_at = 0.0
_mount_cache: list[tuple[str, str, str]] = []


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def is_elementary_hevc_path(path: str) -> bool:
    """True for annex-B HEVC elementary streams (e.g. dovi_tool convert output)."""
    if not path or "://" in path:
        return False
    return path.lower().endswith(".hevc")


def elementary_hevc_input_args(path: str) -> tuple[str, ...]:
    return ("-f", "hevc") if is_elementary_hevc_path(path) else ()


def _is_local_filesystem_path(path: str) -> bool:
    if not path or "://" in path:
        return False
    if os.path.isfile(path):
        return True
    # NFS/CIFS mounts may not always pass os.path.isfile on embedded Linux.
    try:
        return vfs_is_file(path)
    except (OSError, RuntimeError, ValueError):
        return False


def _read_vfs_chunk(handle, chunk_size: int) -> bytes:
    """Read binary data from xbmcvfs.File (Python 3 read() is UTF-8 text only)."""
    read_bytes = getattr(handle, "readBytes", None)
    if callable(read_bytes):
        data = read_bytes(chunk_size)
        if not data:
            return b""
        return bytes(data) if isinstance(data, bytearray) else data

    raw = handle.read(chunk_size)
    if raw is None:
        return b""
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    # Legacy text read: preserve bytes 0-255 (read() may have failed on binary).
    return raw.encode("latin-1", errors="ignore")


def _load_mount_table() -> list[tuple[str, str, str]]:
    """Return [(fstype, device, mount_point), ...] from /proc/mounts when available."""
    global _mount_cache_at, _mount_cache

    now = time.monotonic()
    if _mount_cache and now - _mount_cache_at < _MOUNT_CACHE_TTL_SEC:
        return _mount_cache

    mounts: list[tuple[str, str, str]] = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mounts.append((parts[2], parts[0], parts[1]))
    except OSError:
        pass

    _mount_cache = mounts
    _mount_cache_at = now
    return mounts


def _map_network_url_to_local(path: str) -> str | None:
    match = _NETWORK_URL_RE.match(path.strip())
    if not match:
        return None

    scheme, host, remote_path = match.group(1).lower(), match.group(2), match.group(3)
    remote_path = remote_path.replace("\\", "/").lstrip("/")
    host_lower = host.lower()

    best: str | None = None
    for fstype, device, mount_point in _load_mount_table():
        if scheme == "nfs" and fstype not in ("nfs", "nfs4"):
            continue
        if scheme.startswith("smb") and fstype not in ("cifs", "smbfs"):
            continue

        device_lower = device.lower()
        export = ""
        if scheme == "nfs":
            if host_lower not in device_lower or ":" not in device:
                continue
            export = device.split(":", 1)[1].strip("/")
        else:
            if not device.startswith("//"):
                continue
            server_share = device[2:]
            slash = server_share.find("/")
            if slash < 0:
                continue
            server = server_share[:slash]
            if server.lower() != host_lower:
                continue
            export = server_share[slash + 1 :].strip("/")

        if export:
            if remote_path != export and not remote_path.startswith(f"{export}/"):
                continue
            rel = remote_path[len(export) :].lstrip("/")
        else:
            rel = remote_path

        candidate = os.path.join(mount_point, rel) if rel else mount_point
        if _is_local_filesystem_path(candidate):
            _log(f"Mapped {path} -> {candidate} via {device} on {mount_point}")
            return candidate
        if best is None and xbmcvfs.exists(candidate):
            best = candidate

    if best and _is_local_filesystem_path(best):
        _log(f"Mapped {path} -> {best} via VFS existence check")
        return best

    return None


def resolve_ffmpeg_media_path(media_path: str) -> tuple[str, bool]:
    """
    Return (ffmpeg_input, use_vfs_stream).

    When use_vfs_stream is False, ffmpeg_input is a local path ffmpeg can open directly.
    When True, ffmpeg_input is the VFS URL/path and media must be streamed via xbmcvfs.
    """
    from vfs_paths import normalize_vfs_path

    path = normalize_vfs_path((media_path or "").strip())
    if not path:
        return path, False

    if _is_local_filesystem_path(path):
        return path, False

    if path.startswith(("special://", "vfs://", "zip://")):
        translated = xbmcvfs.translatePath(path)
        if _is_local_filesystem_path(translated):
            return translated, False

    if "://" in path:
        translated = xbmcvfs.translatePath(path)
        if translated and translated != path and _is_local_filesystem_path(translated):
            return translated, False

        mapped = _map_network_url_to_local(path)
        if mapped:
            return mapped, False

        if xbmcvfs.exists(path):
            _log(
                f"No local ffmpeg path for {path}; using VFS stream fallback (sequential read)",
                xbmc.LOGINFO,
            )
            return path, True

    if xbmcvfs.exists(path):
        return path, False

    return path, False


def _ffmpeg_timeout_for_path(path: str, default: int = 3600) -> int:
    try:
        stat_obj = xbmcvfs.Stat(path)
        size = getattr(stat_obj, "st_size", None)
        if callable(size):
            size = size()
        if size is None:
            size = getattr(stat_obj, "size", None)
            if callable(size):
                size = size()
        size = int(size or 0)
        if size <= 0:
            return default
        # Assume ~5 MiB/s effective read speed; clamp between 10 min and 6 h.
        return max(600, min(6 * 3600, size // (5 * 1024 * 1024) + 300))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return default


def _stream_to_pipe(
    media_path: str,
    proc: subprocess.Popen,
    chunk_size: int = 1024 * 1024,
) -> None:
    from vfs_paths import normalize_vfs_path

    media_path = normalize_vfs_path(media_path)
    try:
        handle = xbmcvfs.File(media_path, "rb")
    except (OSError, RuntimeError, ValueError) as exc:
        _log(f"VFS read open failed for {media_path}: {exc}", xbmc.LOGWARNING)
        return

    try:
        while True:
            data = _read_vfs_chunk(handle, chunk_size)
            if not data:
                break
            if proc.stdin is None:
                break
            proc.stdin.write(data)
    except (OSError, RuntimeError, ValueError, BrokenPipeError) as exc:
        _log(f"VFS read failed for {media_path}: {exc}", xbmc.LOGWARNING)
    finally:
        try:
            handle.close()
        except (OSError, RuntimeError, ValueError):
            pass
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass


_DURATION_RE = re.compile(
    r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_duration_from_ffmpeg_stderr(stderr: str) -> float:
    match = _DURATION_RE.search(stderr or "")
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_hms_duration(tag: str) -> float:
    tag = (tag or "").strip()
    if not tag:
        return 0.0
    parts = tag.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(tag)
    except ValueError:
        return 0.0


def _parse_r_frame_rate(rate: str) -> float:
    rate = (rate or "").strip()
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n, d = float(num), float(den)
            return n / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _video_duration_from_stream(stream: dict) -> float:
    try:
        duration = float(stream.get("duration") or 0)
        if duration > 0:
            return duration
    except (TypeError, ValueError):
        pass

    tags = stream.get("tags") or {}
    tag_duration = _parse_hms_duration(str(tags.get("DURATION") or ""))
    if tag_duration > 0:
        return tag_duration

    try:
        frames = float(tags.get("NUMBER_OF_FRAMES") or 0)
        fps = _parse_r_frame_rate(
            str(stream.get("r_frame_rate") or stream.get("avg_frame_rate") or "")
        )
        if frames > 0 and fps > 0:
            return frames / fps
    except (TypeError, ValueError):
        pass
    return 0.0


def _parse_ffprobe_json_durations(payload: dict) -> tuple[float, float]:
    format_duration = 0.0
    try:
        format_duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    if format_duration <= 0:
        format_duration = 0.0

    video_duration = 0.0
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") == "video":
            video_duration = _video_duration_from_stream(stream)
            if video_duration > 0:
                break
    return format_duration, video_duration


def _run_ffprobe_json(
    cmd: list[str],
    env: dict[str, str] | None,
    *,
    timeout: float,
    media_label: str,
) -> dict | None:
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            **subprocess_hide_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(
            f"ffprobe duration failed for {media_label}: {exc}",
            xbmc.LOGWARNING,
        )
        return None

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        _log(
            f"ffprobe duration failed for {media_label} (rc={completed.returncode}): "
            f"{detail[:300]}",
            xbmc.LOGWARNING,
        )
        return None

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        _log(f"ffprobe duration JSON parse failed for {media_label}", xbmc.LOGWARNING)
        return None


def probe_media_durations_local(
    local: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    debug: bool = False,
    media_label: str = "",
) -> tuple[float, float]:
    label = media_label or local
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=duration:stream_tags=DURATION:stream_tags=NUMBER_OF_FRAMES:"
        "stream=r_frame_rate:stream=avg_frame_rate:stream=codec_type",
        "-select_streams",
        "v:0",
        "-of",
        "json",
        local,
    ]
    payload = _run_ffprobe_json(cmd, env, timeout=60, media_label=label)
    if payload is None:
        return 0.0, 0.0
    format_duration, video_duration = _parse_ffprobe_json_durations(payload)
    if debug and (format_duration > 0 or video_duration > 0):
        _log(
            f"Duration probe for {label}: container={format_duration:.2f}s "
            f"video={video_duration:.2f}s"
        )
    return format_duration, video_duration


def _run_ffprobe_json_via_pipe(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
) -> dict | None:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-probesize",
        "50M",
        "-analyzeduration",
        "50M",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=duration:stream_tags=DURATION:stream_tags=NUMBER_OF_FRAMES:"
        "stream=r_frame_rate:stream=avg_frame_rate:stream=codec_type",
        "-select_streams",
        "v:0",
        "-of",
        "json",
        "pipe:0",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **subprocess_hide_window_kwargs(),
        )
    except OSError as exc:
        _log(f"ffprobe pipe probe failed to start for {media_path}: {exc}", xbmc.LOGWARNING)
        return None

    feeder = threading.Thread(
        target=_stream_to_pipe,
        args=(media_path, proc),
        daemon=True,
    )
    feeder.start()
    timeout = _ffmpeg_timeout_for_path(media_path)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        _log(
            f"ffprobe pipe probe timed out after {timeout}s for {media_path}",
            xbmc.LOGWARNING,
        )
        return None
    finally:
        feeder.join(timeout=1)

    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        _log(
            f"ffprobe pipe probe failed for {media_path} (rc={proc.returncode}): {detail}",
            xbmc.LOGWARNING,
        )
        return None

    try:
        return json.loads((stdout or b"").decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        _log(f"ffprobe pipe duration JSON parse failed for {media_path}", xbmc.LOGWARNING)
        return None


def probe_durations_via_pipe(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    debug: bool = False,
) -> tuple[float, float]:
    payload = _run_ffprobe_json_via_pipe(media_path, ffprobe, env)
    if payload is None:
        return 0.0, 0.0
    format_duration, video_duration = _parse_ffprobe_json_durations(payload)
    if debug and (format_duration > 0 or video_duration > 0):
        _log(
            f"Duration probe for {media_path}: container={format_duration:.2f}s "
            f"video={video_duration:.2f}s (pipe)"
        )
    return format_duration, video_duration


def effective_generation_duration_seconds(
    format_duration: float,
    video_duration: float,
    *,
    media_path: str = "",
    debug: bool = False,
) -> int:
    candidates = [d for d in (format_duration, video_duration) if d > 0]
    if not candidates:
        return 0
    duration = min(candidates) if len(candidates) > 1 else candidates[0]
    if format_duration > 0 and video_duration > 0 and format_duration - video_duration > 1.0:
        _log(
            f"Using video duration {int(duration)}s for {media_path} "
            f"(container reports {int(format_duration)}s)",
            xbmc.LOGINFO,
        )
    elif debug:
        _log(f"Duration {int(duration)}s for {media_path}")
    return max(int(duration), 1)


def probe_duration_via_pipe(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    debug: bool = False,
) -> int:
    format_duration, video_duration = probe_durations_via_pipe(
        media_path, ffprobe, env, debug=debug
    )
    return effective_generation_duration_seconds(
        format_duration,
        video_duration,
        media_path=media_path,
        debug=debug,
    )


def extract_frames_via_pipe(
    media_path: str,
    ffmpeg: str,
    env: dict[str, str] | None,
    output_pattern: str,
    video_filter: str,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> bool:
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        *ffmpeg_input_args,
        "-probesize",
        "50M",
        "-analyzeduration",
        "50M",
        "-i",
        "pipe:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        video_filter,
        "-q:v",
        "2",
        output_pattern,
    ]
    if output_color_args:
        cmd = [*cmd[:-1], *output_color_args, cmd[-1]]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env, **subprocess_hide_window_kwargs(),
        )
    except OSError as exc:
        _log(f"ffmpeg pipe extract failed to start for {media_path}: {exc}", xbmc.LOGWARNING)
        return False

    feeder = threading.Thread(
        target=_stream_to_pipe,
        args=(media_path, proc),
        daemon=True,
    )
    feeder.start()
    timeout = _ffmpeg_timeout_for_path(media_path)
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if should_cancel and should_cancel():
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                _log(f"Streamed frame extract cancelled for {media_path}", xbmc.LOGINFO)
                return False
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                _log(
                    f"ffmpeg pipe extract timed out after {timeout}s for {media_path}",
                    xbmc.LOGWARNING,
                )
                return False
            time.sleep(0.15)
        _, stderr = proc.communicate()
    except OSError:
        proc.kill()
        proc.communicate()
        return False
    finally:
        feeder.join(timeout=1)

    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        _log(
            f"ffmpeg pipe extract failed for {media_path} (rc={proc.returncode}): {detail}",
            xbmc.LOGWARNING,
        )
        return False

    if debug:
        _log(f"Streamed frames from {media_path} -> {output_pattern}")
    return True


def extract_frames_from_local_file(
    local_input: str,
    ffmpeg: str,
    env: dict[str, str] | None,
    output_pattern: str,
    video_filter: str,
    frame_count: int,
    *,
    timeout_sec: float = 3600.0,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> bool:
    """Decode a local file sequentially (used for .hevc with no seek index)."""
    if frame_count <= 0:
        return False
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        *ffmpeg_input_args,
        *elementary_hevc_input_args(local_input),
        "-i",
        local_input,
        "-an",
        "-sn",
        "-dn",
        "-vf",
        video_filter,
        "-frames:v",
        str(frame_count),
        "-q:v",
        "2",
        output_pattern,
    ]
    if output_color_args:
        cmd = [*cmd[:-1], *output_color_args, cmd[-1]]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env, **subprocess_hide_window_kwargs(),
        )
    except OSError as exc:
        _log(
            f"ffmpeg local extract failed to start for {local_input}: {exc}",
            xbmc.LOGWARNING,
        )
        return False

    deadline = time.monotonic() + max(timeout_sec, 120.0)
    try:
        while proc.poll() is None:
            if should_cancel and should_cancel():
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                _log(f"Local frame extract cancelled for {local_input}", xbmc.LOGINFO)
                return False
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                _log(
                    f"ffmpeg local extract timed out after {int(timeout_sec)}s "
                    f"for {local_input}",
                    xbmc.LOGWARNING,
                )
                return False
            time.sleep(0.15)
        _, stderr = proc.communicate()
    except OSError:
        proc.kill()
        proc.communicate()
        return False

    if proc.returncode != 0:
        detail = (stderr or "").strip()
        _log(
            f"ffmpeg local extract failed for {local_input} (rc={proc.returncode}): "
            f"{detail[:800]}",
            xbmc.LOGWARNING,
        )
        return False

    if debug:
        _log(f"Local frames from {local_input} -> {output_pattern}")
    return True

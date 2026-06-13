"""Resolve Kodi VFS media paths for ffmpeg/ffprobe subprocesses."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable

import xbmc
import xbmcvfs

_NETWORK_URL_RE = re.compile(r"^(nfs|smb|smb2|smb3)://([^/]+)/(.+)$", re.IGNORECASE)
_MOUNT_CACHE_TTL_SEC = 60.0
_mount_cache_at = 0.0
_mount_cache: list[tuple[str, str, str]] = []


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def _is_local_filesystem_path(path: str) -> bool:
    if not path or "://" in path:
        return False
    if os.path.isfile(path):
        return True
    # NFS/CIFS mounts may not always pass os.path.isfile on embedded Linux.
    try:
        return xbmcvfs.exists(path) and not xbmcvfs.isdir(path)
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
    path = (media_path or "").strip()
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


def probe_duration_via_pipe(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    debug: bool = False,
) -> int:
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
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "pipe:0",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        _log(f"ffprobe pipe probe failed to start for {media_path}: {exc}", xbmc.LOGWARNING)
        return 0

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
        _log(f"ffprobe pipe probe timed out after {timeout}s for {media_path}", xbmc.LOGWARNING)
        return 0
    finally:
        feeder.join(timeout=1)

    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        _log(
            f"ffprobe pipe probe failed for {media_path} (rc={proc.returncode}): {detail}",
            xbmc.LOGWARNING,
        )
        return 0

    try:
        duration = float((stdout or b"").decode("utf-8", errors="replace").strip())
    except ValueError:
        return 0

    if duration <= 0:
        return 0

    if debug:
        _log(f"Duration {int(duration)}s for {media_path} via ffprobe pipe")
    return max(int(duration), 1)


def extract_frames_via_pipe(
    media_path: str,
    ffmpeg: str,
    env: dict[str, str] | None,
    output_pattern: str,
    video_filter: str,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    output_color_args: tuple[str, ...] = (),
) -> bool:
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
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
            env=env,
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

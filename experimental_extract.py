"""Fast (batch seeks) tile extraction: multi-seek ffmpeg chunks + optional PyAV.

Hardened path: small ffmpeg input chunks, per-frame Fast fallback on misses,
optional PyAV seek-loop for local SDR when installed.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable

import xbmc

# Keep multi-input ffmpeg commands modest (Windows cmdline / demuxer stability).
_BATCH_SEEKS_FFMPEG_CHUNK = 8
_BATCH_SEEKS_MIN_CHUNK_TIMEOUT_SEC = 25.0
_BATCH_SEEKS_MAX_CHUNK_TIMEOUT_SEC = 60.0
_BATCH_SEEKS_TIMEOUT_PER_INPUT_SEC = 8.0

FrameFallback = Callable[[float, str], bool]


def _reuse_frame(src: str, dest: str) -> bool:
    """Copy last good JPEG so a missed timestamp still occupies its grid cell."""
    if not src or src == dest or not os.path.isfile(src):
        return False
    try:
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError:
        return False
    return os.path.isfile(dest)


def _batch_seeks_ffmpeg_chunk_size(ffmpeg_input: str) -> int:
    """Avoid opening the same path many times in one ffmpeg process.

    Eight concurrent ``-ss … -i`` on one Windows mapped drive (``X:``) can
    deadlock the redirector: ffmpeg never returns, Kodi stays blocked, and the
    old timeout was ``chunk_len * 120`` (960s). Fast seek (one ``-i``) works.
    """
    if os.name == "nt":
        return 1
    lowered = ffmpeg_input.lower().replace("\\", "/")
    if lowered.startswith("//") or "://" in ffmpeg_input:
        return 1
    return _BATCH_SEEKS_FFMPEG_CHUNK


def _batch_seeks_chunk_timeout_sec(chunk_len: int) -> float:
    """Cap wait so a stuck ffmpeg cannot freeze Kodi for ~16 minutes."""
    per_input = max(1, int(chunk_len)) * _BATCH_SEEKS_TIMEOUT_PER_INPUT_SEC
    return max(
        _BATCH_SEEKS_MIN_CHUNK_TIMEOUT_SEC,
        min(_BATCH_SEEKS_MAX_CHUNK_TIMEOUT_SEC, per_input),
    )


def _chunk_timed_out(
    returncode: int | None,
    detail: str,
    elapsed: float,
    timeout: float,
) -> bool:
    if returncode != -1:
        return False
    text = (detail or "").strip().lower()
    return text == "timeout" or elapsed >= max(timeout - 0.5, 0.0)


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def _append_or_fallback_chunk(
    *,
    start_index: int,
    interval_sec: float,
    chunk_offsets: list[int],
    chunk_outputs: list[str],
    frame_paths: list[str],
    frame_fallback: FrameFallback | None,
    should_cancel: Callable[[], bool] | None,
    reason: str,
    skip_fast: bool = False,
) -> bool:
    """Collect chunk JPEGs, falling back or reusing the previous frame on miss."""
    for offset, output_path in zip(chunk_offsets, chunk_outputs):
        if should_cancel and should_cancel():
            return False
        timestamp = (start_index + offset) * interval_sec
        if os.path.isfile(output_path):
            frame_paths.append(output_path)
            continue
        try_fast = not skip_fast or not frame_paths
        if try_fast and _fallback_frame(
            frame_fallback,
            timestamp,
            output_path,
            reason=reason,
        ) and os.path.isfile(output_path):
            frame_paths.append(output_path)
            continue
        if frame_paths and _reuse_frame(frame_paths[-1], output_path):
            _log(
                f"Batch seeks: {reason} at {timestamp:.1f}s; "
                "reused previous frame and continuing",
                xbmc.LOGWARNING,
            )
            frame_paths.append(output_path)
            continue
        _log(
            f"Batch seeks: missing frame at {timestamp:.1f}s ({output_path!r})",
            xbmc.LOGWARNING,
        )
        return False
    return True


def _pyav_available() -> bool:
    try:
        import av  # noqa: F401

        return True
    except ImportError:
        return False


def _write_av_frame_jpeg(frame, output_path: str) -> None:
    import av

    out = av.open(output_path, mode="w")
    try:
        stream = out.add_stream("mjpeg", rate=1)
        stream.width = frame.width
        stream.height = frame.height
        stream.pix_fmt = "yuvj420p"
        if frame.format.name != "yuvj420p":
            frame = frame.reformat(format="yuvj420p")
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    finally:
        out.close()


def _fallback_frame(
    frame_fallback: FrameFallback | None,
    timestamp: float,
    output_path: str,
    *,
    reason: str,
) -> bool:
    if frame_fallback is None:
        return False
    _log(
        f"Batch seeks: {reason} at {timestamp:.1f}s — Fast single-frame fallback",
        xbmc.LOGWARNING,
    )
    try:
        return bool(frame_fallback(timestamp, output_path))
    except Exception as exc:
        _log(f"Batch seeks Fast fallback failed at {timestamp:.1f}s: {exc}", xbmc.LOGWARNING)
        return False


def _extract_tile_batch_seeks_pyav(
    ffmpeg_input: str,
    start_index: int,
    frame_count: int,
    interval_sec: float,
    tile_width: int,
    output_dir: str,
    tile_index: int,
    tile_count: int,
    debug: bool,
    should_cancel: Callable[[], bool] | None,
    frame_fallback: FrameFallback | None,
) -> list[str]:
    import av

    thumb_height = max(int(round(tile_width * 9 / 16)), 2)
    tile_start = start_index * interval_sec
    _log(
        f"Tile {tile_index + 1}/{tile_count}: batch seeks PyAV "
        f"{frame_count} frame(s) every {interval_sec:.1f}s from {tile_start:.1f}s"
    )

    frame_paths: list[str] = []
    container = av.open(ffmpeg_input)
    try:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for offset in range(frame_count):
            if should_cancel and should_cancel():
                return frame_paths
            thumb_index = start_index + offset
            timestamp = thumb_index * interval_sec
            frame_path = os.path.join(output_dir, f"{offset:05d}.jpg")
            seek_pts = int(timestamp / stream.time_base)
            container.seek(seek_pts, backward=True, stream=stream)
            saved = False
            for frame in container.decode(stream):
                if frame.pts is not None:
                    frame_time = float(frame.pts * stream.time_base)
                    if frame_time + (interval_sec * 0.5) < timestamp:
                        continue
                scaled = frame.reformat(
                    width=tile_width,
                    height=thumb_height,
                    format="yuvj420p",
                )
                _write_av_frame_jpeg(scaled, frame_path)
                frame_paths.append(frame_path)
                saved = True
                if debug:
                    _log(f"Batch seeks PyAV frame at {timestamp:.1f}s -> {frame_path}")
                break
            if not saved:
                if _fallback_frame(
                    frame_fallback,
                    timestamp,
                    frame_path,
                    reason="PyAV miss",
                ) and os.path.isfile(frame_path):
                    frame_paths.append(frame_path)
                elif frame_paths and _reuse_frame(frame_paths[-1], frame_path):
                    _log(
                        f"Batch seeks PyAV: no frame at {timestamp:.1f}s; "
                        "reused previous frame and continuing",
                        xbmc.LOGWARNING,
                    )
                    frame_paths.append(frame_path)
                else:
                    _log(
                        f"Batch seeks PyAV: no frame at {timestamp:.1f}s",
                        xbmc.LOGWARNING,
                    )
                    return frame_paths
    finally:
        container.close()

    _log(
        f"Tile {tile_index + 1}/{tile_count}: batch seeks PyAV extracted "
        f"{len(frame_paths)} frame(s)"
    )
    return frame_paths


def _extract_tile_batch_seeks_ffmpeg(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    start_index: int,
    frame_count: int,
    interval_sec: float,
    vf: str,
    output_dir: str,
    tile_index: int,
    tile_count: int,
    debug: bool,
    should_cancel: Callable[[], bool] | None,
    run_subprocess: Callable[..., tuple[int | None, str]],
    frame_fallback: FrameFallback | None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    tile_start = start_index * interval_sec
    chunk_size = _batch_seeks_ffmpeg_chunk_size(ffmpeg_input)
    _log(
        f"Tile {tile_index + 1}/{tile_count}: batch seeks ffmpeg "
        f"{frame_count} frame(s) every {interval_sec:.1f}s from {tile_start:.1f}s "
        f"(chunk={chunk_size})"
    )

    frame_paths: list[str] = []
    sequential = False
    for chunk_start in range(0, frame_count, chunk_size):
        if should_cancel and should_cancel():
            return frame_paths
        chunk_end = min(chunk_start + chunk_size, frame_count)
        chunk_len = chunk_end - chunk_start
        chunk_offsets = list(range(chunk_start, chunk_end))
        chunk_outputs = [
            os.path.join(output_dir, f"{offset:05d}.jpg") for offset in chunk_offsets
        ]
        timeout = _batch_seeks_chunk_timeout_sec(chunk_len)

        if sequential:
            if not _append_or_fallback_chunk(
                start_index=start_index,
                interval_sec=interval_sec,
                chunk_offsets=chunk_offsets,
                chunk_outputs=chunk_outputs,
                frame_paths=frame_paths,
                frame_fallback=frame_fallback,
                should_cancel=should_cancel,
                reason="post-timeout Fast seek",
            ):
                return frame_paths
            last_ts = (start_index + chunk_offsets[-1]) * interval_sec
            _log(
                f"Tile {tile_index + 1}/{tile_count}: batch seeks Fast "
                f"{len(frame_paths)}/{frame_count} at {last_ts:.1f}s"
            )
            continue

        cmd = [ffmpeg, "-y", "-loglevel", "error", *ffmpeg_input_args]
        for offset in chunk_offsets:
            timestamp = (start_index + offset) * interval_sec
            cmd.extend(
                [
                    "-ss",
                    f"{max(timestamp, 0.0):.3f}",
                    "-i",
                    ffmpeg_input,
                ]
            )
        for input_index, output_path in enumerate(chunk_outputs):
            cmd.extend(
                [
                    "-map",
                    f"{input_index}:v:0",
                    "-an",
                    "-sn",
                    "-dn",
                    "-frames:v",
                    "1",
                    "-vf",
                    vf,
                    "-q:v",
                    "2",
                    *output_color_args,
                    output_path,
                ]
            )
        _log(
            f"Batch seeks ffmpeg starting chunk {chunk_start}-{chunk_end - 1} "
            f"({chunk_len} input(s), timeout={timeout:.0f}s)",
            xbmc.LOGINFO if chunk_start == 0 else xbmc.LOGDEBUG,
        )
        started = time.monotonic()
        returncode, detail = run_subprocess(cmd, env, timeout, should_cancel)
        elapsed = time.monotonic() - started
        if returncode is None:
            return frame_paths

        timed_out = _chunk_timed_out(returncode, detail, elapsed, timeout)

        chunk_ok = returncode == 0
        if timed_out:
            sequential = True
            _log(
                f"Batch seeks ffmpeg chunk timed out after {elapsed:.1f}s "
                f"(limit {timeout:.0f}s, frames {chunk_start}-{chunk_end - 1}); "
                f"remaining thumbs use Fast seek",
                xbmc.LOGWARNING,
            )
        elif not chunk_ok:
            _log(
                f"Batch seeks ffmpeg chunk failed "
                f"(frames {chunk_start}-{chunk_end - 1}): {detail[:500]}",
                xbmc.LOGWARNING,
            )

        miss_reason = "ffmpeg chunk miss"
        if timed_out:
            miss_reason = "ffmpeg chunk timeout"
        elif not chunk_ok:
            miss_reason = "ffmpeg chunk fail"
        if not _append_or_fallback_chunk(
            start_index=start_index,
            interval_sec=interval_sec,
            chunk_offsets=chunk_offsets,
            chunk_outputs=chunk_outputs,
            frame_paths=frame_paths,
            frame_fallback=frame_fallback,
            should_cancel=should_cancel,
            reason=miss_reason,
            skip_fast=timed_out,
        ):
            return frame_paths

        _log(
            f"Batch seeks ffmpeg chunk {chunk_start}-{chunk_end - 1} "
            f"({len(chunk_outputs)} frame(s), {elapsed:.1f}s)",
            xbmc.LOGDEBUG,
        )

    _log(
        f"Tile {tile_index + 1}/{tile_count}: batch seeks ffmpeg extracted "
        f"{len(frame_paths)} frame(s)"
    )
    return frame_paths


def extract_tile_batch_seeks(
    ffmpeg: str,
    env: dict[str, str],
    ffmpeg_input: str,
    start_index: int,
    frame_count: int,
    interval_sec: float,
    tile_width: int,
    vf: str,
    output_dir: str,
    tile_index: int = 0,
    tile_count: int = 1,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    run_subprocess: Callable[..., tuple[int | None, str]] | None = None,
    force_ffmpeg: bool = False,
    frame_fallback: FrameFallback | None = None,
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    """Extract one tile via batch seeks (PyAV when safe, else chunked ffmpeg).

    ``frame_fallback(timestamp, output_path)`` should run a single Fast seek extract
    when a batch/PyAV capture misses.
    """
    if should_cancel and should_cancel() or frame_count <= 0:
        return []

    if run_subprocess is None:
        raise ValueError("run_subprocess callback is required")

    os.makedirs(output_dir, exist_ok=True)

    if not force_ffmpeg and _pyav_available():
        try:
            paths = _extract_tile_batch_seeks_pyav(
                ffmpeg_input,
                start_index,
                frame_count,
                interval_sec,
                tile_width,
                output_dir,
                tile_index,
                tile_count,
                debug,
                should_cancel,
                frame_fallback,
            )
            if len(paths) == frame_count:
                return paths
            _log(
                "Batch seeks PyAV incomplete; trying ffmpeg multi-seek",
                xbmc.LOGWARNING,
            )
        except Exception as exc:
            _log(f"Batch seeks PyAV failed: {exc}", xbmc.LOGWARNING)
    elif force_ffmpeg and debug:
        _log("Batch seeks: using ffmpeg (HDR / hardware decode)")

    return _extract_tile_batch_seeks_ffmpeg(
        ffmpeg,
        env,
        ffmpeg_input,
        start_index,
        frame_count,
        interval_sec,
        vf,
        output_dir,
        tile_index,
        tile_count,
        debug,
        should_cancel,
        run_subprocess,
        frame_fallback,
        output_color_args,
        ffmpeg_input_args,
    )


# Back-compat alias for older call sites / tests.
extract_tile_experimental = extract_tile_batch_seeks

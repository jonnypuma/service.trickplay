"""Experimental single-process tile extraction (PyAV seek loop or ffmpeg multi-seek)."""

from __future__ import annotations

import os
from collections.abc import Callable

import xbmc

_EXPERIMENTAL_FFMPEG_CHUNK = 25
_FAST_FRAME_TIMEOUT_SEC = 120.0


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


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


def _extract_tile_experimental_pyav(
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
) -> list[str]:
    import av

    thumb_height = max(int(round(tile_width * 9 / 16)), 2)
    tile_start = start_index * interval_sec
    _log(
        f"Tile {tile_index + 1}/{tile_count}: experimental PyAV "
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
                    _log(f"Experimental PyAV frame at {timestamp:.1f}s -> {frame_path}")
                break
            if not saved:
                _log(
                    f"Experimental PyAV: no frame at {timestamp:.1f}s",
                    xbmc.LOGWARNING,
                )
                return frame_paths
    finally:
        container.close()

    _log(
        f"Tile {tile_index + 1}/{tile_count}: experimental PyAV extracted "
        f"{len(frame_paths)} frame(s)"
    )
    return frame_paths


def _extract_tile_experimental_ffmpeg(
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
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    tile_start = start_index * interval_sec
    _log(
        f"Tile {tile_index + 1}/{tile_count}: experimental ffmpeg multi-seek "
        f"{frame_count} frame(s) every {interval_sec:.1f}s from {tile_start:.1f}s"
    )

    frame_paths: list[str] = []
    for chunk_start in range(0, frame_count, _EXPERIMENTAL_FFMPEG_CHUNK):
        if should_cancel and should_cancel():
            return frame_paths
        chunk_end = min(chunk_start + _EXPERIMENTAL_FFMPEG_CHUNK, frame_count)
        chunk_len = chunk_end - chunk_start
        cmd = [ffmpeg, "-y", "-loglevel", "error", *ffmpeg_input_args]
        chunk_outputs: list[str] = []
        for offset in range(chunk_start, chunk_end):
            timestamp = (start_index + offset) * interval_sec
            cmd.extend(
                [
                    "-ss",
                    f"{max(timestamp, 0.0):.3f}",
                    "-i",
                    ffmpeg_input,
                ]
            )
        for input_index, offset in enumerate(range(chunk_start, chunk_end)):
            output_path = os.path.join(output_dir, f"{offset:05d}.jpg")
            chunk_outputs.append(output_path)
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
        timeout = max(120.0, chunk_len * _FAST_FRAME_TIMEOUT_SEC)
        returncode, detail = run_subprocess(cmd, env, timeout, should_cancel)
        if returncode is None:
            return frame_paths
        if returncode != 0:
            _log(
                f"Experimental ffmpeg multi-seek failed "
                f"(frames {chunk_start}-{chunk_end - 1}): {detail[:500]}",
                xbmc.LOGWARNING,
            )
            return frame_paths
        for output_path in chunk_outputs:
            if os.path.isfile(output_path):
                frame_paths.append(output_path)
            else:
                _log(
                    f"Experimental ffmpeg: missing {output_path!r}",
                    xbmc.LOGWARNING,
                )
                return frame_paths
        if debug:
            _log(
                f"Experimental ffmpeg chunk {chunk_start}-{chunk_end - 1} "
                f"({len(chunk_outputs)} frame(s))"
            )

    _log(
        f"Tile {tile_index + 1}/{tile_count}: experimental ffmpeg extracted "
        f"{len(frame_paths)} frame(s)"
    )
    return frame_paths


def extract_tile_experimental(
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
    output_color_args: tuple[str, ...] = (),
    ffmpeg_input_args: tuple[str, ...] = (),
) -> list[str]:
    """One open + seek loop (PyAV) or one ffmpeg process with many seeks per chunk."""
    if should_cancel and should_cancel() or frame_count <= 0:
        return []

    if run_subprocess is None:
        raise ValueError("run_subprocess callback is required")

    os.makedirs(output_dir, exist_ok=True)

    if not force_ffmpeg and _pyav_available():
        try:
            paths = _extract_tile_experimental_pyav(
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
            )
            if len(paths) == frame_count:
                return paths
            _log(
                "Experimental PyAV incomplete; trying ffmpeg multi-seek fallback",
                xbmc.LOGWARNING,
            )
        except Exception as exc:
            _log(f"Experimental PyAV failed: {exc}", xbmc.LOGWARNING)
    elif force_ffmpeg and debug:
        _log("Experimental: using ffmpeg for HDR tone mapping")

    return _extract_tile_experimental_ffmpeg(
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
        output_color_args,
        ffmpeg_input_args,
    )

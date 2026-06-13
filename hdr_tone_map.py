"""Optional HDR/DV to SDR tone mapping for trickplay thumbnail generation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass

import xbmc
import xbmcvfs

from ffmpeg_media import _stream_to_pipe, resolve_ffmpeg_media_path

_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67", "smpte240m"})
_HDR_PRIMARIES = frozenset({"bt2020", "bt2020nc", "bt2020c"})
_HDR_SIDE_DATA_HINTS = (
    "dovi",
    "dolby vision",
    "mastering display",
    "content light level",
    "hdr dynamic metadata",
    "hdr10+",
    "dynamic hdr",
)
_10BIT_PIX_FMT_RE = re.compile(r"(10(le|be)?|p010)", re.IGNORECASE)
_DOVI_PROFILE_RE = re.compile(r"profile[^0-9]*([0-9]{1,2})", re.IGNORECASE)
_DOVI_RPU_EXTRACT_SEC = 2.0
_DOVI_PROBE_TIMEOUT_SEC = 90.0
_TONEMAP_MODE_NONE = "none"
_TONEMAP_MODE_SIMPLE = "simple"
_TONEMAP_MODE_ZSCALE = "zscale"
_TONEMAP_MODE_LIBPLACEBO = "libplacebo"
_TONEMAP_TRANSFER_PQ = "smpte2084"
_TONEMAP_TRANSFER_HLG = "arib-std-b67"
_tonemap_support_cache: dict[str, str] = {}
_logged_hdr_dovi_tool_fallback_setting = False


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


@dataclass(frozen=True)
class ThumbFilterContext:
    """Precomputed video filter chain for one generation job."""

    apply_tonemap: bool
    tonemap_mode: str
    thumb_vf: str
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ
    ffmpeg_color_args: tuple[str, ...] = ()


def ffmpeg_sdr_output_color_args() -> tuple[str, ...]:
    """Output tags for tone-mapped SDR JPEGs (full-range yuvj420p for mjpeg in ffmpeg 8+)."""
    return (
        "-strict",
        "unofficial",
        "-pix_fmt",
        "yuvj420p",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-color_range",
        "pc",
    )


def _normalize_hdr_transfer(transfer: str | None) -> str:
    cleaned = (transfer or "").strip().lower()
    if cleaned == _TONEMAP_TRANSFER_HLG:
        return _TONEMAP_TRANSFER_HLG
    if cleaned in _HDR_TRANSFERS:
        return cleaned
    return _TONEMAP_TRANSFER_PQ


def _hdr_setparams_prefix(transfer: str) -> str:
    transfer = _normalize_hdr_transfer(transfer)
    return (
        "setparams=color_primaries=bt2020:"
        f"color_trc={transfer}:colorspace=bt2020nc:range=tv,"
    )


def _tonemap_algorithm(transfer: str) -> str:
    if _normalize_hdr_transfer(transfer) == _TONEMAP_TRANSFER_HLG:
        return "bt2390"
    return "hable"


def _zscale_tonemap_chain(transfer: str) -> str:
    """Jellyfin-style HDR10/HLG to SDR (linearize, gamut map, tonemap, tag 709)."""
    algorithm = _tonemap_algorithm(transfer)
    return (
        f"{_hdr_setparams_prefix(transfer)}"
        "zscale=t=linear:npl=100,format=gbrpf32le,"
        "zscale=p=bt709,"
        f"tonemap=tonemap={algorithm}:desat=0,"
        "zscale=t=bt709:m=bt709:r=full,format=yuvj420p,"
    )


def _libplacebo_tonemap_chain() -> str:
    return (
        "libplacebo=tonemapping=hable:desaturation=0:peak_detect=1:"
        "color_mapping=perceptual:color_primaries=bt709:color_trc=bt709:"
        "colorspace=bt709,format=yuvj420p,"
    )


def _simple_tonemap_chain(transfer: str) -> str:
    """Best-effort when zscale/libplacebo are unavailable (quality may vary)."""
    algorithm = _tonemap_algorithm(transfer)
    if algorithm == "bt2390":
        tonemap_filter = f"tonemap=tonemap={algorithm}:desat=0"
    else:
        tonemap_filter = f"tonemap=tonemap={algorithm}:desat=0:peak=100"
    return (
        f"{_hdr_setparams_prefix(transfer)}"
        "format=gbrpf32le,"
        f"{tonemap_filter},"
        "format=yuvj420p,"
    )


def _scale_pad_filter(tile_width: int) -> str:
    thumb_height = max(int(round(tile_width * 9 / 16)), 2)
    return (
        f"scale={tile_width}:{thumb_height}:force_original_aspect_ratio=decrease,"
        f"pad={tile_width}:{thumb_height}:(ow-iw)/2:(oh-ih)/2"
    )


def _tonemap_prefix(mode: str, hdr_transfer: str = _TONEMAP_TRANSFER_PQ) -> str:
    if mode == _TONEMAP_MODE_ZSCALE:
        return _zscale_tonemap_chain(hdr_transfer)
    if mode == _TONEMAP_MODE_LIBPLACEBO:
        return _libplacebo_tonemap_chain()
    if mode == _TONEMAP_MODE_SIMPLE:
        return _simple_tonemap_chain(hdr_transfer)
    return ""


def build_thumb_video_filter(
    tile_width: int,
    apply_tonemap: bool,
    tonemap_mode: str,
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ,
) -> str:
    scale_pad = _scale_pad_filter(tile_width)
    if apply_tonemap and tonemap_mode in (
        _TONEMAP_MODE_ZSCALE,
        _TONEMAP_MODE_SIMPLE,
        _TONEMAP_MODE_LIBPLACEBO,
    ):
        return f"{_tonemap_prefix(tonemap_mode, hdr_transfer)}{scale_pad}"
    return f"yadif=0:-1:0,{scale_pad}"


def build_fps_batch_filter(
    tile_width: int,
    interval_sec: float,
    apply_tonemap: bool,
    tonemap_mode: str,
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ,
) -> str:
    if interval_sec == int(interval_sec):
        fps_expr = f"1/{int(interval_sec)}"
    else:
        fps_expr = f"{1.0 / interval_sec:.8g}"
    thumb_vf = build_thumb_video_filter(
        tile_width, apply_tonemap, tonemap_mode, hdr_transfer
    )
    return f"fps={fps_expr},{thumb_vf}"


def _ffmpeg_lists_filter(filters_text: str, filter_name: str) -> bool:
    """True when ffmpeg -filters output lists a video filter by name."""
    # ffmpeg 8.x lines look like: ".S tonemap           V->V       ..."
    pattern = rf"^\s*\S+\s+{re.escape(filter_name)}\s+V->"
    if re.search(pattern, filters_text, re.MULTILINE):
        return True
    # Some shared builds pad columns differently; accept name before V-> on the line.
    loose = rf"^\s*\S*\s*{re.escape(filter_name)}\s+.*V->"
    return re.search(loose, filters_text, re.MULTILINE) is not None


def _tonemap_cache_key(ffmpeg: str, env: dict[str, str] | None) -> str:
    ld_path = ""
    if env:
        ld_path = env.get("LD_LIBRARY_PATH", "") or ""
    return f"{ffmpeg or ''}\0{ld_path}"


def invalidate_tonemap_support_cache() -> None:
    """Clear cached ffmpeg filter detection (e.g. after installing custom ffmpeg)."""
    _tonemap_support_cache.clear()


def detect_tonemap_support(
    ffmpeg: str,
    env: dict[str, str] | None,
    *,
    use_cache: bool = True,
) -> str:
    cache_key = _tonemap_cache_key(ffmpeg, env)
    if use_cache:
        cached = _tonemap_support_cache.get(cache_key)
        if cached is not None:
            return cached

    mode = _TONEMAP_MODE_NONE
    ld_path = env.get("LD_LIBRARY_PATH", "") if env else ""
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        has_tonemap = _ffmpeg_lists_filter(text, "tonemap")
        has_zscale = _ffmpeg_lists_filter(text, "zscale")
        has_libplacebo = _ffmpeg_lists_filter(text, "libplacebo")
        if has_tonemap and has_zscale:
            mode = _TONEMAP_MODE_ZSCALE
        elif has_libplacebo:
            mode = _TONEMAP_MODE_LIBPLACEBO
        elif has_tonemap:
            mode = _TONEMAP_MODE_SIMPLE
        if mode in (_TONEMAP_MODE_NONE, _TONEMAP_MODE_SIMPLE):
            _log(
                f"ffmpeg filter probe ({ffmpeg}): "
                f"zscale={has_zscale} libplacebo={has_libplacebo} tonemap={has_tonemap} "
                f"rc={completed.returncode} LD_LIBRARY_PATH={ld_path or '(unset)'}",
                xbmc.LOGWARNING if mode == _TONEMAP_MODE_SIMPLE else xbmc.LOGINFO,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip().splitlines()
                if detail:
                    _log(f"ffmpeg -filters stderr: {detail[0]}", xbmc.LOGWARNING)
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"Could not detect ffmpeg tonemap filters: {exc}", xbmc.LOGWARNING)

    if use_cache:
        _tonemap_support_cache[cache_key] = mode
    if mode == _TONEMAP_MODE_NONE:
        _log("ffmpeg tonemap filter not available; HDR tone mapping disabled", xbmc.LOGWARNING)
    elif mode == _TONEMAP_MODE_ZSCALE:
        _log("HDR tone mapping: using zscale + tonemap (Jellyfin-style chain)")
    elif mode == _TONEMAP_MODE_LIBPLACEBO:
        _log("HDR tone mapping: using libplacebo")
    else:
        _log(
            "HDR tone mapping: using tonemap only (no zscale/libplacebo; "
            "quality may be poor — prefer ffmpeg with libzimg or Jellyfin sidecars)",
            xbmc.LOGWARNING,
        )
    return mode


def _side_data_list_looks_hdr(side_data_list: list | None) -> bool:
    is_hdr, _reason = _side_data_list_hdr_reason(side_data_list)
    return is_hdr


def _dovi_profile_from_side_entry(side: dict) -> str | None:
    side_type = str(side.get("side_data_type") or "")
    if "dovi configuration record" not in side_type.lower():
        return None
    for key in ("dv_profile", "dovi_profile", "profile"):
        value = side.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    match = _DOVI_PROFILE_RE.search(side_type)
    if match:
        return match.group(1)
    return "unknown"


def _side_data_list_hdr_reason(side_data_list: list | None) -> tuple[bool, str]:
    for side in side_data_list or []:
        side_type = (side.get("side_data_type") or "").lower()
        if any(hint in side_type for hint in _HDR_SIDE_DATA_HINTS):
            return True, f"side_data={side.get('side_data_type')}"
        profile = _dovi_profile_from_side_entry(side)
        if profile is not None:
            return True, f"DOVI configuration record profile={profile}"
    return False, ""


def _video_stream_is_enhancement_layer(stream: dict) -> bool:
    if (stream.get("codec_type") or "").lower() != "video":
        return False
    codec_name = (stream.get("codec_name") or "").lower()
    if "enhancement" in codec_name:
        return True
    tags = stream.get("tags") or {}
    if isinstance(tags, dict):
        for key, value in tags.items():
            combined = f"{key} {value}".lower()
            if "enhancement" in combined or "dolby vision" in combined:
                return True
    return False


def _stream_entry_looks_hdr(stream: dict) -> tuple[bool, str]:
    if _video_stream_is_enhancement_layer(stream):
        return True, "Dolby Vision enhancement-layer video stream"

    is_hdr, reason = _media_dict_looks_hdr(stream)
    if is_hdr:
        return True, reason

    side_hdr, side_reason = _side_data_list_hdr_reason(stream.get("side_data_list"))
    if side_hdr:
        return True, side_reason

    return False, (
        f"transfer={stream.get('color_transfer') or 'unknown'} "
        f"primaries={stream.get('color_primaries') or 'unknown'} "
        f"pix_fmt={stream.get('pix_fmt') or 'unknown'}"
    )


def _looks_10bit_pix_fmt(pix_fmt: str) -> bool:
    return bool(_10BIT_PIX_FMT_RE.search(pix_fmt or ""))


def _media_dict_looks_hdr(entry: dict) -> tuple[bool, str]:
    """Return (is_hdr, reason) for an ffprobe stream or frame dict."""
    transfer = (entry.get("color_transfer") or "").strip().lower()
    primaries = (entry.get("color_primaries") or "").strip().lower()
    color_space = (entry.get("color_space") or "").strip().lower()
    pix_fmt = (entry.get("pix_fmt") or "").strip().lower()
    codec_name = (entry.get("codec_name") or "").strip().lower()

    if transfer in _HDR_TRANSFERS:
        return True, f"transfer={transfer}"

    if _side_data_list_looks_hdr(entry.get("side_data_list")):
        return True, "side_data HDR metadata"

    if primaries in _HDR_PRIMARIES and transfer in _HDR_TRANSFERS:
        return True, f"primaries={primaries} transfer={transfer}"

    if color_space in _HDR_PRIMARIES and transfer in _HDR_TRANSFERS:
        return True, f"colorspace={color_space} transfer={transfer}"

    if primaries in _HDR_PRIMARIES and _looks_10bit_pix_fmt(pix_fmt):
        return True, f"bt2020 10-bit pix_fmt={pix_fmt}"

    if transfer in _HDR_TRANSFERS and _looks_10bit_pix_fmt(pix_fmt):
        return True, f"HDR transfer 10-bit pix_fmt={pix_fmt}"

    # Dolby Vision remuxes often tag bt2020 primaries with bt709 transfer at stream level.
    if primaries in _HDR_PRIMARIES and transfer in ("bt709", "") and _looks_10bit_pix_fmt(pix_fmt):
        return True, f"bt2020 primaries + 10-bit ({pix_fmt})"

    profile = (entry.get("profile") or "").lower()
    if (
        codec_name in ("hevc", "h265")
        and "main 10" in profile
        and _looks_10bit_pix_fmt(pix_fmt)
        and primaries in _HDR_PRIMARIES
    ):
        return True, f"HEVC Main 10 bt2020 ({pix_fmt})"

    return False, (
        f"transfer={transfer or 'unknown'} primaries={primaries or 'unknown'} "
        f"pix_fmt={pix_fmt or 'unknown'}"
    )


def _parse_hdr_from_ffprobe_json(
    payload: str,
    debug: bool,
    *,
    source_label: str,
) -> tuple[bool, str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False, "invalid ffprobe json"

    for stream in data.get("streams") or []:
        if (stream.get("codec_type") or "").lower() != "video":
            continue
        is_hdr, reason = _stream_entry_looks_hdr(stream)
        if is_hdr:
            if debug:
                _log(f"HDR detected from {source_label} stream metadata: {reason}")
            return True, reason

    for frame in data.get("frames") or []:
        is_hdr, reason = _media_dict_looks_hdr(frame)
        if is_hdr:
            if debug:
                _log(f"HDR detected from {source_label} frame metadata: {reason}")
            return True, reason
        side_hdr, side_reason = _side_data_list_hdr_reason(frame.get("side_data_list"))
        if side_hdr:
            if debug:
                _log(f"HDR detected from {source_label} frame side_data: {side_reason}")
            return True, side_reason

    return False, "no HDR stream/frame signals"


def _stream_probe_entries() -> str:
    return (
        "stream=codec_type,codec_name,profile,pix_fmt,bits_per_raw_sample,"
        "color_transfer,color_primaries,color_space,side_data_list,tags"
    )


def _ffprobe_json(
    ffprobe: str,
    args: list[str],
    env: dict[str, str] | None,
    timeout: float,
) -> str | None:
    try:
        completed = subprocess.run(
            [ffprobe, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"HDR ffprobe failed: {exc}", xbmc.LOGWARNING)
        return None

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            _log(f"HDR ffprobe error: {detail[:300]}", xbmc.LOGWARNING)
        return None

    return completed.stdout or "{}"


def _ffprobe_hdr_local(ffprobe: str, local_path: str, env: dict[str, str] | None, debug: bool) -> bool:
    stream_args = [
        "-v",
        "error",
        "-show_entries",
        _stream_probe_entries(),
        "-of",
        "json",
        local_path,
    ]
    payload = _ffprobe_json(ffprobe, stream_args, env, 120.0)
    if payload:
        is_hdr, reason = _parse_hdr_from_ffprobe_json(
            payload, debug, source_label="stream"
        )
        if is_hdr:
            return True
        if debug:
            _log(f"Stream HDR probe negative: {reason}")

    frame_args = [
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        "%+#1",
        "-show_frames",
        "-show_entries",
        "frame=pix_fmt,color_transfer,color_primaries,color_space,side_data_list",
        "-of",
        "json",
        local_path,
    ]
    payload = _ffprobe_json(ffprobe, frame_args, env, 180.0)
    if not payload:
        return False

    is_hdr, reason = _parse_hdr_from_ffprobe_json(
        payload, debug, source_label="first-frame"
    )
    if not is_hdr and debug:
        _log(f"Frame HDR probe negative: {reason}")
    return is_hdr


def _ffprobe_hdr_via_pipe(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    debug: bool,
) -> bool:
    stream_args = [
        "-v",
        "error",
        "-probesize",
        "50M",
        "-analyzeduration",
        "50M",
        "-show_entries",
        _stream_probe_entries(),
        "-of",
        "json",
        "pipe:0",
    ]
    payload = _ffprobe_hdr_via_pipe_impl(media_path, ffprobe, env, stream_args, 120.0)
    if payload:
        is_hdr, reason = _parse_hdr_from_ffprobe_json(
            payload, debug, source_label="stream pipe"
        )
        if is_hdr:
            return True
        if debug:
            _log(f"Stream HDR pipe probe negative: {reason}")

    frame_args = [
        "-v",
        "error",
        "-probesize",
        "50M",
        "-analyzeduration",
        "50M",
        "-select_streams",
        "v:0",
        "-read_intervals",
        "%+#1",
        "-show_frames",
        "-show_entries",
        "frame=pix_fmt,color_transfer,color_primaries,color_space,side_data_list",
        "-of",
        "json",
        "pipe:0",
    ]
    payload = _ffprobe_hdr_via_pipe_impl(media_path, ffprobe, env, frame_args, 180.0)
    if not payload:
        return False

    is_hdr, reason = _parse_hdr_from_ffprobe_json(
        payload, debug, source_label="first-frame pipe"
    )
    if not is_hdr and debug:
        _log(f"Frame HDR pipe probe negative: {reason}")
    return is_hdr


def _dovi_tool_candidates() -> list[str]:
    candidates: list[str] = []
    addon_paths: list[str] = []
    try:
        import xbmcaddon

        addon_paths.append(xbmcaddon.Addon().getAddonInfo("path"))
    except RuntimeError:
        pass
    addon_paths.append(os.path.dirname(os.path.abspath(__file__)))

    seen: set[str] = set()
    for addon_path in addon_paths:
        if not addon_path or addon_path in seen:
            continue
        seen.add(addon_path)
        for name in ("dovi_tool", "dovi_tool.exe"):
            candidates.append(os.path.join(addon_path, name))

    for name in ("dovi_tool", "dovi_tool.exe"):
        candidates.append(name)
    return candidates


def find_dovi_tool() -> str | None:
    """Return path to dovi_tool in the add-on folder or on PATH."""
    return _find_dovi_tool()


def _find_dovi_tool() -> str | None:
    for candidate in _dovi_tool_candidates():
        if candidate in ("dovi_tool", "dovi_tool.exe"):
            found = shutil.which(candidate)
            if found:
                return found
            continue
        if xbmcvfs.exists(candidate):
            return candidate
        if os.path.isfile(candidate):
            return candidate
    return None


def _dovi_profile_from_info_output(payload: str) -> str | None:
    stripped = (payload or "").strip()
    if not stripped:
        return None
    try:
        info = json.loads(stripped)
    except json.JSONDecodeError:
        match = _DOVI_PROFILE_RE.search(stripped)
        return match.group(1) if match else "unknown"
    for key in ("dovi_profile", "dv_profile", "profile"):
        value = info.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown"


def _probe_hdr_via_dovi_tool(
    local_path: str,
    ffmpeg: str,
    env: dict[str, str] | None,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    dovi_tool = _find_dovi_tool()
    if not dovi_tool:
        _log("HDR dovi_tool fallback: dovi_tool not found (addon folder or PATH)", xbmc.LOGWARNING)
        return False, "dovi_tool missing"

    rpu_fd, rpu_file = tempfile.mkstemp(suffix=".bin", prefix="trickplay_dovi_rpu_")
    os.close(rpu_fd)
    try:
        ffmpeg_cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            local_path,
            "-c:v",
            "copy",
            "-to",
            str(_DOVI_RPU_EXTRACT_SEC),
            "-f",
            "hevc",
            "-",
        ]
        extract_cmd = [dovi_tool, "extract-rpu", "-", "-o", rpu_file]
        try:
            ff_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            dt_proc = subprocess.Popen(
                extract_cmd,
                stdin=ff_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            if ff_proc.stdout is not None:
                ff_proc.stdout.close()
            dt_proc.communicate(timeout=_DOVI_PROBE_TIMEOUT_SEC)
            ff_proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
            _log(f"HDR dovi_tool extract failed: {exc}", xbmc.LOGWARNING)
            return False, f"dovi_tool extract failed: {exc}"

        if not os.path.isfile(rpu_file) or os.path.getsize(rpu_file) <= 0:
            if debug:
                _log(
                    f"HDR dovi_tool fallback: no RPU extracted for "
                    f"{os.path.basename(local_path)}"
                )
            return False, "no RPU extracted"

        info_cmd = [dovi_tool, "info", "-i", rpu_file, "-f", "0"]
        try:
            completed = subprocess.run(
                info_cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=30.0,
                env=env,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            _log(f"HDR dovi_tool info failed: {exc}", xbmc.LOGWARNING)
            return True, "dovi_tool RPU extracted (info unavailable)"

        profile = _dovi_profile_from_info_output(
            completed.stdout or completed.stderr or ""
        )
        reason = f"dovi_tool DOVI profile {profile}" if profile else "dovi_tool RPU extracted"
        if debug:
            _log(f"HDR detected via dovi_tool fallback: {reason}")
        return True, reason
    finally:
        try:
            os.remove(rpu_file)
        except OSError:
            pass


def _ffprobe_hdr_via_pipe_impl(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    ffprobe_args: list[str],
    timeout: float,
) -> str | None:
    try:
        proc = subprocess.Popen(
            [ffprobe, *ffprobe_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        _log(f"HDR pipe probe failed to start for {media_path}: {exc}", xbmc.LOGWARNING)
        return None

    feeder = threading.Thread(
        target=_stream_to_pipe,
        args=(media_path, proc),
        daemon=True,
    )
    feeder.start()
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        _log(f"HDR pipe probe timed out for {media_path}", xbmc.LOGWARNING)
        return None
    finally:
        feeder.join(timeout=1)

    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        if detail:
            _log(f"HDR pipe probe failed: {detail[:300]}", xbmc.LOGWARNING)
        return None

    return (stdout or b"").decode("utf-8", errors="replace")


def probe_video_is_hdr(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    ffmpeg: str | None = None,
    dovi_tool_fallback: bool = False,
    debug: bool = False,
) -> bool:
    if not ffprobe or not media_path:
        return False

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        ffprobe_hdr = _ffprobe_hdr_via_pipe(media_path, ffprobe, env, debug)
        if ffprobe_hdr:
            return True
        if dovi_tool_fallback:
            _log(
                "HDR dovi_tool fallback skipped for VFS stream path "
                f"({os.path.basename(media_path)})",
                xbmc.LOGINFO,
            )
        return False

    local_path = ffmpeg_input
    if not local_path:
        return False
    if not os.path.isfile(local_path):
        if not xbmcvfs.exists(local_path):
            return False

    if _ffprobe_hdr_local(ffprobe, local_path, env, debug):
        return True

    if dovi_tool_fallback and ffmpeg:
        is_hdr, reason = _probe_hdr_via_dovi_tool(
            local_path, ffmpeg, env, debug=debug
        )
        if is_hdr:
            _log(
                f"HDR confirmed via dovi_tool fallback for "
                f"{os.path.basename(media_path)}: {reason}"
            )
            return True
        if debug:
            _log(f"HDR dovi_tool fallback negative: {reason}")

    return False


def probe_hdr_transfer(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    debug: bool = False,
) -> str:
    """Return HDR transfer characteristic for tonemap filter tagging (PQ default)."""
    if not ffprobe or not media_path:
        return _TONEMAP_TRANSFER_PQ

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    stream_args = [
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,color_transfer",
        "-of",
        "json",
    ]
    if use_vfs_stream:
        stream_args.extend(
            [
                "-probesize",
                "50M",
                "-analyzeduration",
                "50M",
                "pipe:0",
            ]
        )
        payload = _ffprobe_hdr_via_pipe_impl(
            media_path, ffprobe, env, stream_args, 120.0
        )
    else:
        local_path = ffmpeg_input
        if not local_path:
            return _TONEMAP_TRANSFER_PQ
        stream_args.append(local_path)
        payload = _ffprobe_json(ffprobe, stream_args, env, 120.0)

    if not payload:
        return _TONEMAP_TRANSFER_PQ

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _TONEMAP_TRANSFER_PQ

    for stream in data.get("streams") or []:
        if (stream.get("codec_type") or "").lower() != "video":
            continue
        transfer = _normalize_hdr_transfer(stream.get("color_transfer"))
        if debug:
            _log(f"HDR transfer for tonemap: {transfer}")
        return transfer

    return _TONEMAP_TRANSFER_PQ


def resolve_thumb_filter_context(
    *,
    hdr_tone_map_enabled: bool,
    hdr_dovi_tool_fallback: bool = False,
    tile_width: int,
    media_path: str,
    ffmpeg: str,
    ffprobe: str,
    env: dict[str, str] | None,
    debug: bool = False,
) -> ThumbFilterContext:
    tonemap_mode = _TONEMAP_MODE_NONE
    apply_tonemap = False
    hdr_transfer = _TONEMAP_TRANSFER_PQ

    if hdr_tone_map_enabled:
        global _logged_hdr_dovi_tool_fallback_setting
        if hdr_dovi_tool_fallback and not _logged_hdr_dovi_tool_fallback_setting:
            _log(
                "HDR dovi_tool fallback setting: enabled "
                "(used when ffprobe finds no HDR signals; looks in addon folder then PATH)"
            )
            _logged_hdr_dovi_tool_fallback_setting = True
        tonemap_mode = detect_tonemap_support(ffmpeg, env)
        if tonemap_mode != _TONEMAP_MODE_NONE and probe_video_is_hdr(
            media_path,
            ffprobe,
            env,
            ffmpeg=ffmpeg,
            dovi_tool_fallback=hdr_dovi_tool_fallback,
            debug=debug,
        ):
            apply_tonemap = True
            hdr_transfer = probe_hdr_transfer(
                media_path, ffprobe, env, debug=debug
            )
            _log(
                f"HDR tone mapping enabled for {os.path.basename(media_path)} "
                f"({tonemap_mode}, transfer={hdr_transfer})"
            )
        elif tonemap_mode != _TONEMAP_MODE_NONE:
            _log(
                f"No HDR signals from ffprobe for {os.path.basename(media_path)}; "
                f"tone mapping skipped (enable Debug logging for probe details)",
                xbmc.LOGINFO,
            )

    thumb_vf = build_thumb_video_filter(
        tile_width, apply_tonemap, tonemap_mode, hdr_transfer
    )
    color_args = ffmpeg_sdr_output_color_args() if apply_tonemap else ()
    return ThumbFilterContext(
        apply_tonemap=apply_tonemap,
        tonemap_mode=tonemap_mode if apply_tonemap else _TONEMAP_MODE_NONE,
        thumb_vf=thumb_vf,
        hdr_transfer=hdr_transfer,
        ffmpeg_color_args=color_args,
    )

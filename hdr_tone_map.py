"""Optional HDR/DV to SDR tone mapping for trickplay thumbnail generation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import threading
from collections.abc import Callable
from dataclasses import dataclass

import xbmc
import xbmcvfs

from temp_cleanup import DOVI_TEMP_ROOT
from ffmpeg_media import _stream_to_pipe, resolve_ffmpeg_media_path
from ffmpeg_tools import (
    _local_path,
    default_dovi_tool_path,
    legacy_dovi_tool_paths,
    migrate_legacy_dovi_tool_if_needed,
    subprocess_hide_window_kwargs,
)

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
_FILENAME_DOVI_RE = re.compile(r"[._]dv[._]", re.IGNORECASE)
_DOVI_RPU_EXTRACT_SEC = 2.0
_DOVI_PROBE_TIMEOUT_SEC = 90.0
_DOVI_CONVERT_TIMEOUT_MIN_SEC = 600.0
_DOVI_CONVERT_TIMEOUT_MAX_SEC = 7200.0
_vulkan_available_cache: dict[str, bool] = {}
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


def _dovi_prep_temp_root() -> str:
    """Large-temp root on special://temp (not OS /tmp — often too small on CoreELEC)."""
    os.makedirs(DOVI_TEMP_ROOT, exist_ok=True)
    return DOVI_TEMP_ROOT


def _create_dovi_prep_work_dir() -> str:
    work = os.path.join(_dovi_prep_temp_root(), uuid.uuid4().hex)
    os.makedirs(work, exist_ok=True)
    return work


def _media_file_size_bytes(local_path: str) -> int:
    try:
        if os.path.isfile(local_path):
            return os.path.getsize(local_path)
    except OSError:
        pass
    try:
        stat_obj = xbmcvfs.Stat(local_path)
        size = getattr(stat_obj, "st_size", None)
        if callable(size):
            size = size()
        if size is None:
            size = getattr(stat_obj, "size", None)
            if callable(size):
                size = size()
        return int(size or 0)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def _disk_free_bytes(path: str) -> int | None:
    try:
        local = xbmcvfs.translatePath(path) if path.startswith("special://") else path
        return shutil.disk_usage(local).free
    except OSError:
        return None


def _dovi_convert_disk_check(local_input: str, work_dir: str) -> bool:
    """Ensure enough free space for a full-file HEVC rewrite (~source video size)."""
    source_size = _media_file_size_bytes(local_input)
    if source_size <= 0:
        return True
    needed = int(source_size * 1.1) + (32 * 1024 * 1024)
    free = _disk_free_bytes(work_dir)
    if free is None:
        return True
    if free >= needed:
        _log(
            f"Dolby Vision prep: {free // (1024 * 1024)} MB free at {work_dir} "
            f"(need ~{needed // (1024 * 1024)} MB for converted HEVC)"
        )
        return True
    _log(
        f"Dolby Vision prep: not enough disk space at {work_dir}: "
        f"need ~{needed // (1024 * 1024)} MB, have {free // (1024 * 1024)} MB. "
        f"Profile 5 convert writes a full HEVC copy under special://temp — "
        f"free space on /storage or run batch generation on a device with more temp storage",
        xbmc.LOGERROR,
    )
    return False


@dataclass(frozen=True)
class ThumbFilterContext:
    """Precomputed video filter chain for one generation job."""

    apply_tonemap: bool
    tonemap_mode: str
    thumb_vf: str
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ
    dolby_vision: bool = False
    use_dovi_tool_zscale_prep: bool = False
    ffmpeg_color_args: tuple[str, ...] = ()
    ffmpeg_input_args: tuple[str, ...] = ()


def ffmpeg_libplacebo_input_args() -> tuple[str, ...]:
    """Vulkan device init for libplacebo (Dolby Vision / HDR tone map)."""
    return ("-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk")


_HW_DOWNLOAD_PREFIX = "hwdownload,format=p010le,"


def ffmpeg_d3d11_hwaccel_input_args() -> tuple[str, ...]:
    """Windows D3D11VA decode (pairs with hwdownload before CPU/GPU filters)."""
    return ("-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11")


def windows_hw_decode_available() -> bool:
    """True when this host can use the Windows D3D11VA thumbnail decode path."""
    return sys.platform == "win32"


def _primary_video_stream_from_ffprobe(payload: str) -> dict | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    for stream in data.get("streams") or []:
        if (stream.get("codec_type") or "").lower() != "video":
            continue
        if _video_stream_is_enhancement_layer(stream):
            continue
        return stream
    return None


def probe_windows_hw_decode_eligible(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """
    True when the Windows D3D11VA path applies: HEVC with 10-bit and/or HDR/DV.

    AVC and 8-bit SDR HEVC should use software decode only (p010le hwdownload path).
    """
    if not ffprobe or not media_path:
        return False, "ffprobe or media path unavailable"

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        return False, "VFS stream input"
    if not ffmpeg_input:
        return False, "no local input path"
    if not os.path.isfile(ffmpeg_input) and not xbmcvfs.exists(ffmpeg_input):
        return False, "file not found"

    stream_args = [
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        _stream_probe_entries(),
        "-of",
        "json",
        ffmpeg_input,
    ]
    payload = _ffprobe_json(ffprobe, stream_args, env, 120.0)
    if not payload:
        return False, "ffprobe failed"

    video = _primary_video_stream_from_ffprobe(payload)
    if video is None:
        return False, "no video stream"

    codec = (video.get("codec_name") or "").lower()
    if codec not in ("hevc", "h265"):
        reason = f"codec={codec or 'unknown'} (D3D11VA path is HEVC only)"
        if debug:
            _log(f"Windows HW decode skipped: {reason}")
        return False, reason

    pix_fmt = (video.get("pix_fmt") or "").strip()
    is_hdr, hdr_reason = _stream_entry_looks_hdr(video)
    is_10bit = _looks_10bit_pix_fmt(pix_fmt)
    profile = (video.get("profile") or "").lower()
    main10 = "main 10" in profile

    if is_hdr or is_10bit or main10:
        detail = f"HEVC {pix_fmt or 'unknown'}"
        if is_hdr:
            detail = f"{detail}, {hdr_reason}"
        return True, detail

    reason = f"HEVC SDR 8-bit ({pix_fmt or 'unknown'}); software decode"
    if debug:
        _log(f"Windows HW decode skipped: {reason}")
    return False, reason


def augment_thumb_extract_for_windows_hw_decode(
    thumb_vf: str,
    ffmpeg_input_args: tuple[str, ...],
    *,
    enabled: bool,
) -> tuple[str, tuple[str, ...], bool]:
    """
    Prefix filter/input args for D3D11VA HEVC decode on Windows.

    Uses p010le after hwdownload (10-bit HEVC Main10 / HDR/DV). Caller should
    pass software thumb_vf and ffmpeg_input_args as fallback when hw fails.
    """
    if not enabled or not windows_hw_decode_available():
        return thumb_vf, ffmpeg_input_args, False
    return (
        f"{_HW_DOWNLOAD_PREFIX}{thumb_vf}",
        (*ffmpeg_d3d11_hwaccel_input_args(), *ffmpeg_input_args),
        True,
    )


def probe_vulkan_available(ffmpeg: str, env: dict[str, str] | None) -> bool:
    """True when ffmpeg can init a Vulkan device (libvulkan present on the host)."""
    if not ffmpeg:
        return False
    ld_path = env.get("LD_LIBRARY_PATH", "") if env else ""
    cache_key = f"{ffmpeg}|{ld_path}"
    cached = _vulkan_available_cache.get(cache_key)
    if cached is not None:
        return cached
    available = False
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-init_hw_device",
                "vulkan=vk",
                "-f",
                "lavfi",
                "-i",
                "nullsrc",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env, **subprocess_hide_window_kwargs(),
        )
        available = completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        available = False
    _vulkan_available_cache[cache_key] = available
    if not available:
        if sys.platform.startswith("linux") and _linux_has_vulkan_icd_configs():
            _log(
                "Vulkan init failed but system ICD configs exist — static BtbN ffmpeg "
                "may need VK_ICD_FILENAMES (and related VK_* vars) in the environment "
                "so libplacebo can load GPU drivers; see README",
                xbmc.LOGWARNING,
            )
        else:
            _log(
                "Vulkan unavailable (libvulkan missing or no device); "
                "libplacebo cannot run on this host",
                xbmc.LOGINFO,
            )
    return available


def _linux_has_vulkan_icd_configs() -> bool:
    icd_dir = "/usr/share/vulkan/icd.d"
    try:
        return os.path.isdir(icd_dir) and bool(os.listdir(icd_dir))
    except OSError:
        return False


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
    # Stock ffmpeg vf_tonemap only supports none/linear/gamma/clip/reinhard/hable/mobius.
    # bt2390 exists on libplacebo (and jellyfin-ffmpeg forks), not on the CPU tonemap filter —
    # requesting it aborts HLG (arib-std-b67) generation with "Unable to parse tonemap=bt2390".
    _ = transfer
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


def _libplacebo_tonemap_chain(*, dolby_vision: bool = False) -> str:
    dv_opts = "apply_dolbyvision=1:" if dolby_vision else ""
    # ffmpeg 8.x libplacebo: gamut_mode (not color_mapping), no desaturation option.
    return (
        f"libplacebo={dv_opts}tonemapping=hable:peak_detect=1:"
        "gamut_mode=perceptual:color_primaries=bt709:color_trc=bt709:"
        "colorspace=bt709:range=pc,format=yuvj420p,"
    )


def _simple_tonemap_chain(transfer: str) -> str:
    """Best-effort when zscale/libplacebo are unavailable (quality may vary)."""
    algorithm = _tonemap_algorithm(transfer)
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


def _tonemap_prefix(
    mode: str,
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ,
    *,
    dolby_vision: bool = False,
) -> str:
    if mode == _TONEMAP_MODE_ZSCALE:
        return _zscale_tonemap_chain(hdr_transfer)
    if mode == _TONEMAP_MODE_LIBPLACEBO:
        return _libplacebo_tonemap_chain(dolby_vision=dolby_vision)
    if mode == _TONEMAP_MODE_SIMPLE:
        return _simple_tonemap_chain(hdr_transfer)
    return ""


def ffmpeg_has_libplacebo(ffmpeg: str, env: dict[str, str] | None) -> bool:
    """True when ffmpeg lists the libplacebo video filter."""
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env, **subprocess_hide_window_kwargs(),
        )
        text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        return _ffmpeg_lists_filter(text, "libplacebo")
    except (OSError, subprocess.SubprocessError):
        return False


def ffmpeg_has_zscale(ffmpeg: str, env: dict[str, str] | None) -> bool:
    """True when ffmpeg lists the zscale video filter."""
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env, **subprocess_hide_window_kwargs(),
        )
        text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        return _ffmpeg_lists_filter(text, "zscale")
    except (OSError, subprocess.SubprocessError):
        return False


def build_thumb_video_filter(
    tile_width: int,
    apply_tonemap: bool,
    tonemap_mode: str,
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ,
    *,
    dolby_vision: bool = False,
) -> str:
    scale_pad = _scale_pad_filter(tile_width)
    if apply_tonemap and tonemap_mode in (
        _TONEMAP_MODE_ZSCALE,
        _TONEMAP_MODE_SIMPLE,
        _TONEMAP_MODE_LIBPLACEBO,
    ):
        return f"{_tonemap_prefix(tonemap_mode, hdr_transfer, dolby_vision=dolby_vision)}{scale_pad}"
    return f"yadif=0:-1:0,{scale_pad}"


def build_fps_batch_filter(
    tile_width: int,
    interval_sec: float,
    apply_tonemap: bool,
    tonemap_mode: str,
    hdr_transfer: str = _TONEMAP_TRANSFER_PQ,
    *,
    dolby_vision: bool = False,
) -> str:
    if interval_sec == int(interval_sec):
        fps_expr = f"1/{int(interval_sec)}"
    else:
        fps_expr = f"{1.0 / interval_sec:.8g}"
    thumb_vf = build_thumb_video_filter(
        tile_width,
        apply_tonemap,
        tonemap_mode,
        hdr_transfer,
        dolby_vision=dolby_vision,
    )
    return f"fps={fps_expr},{thumb_vf}"


def _ffmpeg_lists_filter(filters_text: str, filter_name: str) -> bool:
    """True when ffmpeg -filters output lists a filter by name."""
    # ffmpeg 8.x lines look like: ".S zscale V->V ..." or ".. libplacebo N->V ..."
    pattern = rf"^\s*\S+\s+{re.escape(filter_name)}\s+\S+->"
    if re.search(pattern, filters_text, re.MULTILINE):
        return True
    # Some shared builds pad columns differently; accept name before I->O on the line.
    loose = rf"^\s*\S*\s*{re.escape(filter_name)}\s+.*\S+->"
    return re.search(loose, filters_text, re.MULTILINE) is not None


def _tonemap_cache_key(ffmpeg: str, env: dict[str, str] | None) -> str:
    ld_path = ""
    if env:
        ld_path = env.get("LD_LIBRARY_PATH", "") or ""
    return f"{ffmpeg or ''}\0{ld_path}"


def invalidate_tonemap_support_cache() -> None:
    """Clear cached ffmpeg filter detection (e.g. after installing custom ffmpeg)."""
    _tonemap_support_cache.clear()
    _vulkan_available_cache.clear()


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
            env=env, **subprocess_hide_window_kwargs(),
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


def _side_data_list_is_dovi(side_data_list: list | None) -> tuple[bool, str]:
    for side in side_data_list or []:
        side_type = str(side.get("side_data_type") or "")
        side_lower = side_type.lower()
        if "dovi" in side_lower or "dolby vision" in side_lower:
            profile = _dovi_profile_from_side_entry(side)
            detail = side_type if profile is None else f"{side_type} profile={profile}"
            return True, detail
    return False, ""


def _filename_suggests_dolby_vision(media_path: str) -> bool:
    return bool(_FILENAME_DOVI_RE.search(os.path.basename(media_path or "")))


def _parse_dovi_from_ffprobe_json(payload: str, debug: bool, *, source_label: str) -> tuple[bool, str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False, "invalid ffprobe json"

    for stream in data.get("streams") or []:
        if (stream.get("codec_type") or "").lower() != "video":
            continue
        if _video_stream_is_enhancement_layer(stream):
            reason = "Dolby Vision enhancement-layer video stream"
            if debug:
                _log(f"Dolby Vision detected from {source_label} stream metadata: {reason}")
            return True, reason
        is_dovi, reason = _side_data_list_is_dovi(stream.get("side_data_list"))
        if is_dovi:
            if debug:
                _log(f"Dolby Vision detected from {source_label} stream side_data: {reason}")
            return True, reason

    for frame in data.get("frames") or []:
        is_dovi, reason = _side_data_list_is_dovi(frame.get("side_data_list"))
        if is_dovi:
            if debug:
                _log(f"Dolby Vision detected from {source_label} frame side_data: {reason}")
            return True, reason

    return False, "no Dolby Vision signals"


def _ffprobe_dovi_local(ffprobe: str, local_path: str, env: dict[str, str] | None, debug: bool) -> bool:
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
        is_dovi, _reason = _parse_dovi_from_ffprobe_json(
            payload, debug, source_label="stream"
        )
        if is_dovi:
            return True

    frame_args = [
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        "%+#1",
        "-show_frames",
        "-show_entries",
        "frame=side_data_list",
        "-of",
        "json",
        local_path,
    ]
    payload = _ffprobe_json(ffprobe, frame_args, env, 180.0)
    if not payload:
        return False
    is_dovi, _reason = _parse_dovi_from_ffprobe_json(
        payload, debug, source_label="first-frame"
    )
    return is_dovi


def _ffprobe_dovi_via_pipe(
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
        is_dovi, _reason = _parse_dovi_from_ffprobe_json(
            payload, debug, source_label="stream pipe"
        )
        if is_dovi:
            return True

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
        "frame=side_data_list",
        "-of",
        "json",
        "pipe:0",
    ]
    payload = _ffprobe_hdr_via_pipe_impl(media_path, ffprobe, env, frame_args, 180.0)
    if not payload:
        return False
    is_dovi, _reason = _parse_dovi_from_ffprobe_json(
        payload, debug, source_label="first-frame pipe"
    )
    return is_dovi


def probe_video_is_dolby_vision(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    ffmpeg: str | None = None,
    dovi_tool_fallback: bool = False,
    debug: bool = False,
) -> bool:
    if not media_path:
        return False

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        if _ffprobe_dovi_via_pipe(media_path, ffprobe, env, debug):
            return True
    elif ffprobe:
        local_path = ffmpeg_input
        if local_path and (os.path.isfile(local_path) or xbmcvfs.exists(local_path)):
            if _ffprobe_dovi_local(ffprobe, local_path, env, debug):
                return True

    if dovi_tool_fallback and ffmpeg and not use_vfs_stream:
        local_path = ffmpeg_input
        if local_path and (os.path.isfile(local_path) or xbmcvfs.exists(local_path)):
            is_hdr, reason = _probe_hdr_via_dovi_tool(
                local_path, ffmpeg, env, debug=debug
            )
            if is_hdr and "dovi_tool" in reason.lower():
                if debug:
                    _log(f"Dolby Vision detected via dovi_tool for {os.path.basename(media_path)}: {reason}")
                return True

    if _filename_suggests_dolby_vision(media_path):
        if debug:
            _log(
                f"Dolby Vision assumed from filename for {os.path.basename(media_path)} "
                "(ffprobe found no DOVI side_data)",
                xbmc.LOGINFO,
            )
        return True

    return False


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
            env=env, **subprocess_hide_window_kwargs(),
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
    seen: set[str] = set()

    def add(path: str) -> None:
        key = path if path in ("dovi_tool", "dovi_tool.exe") else (_local_path(path) or path)
        if key not in seen:
            seen.add(key)
            candidates.append(path)

    add(default_dovi_tool_path())
    for legacy in legacy_dovi_tool_paths():
        add(legacy)
    for name in ("dovi_tool", "dovi_tool.exe"):
        add(name)
    return candidates


def find_dovi_tool() -> str | None:
    """Return path to a runnable dovi_tool in generator bin/, legacy add-on root, or PATH."""
    return _find_dovi_tool()


def _dovi_tool_runs(path: str) -> bool:
    local = path
    try:
        import xbmcvfs

        local = xbmcvfs.translatePath(path) if path.startswith("special://") else path
    except (RuntimeError, ImportError):
        pass
    if not local or not os.path.isfile(local):
        return False
    try:
        result = subprocess.run(
            [local, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            **subprocess_hide_window_kwargs(),
        )
        return result.returncode == 0
    except OSError as exc:
        if getattr(exc, "errno", None) == 8:
            _log(
                f"dovi_tool at {path!r} is not runnable on this CPU (wrong architecture?)",
                xbmc.LOGWARNING,
            )
        return False


def _try_remove_broken_dovi_tool(path: str) -> None:
    """Remove a non-runnable dovi_tool binary left in the add-on folder (wrong arch)."""
    if path in ("dovi_tool", "dovi_tool.exe"):
        return
    local = path
    try:
        local = xbmcvfs.translatePath(path) if path.startswith("special://") else path
    except (RuntimeError, ValueError):
        pass
    if not local or not os.path.isfile(local):
        return
    try:
        result = subprocess.run(
            [local, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            **subprocess_hide_window_kwargs(),
        )
        if result.returncode == 0:
            return
    except OSError:
        pass
    _log(
        f"Removing unusable dovi_tool at {local} (wrong architecture or corrupt)",
        xbmc.LOGWARNING,
    )
    try:
        os.remove(local)
    except OSError:
        pass


def _find_dovi_tool() -> str | None:
    migrate_legacy_dovi_tool_if_needed()
    for candidate in _dovi_tool_candidates():
        if candidate in ("dovi_tool", "dovi_tool.exe"):
            found = shutil.which(candidate)
            if found and _dovi_tool_runs(found):
                return found
            continue
        if xbmcvfs.exists(candidate) or os.path.isfile(candidate):
            if _dovi_tool_runs(candidate):
                return candidate
            _try_remove_broken_dovi_tool(candidate)
    return None


def _parse_dovi_profile_from_ffprobe_json(payload: str) -> str | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    for stream in data.get("streams") or []:
        if (stream.get("codec_type") or "").lower() != "video":
            continue
        if _video_stream_is_enhancement_layer(stream):
            return "7"
        for side in stream.get("side_data_list") or []:
            profile = _dovi_profile_from_side_entry(side)
            if profile:
                return profile
    for frame in data.get("frames") or []:
        for side in frame.get("side_data_list") or []:
            profile = _dovi_profile_from_side_entry(side)
            if profile:
                return profile
    return None


def probe_dovi_profile(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    ffmpeg: str | None = None,
    debug: bool = False,
) -> str | None:
    """Return Dolby Vision profile string from ffprobe or dovi_tool, or None."""
    if not media_path or not ffprobe:
        return None
    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        return None
    local_path = ffmpeg_input
    if not local_path or not (
        os.path.isfile(local_path) or xbmcvfs.exists(local_path)
    ):
        return None

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
        profile = _parse_dovi_profile_from_ffprobe_json(payload)
        if profile:
            if debug:
                _log(f"Dolby Vision profile from stream side_data: {profile}")
            return profile

    frame_args = [
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        "%+#1",
        "-show_frames",
        "-show_entries",
        "frame=side_data_list",
        "-of",
        "json",
        local_path,
    ]
    payload = _ffprobe_json(ffprobe, frame_args, env, 180.0)
    if payload:
        profile = _parse_dovi_profile_from_ffprobe_json(payload)
        if profile:
            if debug:
                _log(f"Dolby Vision profile from first frame side_data: {profile}")
            return profile

    if ffmpeg:
        profile = _dovi_profile_from_dovi_tool(
            local_path, ffmpeg, env, debug=debug
        )
        if profile and debug:
            _log(f"Dolby Vision profile from dovi_tool RPU: {profile}")
        return profile
    return None


def _ffmpeg_demux_hevc_pipe_cmd(
    ffmpeg: str,
    local_input: str,
    *,
    max_sec: float | None = None,
) -> list[str]:
    """Demux the primary video track to annex-B HEVC on stdout (for dovi_tool)."""
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        local_input,
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-bsf:v",
        "hevc_mp4toannexb",
    ]
    if max_sec is not None:
        cmd.extend(["-t", f"{max_sec:.3f}"])
    cmd.extend(["-f", "hevc", "-"])
    return cmd


def _dovi_profile_from_dovi_tool(
    local_path: str,
    ffmpeg: str,
    env: dict[str, str] | None,
    *,
    debug: bool = False,
) -> str | None:
    """Read DOVI profile from the first RPU via dovi_tool info."""
    dovi_tool = _find_dovi_tool()
    if not dovi_tool:
        return None

    rpu_fd, rpu_file = tempfile.mkstemp(suffix=".bin", prefix="trickplay_dovi_rpu_")
    os.close(rpu_fd)
    try:
        extract_cmd = [dovi_tool, "extract-rpu", "-", "-o", rpu_file]
        ff_proc = subprocess.Popen(
            _ffmpeg_demux_hevc_pipe_cmd(
                ffmpeg, local_path, max_sec=_DOVI_RPU_EXTRACT_SEC
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env, **subprocess_hide_window_kwargs(),
        )
        dt_proc = subprocess.Popen(
            extract_cmd,
            stdin=ff_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env, **subprocess_hide_window_kwargs(),
        )
        if ff_proc.stdout is not None:
            ff_proc.stdout.close()
        dt_proc.communicate(timeout=_DOVI_PROBE_TIMEOUT_SEC)
        ff_proc.wait(timeout=5)

        if not os.path.isfile(rpu_file) or os.path.getsize(rpu_file) <= 0:
            if debug:
                _log(
                    f"dovi_tool profile probe: no RPU for "
                    f"{os.path.basename(local_path)}"
                )
            return None

        completed = subprocess.run(
            [dovi_tool, "info", "-i", rpu_file, "-f", "0"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30.0,
            env=env, **subprocess_hide_window_kwargs(),
        )
        profile = _dovi_profile_from_info_output(
            completed.stdout or completed.stderr or ""
        )
        if profile and profile != "unknown":
            return profile
        return None
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        if debug:
            _log(f"dovi_tool profile probe failed: {exc}", xbmc.LOGWARNING)
        return None
    finally:
        try:
            os.remove(rpu_file)
        except OSError:
            pass


def _run_dovi_convert_mkv_to_hevc(
    ffmpeg: str,
    dovi_tool: str,
    local_input: str,
    convert_cmd: list[str],
    hevc_out: str,
    env: dict[str, str] | None,
    *,
    timeout: float,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """
    Demux MKV/MP4 to annex-B HEVC, pipe through dovi_tool convert to a .hevc file.

    dovi_tool convert does not accept Matroska; ffmpeg must demux first.
    """
    dovi_cmd = [*convert_cmd, "-", "-o", hevc_out]
    ff_proc: subprocess.Popen[bytes] | None = None
    dt_proc: subprocess.Popen[bytes] | None = None
    try:
        ff_proc = subprocess.Popen(
            _ffmpeg_demux_hevc_pipe_cmd(ffmpeg, local_input),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env, **subprocess_hide_window_kwargs(),
        )
        dt_proc = subprocess.Popen(
            dovi_cmd,
            stdin=ff_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env, **subprocess_hide_window_kwargs(),
        )
        if ff_proc.stdout is not None:
            ff_proc.stdout.close()
        _stdout, dt_stderr = dt_proc.communicate(timeout=timeout)
        ff_returncode = ff_proc.wait(timeout=30)
        if should_cancel and should_cancel():
            return False, "cancelled"
        if dt_proc.returncode != 0:
            detail = (dt_stderr or b"").decode("utf-8", errors="replace").strip()
            if ff_returncode != 0:
                detail = f"{detail} (ffmpeg rc={ff_returncode})".strip()
            return False, detail or f"dovi_tool convert rc={dt_proc.returncode}"
        if not os.path.isfile(hevc_out) or os.path.getsize(hevc_out) <= 0:
            return False, "dovi_tool convert produced no output"
        return True, ""
    except subprocess.TimeoutExpired:
        for proc in (dt_proc, ff_proc):
            if proc is not None:
                proc.kill()
                proc.communicate()
        return False, f"timed out after {int(timeout)}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def dovi_profile_needs_convert(profile: str | None) -> bool:
    """
    True when dovi_tool must rewrite the bitstream before zscale tonemap.

    Profile 5 (IPT-PQ / web-DV) has no HDR10 base layer — zscale alone tinting.
    Profiles 7 and 8 carry an HDR10-compatible base layer; zscale+tonemap is enough.
    """
    if not profile:
        return False
    normalized = str(profile).strip().lower().split(".")[0]
    if not normalized.isdigit():
        return False
    return int(normalized) == 5


def is_dv_profile_5(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    ffmpeg: str | None = None,
    debug: bool = False,
) -> bool:
    """True when media is Dolby Vision profile 5 (needs dovi_tool convert for tonemap)."""
    if not media_path or not ffprobe:
        return False
    if not probe_video_is_dolby_vision(
        media_path,
        ffprobe,
        env,
        ffmpeg=ffmpeg,
        debug=debug,
    ):
        return False
    profile = probe_dovi_profile(
        media_path,
        ffprobe,
        env,
        ffmpeg=ffmpeg,
        debug=debug,
    )
    return dovi_profile_needs_convert(profile)


def _dovi_convert_command(
    dovi_tool: str,
    profile: str | None,
    *,
    has_enhancement_layer: bool = False,
) -> list[str]:
    """dovi_tool argv ending before input path (includes 'convert'). Profile 5 only."""
    if not dovi_profile_needs_convert(profile):
        return []
    return [dovi_tool, "-m", "3", "convert"]


def _media_has_dovi_enhancement_layer(
    media_path: str,
    ffprobe: str,
    env: dict[str, str] | None,
) -> bool:
    if not media_path or not ffprobe:
        return False
    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        return False
    local_path = ffmpeg_input
    if not local_path or not (
        os.path.isfile(local_path) or xbmcvfs.exists(local_path)
    ):
        return False
    stream_args = [
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name:stream_tags=title",
        "-of",
        "json",
        local_path,
    ]
    payload = _ffprobe_json(ffprobe, stream_args, env, 120.0)
    if not payload:
        return False
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False
    for stream in data.get("streams") or []:
        if _video_stream_is_enhancement_layer(stream):
            return True
    return False


def prepare_dovi_zscale_media(
    media_path: str,
    ffmpeg: str,
    ffprobe: str,
    env: dict[str, str] | None,
    *,
    duration_sec: float = 0.0,
    debug: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str | None, str | None]:
    """
    Convert Profile 5 DV to 8.1-compatible HEVC for zscale tonemap.

    Returns (prepared_hevc_path, temp_dir). temp_dir must be removed by caller.
    """
    dovi_tool = _find_dovi_tool()
    if not dovi_tool:
        _log(
            "Dolby Vision on this device requires dovi_tool (no Vulkan for libplacebo); "
            "install dovi_tool via batch Run or place it in generator ffmpeg bin/ "
            "(see README)",
            xbmc.LOGERROR,
        )
        return None, None

    ffmpeg_input, use_vfs_stream = resolve_ffmpeg_media_path(media_path)
    if use_vfs_stream:
        _log(
            "Dolby Vision dovi_tool convert cannot run on VFS stream paths",
            xbmc.LOGERROR,
        )
        return None, None
    local_input = ffmpeg_input
    if not local_input or not (
        os.path.isfile(local_input) or xbmcvfs.exists(local_input)
    ):
        _log(f"Dolby Vision prep: media not found: {media_path!r}", xbmc.LOGERROR)
        return None, None

    profile = probe_dovi_profile(
        media_path, ffprobe, env, ffmpeg=ffmpeg, debug=debug
    )
    has_el = _media_has_dovi_enhancement_layer(media_path, ffprobe, env)
    convert_cmd = _dovi_convert_command(
        dovi_tool, profile, has_enhancement_layer=has_el
    )
    if not convert_cmd:
        _log(
            f"Dolby Vision profile {profile or 'unknown'}: "
            "zscale+tonemap on source (no dovi_tool convert needed)"
        )
        return local_input, None

    work_dir = _create_dovi_prep_work_dir()
    if not _dovi_convert_disk_check(local_input, work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, None

    hevc_out = os.path.join(work_dir, "converted.hevc")
    mode_label = " ".join(convert_cmd[1:-1]) if len(convert_cmd) > 2 else "convert"
    _log(
        f"Dolby Vision profile {profile}: converting {os.path.basename(media_path)} "
        f"via ffmpeg pipe → dovi_tool ({mode_label}) + zscale "
        f"(temp {work_dir}) — one-time step, may take several minutes"
    )

    timeout = min(
        max(
            _DOVI_CONVERT_TIMEOUT_MIN_SEC,
            duration_sec * 1.5 + 120.0,
        ),
        _DOVI_CONVERT_TIMEOUT_MAX_SEC,
    )
    try:
        ok, detail = _run_dovi_convert_mkv_to_hevc(
            ffmpeg,
            dovi_tool,
            local_input,
            convert_cmd,
            hevc_out,
            env,
            timeout=timeout,
            should_cancel=should_cancel,
        )
        if should_cancel and should_cancel():
            shutil.rmtree(work_dir, ignore_errors=True)
            return None, None
        if not ok:
            _log(f"dovi_tool convert failed: {detail[:500]}", xbmc.LOGERROR)
            shutil.rmtree(work_dir, ignore_errors=True)
            return None, None

        _log(
            f"Dolby Vision prep complete -> {hevc_out} "
            f"({os.path.getsize(hevc_out) // (1024 * 1024)} MB)"
        )
        return hevc_out, work_dir
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"Dolby Vision prep failed: {exc}", xbmc.LOGERROR)
        shutil.rmtree(work_dir, ignore_errors=True)
        return None, None


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
        _log("HDR dovi_tool fallback: dovi_tool not found (generator bin/, legacy add-on root, or PATH)", xbmc.LOGWARNING)
        return False, "dovi_tool missing"

    rpu_fd, rpu_file = tempfile.mkstemp(suffix=".bin", prefix="trickplay_dovi_rpu_")
    os.close(rpu_fd)
    try:
        ffmpeg_cmd = _ffmpeg_demux_hevc_pipe_cmd(
            ffmpeg, local_path, max_sec=_DOVI_RPU_EXTRACT_SEC
        )
        extract_cmd = [dovi_tool, "extract-rpu", "-", "-o", rpu_file]
        try:
            ff_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env, **subprocess_hide_window_kwargs(),
            )
            dt_proc = subprocess.Popen(
                extract_cmd,
                stdin=ff_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env, **subprocess_hide_window_kwargs(),
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
                env=env, **subprocess_hide_window_kwargs(),
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
            env=env, **subprocess_hide_window_kwargs(),
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
    is_dovi = False
    use_dovi_tool_zscale_prep = False

    if hdr_tone_map_enabled:
        global _logged_hdr_dovi_tool_fallback_setting
        if hdr_dovi_tool_fallback and not _logged_hdr_dovi_tool_fallback_setting:
            _log(
                "HDR dovi_tool fallback setting: enabled "
                "(used when ffprobe finds no HDR signals; looks in generator ffmpeg bin/ then PATH)"
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
            is_dovi = probe_video_is_dolby_vision(
                media_path,
                ffprobe,
                env,
                ffmpeg=ffmpeg,
                dovi_tool_fallback=hdr_dovi_tool_fallback,
                debug=debug,
            )
            use_dovi_tool_zscale_prep = False
            vulkan_ok = probe_vulkan_available(ffmpeg, env) if is_dovi else False
            has_libplacebo = ffmpeg_has_libplacebo(ffmpeg, env)
            zscale_ok = tonemap_mode == _TONEMAP_MODE_ZSCALE or ffmpeg_has_zscale(
                ffmpeg, env
            )
            if is_dovi:
                dv_profile = probe_dovi_profile(
                    media_path, ffprobe, env, ffmpeg=ffmpeg, debug=debug
                )
                needs_dovi_prep = dovi_profile_needs_convert(dv_profile)
                if vulkan_ok and has_libplacebo and needs_dovi_prep:
                    tonemap_mode = _TONEMAP_MODE_LIBPLACEBO
                    _log(
                        f"Dolby Vision profile {dv_profile} for "
                        f"{os.path.basename(media_path)}; "
                        "using libplacebo with apply_dolbyvision (Vulkan available)"
                    )
                elif vulkan_ok and has_libplacebo and not needs_dovi_prep:
                    tonemap_mode = _TONEMAP_MODE_ZSCALE
                    _log(
                        f"Dolby Vision profile {dv_profile or 'unknown'} for "
                        f"{os.path.basename(media_path)}: "
                        "zscale+tonemap on HDR10 base layer (libplacebo not required)"
                    )
                elif zscale_ok:
                    tonemap_mode = _TONEMAP_MODE_ZSCALE
                    if needs_dovi_prep:
                        if _find_dovi_tool():
                            use_dovi_tool_zscale_prep = True
                            _log(
                                f"Dolby Vision profile {dv_profile} for "
                                f"{os.path.basename(media_path)}: "
                                "dovi_tool convert (-m 3) + zscale tonemap "
                                "(Profile 5 has no HDR10 base layer)"
                            )
                        else:
                            _log(
                                f"Dolby Vision profile 5 for {os.path.basename(media_path)} "
                                "requires dovi_tool when Vulkan/libplacebo is unavailable; "
                                "install via batch Run",
                                xbmc.LOGWARNING,
                            )
                    else:
                        _log(
                            f"Dolby Vision profile {dv_profile or 'unknown'} for "
                            f"{os.path.basename(media_path)}: "
                            "zscale+tonemap on HDR10 base layer (no dovi_tool convert needed)"
                        )
                elif has_libplacebo and not vulkan_ok:
                    _log(
                        f"Dolby Vision detected for {os.path.basename(media_path)} but "
                        "Vulkan/libvulkan is missing and dovi_tool is not installed; "
                        "trickplay may fail or show green/purple tint",
                        xbmc.LOGWARNING,
                    )
                elif not zscale_ok:
                    _log(
                        f"Dolby Vision detected for {os.path.basename(media_path)} but "
                        "generator ffmpeg lacks zscale (required for CPU tonemap on this device)",
                        xbmc.LOGERROR,
                    )
                else:
                    _log(
                        f"Dolby Vision detected for {os.path.basename(media_path)} but "
                        "dovi_tool is not installed; install via batch Run",
                        xbmc.LOGWARNING,
                    )
            mode_label = tonemap_mode
            if is_dovi and tonemap_mode == _TONEMAP_MODE_LIBPLACEBO:
                mode_label = f"{tonemap_mode}+dolbyvision"
            elif is_dovi and use_dovi_tool_zscale_prep:
                mode_label = "zscale+dovi_tool(p5)"
            elif is_dovi and tonemap_mode == _TONEMAP_MODE_ZSCALE:
                mode_label = "zscale+dv-bl"
            _log(
                f"HDR tone mapping enabled for {os.path.basename(media_path)} "
                f"({mode_label}, transfer={hdr_transfer})"
            )
        elif tonemap_mode != _TONEMAP_MODE_NONE:
            _log(
                f"No HDR signals from ffprobe for {os.path.basename(media_path)}; "
                f"tone mapping skipped (enable Debug logging for probe details)",
                xbmc.LOGINFO,
            )

    thumb_vf = build_thumb_video_filter(
        tile_width,
        apply_tonemap,
        tonemap_mode,
        hdr_transfer,
        dolby_vision=is_dovi and tonemap_mode == _TONEMAP_MODE_LIBPLACEBO,
    )
    color_args = ffmpeg_sdr_output_color_args() if apply_tonemap else ()
    input_args = ()
    if apply_tonemap and tonemap_mode == _TONEMAP_MODE_LIBPLACEBO:
        input_args = ffmpeg_libplacebo_input_args()
    return ThumbFilterContext(
        apply_tonemap=apply_tonemap,
        tonemap_mode=tonemap_mode if apply_tonemap else _TONEMAP_MODE_NONE,
        thumb_vf=thumb_vf,
        hdr_transfer=hdr_transfer,
        dolby_vision=is_dovi and tonemap_mode == _TONEMAP_MODE_LIBPLACEBO,
        use_dovi_tool_zscale_prep=use_dovi_tool_zscale_prep if apply_tonemap else False,
        ffmpeg_color_args=color_args,
        ffmpeg_input_args=input_args,
    )

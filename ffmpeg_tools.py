"""FFmpeg/ffprobe resolution for trickplay generation (optional custom HDR-capable build)."""

from __future__ import annotations

import os
import shutil

import xbmc
import xbmcaddon
import xbmcvfs

FFMPEG_TOOLS_ADDON_ID = "tools.ffmpeg-tools"

# Default install location documented in README (CoreELEC / LibreELEC).
DEFAULT_GENERATOR_FFMPEG_ROOTS = (
    "/storage/.kodi/system/ffmpeg",
)

_gen_cache_key: str | None = None
_gen_ffmpeg_bin: str | None = None
_gen_ffprobe_bin: str | None = None
_gen_env: dict[str, str] | None = None


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _path_is_executable_file(path: str) -> bool:
    if not path:
        return False
    local = _local_path(path)
    if local and os.path.isfile(local):
        return os.access(local, os.X_OK) or os.access(local, os.R_OK)
    try:
        return xbmcvfs.exists(path) and not xbmcvfs.isdir(path)
    except (OSError, RuntimeError, ValueError):
        return False


def _prepend_ld_library_path(env: dict[str, str], lib_dir: str) -> None:
    local = _local_path(lib_dir)
    if not local or not os.path.isdir(local):
        return
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{local}:{existing}" if existing else local


def _resolve_lib_dir(*candidates: str) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        local = _local_path(candidate)
        if local and os.path.isdir(local):
            return candidate
    return None


def _layout_from_root(root: str) -> tuple[str, str, str | None]:
    cleaned = root.rstrip("/\\")
    if os.path.basename(cleaned).lower() == "bin":
        cleaned = os.path.dirname(cleaned)
    bin_dir = os.path.join(cleaned, "bin")
    ffmpeg = os.path.join(bin_dir, "ffmpeg")
    ffprobe = os.path.join(bin_dir, "ffprobe")
    lib_path = _resolve_lib_dir(
        os.path.join(cleaned, "lib"),
        os.path.join(cleaned, "lib64"),
        os.path.join(bin_dir, "lib"),
    )
    if not _path_is_executable_file(ffmpeg):
        ffmpeg = os.path.join(cleaned, "ffmpeg")
        ffprobe = os.path.join(cleaned, "ffprobe")
        lib_path = _resolve_lib_dir(
            os.path.join(os.path.dirname(cleaned), "lib"),
            os.path.join(cleaned, "lib"),
            os.path.join(cleaned, "lib64"),
            os.path.join(bin_dir, "lib"),
        )
    return ffmpeg, ffprobe, lib_path


def _layout_from_binary(ffmpeg_path: str) -> tuple[str, str, str | None]:
    bin_dir = os.path.dirname(ffmpeg_path.rstrip("/\\"))
    ffprobe = os.path.join(bin_dir, "ffprobe")
    root = os.path.dirname(bin_dir)
    lib_dir = os.path.join(root, "lib")
    if os.path.basename(bin_dir).lower() != "bin":
        lib_dir = os.path.join(bin_dir, "lib")
    lib_path = lib_dir if os.path.isdir(_local_path(lib_dir)) else None
    return ffmpeg_path, ffprobe, lib_path


def _tools_ffmpeg_tools_layout() -> tuple[str | None, str | None, str | None]:
    try:
        tools_addon = xbmcaddon.Addon(FFMPEG_TOOLS_ADDON_ID)
        addon_path = tools_addon.getAddonInfo("path")
    except RuntimeError:
        return None, None, None
    bin_dir = os.path.join(addon_path, "bin")
    lib_dir = os.path.join(addon_path, "lib")
    ffmpeg = os.path.join(bin_dir, "ffmpeg")
    ffprobe = os.path.join(bin_dir, "ffprobe")
    lib_path = lib_dir if xbmcvfs.exists(lib_dir) else None
    if not _path_is_executable_file(ffmpeg):
        return None, None, lib_path
    if not _path_is_executable_file(ffprobe):
        ffprobe = None
    return ffmpeg, ffprobe, lib_path


def _candidate_layouts(custom_path: str) -> list[tuple[str, str, str | None, str]]:
    layouts: list[tuple[str, str, str | None, str]] = []
    seen: set[str] = set()

    def add(ffmpeg: str, ffprobe: str, lib_dir: str | None, label: str) -> None:
        key = _local_path(ffmpeg) or ffmpeg
        if key in seen:
            return
        seen.add(key)
        layouts.append((ffmpeg, ffprobe, lib_dir, label))

    cleaned = (custom_path or "").strip()
    if cleaned:
        if cleaned.lower().endswith(("ffmpeg", "ffmpeg.exe")):
            ffmpeg, ffprobe, lib_dir = _layout_from_binary(cleaned)
        else:
            ffmpeg, ffprobe, lib_dir = _layout_from_root(cleaned)
        add(ffmpeg, ffprobe, lib_dir, f"custom path ({cleaned})")

    for root in DEFAULT_GENERATOR_FFMPEG_ROOTS:
        ffmpeg, ffprobe, lib_dir = _layout_from_root(root)
        add(ffmpeg, ffprobe, lib_dir, f"default ({root})")

    ffmpeg, ffprobe, lib_dir = _tools_ffmpeg_tools_layout()
    if ffmpeg:
        add(ffmpeg, ffprobe or "", lib_dir, "tools.ffmpeg-tools")

    for name in ("ffmpeg", "/usr/bin/ffmpeg"):
        found = shutil.which(name)
        if found:
            ffmpeg, ffprobe, lib_dir = _layout_from_binary(found)
            add(ffmpeg, ffprobe, lib_dir, f"PATH ({found})")

    return layouts


def resolve_generator_ffmpeg_tools(
    custom_path: str = "",
) -> tuple[str | None, str | None, dict[str, str]]:
    """Resolve ffmpeg for trickplay generation; prefers custom/system HDR-capable builds."""
    global _gen_cache_key, _gen_ffmpeg_bin, _gen_ffprobe_bin, _gen_env

    cache_key = (custom_path or "").strip()
    if _gen_cache_key == cache_key and _gen_ffmpeg_bin is not None:
        return _gen_ffmpeg_bin, _gen_ffprobe_bin, _gen_env or os.environ.copy()

    env = os.environ.copy()
    _gen_ffmpeg_bin = None
    _gen_ffprobe_bin = None

    for ffmpeg, ffprobe, lib_dir, label in _candidate_layouts(custom_path):
        if not _path_is_executable_file(ffmpeg):
            continue
        if lib_dir:
            _prepend_ld_library_path(env, lib_dir)
        _gen_ffmpeg_bin = _local_path(ffmpeg) or ffmpeg
        if _path_is_executable_file(ffprobe):
            _gen_ffprobe_bin = _local_path(ffprobe) or ffprobe
        else:
            _gen_ffprobe_bin = None
            _log(f"ffprobe not found next to generator ffmpeg ({label})", xbmc.LOGWARNING)
        _log(f"Generator ffmpeg: {_gen_ffmpeg_bin} ({label})")
        break

    if not _gen_ffmpeg_bin:
        _log("Generator ffmpeg not found; install tools.ffmpeg-tools or custom ffmpeg", xbmc.LOGERROR)

    _gen_env = env
    _gen_cache_key = cache_key
    return _gen_ffmpeg_bin, _gen_ffprobe_bin, env


def invalidate_generator_ffmpeg_cache() -> None:
    """Clear cached generator ffmpeg resolution (e.g. after settings change)."""
    global _gen_cache_key, _gen_ffmpeg_bin, _gen_ffprobe_bin, _gen_env
    _gen_cache_key = None
    _gen_ffmpeg_bin = None
    _gen_ffprobe_bin = None
    _gen_env = None
    try:
        from hdr_tone_map import invalidate_tonemap_support_cache

        invalidate_tonemap_support_cache()
    except ImportError:
        pass

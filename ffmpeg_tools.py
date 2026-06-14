"""FFmpeg/ffprobe resolution for trickplay generation and playback cropping."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import xbmc
import xbmcaddon
import xbmcvfs

# Windows: hide console window when spawning ffmpeg/ffprobe/dovi_tool (Python 3.7+).
_WIN_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def subprocess_hide_window_kwargs() -> dict[str, int]:
    """Extra kwargs for subprocess.run/Popen on Windows Kodi (no flashing cmd.exe)."""
    if sys.platform.startswith("win"):
        return {"creationflags": _WIN_CREATE_NO_WINDOW}
    return {}


# Default install location documented in README (CoreELEC / LibreELEC).
DEFAULT_GENERATOR_FFMPEG_ROOTS = (
    "/storage/.kodi/system/ffmpeg",
)

ADDON_FFMPEG_INSTALL_ID = "service.trickplay"

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


def _exe_name(stem: str) -> str:
    return f"{stem}.exe" if sys.platform.startswith("win") else stem


def _program_path(directory: str, stem: str) -> str:
    """Resolve ffmpeg/ffprobe with optional .exe on Windows."""
    for name in (_exe_name(stem), stem):
        path = os.path.join(directory, name)
        if _path_is_executable_file(path):
            return path
    return os.path.join(directory, _exe_name(stem))


def addon_ffmpeg_install_roots() -> tuple[str, ...]:
    """Roots where this add-on installs downloaded ffmpeg builds (BtbN Linux, Gyan Windows full)."""
    if sys.platform.startswith("win"):
        root = xbmcvfs.translatePath(
            f"special://profile/addon_data/{ADDON_FFMPEG_INSTALL_ID}/system/ffmpeg"
        )
        return (root,)
    return DEFAULT_GENERATOR_FFMPEG_ROOTS


def default_install_root() -> str:
    return addon_ffmpeg_install_roots()[0]


def default_dovi_tool_bin_dir() -> str:
    """Directory for dovi_tool beside generator ffmpeg (survives add-on updates)."""
    return os.path.join(default_install_root(), "bin")


def default_dovi_tool_path() -> str:
    return _program_path(default_dovi_tool_bin_dir(), "dovi_tool")


def legacy_dovi_tool_paths() -> tuple[str, ...]:
    """Pre-3.2.0 locations in the add-on package root (removed on add-on update)."""
    paths: list[str] = []
    seen: set[str] = set()
    try:
        addon_path = xbmcaddon.Addon(ADDON_FFMPEG_INSTALL_ID).getAddonInfo("path")
        if addon_path:
            candidate = _program_path(addon_path, "dovi_tool")
            key = _local_path(candidate) or candidate
            if key not in seen:
                seen.add(key)
                paths.append(candidate)
    except RuntimeError:
        pass
    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = _program_path(module_dir, "dovi_tool")
    key = _local_path(candidate) or candidate
    if key not in seen:
        paths.append(candidate)
    return tuple(paths)


def _dovi_tool_binary_runs(path: str) -> bool:
    local = _local_path(path) or path
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
    except OSError:
        return False


def migrate_legacy_dovi_tool_if_needed() -> bool:
    """Copy a working legacy add-on-root dovi_tool into generator ffmpeg bin/."""
    dest = default_dovi_tool_path()
    local_dest = _local_path(dest) or dest
    if os.path.isfile(local_dest) and _dovi_tool_binary_runs(local_dest):
        return False
    bin_dir = os.path.dirname(local_dest)
    os.makedirs(bin_dir, exist_ok=True)
    for legacy in legacy_dovi_tool_paths():
        local_legacy = _local_path(legacy) or legacy
        if local_legacy == local_dest:
            continue
        if not os.path.isfile(local_legacy) or not _dovi_tool_binary_runs(local_legacy):
            continue
        if os.path.isfile(local_dest):
            return False
        try:
            shutil.copy2(local_legacy, local_dest)
            if not sys.platform.startswith("win"):
                os.chmod(local_dest, 0o755)
            _log(f"Migrated dovi_tool from {local_legacy} to {local_dest}")
            try:
                os.remove(local_legacy)
            except OSError:
                pass
            return True
        except OSError as exc:
            _log(f"Could not migrate dovi_tool to {local_dest}: {exc}", xbmc.LOGWARNING)
            return False
    return False


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
    env["LD_LIBRARY_PATH"] = build_generator_ld_library_path(local)


def build_generator_ld_library_path(lib_dir: str) -> str:
    """LD_LIBRARY_PATH for BtbN shared ffmpeg without Kodi addon .so shadowing."""
    parts = [lib_dir, "/usr/lib", "/lib"]
    if sys.platform.startswith("linux"):
        parts.extend(("/usr/lib64", "/lib64"))
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part and part not in seen and os.path.isdir(part):
            seen.add(part)
            ordered.append(part)
    return ":".join(ordered)


def build_generator_subprocess_env(
    lib_dir: str | None,
    bin_dir: str | None = None,
) -> dict[str, str]:
    """Environment for generator ffmpeg/ffprobe subprocesses."""
    env = os.environ.copy()
    local_lib = _local_path(lib_dir) if lib_dir else ""
    local_bin = _local_path(bin_dir) if bin_dir else ""

    if sys.platform.startswith("win"):
        prepend: list[str] = []
        for part in (local_bin, local_lib):
            if part and os.path.isdir(part) and part not in prepend:
                prepend.append(part)
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        system32 = os.path.join(system_root, "System32")
        if os.path.isdir(system32) and system32 not in prepend:
            prepend.append(system32)
        if prepend:
            env["PATH"] = os.pathsep.join(prepend) + os.pathsep + env.get("PATH", "")
        return env

    if local_lib and os.path.isdir(local_lib):
        env["LD_LIBRARY_PATH"] = build_generator_ld_library_path(local_lib)
    return env


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
    ffmpeg = _program_path(bin_dir, "ffmpeg")
    ffprobe = _program_path(bin_dir, "ffprobe")
    lib_path = _resolve_lib_dir(
        os.path.join(cleaned, "lib"),
        os.path.join(cleaned, "lib64"),
        os.path.join(bin_dir, "lib"),
    )
    if not _path_is_executable_file(ffmpeg):
        ffmpeg = _program_path(cleaned, "ffmpeg")
        ffprobe = _program_path(cleaned, "ffprobe")
        lib_path = _resolve_lib_dir(
            os.path.join(os.path.dirname(cleaned), "lib"),
            os.path.join(cleaned, "lib"),
            os.path.join(cleaned, "lib64"),
            os.path.join(bin_dir, "lib"),
        )
    return ffmpeg, ffprobe, lib_path


def _layout_from_binary(ffmpeg_path: str) -> tuple[str, str, str | None]:
    bin_dir = os.path.dirname(ffmpeg_path.rstrip("/\\"))
    ffprobe = _program_path(bin_dir, "ffprobe")
    root = os.path.dirname(bin_dir)
    lib_dir = os.path.join(root, "lib")
    if os.path.basename(bin_dir).lower() != "bin":
        lib_dir = os.path.join(bin_dir, "lib")
    lib_path = lib_dir if os.path.isdir(_local_path(lib_dir)) else None
    return ffmpeg_path, ffprobe, lib_path


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

    for root in addon_ffmpeg_install_roots():
        ffmpeg, ffprobe, lib_dir = _layout_from_root(root)
        add(ffmpeg, ffprobe, lib_dir, f"addon install ({root})")

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

    env = build_generator_subprocess_env(None)
    _gen_ffmpeg_bin = None
    _gen_ffprobe_bin = None
    selected_lib: str | None = None
    selected_bin: str | None = None

    for ffmpeg, ffprobe, lib_dir, label in _candidate_layouts(custom_path):
        if not _path_is_executable_file(ffmpeg):
            continue
        selected_lib = lib_dir
        _gen_ffmpeg_bin = _local_path(ffmpeg) or ffmpeg
        selected_bin = os.path.dirname(_gen_ffmpeg_bin)
        if _path_is_executable_file(ffprobe):
            _gen_ffprobe_bin = _local_path(ffprobe) or ffprobe
        else:
            _gen_ffprobe_bin = None
            _log(f"ffprobe not found next to generator ffmpeg ({label})", xbmc.LOGWARNING)
        _log(f"Generator ffmpeg: {_gen_ffmpeg_bin} ({label})")
        break

    if not _gen_ffmpeg_bin:
        _log(
            "Generator ffmpeg not found; install via batch Run (HDR tone mapping) "
            "or set Generator ffmpeg path — see README",
            xbmc.LOGERROR,
        )
    else:
        env = build_generator_subprocess_env(selected_lib, selected_bin)

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
    try:
        from thumb_cropper import invalidate_playback_ffmpeg_cache

        invalidate_playback_ffmpeg_cache()
    except ImportError:
        pass

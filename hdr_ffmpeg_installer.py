"""Download and install BtbN HDR-capable ffmpeg for trickplay generation."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable

import xbmc
import xbmcaddon
import xbmcvfs

from ffmpeg_tools import (
    DEFAULT_GENERATOR_FFMPEG_ROOTS,
    _layout_from_root,
    _local_path,
    _path_is_executable_file,
    _prepend_ld_library_path,
    invalidate_generator_ffmpeg_cache,
)
from hdr_tone_map import (
    _TONEMAP_MODE_LIBPLACEBO,
    _TONEMAP_MODE_ZSCALE,
    detect_tonemap_support,
    find_dovi_tool,
)

# Pinned BtbN builds (autobuild-2026-06-13-13-31).
# Linux: static -gpl-8.1 (zscale/libplacebo built in; no lib/ on CoreELEC).
# Windows: -gpl-8.1 zip.
_BTBN_LINUX64_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-06-13-13-31/"
    "ffmpeg-n8.1.1-13-g83e8541aa6-linux64-gpl-8.1.tar.xz"
)
_BTBN_LINUXARM64_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-06-13-13-31/"
    "ffmpeg-n8.1.1-13-g83e8541aa6-linuxarm64-gpl-8.1.tar.xz"
)
_BTBN_WIN64_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-06-13-13-31/"
    "ffmpeg-n8.1.1-13-g83e8541aa6-win64-gpl-8.1.zip"
)
_BTBN_WINARM64_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-06-13-13-31/"
    "ffmpeg-n8.1.1-13-g83e8541aa6-winarm64-gpl-8.1.zip"
)

# Pinned dovi_tool builds (2.3.2).
_DOVI_LINUX64_URL = (
    "https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/"
    "dovi_tool-2.3.2-x86_64-unknown-linux-musl.tar.gz"
)
_DOVI_LINUXARM64_URL = (
    "https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/"
    "dovi_tool-2.3.2-aarch64-unknown-linux-musl.tar.gz"
)
_DOVI_WIN64_URL = (
    "https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/"
    "dovi_tool-2.3.2-x86_64-pc-windows-msvc.zip"
)
_DOVI_WINARM64_URL = (
    "https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/"
    "dovi_tool-2.3.2-aarch64-pc-windows-msvc.zip"
)


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator] {message}", level)


def default_install_root() -> str:
    if sys.platform.startswith("win"):
        return xbmcvfs.translatePath(
            "special://profile/addon_data/service.trickplay/system/ffmpeg"
        )
    return DEFAULT_GENERATOR_FFMPEG_ROOTS[0]


def default_dovi_tool_install_root() -> str:
    try:
        return xbmcaddon.Addon("service.trickplay").getAddonInfo("path")
    except RuntimeError:
        return os.path.dirname(os.path.abspath(__file__))


def _ffmpeg_download_url_for_platform() -> str | None:
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        if machine in ("aarch64", "arm64"):
            return _BTBN_WINARM64_URL
        return _BTBN_WIN64_URL
    if machine in ("aarch64", "arm64"):
        return _BTBN_LINUXARM64_URL
    if machine in ("x86_64", "amd64", "i686", "i386"):
        return _BTBN_LINUX64_URL
    return None


def _dovi_tool_download_url_for_platform() -> str | None:
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        if machine in ("aarch64", "arm64"):
            return _DOVI_WINARM64_URL
        return _DOVI_WIN64_URL
    if machine in ("aarch64", "arm64"):
        return _DOVI_LINUXARM64_URL
    if machine in ("x86_64", "amd64", "i686", "i386"):
        return _DOVI_LINUX64_URL
    return None


def _env_for_layout(lib_dir: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if lib_dir:
        _prepend_ld_library_path(env, lib_dir)
    return env


def _count_shared_libs(lib_dir: str | None) -> int:
    if not lib_dir:
        return 0
    local = _local_path(lib_dir)
    if not local or not os.path.isdir(local):
        return 0
    count = 0
    for name in os.listdir(local):
        lower = name.lower()
        if lower.endswith(".dll"):
            count += 1
        elif ".so" in lower:
            count += 1
    return count


def _tonemap_mode_for_layout(
    ffmpeg: str,
    ffprobe: str,
    lib_dir: str | None,
    *,
    use_cache: bool = True,
) -> str:
    if not _path_is_executable_file(ffmpeg):
        return "none"
    env = _env_for_layout(lib_dir)
    return detect_tonemap_support(
        _local_path(ffmpeg) or ffmpeg,
        env,
        use_cache=use_cache,
    )


def is_hdr_capable_tonemap_mode(mode: str) -> bool:
    return mode in (_TONEMAP_MODE_ZSCALE, _TONEMAP_MODE_LIBPLACEBO)


def generator_ffmpeg_is_hdr_capable(custom_path: str = "") -> bool:
    """True when the resolved generator ffmpeg has zscale or libplacebo."""
    from ffmpeg_tools import resolve_generator_ffmpeg_tools

    ffmpeg, _, env = resolve_generator_ffmpeg_tools(custom_path)
    if not ffmpeg:
        return False
    mode = detect_tonemap_support(ffmpeg, env)
    return is_hdr_capable_tonemap_mode(mode)


def install_root_is_hdr_capable(install_root: str | None = None) -> bool:
    root = install_root or default_install_root()
    ffmpeg, ffprobe, lib_dir = _layout_from_root(root)
    mode = _tonemap_mode_for_layout(ffmpeg, ffprobe, lib_dir)
    return is_hdr_capable_tonemap_mode(mode)


def should_offer_hdr_ffmpeg_download(
    hdr_tone_map_enabled: bool,
    custom_ffmpeg_path: str = "",
) -> bool:
    if not hdr_tone_map_enabled:
        return False
    if custom_ffmpeg_path.strip():
        return not generator_ffmpeg_is_hdr_capable(custom_ffmpeg_path)
    if install_root_is_hdr_capable():
        return False
    return True


def dovi_tool_is_installed() -> bool:
    return find_dovi_tool() is not None


def should_offer_dovi_tool_download(hdr_dovi_tool_fallback_enabled: bool) -> bool:
    if not hdr_dovi_tool_fallback_enabled:
        return False
    return not dovi_tool_is_installed()


def _find_dovi_binary(extract_dir: str) -> str | None:
    for dirpath, _, filenames in os.walk(extract_dir):
        for name in filenames:
            if name.lower() in ("dovi_tool", "dovi_tool.exe"):
                return os.path.join(dirpath, name)
    return None


def _dovi_tool_dest_path(install_root: str) -> str:
    name = "dovi_tool.exe" if sys.platform.startswith("win") else "dovi_tool"
    return os.path.join(_local_path(install_root) or install_root, name)


def _verify_dovi_tool(install_root: str) -> tuple[bool, str]:
    path = find_dovi_tool()
    if not path:
        return False, "dovi_tool not found after install"
    local = _local_path(path) or path
    if not _path_is_executable_file(path):
        return False, "dovi_tool is not executable"
    try:
        result = subprocess.run(
            [local, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "dovi_tool --version failed"
    version = (result.stdout or result.stderr or "").strip().splitlines()[0]
    return True, version or "installed"


def _find_bin_lib_dirs(extract_dir: str) -> tuple[str, str | None] | None:
    for dirpath, dirnames, filenames in os.walk(extract_dir):
        names_lower = {name.lower() for name in filenames}
        if "ffmpeg" in names_lower or "ffmpeg.exe" in names_lower:
            if "ffprobe" in names_lower or "ffprobe.exe" in names_lower:
                bin_dir = dirpath
                root = os.path.dirname(bin_dir)
                for lib_candidate in (
                    os.path.join(root, "lib"),
                    os.path.join(bin_dir, "lib"),
                ):
                    if os.path.isdir(lib_candidate):
                        return bin_dir, lib_candidate
                return bin_dir, None
        if "bin" in {name.lower() for name in dirnames}:
            candidate_bin = os.path.join(dirpath, "bin")
            if not os.path.isfile(os.path.join(candidate_bin, "ffmpeg")) and not os.path.isfile(
                os.path.join(candidate_bin, "ffmpeg.exe")
            ):
                continue
            candidate_lib = os.path.join(dirpath, "lib")
            lib = candidate_lib if os.path.isdir(candidate_lib) else None
            return candidate_bin, lib
    return None


def _copy_tree_contents(src: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)
        if os.path.isdir(src_path):
            if os.path.isdir(dst_path):
                _copy_tree_contents(src_path, dst_path)
            else:
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)


def _make_unix_executable(bin_dir: str) -> None:
    for name in ("ffmpeg", "ffprobe"):
        path = os.path.join(bin_dir, name)
        if os.path.isfile(path):
            os.chmod(path, 0o755)


def _remove_install_artifacts(install_root: str) -> None:
    local_root = _local_path(install_root)
    for sub in ("bin", "lib"):
        path = os.path.join(local_root, sub)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _verify_installed(install_root: str) -> tuple[bool, str]:
    ffmpeg, ffprobe, lib_dir = _layout_from_root(install_root)
    local_root = _local_path(install_root) or install_root
    lib_count = _count_shared_libs(lib_dir)
    env = _env_for_layout(lib_dir)
    _log(
        f"Verifying HDR ffmpeg at {local_root}: "
        f"ffmpeg={_local_path(ffmpeg) or ffmpeg} "
        f"lib={_local_path(lib_dir) if lib_dir else '(none)'} "
        f"shared_libs={lib_count} "
        f"LD_LIBRARY_PATH={env.get('LD_LIBRARY_PATH', '') or '(unset)'}"
    )
    mode = _tonemap_mode_for_layout(ffmpeg, ffprobe, lib_dir, use_cache=False)
    if not is_hdr_capable_tonemap_mode(mode) and lib_dir:
        _log("HDR ffmpeg probe with lib/ failed; retrying without LD_LIBRARY_PATH")
        mode = _tonemap_mode_for_layout(ffmpeg, ffprobe, None, use_cache=False)
    if not is_hdr_capable_tonemap_mode(mode):
        return False, (
            f"installed ffmpeg lacks zscale/libplacebo filters (detected: {mode}); "
            "re-run download or install BtbN -gpl (Linux) manually"
        )
    return True, mode


def _download_file(
    url: str,
    dest: str,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "service.trickplay/3.0"})
    with urllib.request.urlopen(request, timeout=600) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        chunk_size = 1024 * 256
        with open(dest, "wb") as handle:
            while True:
                if should_cancel and should_cancel():
                    raise RuntimeError("download cancelled")
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
                if progress:
                    if total > 0:
                        percent = min(int(read * 100 / total), 100)
                        progress(percent, f"Downloading… {read // (1024 * 1024)} MB")
                    else:
                        progress(0, f"Downloading… {read // (1024 * 1024)} MB")


def _extract_archive(archive_path: str, extract_dir: str) -> None:
    if archive_path.lower().endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)
        return
    with tarfile.open(archive_path, "r:*") as tf:
        tf.extractall(extract_dir)


def install_hdr_ffmpeg(
    install_root: str | None = None,
    *,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """Download BtbN ffmpeg into install_root. Returns (ok, detail)."""
    root = install_root or default_install_root()
    local_root = _local_path(root)
    url = _ffmpeg_download_url_for_platform()
    if not url:
        return False, f"unsupported platform ({sys.platform} / {platform.machine()})"

    os.makedirs(local_root, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="trickplay_ffmpeg_dl_")
    archive_name = os.path.basename(url.split("?")[0])
    archive_path = os.path.join(temp_dir, archive_name)
    extract_dir = os.path.join(temp_dir, "extract")

    try:
        if progress:
            progress(0, "Downloading HDR ffmpeg…")
        _log(f"Downloading HDR ffmpeg from {url}")
        _download_file(url, archive_path, progress=progress, should_cancel=should_cancel)
        if should_cancel and should_cancel():
            return False, "cancelled"

        os.makedirs(extract_dir, exist_ok=True)
        if progress:
            progress(0, "Extracting…")
        _log(f"Extracting {archive_path}")
        _extract_archive(archive_path, extract_dir)

        found = _find_bin_lib_dirs(extract_dir)
        if not found:
            return False, "could not find ffmpeg/ffprobe in downloaded archive"

        src_bin, src_lib = found
        if progress:
            progress(0, "Installing…")
        _remove_install_artifacts(root)
        dst_bin = os.path.join(local_root, "bin")
        dst_lib = os.path.join(local_root, "lib")
        _copy_tree_contents(src_bin, dst_bin)
        if src_lib:
            _copy_tree_contents(src_lib, dst_lib)
        elif os.path.isdir(dst_lib):
            shutil.rmtree(dst_lib, ignore_errors=True)
        if not sys.platform.startswith("win"):
            _make_unix_executable(dst_bin)

        invalidate_generator_ffmpeg_cache()
        ok, detail = _verify_installed(root)
        if not ok:
            return False, detail
        _log(f"HDR ffmpeg installed at {local_root} ({detail})")
        return True, detail
    except (OSError, urllib.error.URLError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as exc:
        _log(f"HDR ffmpeg install failed: {exc}", xbmc.LOGWARNING)
        return False, str(exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def install_dovi_tool(
    install_root: str | None = None,
    *,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """Download dovi_tool into the add-on root folder. Returns (ok, detail)."""
    root = install_root or default_dovi_tool_install_root()
    local_root = _local_path(root) or root
    url = _dovi_tool_download_url_for_platform()
    if not url:
        return False, f"unsupported platform ({sys.platform} / {platform.machine()})"

    os.makedirs(local_root, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="trickplay_dovi_dl_")
    archive_name = os.path.basename(url.split("?")[0])
    archive_path = os.path.join(temp_dir, archive_name)
    extract_dir = os.path.join(temp_dir, "extract")
    dest_path = _dovi_tool_dest_path(root)

    try:
        if progress:
            progress(0, "Downloading dovi_tool…")
        _log(f"Downloading dovi_tool from {url}")
        _download_file(url, archive_path, progress=progress, should_cancel=should_cancel)
        if should_cancel and should_cancel():
            return False, "cancelled"

        os.makedirs(extract_dir, exist_ok=True)
        if progress:
            progress(0, "Extracting…")
        _log(f"Extracting {archive_path}")
        _extract_archive(archive_path, extract_dir)

        src_binary = _find_dovi_binary(extract_dir)
        if not src_binary:
            return False, "could not find dovi_tool binary in downloaded archive"

        if progress:
            progress(0, "Installing…")
        if os.path.isfile(dest_path):
            os.remove(dest_path)
        shutil.copy2(src_binary, dest_path)
        if not sys.platform.startswith("win"):
            os.chmod(dest_path, 0o755)

        ok, detail = _verify_dovi_tool(root)
        if not ok:
            return False, detail
        _log(f"dovi_tool installed at {dest_path} ({detail})")
        return True, detail
    except (OSError, urllib.error.URLError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as exc:
        _log(f"dovi_tool install failed: {exc}", xbmc.LOGWARNING)
        return False, str(exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def prompt_and_install_hdr_ffmpeg(
    *,
    hdr_tone_map_enabled: bool,
    custom_ffmpeg_path: str = "",
    title: str,
    prompt_yes: str,
    prompt_no: str,
    download_yes: str,
    progress_title: str,
    unsupported_message: str,
    failed_message: str,
    success_message: str,
) -> bool:
    """
    Offer BtbN ffmpeg download when HDR tone mapping is on and zscale is missing.

    Returns True when batch generation may continue, False when the user aborts Run.
    """
    if not should_offer_hdr_ffmpeg_download(hdr_tone_map_enabled, custom_ffmpeg_path):
        if hdr_tone_map_enabled and not generator_ffmpeg_is_hdr_capable(custom_ffmpeg_path):
            _log(
                "HDR tone mapping enabled but generator ffmpeg lacks zscale/libplacebo; "
                "previews may look washed out",
                xbmc.LOGWARNING,
            )
        return True

    if not _ffmpeg_download_url_for_platform():
        xbmcgui = __import__("xbmcgui")
        xbmcgui.Dialog().ok(title, unsupported_message)
        _log(f"HDR ffmpeg auto-install unsupported on {sys.platform}/{platform.machine()}")
        return True

    xbmcgui = __import__("xbmcgui")
    install_root = default_install_root()
    if not xbmcgui.Dialog().yesno(
        title,
        prompt_yes % install_root,
        nolabel=prompt_no,
        yeslabel=download_yes,
    ):
        _log("HDR ffmpeg download declined; continuing with available ffmpeg", xbmc.LOGWARNING)
        return True

    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create(progress_title, "Starting…")
    cancelled = False

    def _should_cancel() -> bool:
        nonlocal cancelled
        if monitor.abortRequested() or progress.iscanceled():
            cancelled = True
            return True
        return False

    def _progress(percent: int, line: str) -> None:
        if _should_cancel():
            return
        progress.update(percent, line)

    try:
        ok, detail = install_hdr_ffmpeg(progress=_progress, should_cancel=_should_cancel)
    finally:
        progress.close()

    if cancelled:
        _log("HDR ffmpeg install cancelled by user")
        return True

    if ok:
        xbmcgui.Dialog().notification(title, success_message % detail, xbmcgui.NOTIFICATION_INFO, 5000)
        return True

    xbmcgui.Dialog().ok(title, failed_message % detail)
    _log(f"HDR ffmpeg install failed: {detail}", xbmc.LOGWARNING)
    return True


def prompt_and_install_dovi_tool(
    *,
    hdr_dovi_tool_fallback_enabled: bool,
    title: str,
    prompt_yes: str,
    prompt_no: str,
    download_yes: str,
    progress_title: str,
    unsupported_message: str,
    failed_message: str,
    success_message: str,
) -> bool:
    """
    Offer dovi_tool download when HDR dovi_tool fallback is on and missing.

    Returns True when batch generation may continue.
    """
    if not should_offer_dovi_tool_download(hdr_dovi_tool_fallback_enabled):
        return True

    if not _dovi_tool_download_url_for_platform():
        xbmcgui = __import__("xbmcgui")
        xbmcgui.Dialog().ok(title, unsupported_message)
        _log(f"dovi_tool auto-install unsupported on {sys.platform}/{platform.machine()}")
        return True

    xbmcgui = __import__("xbmcgui")
    install_root = default_dovi_tool_install_root()
    if not xbmcgui.Dialog().yesno(
        title,
        prompt_yes % install_root,
        nolabel=prompt_no,
        yeslabel=download_yes,
    ):
        _log("dovi_tool download declined; continuing without fallback", xbmc.LOGWARNING)
        return True

    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create(progress_title, "Starting…")
    cancelled = False

    def _should_cancel() -> bool:
        nonlocal cancelled
        if monitor.abortRequested() or progress.iscanceled():
            cancelled = True
            return True
        return False

    def _progress(percent: int, line: str) -> None:
        if _should_cancel():
            return
        progress.update(percent, line)

    try:
        ok, detail = install_dovi_tool(progress=_progress, should_cancel=_should_cancel)
    finally:
        progress.close()

    if cancelled:
        _log("dovi_tool install cancelled by user")
        return True

    if ok:
        xbmcgui.Dialog().notification(title, success_message % detail, xbmcgui.NOTIFICATION_INFO, 5000)
        return True

    xbmcgui.Dialog().ok(title, failed_message % detail)
    _log(f"dovi_tool install failed: {detail}", xbmc.LOGWARNING)
    return True


def prompt_and_install_generator_tools(
    *,
    hdr_tone_map_enabled: bool,
    hdr_dovi_tool_fallback_enabled: bool,
    custom_ffmpeg_path: str = "",
    title: str,
    ffmpeg_prompt_yes: str,
    dovi_prompt_yes: str,
    prompt_no: str,
    download_yes: str,
    ffmpeg_progress_title: str,
    dovi_progress_title: str,
    ffmpeg_unsupported_message: str,
    dovi_unsupported_message: str,
    ffmpeg_failed_message: str,
    dovi_failed_message: str,
    ffmpeg_success_message: str,
    dovi_success_message: str,
) -> bool:
    """Offer HDR ffmpeg and dovi_tool downloads before batch generation."""
    prompt_and_install_hdr_ffmpeg(
        hdr_tone_map_enabled=hdr_tone_map_enabled,
        custom_ffmpeg_path=custom_ffmpeg_path,
        title=title,
        prompt_yes=ffmpeg_prompt_yes,
        prompt_no=prompt_no,
        download_yes=download_yes,
        progress_title=ffmpeg_progress_title,
        unsupported_message=ffmpeg_unsupported_message,
        failed_message=ffmpeg_failed_message,
        success_message=ffmpeg_success_message,
    )
    prompt_and_install_dovi_tool(
        hdr_dovi_tool_fallback_enabled=hdr_dovi_tool_fallback_enabled,
        title=title,
        prompt_yes=dovi_prompt_yes,
        prompt_no=prompt_no,
        download_yes=download_yes,
        progress_title=dovi_progress_title,
        unsupported_message=dovi_unsupported_message,
        failed_message=dovi_failed_message,
        success_message=dovi_success_message,
    )
    return True

"""Download and load Pillow for playback preview cropping (JPEG sprite cells)."""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()

# Pinned release with broad wheel coverage (PyPI).
PILLOW_VERSION = "10.4.0"
PYPI_JSON_URL = f"https://pypi.org/pypi/Pillow/{PILLOW_VERSION}/json"

_pillow_available: bool | None = None
_site_packages: str | None = None


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def default_pillow_site_packages() -> str:
    return xbmcvfs.translatePath(
        "special://profile/addon_data/service.trickplay/system/python/site-packages"
    )


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _ensure_dir(path: str) -> None:
    local = _local_path(path)
    if local:
        os.makedirs(local, exist_ok=True)


def _python_tag() -> str:
    major, minor = sys.version_info.major, sys.version_info.minor
    return f"cp{major}{minor}"


def _platform_tag_candidates() -> list[str]:
    machine = platform.machine().lower()
    if sys.platform.startswith("win"):
        if machine in ("aarch64", "arm64"):
            return ["win_arm64"]
        return ["win_amd64"]
    if sys.platform == "darwin":
        if machine in ("aarch64", "arm64"):
            return ["macosx_11_0_arm64", "macosx_10_9_universal2"]
        return ["macosx_10_10_x86_64"]
    if machine in ("aarch64", "arm64"):
        return [
            "manylinux_2_28_aarch64",
            "manylinux2014_aarch64",
            "linux_aarch64",
        ]
    if machine in ("x86_64", "amd64"):
        return [
            "manylinux_2_28_x86_64",
            "manylinux_2_17_x86_64",
            "manylinux2014_x86_64",
            "linux_x86_64",
        ]
    if machine.startswith("arm") or machine.startswith("-armv7"):
        return ["linux_armv7l", "manylinux2014_armv7l"]
    return []


def _wheel_matches(filename: str, py_tag: str, platform_tags: list[str]) -> bool:
    lower = filename.lower()
    if not lower.endswith(".whl"):
        return False
    parts = lower[:-4].split("-")
    if len(parts) < 5:
        return False
    wheel_py = parts[2]
    wheel_platform = parts[4]
    if not any(wheel_platform == tag.lower() for tag in platform_tags):
        return False
    if wheel_py == py_tag or wheel_py == "py3":
        return True
    if "abi3" in wheel_py and py_tag.startswith("cp3"):
        return True
    return False


def _select_wheel_url(payload: dict) -> str | None:
    py_tag = _python_tag()
    platform_tags = _platform_tag_candidates()
    if not platform_tags:
        return None

    urls = payload.get("urls") or []
    wheels: list[tuple[int, str]] = []
    for entry in urls:
        if entry.get("packagetype") != "bdist_wheel":
            continue
        filename = entry.get("filename") or ""
        url = entry.get("url") or ""
        if not url or not _wheel_matches(filename, py_tag, platform_tags):
            continue
        # Prefer exact python tag over abi3.
        priority = 0 if f"-{py_tag}-" in filename.lower() else 1
        wheels.append((priority, url))

    if not wheels:
        return None
    wheels.sort(key=lambda item: item[0])
    return wheels[0][1]


def _register_site_packages() -> str:
    global _site_packages
    site = default_pillow_site_packages()
    _site_packages = site
    local = _local_path(site)
    if local and local not in sys.path:
        sys.path.insert(0, local)
    return site


def ensure_pillow_loaded(*, force: bool = False) -> bool:
    """Import Pillow from Kodi's Python or the add-on site-packages folder."""
    global _pillow_available
    if not force and _pillow_available is True:
        return True
    if not force and _pillow_available is False:
        return False

    try:
        from PIL import Image  # noqa: F401

        _pillow_available = True
        return True
    except ImportError:
        pass

    _register_site_packages()
    try:
        from PIL import Image  # noqa: F401

        _pillow_available = True
        return True
    except ImportError:
        _pillow_available = False
        return False


def pillow_is_available() -> bool:
    return ensure_pillow_loaded()


def should_offer_pillow_download() -> bool:
    return not pillow_is_available()


def invalidate_pillow_cache() -> None:
    global _pillow_available
    _pillow_available = None


def _download(url: str, dest: str, progress: Callable[[int, str], None] | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "service.trickplay/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        chunk_size = 256 * 1024
        with open(dest, "wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                read += len(chunk)
                if progress and total > 0:
                    percent = min(int(read * 100 / total), 99)
                    progress(percent, f"Downloading Pillow… ({read // 1024} KB)")


def _install_wheel(wheel_path: str, site_packages: str) -> None:
    local_site = _local_path(site_packages)
    os.makedirs(local_site, exist_ok=True)
    with zipfile.ZipFile(wheel_path, "r") as archive:
        archive.extractall(local_site)


def install_pillow(
    *,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """Download and install a pinned Pillow wheel into add-on site-packages."""
    if should_cancel and should_cancel():
        return False, "cancelled"

    py_tag = _python_tag()
    platform_tags = _platform_tag_candidates()
    if not platform_tags:
        return False, f"unsupported platform {sys.platform}/{platform.machine()}"

    if progress:
        progress(0, "Fetching Pillow release info…")

    try:
        with urllib.request.urlopen(
            urllib.request.Request(PYPI_JSON_URL, headers={"User-Agent": "service.trickplay/5.0"}),
            timeout=60,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        return False, f"PyPI lookup failed: {exc}"

    wheel_url = _select_wheel_url(payload)
    if not wheel_url:
        return (
            False,
            f"No Pillow {PILLOW_VERSION} wheel for Python {py_tag} on "
            f"{platform_tags[0]}",
        )

    site_packages = default_pillow_site_packages()
    _ensure_dir(site_packages)

    temp_dir = tempfile.mkdtemp(prefix="trickplay-pillow-")
    wheel_name = os.path.basename(wheel_url.split("?")[0])
    wheel_path = os.path.join(temp_dir, wheel_name)
    try:
        if progress:
            progress(5, "Downloading Pillow wheel…")
        _download(wheel_url, wheel_path, progress)
        if should_cancel and should_cancel():
            return False, "cancelled"
        if progress:
            progress(95, "Installing Pillow…")
        _install_wheel(wheel_path, site_packages)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
        return False, str(exc)
    finally:
        try:
            os.remove(wheel_path)
        except OSError:
            pass
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass

    invalidate_pillow_cache()
    if ensure_pillow_loaded(force=True):
        if progress:
            progress(100, "Pillow ready")
        return True, f"Pillow {PILLOW_VERSION}"

    return False, "Pillow installed but import failed"


def prompt_and_install_pillow(
    *,
    title: str,
    prompt_yes: str,
    prompt_no: str,
    download_yes: str,
    progress_title: str,
    unsupported_message: str,
    failed_message: str,
    success_message: str,
) -> bool:
    """Offer Pillow download when preview cropping libraries are missing."""
    if not should_offer_pillow_download():
        return True

    if not _platform_tag_candidates():
        xbmcgui = __import__("xbmcgui")
        xbmcgui.Dialog().ok(title, unsupported_message)
        _log(
            f"Pillow auto-install unsupported on {sys.platform}/{platform.machine()} "
            f"Python {_python_tag()}",
            xbmc.LOGWARNING,
        )
        return True

    xbmcgui = __import__("xbmcgui")
    install_root = default_pillow_site_packages()
    if not xbmcgui.Dialog().yesno(
        title,
        prompt_yes % install_root,
        nolabel=prompt_no,
        yeslabel=download_yes,
    ):
        _log("Pillow download declined; preview cropping unavailable", xbmc.LOGWARNING)
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
        ok, detail = install_pillow(progress=_progress, should_cancel=_should_cancel)
    finally:
        progress.close()

    if cancelled:
        _log("Pillow install cancelled by user")
        return True

    if ok:
        xbmcgui.Dialog().notification(
            title, success_message % detail, xbmcgui.NOTIFICATION_INFO, 5000
        )
        _log(f"Pillow installed: {detail}")
        return True

    xbmcgui.Dialog().ok(title, failed_message % detail)
    _log(f"Pillow install failed: {detail}", xbmc.LOGWARNING)
    return True

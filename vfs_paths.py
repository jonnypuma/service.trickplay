"""Kodi VFS path helpers (xbmcvfs has exists/listdir but no isdir/isfile)."""

from __future__ import annotations

import os
import re

import xbmcvfs

_REMOTE_URL_RE = re.compile(
    r"^(nfs|smb|smb2|smb3|ftp|http|https|dav|davs|upnp|zip|vfs)://",
    re.IGNORECASE,
)


def local_path(path: str) -> str:
    if not path:
        return path
    if "://" in path or path.startswith("special://"):
        try:
            return xbmcvfs.translatePath(path)
        except (RuntimeError, TypeError, ValueError):
            return path
    return path


def is_remote_vfs_url(path: str) -> bool:
    """True for Kodi network/VFS URLs that must keep forward slashes on Windows."""
    return bool(path) and bool(_REMOTE_URL_RE.match(path.strip()))


def normalize_vfs_path(path: str) -> str:
    """Normalize separators in VFS URLs so Windows never keeps '\\' in nfs/smb paths."""
    cleaned = (path or "").strip()
    if not cleaned or "://" not in cleaned:
        return cleaned
    scheme, _, rest = cleaned.partition("://")
    rest = rest.replace("\\", "/")
    while "//" in rest:
        rest = rest.replace("//", "/")
    return f"{scheme}://{rest}"


def vfs_join(base: str, *parts: str) -> str:
    """Join path segments without using os.path.join on remote VFS URLs."""
    if not base:
        base = ""
    if is_remote_vfs_url(base) or ("://" in base and not base.lower().startswith("special://")):
        path = normalize_vfs_path(base).rstrip("/")
        for part in parts:
            piece = str(part).replace("\\", "/").strip("/")
            if piece:
                path = f"{path}/{piece}"
        return path

    path = base
    for part in parts:
        path = os.path.join(path, part)
    return path


def network_url_to_local(path: str) -> str | None:
    """Map nfs:// or smb:// URL to an OS mount path when /proc/mounts has a match."""
    if not path or "://" not in path:
        return None
    try:
        from ffmpeg_media import _map_network_url_to_local

        return _map_network_url_to_local(path)
    except ImportError:
        return None


def path_variants(path: str) -> tuple[str, ...]:
    """
    Distinct paths that may denote the same file or folder.

    Covers Kodi VFS URLs (nfs/smb), translatePath results, and OS bind mounts
    (e.g. /storage/remote-shares/… on CoreELEC).
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def add(candidate: str) -> None:
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)

    add(path)
    if not path:
        return tuple()

    if "://" in path:
        add(normalize_vfs_path(path))

    translated = local_path(path)
    if translated:
        add(translated)

    mapped = network_url_to_local(normalize_vfs_path(path) if "://" in path else path)
    if mapped:
        add(mapped)

    return tuple(ordered)


def _os_is_dir(path: str) -> bool:
    if not path or "://" in path:
        return False
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def _os_is_file(path: str) -> bool:
    if not path or "://" in path:
        return False
    try:
        return os.path.isfile(path)
    except OSError:
        return False


def _vfs_listdir(path: str) -> tuple[list[str], list[str]] | None:
    if not xbmcvfs.exists(path):
        return None
    try:
        entries = xbmcvfs.listdir(path)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if isinstance(entries, (list, tuple)) and len(entries) == 2:
        dirs, files = entries[0], entries[1]
        return [str(name) for name in dirs], [str(name) for name in files]
    if isinstance(entries, (list, tuple)):
        return [], [str(name) for name in entries]
    return None


def vfs_is_dir(path: str) -> bool:
    for candidate in path_variants(path):
        translated = local_path(candidate)
        if translated and _os_is_dir(translated):
            return True
        if _os_is_dir(candidate):
            return True
        listed = _vfs_listdir(candidate)
        if listed is not None:
            return True
    return False


def vfs_is_file(path: str) -> bool:
    if not path:
        return False
    if vfs_is_dir(path):
        return False
    for candidate in path_variants(path):
        translated = local_path(candidate)
        if translated and _os_is_file(translated):
            return True
        if _os_is_file(candidate):
            return True
        if xbmcvfs.exists(candidate) and _vfs_listdir(candidate) is None:
            return True
    return False


def vfs_list_subdir_names(directory: str) -> list[str]:
    """Child directory names; prefers OS mount paths, then VFS listdir."""
    names: list[str] = []
    for candidate in path_variants(directory):
        translated = local_path(candidate)
        for listing_root in (translated, candidate):
            if not listing_root or "://" in listing_root:
                continue
            if not _os_is_dir(listing_root):
                continue
            try:
                for entry in os.listdir(listing_root):
                    full = os.path.join(listing_root, entry)
                    if _os_is_dir(full):
                        names.append(str(entry))
            except OSError:
                continue
            if names:
                return names

        listed = _vfs_listdir(candidate)
        if listed is not None:
            return [str(name) for name in listed[0]]

    return names


def vfs_list_file_names(directory: str) -> list[str]:
    """File names in a directory; prefers OS mount paths, then VFS listdir."""
    names: list[str] = []
    for candidate in path_variants(directory):
        translated = local_path(candidate)
        for listing_root in (translated, candidate):
            if not listing_root or "://" in listing_root:
                continue
            if not _os_is_dir(listing_root):
                continue
            try:
                for entry in os.listdir(listing_root):
                    full = os.path.join(listing_root, entry)
                    if _os_is_file(full):
                        names.append(str(entry))
            except OSError:
                continue
            if names:
                return names

        listed = _vfs_listdir(candidate)
        if listed is not None:
            dirs, files = listed
            return [str(name) for name in files + dirs]

    return names

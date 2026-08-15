"""Conservative warnings before a batch writes many sidecars."""

from __future__ import annotations

import os
import shutil

from vfs_paths import network_url_to_local

_LOW_FREE_BYTES = 1 * 1024**3


def warnings_for_batch(root: str, candidates: list[str]) -> tuple[str, ...]:
    warnings: list[str] = []
    sample_paths = [root, *candidates[:10]]
    network = next((path for path in sample_paths if "://" in path), "")
    if network:
        warnings.append(
            "Network/VFS media detected. Generation may be slower and can be "
            "interrupted by connectivity issues; use Fast seek for weak or remote devices."
        )

    local = network_url_to_local(root) if "://" in root else root
    if not local:
        local = network_url_to_local(network) if network else root
    try:
        free = shutil.disk_usage(local).free
    except (OSError, TypeError):
        free = None
    if free is not None and free < _LOW_FREE_BYTES:
        warnings.append(
            f"Low disk space: only {free / 1024**3:.1f} GiB is free where sidecars "
            "or temporary files may be written."
        )
    return tuple(warnings)

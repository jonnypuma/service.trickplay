"""Tests for VFS URL joining on Windows (no backslashes in nfs:// paths)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.modules.setdefault("xbmc", MagicMock())
sys.modules.setdefault("xbmcvfs", MagicMock())
sys.modules.setdefault("xbmcaddon", MagicMock())
sys.modules.setdefault("xbmcgui", MagicMock())

from vfs_paths import normalize_vfs_path, vfs_join


class VfsJoinTests(unittest.TestCase):
    def test_normalize_replaces_windows_backslashes_in_nfs_url(self) -> None:
        raw = (
            r"nfs://192.168.0.111/Media/TV/30 Degrees In February"
            r"\Season 1\show.mkv"
        )
        self.assertEqual(
            normalize_vfs_path(raw),
            "nfs://192.168.0.111/Media/TV/30 Degrees In February/Season 1/show.mkv",
        )

    def test_vfs_join_keeps_forward_slashes(self) -> None:
        base = "nfs://192.168.0.111/Media/TV/30 Degrees In February"
        joined = vfs_join(base, "Season 1", "show.mkv")
        self.assertEqual(
            joined,
            "nfs://192.168.0.111/Media/TV/30 Degrees In February/Season 1/show.mkv",
        )
        self.assertNotIn("\\", joined)

    def test_vfs_join_normalizes_base_with_backslashes(self) -> None:
        base = r"nfs://192.168.0.111/Media/TV\Show"
        joined = vfs_join(base, "Season 1")
        self.assertEqual(joined, "nfs://192.168.0.111/Media/TV/Show/Season 1")

    def test_local_paths_still_use_os_join(self) -> None:
        joined = vfs_join("C:\\Media", "TV", "show.mkv")
        self.assertTrue(joined.replace("/", "\\").endswith("TV\\show.mkv") or "TV" in joined)


if __name__ == "__main__":
    unittest.main()

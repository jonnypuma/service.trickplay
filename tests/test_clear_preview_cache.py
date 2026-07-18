"""Tests for clearing cropped thumbs and local tile copies."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = MagicMock()
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
sys.modules.setdefault("xbmc", xbmc)
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

import thumb_cropper
from thumb_cropper import clear_preview_cache


class ClearPreviewCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache_dir = os.path.join(self._tmpdir.name, "thumbs")
        self.temp_dir = os.path.join(self._tmpdir.name, "temp")
        os.makedirs(self.cache_dir)
        os.makedirs(os.path.join(self.temp_dir, "generate"))
        os.makedirs(os.path.join(self.temp_dir, "dovi"))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, path: str, size: int = 10) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)

    def test_clears_thumbs_and_top_level_tiles_only(self) -> None:
        self._write(os.path.join(self.cache_dir, "a.jpg"), 20)
        self._write(os.path.join(self.cache_dir, "b.jpg"), 30)
        self._write(os.path.join(self.temp_dir, "tile.jpg"), 40)
        generate_keep = os.path.join(self.temp_dir, "generate", "work.jpg")
        dovi_keep = os.path.join(self.temp_dir, "dovi", "work.jpg")
        self._write(generate_keep, 50)
        self._write(dovi_keep, 60)

        with (
            patch.object(thumb_cropper, "CACHE_DIR", self.cache_dir),
            patch.object(thumb_cropper, "TEMP_DIR", self.temp_dir),
        ):
            result = clear_preview_cache()

        self.assertEqual(result.thumb_files, 2)
        self.assertEqual(result.thumb_bytes, 50)
        self.assertEqual(result.tile_files, 1)
        self.assertEqual(result.tile_bytes, 40)
        self.assertFalse(os.path.exists(os.path.join(self.cache_dir, "a.jpg")))
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "tile.jpg")))
        self.assertTrue(os.path.exists(generate_keep))
        self.assertTrue(os.path.exists(dovi_keep))

    def test_empty_cache_returns_zeros(self) -> None:
        with (
            patch.object(thumb_cropper, "CACHE_DIR", self.cache_dir),
            patch.object(thumb_cropper, "TEMP_DIR", self.temp_dir),
        ):
            result = clear_preview_cache()

        self.assertEqual(result.total_files, 0)
        self.assertEqual(result.total_bytes, 0)


if __name__ == "__main__":
    unittest.main()

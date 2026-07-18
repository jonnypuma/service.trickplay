"""Tests for in-memory decoded sprite tile reuse."""

from __future__ import annotations

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

from thumb_cropper import (  # noqa: E402
    _DECODED_TILE_MAX,
    _decoded_tile_order,
    _decoded_tiles,
    _get_decoded_tile_image,
    clear_decoded_tile_cache,
)


class DecodedTileCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_decoded_tile_cache()

    def tearDown(self) -> None:
        clear_decoded_tile_cache()

    def test_reuses_decoded_image_for_same_fingerprint(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "tile.jpg")
            Image.new("RGB", (64, 32), color=(10, 20, 30)).save(path, "JPEG")

            first = _get_decoded_tile_image(path, mtime=1.0, size=100)
            second = _get_decoded_tile_image(path, mtime=1.0, size=100)
            self.assertIs(first, second)
            self.assertEqual(len(_decoded_tiles), 1)

    def test_reloads_when_fingerprint_changes(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "tile.jpg")
            Image.new("RGB", (64, 32), color=(10, 20, 30)).save(path, "JPEG")

            first = _get_decoded_tile_image(path, mtime=1.0, size=100)
            second = _get_decoded_tile_image(path, mtime=2.0, size=100)
            self.assertIsNot(first, second)

    def test_evicts_oldest_when_over_cap(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(_DECODED_TILE_MAX + 1):
                path = str(Path(tmp) / f"tile{index}.jpg")
                Image.new("RGB", (32, 16), color=(index, 0, 0)).save(path, "JPEG")
                paths.append(path)
                _get_decoded_tile_image(path, mtime=1.0, size=index + 1)

            self.assertEqual(len(_decoded_tiles), _DECODED_TILE_MAX)
            self.assertNotIn(paths[0], _decoded_tiles)
            self.assertEqual(_decoded_tile_order, paths[1:])


if __name__ == "__main__":
    unittest.main()

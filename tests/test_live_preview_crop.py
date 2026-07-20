"""Tests for RAM crop + live ping-pong publish path."""

from __future__ import annotations

import sys
import tempfile
import time
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
xbmcvfs = MagicMock()
xbmcvfs.translatePath = lambda path: path
xbmcvfs.exists = lambda path: os.path.isdir(path) or os.path.isfile(path)
xbmcvfs.mkdirs = lambda path: os.makedirs(path, exist_ok=True)
sys.modules.setdefault("xbmcvfs", xbmcvfs)
sys.modules.setdefault("xbmcaddon", MagicMock())
sys.modules.setdefault("xbmcgui", MagicMock())

import os  # noqa: E402

import thumb_cropper  # noqa: E402
from thumb_cropper import (  # noqa: E402
    _DECODED_TILE_MAX,
    _live_preview_by_key,
    clear_decoded_tile_cache,
    get_cropped_thumb_path,
)


class LivePreviewCropTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_decoded_tile_cache()
        with thumb_cropper._live_preview_lock:
            _live_preview_by_key.clear()

    def tearDown(self) -> None:
        clear_decoded_tile_cache()
        with thumb_cropper._live_preview_lock:
            _live_preview_by_key.clear()

    def test_decoded_tile_cap_is_eight(self) -> None:
        self.assertEqual(_DECODED_TILE_MAX, 8)

    def test_cache_miss_returns_live_path_then_persists_durable(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            tile_path = str(Path(tmp) / "0.jpg")
            Image.new("RGB", (40, 40), color=(12, 34, 56)).save(tile_path, "JPEG")
            cache_dir = str(Path(tmp) / "thumbs")
            temp_dir = str(Path(tmp) / "temp")
            os.makedirs(cache_dir, exist_ok=True)
            os.makedirs(temp_dir, exist_ok=True)
            durable = str(Path(cache_dir) / "cell.jpg")
            key = (tile_path, 0, 0, 20, 20, 1.0, 100)

            with patch.object(thumb_cropper, "CACHE_DIR", cache_dir), patch.object(
                thumb_cropper, "TEMP_DIR", temp_dir
            ), patch.object(
                thumb_cropper, "temp_tile_copy", return_value=tile_path
            ), patch.object(
                thumb_cropper, "_source_fingerprint", return_value=(1.0, 100)
            ), patch.object(
                thumb_cropper, "ensure_pillow_loaded", return_value=True
            ), patch.object(
                thumb_cropper, "cache_path_for_thumb", return_value=durable
            ), patch.object(
                thumb_cropper, "thumb_cache_key", return_value=key
            ), patch.object(
                thumb_cropper, "maybe_prune_thumb_cache", return_value=0
            ), patch.object(
                thumb_cropper, "_legacy_cache_path_for_thumb", return_value=""
            ):
                path = get_cropped_thumb_path(tile_path, 0, 0, 20, 20)
                self.assertIsNotNone(path)
                assert path is not None
                self.assertIn(os.path.join("live", "preview_"), path.replace("/", os.sep))
                self.assertTrue(os.path.isfile(path))

                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and not os.path.isfile(durable):
                    time.sleep(0.05)
                self.assertTrue(os.path.isfile(durable))


if __name__ == "__main__":
    unittest.main()

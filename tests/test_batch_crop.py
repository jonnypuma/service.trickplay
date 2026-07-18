"""Tests for batch sprite-cell cropping."""

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
xbmcvfs = MagicMock()
xbmcvfs.translatePath = lambda path: path
sys.modules.setdefault("xbmcvfs", xbmcvfs)
sys.modules.setdefault("xbmcaddon", MagicMock())
sys.modules.setdefault("xbmcgui", MagicMock())

import thumb_cropper  # noqa: E402
from thumb_cropper import cell_crop_rect, clear_decoded_tile_cache, crop_tile_cells_batch


class BatchCropTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_decoded_tile_cache()

    def tearDown(self) -> None:
        clear_decoded_tile_cache()

    def test_batch_writes_multiple_cells_from_one_tile(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            tile_path = str(Path(tmp) / "0.jpg")
            # 2x2 grid of 10x10 cells
            img = Image.new("RGB", (20, 20), color=(0, 0, 0))
            for col, color in ((0, (255, 0, 0)), (1, (0, 255, 0))):
                for row in range(2):
                    left, top, w, h = cell_crop_rect(col, row, 10, 10)
                    patch_img = Image.new("RGB", (w, h), color=color)
                    img.paste(patch_img, (left, top))
            img.save(tile_path, "JPEG", quality=95)

            cache_dir = str(Path(tmp) / "thumbs")
            with patch.object(thumb_cropper, "CACHE_DIR", cache_dir), patch.object(
                thumb_cropper, "TEMP_DIR", tmp
            ), patch.object(
                thumb_cropper, "temp_tile_copy", return_value=tile_path
            ), patch.object(
                thumb_cropper, "_source_fingerprint", return_value=(1.0, 100)
            ), patch.object(
                thumb_cropper, "ensure_pillow_loaded", return_value=True
            ), patch.object(
                thumb_cropper, "get_cached_thumb_path", return_value=None
            ), patch.object(
                thumb_cropper,
                "cache_path_for_thumb",
                side_effect=lambda *_a, **_k: str(
                    Path(cache_dir) / f"{_a[1]}_{_a[2]}.jpg"
                ),
            ), patch.object(
                thumb_cropper,
                "thumb_cache_key",
                side_effect=lambda *a, **k: (a[0], a[1], a[2], a[3], a[4], 1.0, 100),
            ), patch.object(
                thumb_cropper, "maybe_prune_thumb_cache", return_value=0
            ):
                written = crop_tile_cells_batch(
                    tile_path,
                    [(0, 0, 10, 10), (1, 0, 10, 10), (0, 1, 10, 10)],
                    debug=False,
                )

            self.assertEqual(written, 3)
            self.assertTrue((Path(cache_dir) / "0_0.jpg").is_file())
            self.assertTrue((Path(cache_dir) / "1_0.jpg").is_file())
            self.assertTrue((Path(cache_dir) / "0_1.jpg").is_file())


if __name__ == "__main__":
    unittest.main()

"""Tests for cropped-thumb JPEG RAM cache."""

from __future__ import annotations

import sys
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
from thumb_cropper import (  # noqa: E402
    clear_crop_ram_cache,
    crop_ram_has,
    get_crop_ram_jpeg,
    remember_crop_jpeg,
)


class CropRamCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_crop_ram_cache()

    def tearDown(self) -> None:
        clear_crop_ram_cache()

    def test_stores_and_returns_jpeg_bytes(self) -> None:
        key = ("/tiles/0.jpg", 0, 0, 320, 180, 1.0, 100)
        payload = b"jpeg-bytes"
        with patch.object(thumb_cropper, "_crop_ram_limit_bytes", return_value=1024):
            remember_crop_jpeg(key, payload)
            self.assertTrue(crop_ram_has(key))
            self.assertEqual(get_crop_ram_jpeg(key), payload)

    def test_zero_limit_disables_ram_cache(self) -> None:
        key = ("/tiles/0.jpg", 0, 0, 320, 180, 1.0, 100)
        with patch.object(thumb_cropper, "_crop_ram_limit_bytes", return_value=0):
            remember_crop_jpeg(key, b"jpeg-bytes")
            self.assertFalse(crop_ram_has(key))
            self.assertIsNone(get_crop_ram_jpeg(key))

    def test_evicts_oldest_when_over_cap(self) -> None:
        first = ("/tiles/0.jpg", 0, 0, 320, 180, 1.0, 100)
        second = ("/tiles/0.jpg", 1, 0, 320, 180, 1.0, 100)
        with patch.object(thumb_cropper, "_crop_ram_limit_bytes", return_value=8):
            remember_crop_jpeg(first, b"1234")
            remember_crop_jpeg(second, b"56789")
            self.assertFalse(crop_ram_has(first))
            self.assertEqual(get_crop_ram_jpeg(second), b"56789")

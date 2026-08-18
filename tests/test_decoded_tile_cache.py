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
    _DECODED_TILE_DEFAULT_MAX,
    _DECODED_TILE_HARD_MAX,
    _DECODED_TILE_MAX,
    _decoded_tile_order,
    _decoded_tiles,
    _get_decoded_tile_image,
    begin_decoded_tile_session,
    clear_decoded_tile_cache,
    decoded_tile_capacity,
    end_decoded_tile_session,
    warm_decoded_tile,
)


class DecodedTileCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        end_decoded_tile_session()
        clear_decoded_tile_cache()

    def tearDown(self) -> None:
        end_decoded_tile_session()
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

    def test_session_uses_tile_count_and_ram_cap(self) -> None:
        begin_decoded_tile_session(12, ram_max=24)
        self.assertEqual(decoded_tile_capacity(), 12)
        begin_decoded_tile_session(100, ram_max=48)
        self.assertEqual(decoded_tile_capacity(), _DECODED_TILE_HARD_MAX)
        begin_decoded_tile_session(100, ram_max=24)
        self.assertEqual(decoded_tile_capacity(), 24)
        begin_decoded_tile_session(3, ram_max=24)
        self.assertEqual(decoded_tile_capacity(), 3)
        begin_decoded_tile_session(12, ram_max=0)
        self.assertEqual(decoded_tile_capacity(), 0)

    def test_session_keeps_all_decoded_tiles_for_file(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        begin_decoded_tile_session(12, ram_max=12)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(12):
                path = str(Path(tmp) / f"tile{index}.jpg")
                Image.new("RGB", (32, 16), color=(index, 0, 0)).save(path, "JPEG")
                paths.append(path)
                _get_decoded_tile_image(path, mtime=1.0, size=index + 1)

            self.assertEqual(len(_decoded_tiles), 12)
            self.assertEqual(_decoded_tile_order, paths)

    def test_end_session_clears_decoded_tiles(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        begin_decoded_tile_session(12, ram_max=12)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "tile.jpg")
            Image.new("RGB", (32, 16), color=(1, 2, 3)).save(path, "JPEG")
            _get_decoded_tile_image(path, mtime=1.0, size=10)
            self.assertEqual(len(_decoded_tiles), 1)
            end_decoded_tile_session()
            self.assertEqual(len(_decoded_tiles), 0)
            self.assertEqual(decoded_tile_capacity(), _DECODED_TILE_DEFAULT_MAX)

    def test_ram_max_zero_does_not_keep_decoded_tiles(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        begin_decoded_tile_session(12, ram_max=0)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "tile.jpg")
            Image.new("RGB", (32, 16), color=(1, 2, 3)).save(path, "JPEG")
            _get_decoded_tile_image(path, mtime=1.0, size=10)
            self.assertEqual(len(_decoded_tiles), 0)

    def test_warm_decoded_tile_loads_ram_cache(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "tile.jpg")
            Image.new("RGB", (64, 32), color=(10, 20, 30)).save(path, "JPEG")
            with patch(
                "thumb_cropper.temp_tile_copy", return_value=path
            ), patch(
                "thumb_cropper._source_fingerprint", return_value=(1.0, 100)
            ), patch(
                "thumb_cropper.ensure_pillow_loaded", return_value=True
            ):
                self.assertTrue(warm_decoded_tile("/remote/0.jpg"))
            self.assertIn(path, _decoded_tiles)


def _jpeg_with_padded_sof(width: int, height: int, pad_bytes: int) -> bytes:
    parts = [b"\xff\xd8"]
    remaining = pad_bytes
    while remaining > 0:
        chunk = min(remaining, 65533)
        length = chunk + 2
        parts.append(b"\xff\xfe" + length.to_bytes(2, "big") + (b"\x00" * chunk))
        remaining -= chunk
    sof = bytearray(b"\xff\xc0\x00\x0b\x08")
    sof += height.to_bytes(2, "big")
    sof += width.to_bytes(2, "big")
    sof += b"\x01\x01\x11\x00"
    parts.append(bytes(sof))
    parts.append(b"\xff\xd9")
    return b"".join(parts)


class JpegHeaderAndFingerprintTests(unittest.TestCase):
    def test_jpeg_sof_after_64kb_padding(self) -> None:
        from thumb_cropper import _JPEG_SOF_SCAN_MAX, _read_jpeg_dimensions_from_bytes

        payload = _jpeg_with_padded_sof(3200, 1800, 80000)
        self.assertGreater(len(payload), 65536)
        self.assertEqual(_read_jpeg_dimensions_from_bytes(payload[:65536]), (0, 0))
        self.assertEqual(
            _read_jpeg_dimensions_from_bytes(payload[:_JPEG_SOF_SCAN_MAX]),
            (3200, 1800),
        )

    def test_probe_image_dimensions_reads_past_64kb(self) -> None:
        import thumb_cropper

        payload = _jpeg_with_padded_sof(3200, 1800, 80000)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "0.jpg")
            Path(path).write_bytes(payload)
            with patch.object(
                thumb_cropper, "temp_tile_copy", return_value=path
            ), patch.object(
                thumb_cropper, "_probe_dimensions_with_ffprobe", return_value=(0, 0)
            ), patch.object(
                thumb_cropper, "_probe_dimensions_with_ffmpeg", return_value=(0, 0)
            ):
                self.assertEqual(thumb_cropper.probe_image_dimensions(path), (3200, 1800))

    def test_source_fingerprint_uses_prepared_temp_without_vfs_stat(self) -> None:
        import thumb_cropper

        thumb_cropper._remember_prepared_temp("/nfs/0.jpg", "/tmp/0.jpg", 12.5, 99)
        try:
            with patch.object(
                thumb_cropper.xbmcvfs,
                "Stat",
                create=True,
                side_effect=AssertionError("STAT"),
            ):
                self.assertEqual(
                    thumb_cropper._source_fingerprint("/nfs/0.jpg"), (12.5, 99)
                )
        finally:
            with thumb_cropper._prepared_temp_lock:
                thumb_cropper._prepared_temp_tiles.pop("/nfs/0.jpg", None)


if __name__ == "__main__":
    unittest.main()

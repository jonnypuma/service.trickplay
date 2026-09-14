"""Regression coverage for the low-latency crop pipeline."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from kodi_test_stubs import install_kodi_stubs  # noqa: E402

install_kodi_stubs()

import thumb_cropper  # noqa: E402


class CacheMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        thumb_cropper._clear_memory_cache_index()

    def tearDown(self) -> None:
        thumb_cropper._clear_memory_cache_index()

    def test_cache_touch_is_debounced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "thumb.jpg")
            Path(path).write_bytes(b"jpeg")
            with patch("thumb_cropper.os.utime") as touch:
                thumb_cropper._touch_cached_file(path)
                thumb_cropper._touch_cached_file(path)
            touch.assert_called_once()

    def test_known_cache_key_skips_repeated_file_stat(self) -> None:
        key = ("/tiles/0.jpg", 0, 0, 20, 20, 1.0, 100)
        with tempfile.TemporaryDirectory() as directory:
            cached = str(Path(directory) / "thumb.jpg")
            Path(cached).write_bytes(b"jpeg")
            with (
                patch("thumb_cropper.thumb_cache_key", return_value=key),
                patch("thumb_cropper.cache_path_for_thumb", return_value=cached),
                patch("thumb_cropper._legacy_cache_path_for_thumb", return_value=""),
                patch(
                    "thumb_cropper._has_file_content",
                    wraps=thumb_cropper._has_file_content,
                ) as has_content,
            ):
                self.assertEqual(
                    thumb_cropper.get_cached_thumb_path(
                        "/tiles/0.jpg", 0, 0, 20, 20
                    ),
                    cached,
                )
                first_calls = has_content.call_count
                self.assertEqual(
                    thumb_cropper.get_cached_thumb_path(
                        "/tiles/0.jpg", 0, 0, 20, 20
                    ),
                    cached,
                )
            self.assertEqual(has_content.call_count, first_calls)


class PersistenceQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        with thumb_cropper._persist_lock:
            thumb_cropper._persist_queue.clear()
            thumb_cropper._persist_queued.clear()

    def test_persistence_queue_carries_immutable_bytes(self) -> None:
        key = ("/tiles/0.jpg", 0, 0, 20, 20, 1.0, 100)
        payload = b"first-image"
        with patch("thumb_cropper._ensure_persist_worker"):
            thumb_cropper._enqueue_durable_jpeg("/cache/a.jpg", payload, key)
        with thumb_cropper._persist_lock:
            path, queued_payload, queued_key = thumb_cropper._persist_queue[0]
        self.assertEqual(path, "/cache/a.jpg")
        self.assertEqual(queued_payload, b"first-image")
        self.assertEqual(queued_key, key)

    def test_persistence_worker_writes_durable_file(self) -> None:
        key = ("/tiles/0.jpg", 0, 0, 20, 20, 1.0, 100)
        with tempfile.TemporaryDirectory() as directory:
            durable = str(Path(directory) / "a.jpg")
            with patch("thumb_cropper._ensure_persist_worker"):
                thumb_cropper._enqueue_durable_jpeg(durable, b"jpeg-data", key)
            with (
                patch("thumb_cropper._mark_thumb_cached") as mark,
                patch("thumb_cropper.maybe_prune_thumb_cache", return_value=0),
            ):
                thumb_cropper._run_persist_queue()
            self.assertEqual(Path(durable).read_bytes(), b"jpeg-data")
            mark.assert_called_once_with(key, durable)

    def test_live_preview_has_more_than_two_rotation_slots(self) -> None:
        self.assertGreaterEqual(thumb_cropper._LIVE_SLOT_COUNT, 4)


class ChunkedPrecropTests(unittest.TestCase):
    def test_batch_yields_before_work_when_foreground_is_pending(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as directory:
            tile = str(Path(directory) / "0.jpg")
            Image.new("RGB", (20, 20), color=(1, 2, 3)).save(tile, "JPEG")
            cache_dir = str(Path(directory) / "cache")
            with (
                patch.object(thumb_cropper, "CACHE_DIR", cache_dir),
                patch.object(thumb_cropper, "TEMP_DIR", directory),
                patch("thumb_cropper.temp_tile_copy", return_value=tile),
                patch("thumb_cropper._source_fingerprint", return_value=(1.0, 100)),
                patch("thumb_cropper.ensure_pillow_loaded", return_value=True),
                patch("thumb_cropper.get_cached_thumb_path", return_value=None),
                patch(
                    "thumb_cropper.cache_path_for_thumb",
                    return_value=str(Path(cache_dir) / "cell.jpg"),
                ),
                patch(
                    "thumb_cropper.thumb_cache_key",
                    return_value=(tile, 0, 0, 10, 10, 1.0, 100),
                ),
            ):
                written = thumb_cropper.crop_tile_cells_batch(
                    tile,
                    [(0, 0, 10, 10)],
                    should_yield=lambda: True,
                )
            self.assertEqual(written, 0)
            self.assertFalse((Path(cache_dir) / "cell.jpg").exists())

    def test_latency_stats_include_averages(self) -> None:
        with thumb_cropper._latency_lock:
            thumb_cropper._latency_stats.clear()
            thumb_cropper._latency_stats.update(
                {"jpeg_encode_count": 2, "jpeg_encode_ms_total": 10}
            )
        stats = thumb_cropper.preview_cache_stats()
        self.assertEqual(stats["jpeg_encode_ms_avg"], 5)


if __name__ == "__main__":
    unittest.main()

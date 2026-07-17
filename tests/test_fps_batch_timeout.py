"""Tests for fps-batch tile timeout budgeting."""

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
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

from trickplay_generator import (  # noqa: E402
    _FPS_BATCH_TIMEOUT_CAP_SEC,
    _FPS_BATCH_TIMEOUT_FLOOR_SEC,
    _extract_tile_fast,
    _fps_batch_timeout_sec,
)


class FpsBatchTimeoutTests(unittest.TestCase):
    def test_short_tile_uses_floor(self) -> None:
        # 10 frames × 10s = 100s span → below floor
        self.assertEqual(_fps_batch_timeout_sec(100.0), _FPS_BATCH_TIMEOUT_FLOOR_SEC)

    def test_standard_tile_scales_then_caps(self) -> None:
        # 100 frames × 10s = 1000s span → 0.8*1000+60 = 860, under cap
        self.assertEqual(_fps_batch_timeout_sec(1000.0), 860.0)

    def test_long_span_hits_cap(self) -> None:
        # Would be 0.8*2000+60 = 1660 without cap
        self.assertEqual(_fps_batch_timeout_sec(2000.0), _FPS_BATCH_TIMEOUT_CAP_SEC)

    def test_cap_is_fifteen_minutes(self) -> None:
        self.assertEqual(_FPS_BATCH_TIMEOUT_CAP_SEC, 900.0)


class FpsBatchSeekFallbackTests(unittest.TestCase):
    @patch("trickplay_generator._extract_tile_fast_seek")
    @patch("trickplay_generator._extract_tile_batch_fps")
    @patch("trickplay_generator._should_use_fps_batch", return_value=True)
    @patch("trickplay_generator._clear_jpg_files")
    def test_empty_fps_batch_falls_back_to_seek(
        self,
        mock_clear: MagicMock,
        _mock_should: MagicMock,
        mock_batch: MagicMock,
        mock_seek: MagicMock,
    ) -> None:
        mock_batch.return_value = []
        mock_seek.return_value = ["a.jpg"]

        paths = _extract_tile_fast(
            ffmpeg="ffmpeg",
            env={},
            ffmpeg_input="/media.mkv",
            start_index=0,
            frame_count=10,
            interval_sec=10.0,
            tile_width=320,
            output_dir="/tmp/tile",
            thumb_vf="scale=320:-1",
            batch_vf="fps=1/10,scale=320:-1",
            tile_index=0,
            tile_count=1,
        )

        mock_batch.assert_called_once()
        mock_clear.assert_called_once_with("/tmp/tile")
        mock_seek.assert_called_once()
        self.assertEqual(paths, ["a.jpg"])

    @patch("trickplay_generator._extract_tile_fast_seek")
    @patch("trickplay_generator._extract_tile_batch_fps")
    @patch("trickplay_generator._should_use_fps_batch", return_value=True)
    def test_successful_fps_batch_skips_seek(
        self,
        _mock_should: MagicMock,
        mock_batch: MagicMock,
        mock_seek: MagicMock,
    ) -> None:
        mock_batch.return_value = ["a.jpg", "b.jpg"]

        paths = _extract_tile_fast(
            ffmpeg="ffmpeg",
            env={},
            ffmpeg_input="/media.mkv",
            start_index=0,
            frame_count=2,
            interval_sec=10.0,
            tile_width=320,
            output_dir="/tmp/tile",
            thumb_vf="scale=320:-1",
            batch_vf="fps=1/10,scale=320:-1",
        )

        mock_seek.assert_not_called()
        self.assertEqual(paths, ["a.jpg", "b.jpg"])


if __name__ == "__main__":
    unittest.main()

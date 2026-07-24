"""Tests for MJPEG-safe SDR JPEG output args."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.modules.setdefault("xbmc", MagicMock())
sys.modules.setdefault("xbmcvfs", MagicMock())
sys.modules.setdefault("xbmcaddon", MagicMock())
sys.modules.setdefault("xbmcgui", MagicMock())

from hdr_tone_map import (  # noqa: E402
    build_thumb_video_filter,
    ffmpeg_sdr_output_color_args,
    resolve_thumb_filter_context,
)


class MjpegSdrOutputTests(unittest.TestCase):
    def test_sdr_filter_forces_yuvj420p(self) -> None:
        vf = build_thumb_video_filter(320, apply_tonemap=False, tonemap_mode="none")
        self.assertTrue(vf.endswith("format=yuvj420p"))
        self.assertIn("yadif=", vf)

    def test_color_args_include_strict_unofficial(self) -> None:
        args = ffmpeg_sdr_output_color_args()
        self.assertIn("-strict", args)
        self.assertIn("unofficial", args)
        self.assertIn("yuvj420p", args)

    @patch("hdr_tone_map.probe_video_is_hdr", return_value=False)
    @patch("hdr_tone_map.detect_tonemap_support", return_value="zscale")
    def test_sdr_context_always_sets_mjpeg_color_args(
        self,
        _mock_detect: MagicMock,
        _mock_probe: MagicMock,
    ) -> None:
        ctx = resolve_thumb_filter_context(
            hdr_tone_map_enabled=True,
            tile_width=320,
            media_path="/media/show.mkv",
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            env={},
        )
        self.assertFalse(ctx.apply_tonemap)
        self.assertEqual(ctx.ffmpeg_color_args, ffmpeg_sdr_output_color_args())
        self.assertIn("format=yuvj420p", ctx.thumb_vf)

    @patch("hdr_tone_map.probe_video_is_hdr", return_value=False)
    def test_sdr_context_without_tonemap_setting_still_sets_color_args(
        self,
        _mock_probe: MagicMock,
    ) -> None:
        ctx = resolve_thumb_filter_context(
            hdr_tone_map_enabled=False,
            tile_width=320,
            media_path="/media/show.mkv",
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            env={},
        )
        self.assertFalse(ctx.apply_tonemap)
        self.assertEqual(ctx.ffmpeg_color_args, ffmpeg_sdr_output_color_args())


if __name__ == "__main__":
    unittest.main()

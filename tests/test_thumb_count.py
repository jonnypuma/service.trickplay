"""Tests for generator thumb timestamps vs media duration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = MagicMock()
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
sys.modules.setdefault("xbmc", xbmc)
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

from trickplay_generator import _thumb_count_for_duration  # noqa: E402


class ThumbCountTests(unittest.TestCase):
    def test_exact_multiple_excludes_eof_timestamp(self) -> None:
        # 2800s / 10s used to request t=2800.0, which ffmpeg cannot extract.
        self.assertEqual(_thumb_count_for_duration(2800.0, 10.0), 280)
        self.assertEqual((280 - 1) * 10.0, 2790.0)

    def test_non_multiple_keeps_last_in_range_thumb(self) -> None:
        self.assertEqual(_thumb_count_for_duration(2801.0, 10.0), 281)
        self.assertEqual(_thumb_count_for_duration(2791.0, 10.0), 280)

    def test_shorter_than_one_interval(self) -> None:
        self.assertEqual(_thumb_count_for_duration(5.0, 10.0), 1)


if __name__ == "__main__":
    unittest.main()

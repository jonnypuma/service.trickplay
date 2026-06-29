"""Tests for playhead-following prefetch index selection."""

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

from prefetch import _follow_warm_indices, _symmetric_window_indices


class PrefetchFollowIndicesTests(unittest.TestCase):
    def test_symmetric_window_includes_center_and_neighbors(self) -> None:
        indices = _symmetric_window_indices(center_index=10, max_index=20, radius=2)
        self.assertEqual(indices, [10, 11, 9, 12, 8])

    def test_follow_warm_full_window_on_first_position(self) -> None:
        indices = _follow_warm_indices(
            center_index=10, last_index=-1, max_index=20, radius=2
        )
        self.assertEqual(indices, [10, 11, 9, 12, 8])

    def test_follow_warm_only_new_edge_when_advancing(self) -> None:
        indices = _follow_warm_indices(
            center_index=11, last_index=10, max_index=20, radius=2
        )
        self.assertEqual(indices, [11, 13])

    def test_follow_warm_skips_when_unchanged(self) -> None:
        indices = _follow_warm_indices(
            center_index=10, last_index=10, max_index=20, radius=2
        )
        self.assertEqual(indices, [])


if __name__ == "__main__":
    unittest.main()

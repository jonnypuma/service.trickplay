"""Tests for playhead-following prefetch index selection."""

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

from prefetch import ThumbPrefetch, _follow_warm_indices, _symmetric_window_indices
from trickplay_resolver import TrickplayLookup, TrickplayResolution


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

    @patch("prefetch.lookup_thumbnail")
    @patch("prefetch.read_prefetch_settings")
    def test_schedule_playhead_follow_resolves_lookup(
        self,
        mock_read_settings: MagicMock,
        mock_lookup_thumbnail: MagicMock,
    ) -> None:
        settings = MagicMock()
        settings.enabled = True
        settings.during_playback = True
        settings.radius = 2
        settings.max_queue = 48
        mock_read_settings.return_value = settings

        resolution = TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg",),
            thumb_width=320,
            thumb_height=180,
            thumbnail_count=10,
        )
        lookup = TrickplayLookup(
            tile_path="/tiles/0.jpg",
            col=1,
            row=0,
            thumb_width=320,
            thumb_height=180,
            thumb_index=1,
            target_second=10,
        )
        mock_lookup_thumbnail.return_value = lookup

        prefetch = ThumbPrefetch()
        prefetch._schedule_indices = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_playhead_follow(resolution, 10, 10000)

        mock_lookup_thumbnail.assert_called_once_with(resolution, 10, 10000)
        prefetch._schedule_indices.assert_called_once()


if __name__ == "__main__":
    unittest.main()

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


class PrefetchPriorityTests(unittest.TestCase):
    def _lookup(self, index: int, tile: str = "/tiles/0.jpg") -> TrickplayLookup:
        return TrickplayLookup(
            tile_path=tile,
            col=index % 10,
            row=index // 10,
            thumb_width=320,
            thumb_height=180,
            thumb_index=index,
            target_second=index * 10,
        )

    @patch("prefetch.get_cached_thumb_path", return_value=None)
    def test_high_priority_goes_to_front(self, _mock_cached: MagicMock) -> None:
        prefetch = ThumbPrefetch()
        prefetch._max_queue = 48
        prefetch._ensure_worker = MagicMock()  # type: ignore[method-assign]

        prefetch._enqueue(self._lookup(1), high_priority=False)
        prefetch._enqueue(self._lookup(2), high_priority=False)
        prefetch._enqueue(self._lookup(9), high_priority=True)

        with prefetch._lock:
            front = prefetch._queue[0].lookup.thumb_index
        self.assertEqual(front, 9)

    @patch("prefetch.get_cached_thumb_path", return_value=None)
    def test_yield_for_scrub_keeps_preferred_high_priority(
        self, _mock_cached: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_worker = MagicMock()  # type: ignore[method-assign]
        prefetch._debug = False

        prefetch._enqueue(self._lookup(1, "/tiles/0.jpg"), high_priority=False)
        prefetch._enqueue(self._lookup(2, "/tiles/0.jpg"), high_priority=False)
        prefetch._enqueue(self._lookup(201, "/tiles/2.jpg"), high_priority=True)

        prefetch.yield_for_scrub("/tiles/2.jpg")

        with prefetch._lock:
            indices = [item.lookup.thumb_index for item in prefetch._queue]
            tiles = [item.lookup.tile_path for item in prefetch._queue]
        self.assertEqual(indices, [201])
        self.assertEqual(tiles, ["/tiles/2.jpg"])


class ScrubChurnTests(unittest.TestCase):
    def test_single_large_jump_is_not_fast_scrub(self) -> None:
        from preview_dialog import PreviewDialogController

        controller = PreviewDialogController("/addon")
        lookup_near = TrickplayLookup(
            tile_path="/t/0.jpg",
            col=0,
            row=0,
            thumb_width=320,
            thumb_height=180,
            thumb_index=1,
            target_second=10,
        )
        lookup_far = TrickplayLookup(
            tile_path="/t/2.jpg",
            col=1,
            row=4,
            thumb_width=320,
            thumb_height=180,
            thumb_index=241,
            target_second=2410,
        )
        # Prime last scrub as a settled position (not within coalesce window).
        controller._last_scrub_at = 0.0
        controller._last_scrub_thumb_index = 1
        self.assertFalse(
            controller._scrub_churn_active(lookup_far, seeking=True)
        )

        # Rapid follow-up with another jump is churn.
        controller._last_scrub_at = __import__("time").monotonic()
        controller._last_scrub_thumb_index = 241
        self.assertTrue(
            controller._scrub_churn_active(lookup_near, seeking=True)
        )


if __name__ == "__main__":
    unittest.main()

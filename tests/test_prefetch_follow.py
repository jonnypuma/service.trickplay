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

from prefetch import (
    ThumbPrefetch,
    _follow_warm_indices,
    _symmetric_window_indices,
    copy_order_for_tiles,
    nearest_ready_thumb_path,
    upcoming_tile_to_warm,
)
from prefetch_settings import (
    PLAYBACK_WARM_SECONDS,
    PrefetchSettings,
    thumb_indices_for_seconds,
)
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

    def test_playback_warm_converts_time_window_to_indices(self) -> None:
        settings = PrefetchSettings(radius_seconds=120)
        self.assertEqual(settings.radius_indices(10000), 12)
        self.assertEqual(settings.radius_indices(5000), 24)
        self.assertEqual(settings.playback_warm_indices(10000), 5)
        self.assertEqual(settings.playback_warm_indices(5000), 10)
        self.assertEqual(settings.radius_symmetric(10000), 12)
        defaults = PrefetchSettings()
        self.assertEqual(defaults.cache_max_mb, 1000)
        self.assertEqual(defaults.decoded_tile_ram_max, 24)
        self.assertEqual(defaults.crop_ram_max_mb, 64)
        self.assertTrue(defaults.preload_tiles)

    def test_thumb_indices_for_seconds_caps_and_floors(self) -> None:
        self.assertEqual(thumb_indices_for_seconds(120, 10000, cap=48), 12)
        self.assertEqual(thumb_indices_for_seconds(120, 2000, cap=24), 24)
        self.assertEqual(thumb_indices_for_seconds(15, 10000, cap=48), 2)
        self.assertEqual(thumb_indices_for_seconds(50, 10000, cap=48), 5)
        self.assertEqual(PLAYBACK_WARM_SECONDS, 50)

    @patch("prefetch.lookup_thumbnail")
    @patch("prefetch.read_prefetch_settings")
    def test_schedule_playhead_follow_uses_playback_warm_indices(
        self,
        mock_read_settings: MagicMock,
        mock_lookup_thumbnail: MagicMock,
    ) -> None:
        settings = PrefetchSettings(
            enabled=True,
            during_playback=True,
            radius_seconds=120,
            max_queue=48,
        )
        mock_read_settings.return_value = settings

        resolution = TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg",),
            thumb_width=320,
            thumb_height=180,
            thumbnail_count=100,
        )
        lookup = TrickplayLookup(
            tile_path="/tiles/0.jpg",
            col=1,
            row=0,
            thumb_width=320,
            thumb_height=180,
            thumb_index=10,
            target_second=100,
        )
        mock_lookup_thumbnail.return_value = lookup

        prefetch = ThumbPrefetch()
        prefetch._schedule_indices = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_playhead_follow(resolution, 100, 10000)

        mock_lookup_thumbnail.assert_called_once_with(resolution, 100, 10000)
        prefetch._schedule_indices.assert_called_once()
        indices = prefetch._schedule_indices.call_args.args[2]
        # ±50 s playback window at 10 s interval = 5 indices, not full ±120 s
        self.assertEqual(indices, [10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 5])

    @patch("prefetch.lookup_thumbnail")
    @patch("prefetch.read_prefetch_settings")
    def test_schedule_playhead_follow_scales_with_shorter_interval(
        self,
        mock_read_settings: MagicMock,
        mock_lookup_thumbnail: MagicMock,
    ) -> None:
        mock_read_settings.return_value = PrefetchSettings(
            enabled=True,
            during_playback=True,
            radius_seconds=120,
        )
        resolution = TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg",),
            thumb_width=320,
            thumb_height=180,
            thumbnail_count=200,
        )
        lookup = TrickplayLookup(
            tile_path="/tiles/0.jpg",
            col=0,
            row=2,
            thumb_width=320,
            thumb_height=180,
            thumb_index=20,
            target_second=100,
        )
        mock_lookup_thumbnail.return_value = lookup
        prefetch = ThumbPrefetch()
        prefetch._schedule_indices = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_playhead_follow(resolution, 100, 5000)
        indices = prefetch._schedule_indices.call_args.args[2]
        # ±50 s at 5 s interval = 10 indices (center + 10 ahead/behind interleaved)
        self.assertEqual(len(indices), 21)
        self.assertEqual(indices[0], 20)
        self.assertIn(30, indices)
        self.assertIn(10, indices)
        self.assertNotIn(31, indices)


class UpcomingTileWarmTests(unittest.TestCase):
    def _resolution(self, thumbnail_count: int = 300) -> TrickplayResolution:
        return TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"),
            thumb_width=320,
            thumb_height=180,
            thumbnail_count=thumbnail_count,
        )

    def test_last_20_percent_selects_next_tile(self) -> None:
        resolution = self._resolution()
        self.assertIsNone(upcoming_tile_to_warm(resolution, 79, direction=1))
        self.assertEqual(
            upcoming_tile_to_warm(resolution, 80, direction=1),
            "/tiles/1.jpg",
        )
        self.assertEqual(
            upcoming_tile_to_warm(resolution, 180, direction=1),
            "/tiles/2.jpg",
        )
        self.assertIsNone(upcoming_tile_to_warm(resolution, 280, direction=1))

    def test_first_20_percent_selects_previous_tile_in_reverse(self) -> None:
        resolution = self._resolution()
        self.assertEqual(
            upcoming_tile_to_warm(resolution, 100, direction=-1),
            "/tiles/0.jpg",
        )
        self.assertIsNone(upcoming_tile_to_warm(resolution, 130, direction=-1))

    def test_partial_last_tile_has_no_next(self) -> None:
        resolution = self._resolution(thumbnail_count=250)
        self.assertIsNone(upcoming_tile_to_warm(resolution, 240, direction=1))
        self.assertEqual(
            upcoming_tile_to_warm(resolution, 180, direction=1),
            "/tiles/2.jpg",
        )

    @patch("prefetch.read_prefetch_settings")
    def test_playhead_follow_warms_next_tile_in_last_20_percent(
        self, mock_read_settings: MagicMock
    ) -> None:
        mock_read_settings.return_value = PrefetchSettings(
            enabled=True,
            during_playback=True,
        )
        resolution = self._resolution()
        prefetch = ThumbPrefetch()
        prefetch._schedule_indices = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_tile_warm = MagicMock(  # type: ignore[method-assign]
            return_value="/tiles/1.jpg"
        )

        prefetch.schedule_playhead_follow(resolution, 790, 10000)
        prefetch.schedule_tile_warm.assert_not_called()

        prefetch.schedule_playhead_follow(resolution, 850, 10000)
        prefetch.schedule_tile_warm.assert_called_once_with(
            "/tiles/1.jpg", debug=False
        )

    @patch("prefetch.threading.Thread")
    def test_schedule_tile_warm_is_once_per_tile(
        self, mock_thread: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch.prioritize_tile_copy = MagicMock()  # type: ignore[method-assign]

        first = prefetch.schedule_tile_warm("/tiles/1.jpg")
        second = prefetch.schedule_tile_warm("/tiles/1.jpg")

        self.assertEqual(first, "/tiles/1.jpg")
        self.assertIsNone(second)
        prefetch.prioritize_tile_copy.assert_called_once_with("/tiles/1.jpg")
        mock_thread.assert_called_once()

    @patch("prefetch.threading.Thread")
    def test_cancel_without_clearing_copies_keeps_warmed_set(
        self, _mock_thread: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch.prioritize_tile_copy = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_tile_warm("/tiles/1.jpg")
        prefetch.cancel(clear_copies=False)
        self.assertIn("/tiles/1.jpg", prefetch._warmed_tiles)
        prefetch.cancel()
        self.assertNotIn("/tiles/1.jpg", prefetch._warmed_tiles)


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
        prefetch._enqueue_tile_decode = MagicMock()  # type: ignore[method-assign]
        prefetch.prioritize_tile_copy = MagicMock()  # type: ignore[method-assign]
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

    @patch("prefetch.get_cached_thumb_path", return_value=None)
    def test_yield_for_scrub_keeps_already_local_tiles(
        self, _mock_cached: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_worker = MagicMock()  # type: ignore[method-assign]
        prefetch._enqueue_tile_decode = MagicMock()  # type: ignore[method-assign]
        prefetch.prioritize_tile_copy = MagicMock()  # type: ignore[method-assign]
        prefetch._debug = False
        prefetch._copy_done.add("/tiles/0.jpg")

        prefetch._enqueue(self._lookup(1, "/tiles/0.jpg"), high_priority=False)
        prefetch._enqueue(self._lookup(2, "/tiles/0.jpg"), high_priority=False)
        prefetch._enqueue(self._lookup(201, "/tiles/2.jpg"), high_priority=True)

        prefetch.yield_for_scrub("/tiles/2.jpg")

        with prefetch._lock:
            indices = [item.lookup.thumb_index for item in prefetch._queue]
        self.assertEqual(indices, [201, 1, 2])


    @patch("prefetch.get_cached_thumb_path", return_value=None)
    def test_yield_for_scrub_skips_decode_when_tile_already_ready(
        self, _mock_cached: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_worker = MagicMock()  # type: ignore[method-assign]
        prefetch._enqueue_tile_decode = MagicMock()  # type: ignore[method-assign]
        prefetch.prioritize_tile_copy = MagicMock()  # type: ignore[method-assign]
        prefetch._copy_done.add("/tiles/0.jpg")
        prefetch._decoded_done.add("/tiles/0.jpg")
        prefetch.yield_for_scrub("/tiles/0.jpg")
        prefetch.prioritize_tile_copy.assert_called_once_with("/tiles/0.jpg")
        prefetch._enqueue_tile_decode.assert_not_called()


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


class PrefetchTileCopyTests(unittest.TestCase):
    def test_copy_order_puts_first_sprite_ahead_of_priority(self) -> None:
        self.assertEqual(
            copy_order_for_tiles(
                ("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"),
                prioritize=("/tiles/2.jpg",),
            ),
            ["/tiles/0.jpg", "/tiles/2.jpg", "/tiles/1.jpg"],
        )

    @patch("prefetch.temp_tile_copy", return_value="/local/tile.jpg")
    def test_schedule_all_tile_copies_priority_order(
        self, mock_copy: MagicMock
    ) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_copy_worker = MagicMock()  # type: ignore[method-assign]

        prefetch.schedule_all_tile_copies(
            ("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"),
            prioritize=("/tiles/2.jpg",),
        )

        with prefetch._copy_lock:
            ordered = list(prefetch._copy_queue)
        self.assertEqual(
            ordered, ["/tiles/0.jpg", "/tiles/2.jpg", "/tiles/1.jpg"]
        )
        prefetch._ensure_copy_worker.assert_called()

    def test_prioritize_moves_to_front(self) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_copy_worker = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_all_tile_copies(
            ("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg")
        )
        prefetch.prioritize_tile_copy("/tiles/2.jpg")
        with prefetch._copy_lock:
            ordered = list(prefetch._copy_queue)
        self.assertEqual(ordered[0], "/tiles/2.jpg")


class EpisodePreloadTests(unittest.TestCase):
    def _resolution(self) -> TrickplayResolution:
        return TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg", "/tiles/1.jpg"),
            thumb_width=320,
            thumb_height=180,
            thumbnail_count=200,
        )

    def test_schedule_episode_preload_copies_and_queues_decode(self) -> None:
        prefetch = ThumbPrefetch()
        prefetch.schedule_all_tile_copies = MagicMock()  # type: ignore[method-assign]
        prefetch._enqueue_tile_decode = MagicMock()  # type: ignore[method-assign]
        settings = PrefetchSettings(enabled=True, preload_tiles=True)
        prefetch.schedule_episode_preload(
            self._resolution(),
            10000,
            prioritize=("/tiles/1.jpg",),
            settings=settings,
        )
        self.assertFalse(prefetch._episode_precrop)
        self.assertTrue(prefetch._episode_want_precrop)
        prefetch.schedule_all_tile_copies.assert_called_once()
        prefetch._enqueue_tile_decode.assert_called_once_with(
            "/tiles/0.jpg", high_priority=True
        )

    def test_enable_episode_precrop_queues_first_tile_first(self) -> None:
        prefetch = ThumbPrefetch()
        prefetch._enqueue_tile_decode = MagicMock()  # type: ignore[method-assign]
        settings = PrefetchSettings(enabled=True, preload_tiles=True)
        prefetch.schedule_all_tile_copies = MagicMock()  # type: ignore[method-assign]
        prefetch.schedule_episode_preload(
            self._resolution(), 10000, settings=settings
        )
        prefetch._enqueue_tile_decode.reset_mock()
        prefetch.enable_episode_precrop()
        self.assertTrue(prefetch._episode_precrop)
        calls = [call.args[0] for call in prefetch._enqueue_tile_decode.call_args_list]
        self.assertEqual(calls, ["/tiles/0.jpg", "/tiles/1.jpg"])
        self.assertTrue(
            prefetch._enqueue_tile_decode.call_args_list[0].kwargs.get("high_priority")
        )

    def test_enqueue_decode_is_fifo_unless_high_priority(self) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_decode_worker = MagicMock()  # type: ignore[method-assign]
        prefetch._enqueue_tile_decode("/tiles/0.jpg")
        prefetch._enqueue_tile_decode("/tiles/1.jpg")
        prefetch._enqueue_tile_decode("/tiles/2.jpg")
        with prefetch._decode_lock:
            ordered = list(prefetch._decode_queue)
        self.assertEqual(ordered, ["/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"])
        prefetch._enqueue_tile_decode("/tiles/2.jpg", high_priority=True)
        with prefetch._decode_lock:
            ordered = list(prefetch._decode_queue)
        self.assertEqual(ordered, ["/tiles/2.jpg", "/tiles/0.jpg", "/tiles/1.jpg"])

    def test_schedule_copies_skips_already_copied_tiles(self) -> None:
        prefetch = ThumbPrefetch()
        prefetch._ensure_copy_worker = MagicMock()  # type: ignore[method-assign]
        prefetch._copy_done.add("/tiles/0.jpg")
        prefetch._copy_done.add("/tiles/1.jpg")
        prefetch._copy_done.add("/tiles/2.jpg")
        prefetch.schedule_all_tile_copies(
            ("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"),
            debug=True,
        )
        with prefetch._copy_lock:
            self.assertEqual(list(prefetch._copy_queue), [])
        prefetch._ensure_copy_worker.assert_not_called()

    def test_nearest_ready_returns_closest_cached_neighbor(self) -> None:
        resolution = self._resolution()
        lookup = TrickplayLookup(
            tile_path="/tiles/0.jpg",
            col=0,
            row=1,
            thumb_width=320,
            thumb_height=180,
            thumb_index=10,
            target_second=100,
        )

        def _ready(tile_path, col, row, thumb_w, thumb_h):
            if col == 8 and row == 0:
                return "/ready-8.jpg"
            return None

        with patch("prefetch.get_ready_thumb_path", side_effect=_ready):
            path = nearest_ready_thumb_path(resolution, lookup, 10000)
        self.assertEqual(path, "/ready-8.jpg")


class FirstTileEnrichTests(unittest.TestCase):
    def _resolution(self) -> TrickplayResolution:
        return TrickplayResolution(
            width=320,
            tile_width=10,
            tile_height=10,
            tiles_dir="/tiles",
            tile_paths=("/tiles/0.jpg", "/tiles/1.jpg", "/tiles/2.jpg"),
        )

    @patch("trickplay_resolver.probe_image_dimensions", return_value=(3200, 1800))
    def test_initial_enrich_only_probes_first_sprite(
        self, mock_probe: MagicMock
    ) -> None:
        from trickplay_resolver import enrich_resolution

        enrich_resolution(
            self._resolution(), 3600, 10000, probe_last_tile=False
        )
        mock_probe.assert_called_once_with("/tiles/0.jpg", debug=False)

    @patch("trickplay_resolver.probe_image_dimensions", return_value=(3200, 1800))
    def test_last_tile_refine_probes_final_sprite(
        self, mock_probe: MagicMock
    ) -> None:
        from trickplay_resolver import enrich_resolution

        enrich_resolution(
            self._resolution(), 3600, 10000, probe_last_tile=True
        )
        probed = [call.args[0] for call in mock_probe.call_args_list]
        self.assertEqual(probed, ["/tiles/0.jpg", "/tiles/2.jpg"])


class SidecarLookupTests(unittest.TestCase):
    def test_lookup_paths_do_not_stat_playing_video(self) -> None:
        from trickplay_resolver import _sidecar_lookup_media_paths

        url = (
            "nfs://192.168.0.3/Media2/TV/Sugar (2024)/Season 1/"
            "Sugar.2024.S01E01.Olivia.mkv"
        )
        with patch("vfs_paths.xbmcvfs.translatePath", side_effect=lambda p: p), patch(
            "trickplay_resolver.resolve_media_path"
        ) as resolve_media, patch(
            "ffmpeg_media.resolve_ffmpeg_media_path"
        ) as resolve_ff:
            paths = _sidecar_lookup_media_paths(url)
        resolve_media.assert_not_called()
        resolve_ff.assert_not_called()
        self.assertIn(url, paths)


if __name__ == "__main__":
    unittest.main()

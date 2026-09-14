"""Generator queue snapshot, recent-idle filter, and weak-device preset."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import types
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

from generator_settings import apply_weak_device_generator_preset  # noqa: E402
from generator_status import (  # noqa: E402
    GeneratorQueueSnapshot,
    display_name,
    format_queue_report,
    read_queue_snapshot,
    write_queue_snapshot,
)
from generator_worker import GeneratorWorker  # noqa: E402
from library_recent import (  # noqa: E402
    apply_recent_idle_filter,
    filter_paths_by_recent,
    is_recent_by_mtime,
)


def _settings(**kwargs):
    values = {
        "tile_width": 320,
        "grid": "10x10",
        "interval_ms": 10000,
        "extract_mode": "fast",
        "overwrite_existing": False,
        "library_path": "/media",
        "debug": False,
        "idle_recent_only": False,
        "idle_recent_days": 14,
    }
    values.update(kwargs)
    return types.SimpleNamespace(**values)


class QueueSnapshotTests(unittest.TestCase):
    def test_display_name_uses_parent_and_file(self) -> None:
        self.assertEqual(
            display_name("/media/Show/Season 1/Show.S01E01.mkv"),
            "Season 1 / Show.S01E01.mkv",
        )
        self.assertEqual(display_name(""), "")

    def test_format_report_lists_current_and_queued(self) -> None:
        report = format_queue_report(
            GeneratorQueueSnapshot(
                state="running",
                current_path="/media/a.mkv",
                queued=["/media/b.mkv", "/media/c.mkv"],
                idle_remaining=4,
                paused=False,
            )
        )
        self.assertIn("State: running", report)
        self.assertIn("Current: media / a.mkv", report)
        self.assertIn("Queued: 2", report)
        self.assertIn("Idle remaining: 4", report)
        self.assertIn("- media / b.mkv", report)

    def test_write_and_read_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "queue.json")
            snapshot = GeneratorQueueSnapshot(
                state="queued",
                current_path="/media/now.mkv",
                queued=["/media/next.mkv"],
                idle_remaining=3,
                last_error="",
                paused=True,
            )
            with patch("generator_status._local_status_path", return_value=path):
                write_queue_snapshot(snapshot)
                loaded = read_queue_snapshot()
            self.assertEqual(loaded.state, "queued")
            self.assertEqual(loaded.current_path, "/media/now.mkv")
            self.assertEqual(loaded.queued, ["/media/next.mkv"])
            self.assertEqual(loaded.idle_remaining, 3)
            self.assertTrue(loaded.paused)


class RecentIdleFilterTests(unittest.TestCase):
    def test_filter_matches_path_variants(self) -> None:
        candidates = [
            "nfs://server/share/Show/a.mkv",
            "/media/old.mkv",
        ]
        recent = ["/storage/remote-shares/share/Show/a.mkv"]
        with patch(
            "library_recent.path_variants",
            side_effect=lambda path: (path, path.replace("nfs://server/", "/storage/remote-shares/")),
        ):
            matched = filter_paths_by_recent(candidates, recent)
        self.assertEqual(matched, ["nfs://server/share/Show/a.mkv"])

    def test_mtime_keeps_recent_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recent = Path(directory) / "new.mkv"
            old = Path(directory) / "old.mkv"
            recent.write_bytes(b"n")
            old.write_bytes(b"o")
            old_time = time.time() - 40 * 86400
            os.utime(old, (old_time, old_time))
            self.assertTrue(is_recent_by_mtime(str(recent), 14))
            self.assertFalse(is_recent_by_mtime(str(old), 14))

    def test_apply_uses_mtime_when_library_rpc_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recent = Path(directory) / "new.mkv"
            old = Path(directory) / "old.mkv"
            recent.write_bytes(b"n")
            old.write_bytes(b"o")
            old_time = time.time() - 40 * 86400
            os.utime(old, (old_time, old_time))
            with patch(
                "library_recent.list_recent_library_files", return_value=None
            ):
                kept = apply_recent_idle_filter([str(recent), str(old)], 14)
            self.assertEqual(kept, [str(recent)])


class IdleRecentWorkerTests(unittest.TestCase):
    def test_idle_scan_filters_recent_only(self) -> None:
        worker = GeneratorWorker()
        settings = _settings(idle_recent_only=True, idle_recent_days=14)
        plan = types.SimpleNamespace(
            candidates=["/media/a.mkv", "/media/b.mkv", "/media/c.mkv"]
        )
        with (
            patch(
                "generator_worker.collect_generation_candidates",
                return_value=plan,
            ),
            patch("generator_worker.load_completed", return_value=set()),
            patch(
                "generator_worker.apply_recent_idle_filter",
                return_value=["/media/b.mkv"],
            ) as recent_filter,
            patch.object(worker, "_publish_status"),
        ):
            worker._refresh_idle_candidates(settings)
        recent_filter.assert_called_once()
        self.assertEqual(worker._idle_candidates, ["/media/b.mkv"])

    def test_enqueue_publishes_snapshot(self) -> None:
        worker = GeneratorWorker()
        with patch.object(worker, "_publish_status") as publish, patch.object(
            worker, "_ensure_worker"
        ):
            worker.enqueue_paths(["/media/a.mkv"])
        publish.assert_called()
        self.assertEqual(worker.snapshot().queued, ["/media/a.mkv"])
        self.assertEqual(worker.snapshot().state, "queued")


class WeakDevicePresetTests(unittest.TestCase):
    def test_preset_writes_fast_seek_and_disables_hdr(self) -> None:
        addon = MagicMock()
        with patch("generator_settings._addon", return_value=addon):
            applied = apply_weak_device_generator_preset()
        self.assertEqual(applied["extract_mode"], "fast_seek")
        addon.setSettingString.assert_any_call("generator_extract_mode", "fast_seek")
        addon.setSettingBool.assert_any_call("generator_hdr_tone_map", False)
        addon.setSettingBool.assert_any_call("generator_hw_decode", False)

    def test_script_dispatch_resolves_new_modes(self) -> None:
        import script_generator

        self.assertEqual(
            script_generator._resolve_mode(
                ["service.trickplay", "generator_queue"]
            ),
            "generator_queue",
        )
        self.assertEqual(
            script_generator._resolve_mode(
                ["service.trickplay", "weak_device_preset"]
            ),
            "weak_device_preset",
        )


if __name__ == "__main__":
    unittest.main()

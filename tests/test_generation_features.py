"""Coverage for restart state and validation cache behavior."""

from __future__ import annotations

import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from kodi_test_stubs import install_kodi_stubs  # noqa: E402

install_kodi_stubs()

from generation_state import begin_or_update, clear, load_completed, load_remaining, mark_completed  # noqa: E402
from trickplay_validation import (  # noqa: E402
    _load_valid_cache,
    _write_valid_cache,
)
from generator_settings import GeneratorSettings  # noqa: E402
from trickplay_generator import (  # noqa: E402
    _atomic_promote_sidecar,
    generate_trickplay_for_media,
)
from vfs_paths import extended_length_path  # noqa: E402


class GenerationFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = types.SimpleNamespace(
            tile_width=320,
            grid="10x10",
            interval_ms=10000,
            extract_mode="fast",
        )

    def test_resume_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update("/media", self.settings, {"/media/a.mkv"})
                self.assertEqual(
                    load_completed("/media", self.settings),
                    {"/media/a.mkv"},
                )
                clear()
                self.assertEqual(load_completed("/media", self.settings), set())

    def test_remaining_queue_round_trip_and_mark_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    self.settings,
                    set(),
                    remaining=["/media/a.mkv", "/media/b.mkv", "/media/c.mkv"],
                )
                self.assertEqual(
                    load_remaining("/media", self.settings),
                    ["/media/a.mkv", "/media/b.mkv", "/media/c.mkv"],
                )
                mark_completed("/media", self.settings, "/media/a.mkv")
                self.assertEqual(
                    load_completed("/media", self.settings),
                    {"/media/a.mkv"},
                )
                self.assertEqual(
                    load_remaining("/media", self.settings),
                    ["/media/b.mkv", "/media/c.mkv"],
                )

    def test_begin_or_update_preserves_remaining_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    self.settings,
                    set(),
                    remaining=["/media/a.mkv", "/media/b.mkv"],
                )
                begin_or_update("/media", self.settings, {"/media/a.mkv"})
                self.assertEqual(
                    load_remaining("/media", self.settings),
                    ["/media/b.mkv"],
                )

    def test_remaining_drops_vanished_local_files_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            present = Path(directory) / "keep.mkv"
            present.write_bytes(b"data")
            missing = str(Path(directory) / "gone.mkv")
            state_path = str(Path(directory) / "state.json")
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    self.settings,
                    set(),
                    remaining=[str(present), missing],
                )
                self.assertEqual(
                    load_remaining("/media", self.settings, check_exists=False),
                    [str(present), missing],
                )
                self.assertEqual(
                    load_remaining("/media", self.settings, check_exists=True),
                    [str(present)],
                )

    def test_remaining_keeps_remote_urls_when_checking_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            remote = "nfs://server/share/show.mkv"
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    self.settings,
                    set(),
                    remaining=[remote],
                )
                self.assertEqual(
                    load_remaining("/media", self.settings, check_exists=True),
                    [remote],
                )

    def test_remaining_ignored_when_profile_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            other = types.SimpleNamespace(
                tile_width=320,
                grid="10x10",
                interval_ms=10000,
                extract_mode="accurate",
            )
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    self.settings,
                    set(),
                    remaining=["/media/a.mkv"],
                )
                self.assertEqual(load_remaining("/media", other), [])

    def test_validation_cache_tracks_tile_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tile = Path(directory) / "0.jpg"
            tile.write_bytes(b"tile")
            paths = {0: str(tile)}
            with patch(
                "trickplay_validation._valid_cache_path",
                return_value=str(Path(directory) / "valid.json"),
            ):
                _write_valid_cache(
                    directory,
                    tile_width=320,
                    grid="10x10",
                    interval_ms=10000,
                    duration=30,
                    expected_tiles=1,
                    paths=paths,
                )
                self.assertTrue(
                    _load_valid_cache(
                        directory,
                        tile_width=320,
                        grid="10x10",
                        interval_ms=10000,
                        duration=30,
                        expected_tiles=1,
                        paths=paths,
                    )
                )
                tile.write_bytes(b"changed")
                self.assertFalse(
                    _load_valid_cache(
                        directory,
                        tile_width=320,
                        grid="10x10",
                        interval_ms=10000,
                        duration=30,
                        expected_tiles=1,
                        paths=paths,
                    )
                )

    def test_atomic_promotion_replaces_only_after_staging_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "tiles"
            staging = Path(directory) / "tiles.tmp"
            final.mkdir()
            (final / "0.jpg").write_bytes(b"old")
            staging.mkdir()
            (staging / "0.jpg").write_bytes(b"new")
            promoted, error = _atomic_promote_sidecar(str(staging), str(final))
            self.assertTrue(promoted, error)
            self.assertEqual((final / "0.jpg").read_bytes(), b"new")
            self.assertFalse(staging.exists())

    def test_atomic_promotion_reports_os_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "tiles.tmp"
            final = Path(directory) / "tiles"
            staging.mkdir()
            (staging / "0.jpg").write_bytes(b"new")
            with patch(
                "trickplay_generator.os.replace",
                side_effect=OSError(206, "The filename or extension is too long"),
            ):
                promoted, error = _atomic_promote_sidecar(str(staging), str(final))
            self.assertFalse(promoted)
            self.assertIn("filename or extension is too long", error)

    def test_short_sidecar_rename_uses_plain_windows_path(self) -> None:
        if os.name != "nt":
            self.skipTest("windows extended paths")
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "tiles"
            staging = Path(directory) / "tiles.tmp"
            final.mkdir()
            (final / "0.jpg").write_bytes(b"old")
            staging.mkdir()
            (staging / "0.jpg").write_bytes(b"new")
            self.assertLess(len(str(staging)), 260)
            calls: list[tuple[str, str]] = []
            real_replace = os.replace

            def _spy(src: str, dst: str) -> None:
                calls.append((src, dst))
                real_replace(src, dst)

            with patch("trickplay_generator.os.replace", side_effect=_spy):
                promoted, error = _atomic_promote_sidecar(str(staging), str(final))
            self.assertTrue(promoted, error)
            self.assertTrue(calls)
            for src, dst in calls:
                self.assertFalse(src.startswith("\\\\?\\"), src)
                self.assertFalse(dst.startswith("\\\\?\\"), dst)
            self.assertEqual((final / "0.jpg").read_bytes(), b"new")

    def test_directory_rename_access_denied_replaces_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "tiles"
            staging = Path(directory) / "tiles.tmp"
            final.mkdir()
            (final / "0.jpg").write_bytes(b"old")
            (final / "1.jpg").write_bytes(b"stale")
            staging.mkdir()
            (staging / "0.jpg").write_bytes(b"new")
            real_replace = os.replace

            def _deny_directory_rename(src: str, dst: str) -> None:
                if os.path.isdir(src):
                    exc = OSError(13, "Access is denied")
                    exc.winerror = 5
                    raise exc
                real_replace(src, dst)

            with patch(
                "trickplay_generator.os.replace",
                side_effect=_deny_directory_rename,
            ):
                promoted, error = _atomic_promote_sidecar(str(staging), str(final))
            self.assertTrue(promoted, error)
            self.assertEqual((final / "0.jpg").read_bytes(), b"new")
            self.assertFalse((final / "1.jpg").exists())
            self.assertFalse(staging.exists())

    def test_atomic_promotion_past_max_path(self) -> None:
        if os.name != "nt":
            self.skipTest("windows extended paths")
        directory = tempfile.mkdtemp()
        try:
            deep = Path(directory)
            for _ in range(6):
                deep = deep / ("n" * 40)
            final = deep / "320 - 10x10 - 10000"
            staging = Path(str(final) + ".tmp-0123456789")
            self.assertGreater(len(str(staging)), 260)
            os.makedirs(extended_length_path(str(staging)))
            jpg = extended_length_path(os.path.join(str(staging), "0.jpg"))
            with open(jpg, "wb") as handle:
                handle.write(b"new")
            promoted, error = _atomic_promote_sidecar(str(staging), str(final))
            self.assertTrue(promoted, error)
            with open(
                extended_length_path(os.path.join(str(final), "0.jpg")),
                "rb",
            ) as handle:
                self.assertEqual(handle.read(), b"new")
            self.assertFalse(os.path.isdir(extended_length_path(str(staging))))
        finally:
            shutil.rmtree(extended_length_path(directory), ignore_errors=True)

    def test_missing_media_records_failure_reason(self) -> None:
        with patch("trickplay_generator.xbmcvfs.exists", return_value=False):
            result = generate_trickplay_for_media(
                r"Y:\TV\missing.mkv",
                GeneratorSettings(),
            )
        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "media not found")

    def test_unreadable_media_records_duration_reason(self) -> None:
        filter_ctx = types.SimpleNamespace(
            ffmpeg_color_args=(),
            ffmpeg_input_args=(),
            apply_tonemap=False,
            thumb_vf="",
            use_dovi_tool_zscale_prep=False,
        )
        with (
            patch("trickplay_generator.xbmcvfs.exists", return_value=True),
            patch(
                "trickplay_generator.find_matching_sidecar_resolution",
                return_value=None,
            ),
            patch("trickplay_generator._has_jpg_tiles", return_value=False),
            patch(
                "trickplay_generator.resolve_generator_ffmpeg_tools",
                return_value=("ffmpeg", "ffprobe", {}),
            ),
            patch(
                "trickplay_generator.resolve_thumb_filter_context",
                return_value=filter_ctx,
            ),
            patch("trickplay_generator.probe_video_duration_seconds", return_value=0),
        ):
            result = generate_trickplay_for_media(
                r"Y:\TV\Show\Episode.mkv",
                GeneratorSettings(),
            )
        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "could not read media duration")


if __name__ == "__main__":
    unittest.main()

"""Fast-seek continue-on-fail and shorter per-frame timeout."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from kodi_test_stubs import install_kodi_stubs  # noqa: E402

install_kodi_stubs()

import trickplay_generator as gen  # noqa: E402


class FastSeekTimeoutTests(unittest.TestCase):
    def test_timeout_matches_batch_seeks_single_input(self) -> None:
        self.assertEqual(gen._FAST_FRAME_TIMEOUT_SEC, 25.0)


class FastSeekSkipTests(unittest.TestCase):
    def test_failed_mid_tile_reuses_previous_and_continues(self) -> None:
        fail_at = {10.0}

        def fake_extract(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            if timestamp in fail_at:
                return False
            Path(output_path).write_bytes(f"ok-{timestamp}".encode())
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_fast", side_effect=fake_extract):
                paths = gen._extract_tile_fast_seek(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=4,
                    interval_sec=10.0,
                    tile_width=320,
                    output_dir=tmp,
                    thumb_vf="scale=320:-2",
                )
            self.assertEqual(len(paths), 4)
            self.assertEqual(Path(paths[0]).read_bytes(), b"ok-0.0")
            self.assertEqual(Path(paths[1]).read_bytes(), b"ok-0.0")
            self.assertEqual(Path(paths[2]).read_bytes(), b"ok-20.0")
            self.assertEqual(Path(paths[3]).read_bytes(), b"ok-30.0")

    def test_leading_failures_backfill_from_first_success(self) -> None:
        def fake_extract(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            if timestamp < 20.0:
                return False
            Path(output_path).write_bytes(b"later")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_fast", side_effect=fake_extract):
                paths = gen._extract_tile_fast_seek(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=3,
                    interval_sec=10.0,
                    tile_width=320,
                    output_dir=tmp,
                    thumb_vf="scale=320:-2",
                )
            self.assertEqual(len(paths), 3)
            for path in paths:
                self.assertEqual(Path(path).read_bytes(), b"later")
            names = [os.path.basename(path) for path in paths]
            self.assertEqual(names, ["00000.jpg", "00001.jpg", "00002.jpg"])

    def test_all_failures_return_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_fast", return_value=False):
                paths = gen._extract_tile_fast_seek(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=3,
                    interval_sec=10.0,
                    tile_width=320,
                    output_dir=tmp,
                    thumb_vf="scale=320:-2",
                )
            self.assertEqual(paths, [])


class AccurateTimeoutTests(unittest.TestCase):
    def test_early_stamp_matches_fast_seek_floor(self) -> None:
        self.assertEqual(gen._accurate_frame_timeout_sec(0.0), 25.0)
        self.assertEqual(gen._accurate_frame_timeout_sec(10.0), 27.0)

    def test_late_stamp_caps_below_old_ten_minute_floor(self) -> None:
        self.assertEqual(gen._accurate_frame_timeout_sec(2791.0), 180.0)
        self.assertLess(gen._accurate_frame_timeout_sec(2791.0), 600.0)


class AccurateSkipTests(unittest.TestCase):
    def test_failed_mid_tile_falls_back_to_fast_seek(self) -> None:
        accurate_at: list[float] = []

        def fake_accurate(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            accurate_at.append(timestamp)
            if timestamp == 0.0:
                Path(output_path).write_bytes(b"acc-0")
                return True
            return False

        def fake_fast(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            Path(output_path).write_bytes(f"fast-{timestamp}".encode())
            return True

        state = gen.AccurateExtractState()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_accurate", side_effect=fake_accurate):
                with patch.object(gen, "_extract_frame_fast", side_effect=fake_fast):
                    paths = gen._extract_tile_accurate(
                        ffmpeg="ffmpeg",
                        env={},
                        ffmpeg_input=r"X:\TV\ep.mkv",
                        start_index=0,
                        frame_count=4,
                        interval_sec=10.0,
                        tile_width=320,
                        output_dir=tmp,
                        thumb_vf="scale=320:-2",
                        accurate_state=state,
                    )
            self.assertEqual(len(paths), 4)
            self.assertEqual(accurate_at, [0.0, 10.0])
            self.assertTrue(state.fast_fallback_active)
            self.assertEqual(Path(paths[0]).read_bytes(), b"acc-0")
            self.assertEqual(Path(paths[1]).read_bytes(), b"fast-10.0")
            self.assertEqual(Path(paths[2]).read_bytes(), b"fast-20.0")
            self.assertEqual(Path(paths[3]).read_bytes(), b"fast-30.0")

    def test_fast_fallback_then_reuse_when_fast_also_fails(self) -> None:
        def fake_accurate(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            if timestamp == 0.0:
                Path(output_path).write_bytes(b"acc-0")
                return True
            return False

        def fake_fast(
            ffmpeg,
            env,
            ffmpeg_input,
            timestamp,
            tile_width,
            output_path,
            thumb_vf,
            **kwargs,
        ) -> bool:
            if timestamp == 10.0:
                return False
            Path(output_path).write_bytes(f"fast-{timestamp}".encode())
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_accurate", side_effect=fake_accurate):
                with patch.object(gen, "_extract_frame_fast", side_effect=fake_fast):
                    paths = gen._extract_tile_accurate(
                        ffmpeg="ffmpeg",
                        env={},
                        ffmpeg_input=r"X:\TV\ep.mkv",
                        start_index=0,
                        frame_count=3,
                        interval_sec=10.0,
                        tile_width=320,
                        output_dir=tmp,
                        thumb_vf="scale=320:-2",
                    )
            self.assertEqual(len(paths), 3)
            self.assertEqual(Path(paths[0]).read_bytes(), b"acc-0")
            self.assertEqual(Path(paths[1]).read_bytes(), b"acc-0")
            self.assertEqual(Path(paths[2]).read_bytes(), b"fast-20.0")

    def test_all_failures_return_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "_extract_frame_accurate", return_value=False):
                with patch.object(gen, "_extract_frame_fast", return_value=False):
                    paths = gen._extract_tile_accurate(
                        ffmpeg="ffmpeg",
                        env={},
                        ffmpeg_input=r"X:\TV\ep.mkv",
                        start_index=0,
                        frame_count=3,
                        interval_sec=10.0,
                        tile_width=320,
                        output_dir=tmp,
                        thumb_vf="scale=320:-2",
                    )
            self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()

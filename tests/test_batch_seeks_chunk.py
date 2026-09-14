"""Batch-seeks chunk size and timeout (Windows multi-open hang)."""

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

import experimental_extract  # noqa: E402


class BatchSeeksChunkPolicyTests(unittest.TestCase):
    def test_windows_always_single_input(self) -> None:
        with patch.object(experimental_extract.os, "name", "nt"):
            self.assertEqual(
                experimental_extract._batch_seeks_ffmpeg_chunk_size(r"X:\TV\ep.mkv"),
                1,
            )
            self.assertEqual(
                experimental_extract._batch_seeks_ffmpeg_chunk_size(r"C:\local\ep.mkv"),
                1,
            )

    def test_posix_local_keeps_eight(self) -> None:
        with patch.object(experimental_extract.os, "name", "posix"):
            self.assertEqual(
                experimental_extract._batch_seeks_ffmpeg_chunk_size("/storage/ep.mkv"),
                8,
            )

    def test_posix_network_is_single_input(self) -> None:
        with patch.object(experimental_extract.os, "name", "posix"):
            self.assertEqual(
                experimental_extract._batch_seeks_ffmpeg_chunk_size(
                    "smb://nas/Media/ep.mkv"
                ),
                1,
            )

    def test_chunk_timeout_is_capped(self) -> None:
        self.assertEqual(experimental_extract._batch_seeks_chunk_timeout_sec(1), 25.0)
        self.assertEqual(experimental_extract._batch_seeks_chunk_timeout_sec(8), 60.0)
        self.assertLess(
            experimental_extract._batch_seeks_chunk_timeout_sec(8),
            8 * 120,
        )

    def test_timeout_detail_is_detected(self) -> None:
        self.assertTrue(
            experimental_extract._chunk_timed_out(-1, "timeout", 1.0, 25.0)
        )
        self.assertTrue(
            experimental_extract._chunk_timed_out(-1, "ffmpeg: error", 25.0, 25.0)
        )
        self.assertFalse(
            experimental_extract._chunk_timed_out(0, "", 0.4, 25.0)
        )


class BatchSeeksFfmpegExtractTests(unittest.TestCase):
    def test_windows_passes_one_input_and_short_timeout(self) -> None:
        calls: list[tuple[list[str], float]] = []

        def run_sub(cmd, env, timeout, should_cancel):
            calls.append((cmd, timeout))
            out = cmd[-1]
            Path(out).write_bytes(b"jpg")
            return (0, "")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(experimental_extract.os, "name", "nt"):
                paths = experimental_extract._extract_tile_batch_seeks_ffmpeg(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=3,
                    interval_sec=10.0,
                    vf="scale=320:-2",
                    output_dir=tmp,
                    tile_index=0,
                    tile_count=1,
                    debug=False,
                    should_cancel=None,
                    run_subprocess=run_sub,
                    frame_fallback=None,
                )
        self.assertEqual(len(paths), 3)
        self.assertEqual(len(calls), 3)
        for cmd, timeout in calls:
            self.assertEqual(sum(1 for part in cmd if part == "-i"), 1)
            self.assertEqual(timeout, 25.0)

    def test_timeout_falls_back_and_skips_later_ffmpeg(self) -> None:
        ffmpeg_calls = {"n": 0}
        fallback_ts: list[float] = []

        def run_sub(cmd, env, timeout, should_cancel):
            ffmpeg_calls["n"] += 1
            return (-1, "timeout")

        def fallback(timestamp: float, output_path: str) -> bool:
            fallback_ts.append(timestamp)
            Path(output_path).write_bytes(b"jpg")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(experimental_extract.os, "name", "nt"):
                paths = experimental_extract._extract_tile_batch_seeks_ffmpeg(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=3,
                    interval_sec=10.0,
                    vf="scale=320:-2",
                    output_dir=tmp,
                    tile_index=0,
                    tile_count=1,
                    debug=False,
                    should_cancel=None,
                    run_subprocess=run_sub,
                    frame_fallback=fallback,
                )
        self.assertEqual(len(paths), 3)
        # First chunk times out; remaining frames skip ffmpeg.
        self.assertEqual(ffmpeg_calls["n"], 1)
        self.assertEqual(fallback_ts, [0.0, 10.0, 20.0])

    def test_timeout_reuses_previous_and_continues(self) -> None:
        ffmpeg_calls = {"n": 0}
        fallback_ts: list[float] = []

        def run_sub(cmd, env, timeout, should_cancel):
            ffmpeg_calls["n"] += 1
            if ffmpeg_calls["n"] == 1:
                Path(cmd[-1]).write_bytes(b"first")
                return (0, "")
            return (-1, "timeout")

        def fallback(timestamp: float, output_path: str) -> bool:
            fallback_ts.append(timestamp)
            Path(output_path).write_bytes(b"fast")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(experimental_extract.os, "name", "nt"):
                paths = experimental_extract._extract_tile_batch_seeks_ffmpeg(
                    ffmpeg="ffmpeg",
                    env={},
                    ffmpeg_input=r"X:\TV\ep.mkv",
                    start_index=0,
                    frame_count=3,
                    interval_sec=10.0,
                    vf="scale=320:-2",
                    output_dir=tmp,
                    tile_index=0,
                    tile_count=1,
                    debug=False,
                    should_cancel=None,
                    run_subprocess=run_sub,
                    frame_fallback=fallback,
                )
            self.assertEqual(len(paths), 3)
            self.assertEqual(ffmpeg_calls["n"], 2)
            # Timed-out 10.0s copies the first JPEG; 20.0s still uses Fast.
            self.assertEqual(fallback_ts, [20.0])
            self.assertEqual(Path(paths[0]).read_bytes(), b"first")
            self.assertEqual(Path(paths[1]).read_bytes(), b"first")
            self.assertEqual(Path(paths[2]).read_bytes(), b"fast")


if __name__ == "__main__":
    unittest.main()

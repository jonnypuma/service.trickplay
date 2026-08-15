"""Coverage for restart state and validation cache behavior."""

from __future__ import annotations

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

from generation_state import begin_or_update, clear, load_completed  # noqa: E402
from trickplay_validation import (  # noqa: E402
    _load_valid_cache,
    _write_valid_cache,
)
from trickplay_generator import _atomic_promote_sidecar  # noqa: E402


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
            self.assertTrue(_atomic_promote_sidecar(str(staging), str(final)))
            self.assertEqual((final / "0.jpg").read_bytes(), b"new")
            self.assertFalse(staging.exists())


if __name__ == "__main__":
    unittest.main()

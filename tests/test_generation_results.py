"""Tests for structured generator results and validation classification."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = types.ModuleType("xbmc")
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
xbmc.LOGERROR = 2
xbmc.log = lambda *args, **kwargs: None
sys.modules.setdefault("xbmc", xbmc)

xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda path: path
sys.modules.setdefault("xbmcvfs", xbmcvfs)
sys.modules.setdefault("xbmcaddon", types.ModuleType("xbmcaddon"))
sys.modules.setdefault("xbmcgui", types.ModuleType("xbmcgui"))

from trickplay_generator import GenerationResult  # noqa: E402
from trickplay_validation import SidecarValidation  # noqa: E402


class GenerationResultTests(unittest.TestCase):
    def test_success_result_is_truthy(self) -> None:
        result = GenerationResult(
            media_path="/media/movie.mkv",
            success=True,
            tiles_written=3,
            tile_count=3,
            elapsed_seconds=12.5,
            fallback_count=1,
        )
        self.assertTrue(result)
        self.assertEqual(result.fallback_count, 1)

    def test_cancelled_result_is_false(self) -> None:
        result = GenerationResult(
            media_path="/media/movie.mkv",
            success=False,
            cancelled=True,
        )
        self.assertFalse(result)


class SidecarValidationTests(unittest.TestCase):
    def test_complete_sidecar_is_valid(self) -> None:
        item = SidecarValidation(
            media_path="/media/movie.mkv",
            sidecar_dir="/media/movie.trickplay/320 - 10x10 - 10000",
            expected_tiles=2,
            present_tiles=2,
        )
        self.assertTrue(item.valid)
        self.assertFalse(item.repair_needed)

    def test_missing_or_corrupt_tiles_need_repair(self) -> None:
        item = SidecarValidation(
            media_path="/media/movie.mkv",
            sidecar_dir="/media/movie.trickplay/320 - 10x10 - 10000",
            expected_tiles=3,
            present_tiles=2,
            missing_tiles=(2,),
            corrupt_tiles=(1,),
            reason="missing tile(s): 2; corrupt tile(s): 1",
        )
        self.assertFalse(item.valid)
        self.assertTrue(item.repair_needed)


if __name__ == "__main__":
    unittest.main()

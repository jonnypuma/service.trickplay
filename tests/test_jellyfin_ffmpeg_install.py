"""Tests for jellyfin-ffmpeg download candidates and flat archive discovery."""

from __future__ import annotations

import os
import sys
import tempfile
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

from hdr_ffmpeg_installer import (
    _JELLYFIN_LINUX64_URL,
    _JELLYFIN_WIN64_URL,
    _BTBN_LINUX64_URL,
    _GYAN_WIN64_URL,
    _ffmpeg_download_candidates_for_platform,
    _find_bin_lib_dirs,
    should_offer_jellyfin_ffmpeg_upgrade,
)


class JellyfinDownloadCandidateTests(unittest.TestCase):
    @patch("hdr_ffmpeg_installer.platform.machine", return_value="AMD64")
    @patch("hdr_ffmpeg_installer.sys.platform", "win32")
    def test_win64_jellyfin_then_gyan(self, *_mocks) -> None:
        candidates = _ffmpeg_download_candidates_for_platform()
        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0][0], _JELLYFIN_WIN64_URL)
        self.assertIn("jellyfin", candidates[0][1].lower())
        self.assertEqual(candidates[1][0], _GYAN_WIN64_URL)

    @patch("hdr_ffmpeg_installer.platform.machine", return_value="x86_64")
    @patch("hdr_ffmpeg_installer.sys.platform", "linux")
    def test_linux64_jellyfin_then_btbn(self, *_mocks) -> None:
        candidates = _ffmpeg_download_candidates_for_platform()
        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0][0], _JELLYFIN_LINUX64_URL)
        self.assertEqual(candidates[1][0], _BTBN_LINUX64_URL)


class FlatArchiveLayoutTests(unittest.TestCase):
    def test_find_bin_lib_dirs_flat_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "ffmpeg"), "wb").close()
            open(os.path.join(tmp, "ffprobe"), "wb").close()
            found = _find_bin_lib_dirs(tmp)
            self.assertIsNotNone(found)
            assert found is not None
            bin_dir, lib_dir = found
            self.assertEqual(bin_dir, tmp)
            self.assertIsNone(lib_dir)

    def test_find_bin_lib_dirs_windows_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "ffmpeg.exe"), "wb").close()
            open(os.path.join(tmp, "ffprobe.exe"), "wb").close()
            found = _find_bin_lib_dirs(tmp)
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found[0], tmp)


class JellyfinUpgradeOfferTests(unittest.TestCase):
    @patch("hdr_ffmpeg_installer._ffmpeg_download_url_for_platform", return_value="http://x")
    @patch("hdr_ffmpeg_installer.should_offer_ffmpeg_download", return_value=False)
    @patch("hdr_ffmpeg_installer._resolved_ffmpeg_under_addon_install", return_value=True)
    @patch("hdr_ffmpeg_installer.generator_ffmpeg_is_jellyfin", return_value=False)
    def test_offers_when_legacy_addon_install(self, *_mocks) -> None:
        self.assertTrue(should_offer_jellyfin_ffmpeg_upgrade(""))

    @patch("hdr_ffmpeg_installer._ffmpeg_download_url_for_platform", return_value="http://x")
    @patch("hdr_ffmpeg_installer.should_offer_ffmpeg_download", return_value=False)
    @patch("hdr_ffmpeg_installer._resolved_ffmpeg_under_addon_install", return_value=True)
    @patch("hdr_ffmpeg_installer.generator_ffmpeg_is_jellyfin", return_value=True)
    def test_skips_when_already_jellyfin(self, *_mocks) -> None:
        self.assertFalse(should_offer_jellyfin_ffmpeg_upgrade(""))

    @patch("hdr_ffmpeg_installer._ffmpeg_download_url_for_platform", return_value="http://x")
    @patch("hdr_ffmpeg_installer.should_offer_ffmpeg_download", return_value=False)
    @patch("hdr_ffmpeg_installer._resolved_ffmpeg_under_addon_install", return_value=False)
    @patch("hdr_ffmpeg_installer.generator_ffmpeg_is_jellyfin", return_value=False)
    def test_skips_custom_external_path(self, *_mocks) -> None:
        self.assertFalse(should_offer_jellyfin_ffmpeg_upgrade("C:\\other\\ffmpeg.exe"))


class FfmpegBuildIdentityTests(unittest.TestCase):
    def test_identify_jellyfin(self) -> None:
        from ffmpeg_tools import identify_ffmpeg_build

        fake = MagicMock()
        fake.stdout = (
            "ffmpeg version 8.1.2-Jellyfin Copyright (c) 2000-2025 the FFmpeg developers\n"
            "built with gcc\n"
        )
        fake.stderr = ""
        with patch("ffmpeg_tools.subprocess.run", return_value=fake):
            vendor, first = identify_ffmpeg_build("/fake/ffmpeg")
        self.assertEqual(vendor, "jellyfin-ffmpeg")
        self.assertIn("Jellyfin", first)

    def test_identify_gyan(self) -> None:
        from ffmpeg_tools import identify_ffmpeg_build

        fake = MagicMock()
        fake.stdout = (
            "ffmpeg version 8.0-full_build-www.gyan.dev Copyright (c) 2000-2025\n"
        )
        fake.stderr = ""
        with patch("ffmpeg_tools.subprocess.run", return_value=fake):
            vendor, _first = identify_ffmpeg_build("C:\\fake\\ffmpeg.exe")
        self.assertEqual(vendor, "Gyan")


if __name__ == "__main__":
    unittest.main()


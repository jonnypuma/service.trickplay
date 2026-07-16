"""Unit tests for addon health reporting (no Kodi runtime)."""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _name in ("xbmc", "xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

sys.modules["xbmc"].LOGINFO = 1
sys.modules["xbmc"].LOGWARNING = 2


class AddonHealthTests(unittest.TestCase):
    def test_format_health_report_includes_key_fields(self) -> None:
        from addon_health import AddonHealth, format_health_report

        report = format_health_report(
            AddonHealth(
                skin_id="skin.bingie",
                skin_name="Bingie",
                profile_label="Bingie",
                snippet_file="DialogSeekBar-skin.bingie.xml",
                target_xml="DialogSeekBar.xml",
                snippet_state="stale",
                pillow_ok=True,
                ffmpeg="C:\\ffmpeg\\bin\\ffmpeg.exe",
                overlay_revision=4,
            )
        )
        self.assertIn("Bingie", report)
        self.assertIn("STALE", report)
        self.assertIn("Pillow: OK", report)
        self.assertIn("Expected overlay rev: 4", report)

    def test_collect_addon_health_handles_missing_skin(self) -> None:
        from addon_health import collect_addon_health
        from skin_profiles import DEFAULT_PROFILE

        with (
            patch("addon_health.current_skin_id", return_value=""),
            patch("addon_health.active_profile", return_value=DEFAULT_PROFILE),
            patch("addon_health.pillow_is_available", return_value=False),
            patch("addon_health._ffmpeg_status", return_value="(not found)"),
        ):
            health = collect_addon_health()
        self.assertEqual(health.snippet_state, "no_target")
        self.assertFalse(health.pillow_ok)


if __name__ == "__main__":
    unittest.main()

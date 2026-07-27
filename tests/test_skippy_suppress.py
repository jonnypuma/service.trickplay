"""Tests for Skippy.Skipping clear on user scrub/OSD."""
from __future__ import annotations

import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _name in ("xbmc", "xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

sys.modules["xbmc"].LOGINFO = 1
sys.modules["xbmc"].LOGWARNING = 2
sys.modules["xbmc"].LOGERROR = 3
sys.modules["xbmc"].getCondVisibility = MagicMock(return_value=False)
sys.modules["xbmc"].getInfoLabel = MagicMock(return_value="")
sys.modules["xbmc"].executeJSONRPC = MagicMock(return_value="{}")
sys.modules["xbmc"].log = MagicMock()
sys.modules["xbmc"].Monitor = type("Monitor", (), {"__init__": lambda self: None})
sys.modules["xbmc"].Player = type("Player", (), {"__init__": lambda self, *a, **k: None})
sys.modules["xbmcvfs"].translatePath = lambda path: path
sys.modules["xbmcaddon"].Addon = MagicMock(
    return_value=MagicMock(
        getAddonInfo=MagicMock(return_value=ROOT),
        getSettingInt=MagicMock(return_value=100),
        getSettingString=MagicMock(return_value=""),
        getSettingBool=MagicMock(return_value=False),
        getLocalizedString=MagicMock(return_value=""),
    )
)
sys.modules["xbmcgui"].Window = MagicMock()
sys.modules["xbmcgui"].Dialog = MagicMock()

import service as trickplay_service  # noqa: E402


def _bind(svc, name: str):
    return getattr(trickplay_service.TrickplayService, name).__get__(
        svc, trickplay_service.TrickplayService
    )


class SkippySkippingClearTests(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = MagicMock()
        self.svc._skippy_skipping_latched = True
        self.svc._skip_landing_second = 26
        self.svc._skip_hiding_since = time.monotonic()
        self.svc._video_osd_visible = MagicMock(return_value=False)
        self.svc._seek_ui_visible = MagicMock(return_value=False)
        self.home = MagicMock()
        self.home.getProperty = MagicMock(return_value="true")
        self.home.clearProperty = MagicMock()
        for name in (
            "_skippy_skipping_set",
            "_clear_skippy_skipping",
            "_note_skip_landing",
            "_user_releases_skippy_hide",
            "_skippy_suppress_active",
        ):
            setattr(self.svc, name, _bind(self.svc, name))

    def _skipping_cond(self, cond: str) -> bool:
        return "Skippy.Skipping" in cond

    def test_poll_playhead_lag_does_not_clear(self) -> None:
        """Poll used to clear immediately when playhead still lagged the landing seek."""
        with patch.object(
            trickplay_service.xbmc,
            "getCondVisibility",
            side_effect=self._skipping_cond,
        ):
            self.assertTrue(
                self.svc._skippy_suppress_active(
                    scrubbing=True,
                    target_second=2,
                    allow_seek_clear=False,
                )
            )
        self.home.clearProperty.assert_not_called()

    def test_seek_clear_blocked_during_grace(self) -> None:
        self.svc._skip_hiding_since = time.monotonic()
        with patch.object(
            trickplay_service.xbmc,
            "getCondVisibility",
            side_effect=self._skipping_cond,
        ):
            self.assertTrue(
                self.svc._skippy_suppress_active(
                    scrubbing=True,
                    target_second=88,
                    allow_seek_clear=True,
                )
            )

    def test_seek_clear_after_grace(self) -> None:
        self.svc._skip_hiding_since = time.monotonic() - 2.0
        with patch.object(
            trickplay_service, "HOME_WINDOW", self.home
        ), patch.object(
            trickplay_service, "clear_trickplay_property", MagicMock()
        ), patch.object(
            trickplay_service.xbmc,
            "getCondVisibility",
            side_effect=self._skipping_cond,
        ):
            self.assertFalse(
                self.svc._skippy_suppress_active(
                    scrubbing=True,
                    target_second=88,
                    allow_seek_clear=True,
                )
            )
        self.home.clearProperty.assert_called_with("Skippy.Skipping")

    def test_video_osd_clears_immediately(self) -> None:
        self.svc._video_osd_visible.return_value = True
        with patch.object(
            trickplay_service, "HOME_WINDOW", self.home
        ), patch.object(
            trickplay_service, "clear_trickplay_property", MagicMock()
        ), patch.object(
            trickplay_service.xbmc,
            "getCondVisibility",
            side_effect=self._skipping_cond,
        ):
            self.assertFalse(
                self.svc._skippy_suppress_active(allow_seek_clear=False)
            )
        self.home.clearProperty.assert_called_with("Skippy.Skipping")


if __name__ == "__main__":
    unittest.main()

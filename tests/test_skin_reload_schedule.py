"""Tests for deferred skin reload after snippet install summary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = MagicMock()
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
sys.modules.setdefault("xbmc", xbmc)
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

from skin_snippet_installer import (  # noqa: E402
    SKIN_RELOAD_ALARM,
    SKIN_RELOAD_DELAY,
    cancel_skin_reload,
    schedule_skin_reload,
)


class SkinReloadScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        xbmc.reset_mock()

    def test_schedule_cancels_then_arms_alarm(self) -> None:
        schedule_skin_reload()
        xbmc.executebuiltin.assert_has_calls(
            [
                call(f"CancelAlarm({SKIN_RELOAD_ALARM},silent)"),
                call(
                    f"AlarmClock({SKIN_RELOAD_ALARM},ReloadSkin(),"
                    f"{SKIN_RELOAD_DELAY},silent)"
                ),
            ]
        )

    def test_cancel_only(self) -> None:
        cancel_skin_reload()
        xbmc.executebuiltin.assert_called_once_with(
            f"CancelAlarm({SKIN_RELOAD_ALARM},silent)"
        )

    def test_delay_is_at_least_three_seconds(self) -> None:
        # HH:MM or SS form — we use MM:SS with 3 second delay.
        self.assertEqual(SKIN_RELOAD_DELAY, "00:03")


if __name__ == "__main__":
    unittest.main()

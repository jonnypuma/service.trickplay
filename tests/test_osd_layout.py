"""Tests for seekbar preview slot placement."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from osd_layout import (
    LAYOUT_SEEKBAR,
    PREVIEW_SLOTS,
    preview_placement,
    preview_slot,
)
from skin_profiles import ESTUARY_MODV2


def _adjustment(scale_percent: int = 100, offset_x: int = 0, offset_y: int = 0):
    adj = MagicMock()
    adj.scale_percent = scale_percent
    adj.offset_x = offset_x
    adj.offset_y = offset_y
    return adj


class PreviewPlacementTests(unittest.TestCase):
    def test_preview_slots_is_101(self) -> None:
        self.assertEqual(PREVIEW_SLOTS, 101)

    def test_slot_advances_across_nearby_seeks(self) -> None:
        duration = 3600
        # With 101 slots, ~36s per slot — 500 vs 560 should differ.
        self.assertNotEqual(preview_slot(500, duration), preview_slot(560, duration))

        with patch("osd_layout.active_profile", return_value=ESTUARY_MODV2):
            with patch("osd_layout.preview_layout_mode", return_value=LAYOUT_SEEKBAR):
                with patch(
                    "preview_settings.read_preview_adjustment_settings",
                    return_value=_adjustment(),
                ):
                    a = preview_placement(500, duration, 16 / 9, show_timestamp=True)
                    b = preview_placement(560, duration, 16 / 9, show_timestamp=True)

        self.assertLess(a.slot, b.slot)
        self.assertLess(a.left, b.left)

    def test_endpoints(self) -> None:
        duration = 3600
        with patch("osd_layout.active_profile", return_value=ESTUARY_MODV2):
            with patch("osd_layout.preview_layout_mode", return_value=LAYOUT_SEEKBAR):
                with patch(
                    "preview_settings.read_preview_adjustment_settings",
                    return_value=_adjustment(),
                ):
                    start = preview_placement(0, duration, 16 / 9, show_timestamp=True)
                    end = preview_placement(
                        duration, duration, 16 / 9, show_timestamp=True
                    )

        self.assertEqual(start.slot, 0)
        self.assertEqual(end.slot, PREVIEW_SLOTS - 1)
        self.assertLess(start.left, end.left)


if __name__ == "__main__":
    unittest.main()

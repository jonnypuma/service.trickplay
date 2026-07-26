"""Tests for continuous seekbar preview placement."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from osd_layout import LAYOUT_SEEKBAR, preview_placement, preview_slot
from skin_profiles import ESTUARY_MODV2


def _adjustment(scale_percent: int = 100, offset_x: int = 0, offset_y: int = 0):
    adj = MagicMock()
    adj.scale_percent = scale_percent
    adj.offset_x = offset_x
    adj.offset_y = offset_y
    return adj


class PreviewPlacementTests(unittest.TestCase):
    def test_left_moves_within_same_slot(self) -> None:
        """Left must track seek second continuously, not only when PreviewSlot changes."""
        duration = 3600
        # Mid-timeline seconds that share a slot (avoid left-edge clamp at bar.left).
        self.assertEqual(preview_slot(500, duration), preview_slot(520, duration))

        with patch("osd_layout.active_profile", return_value=ESTUARY_MODV2):
            with patch("osd_layout.preview_layout_mode", return_value=LAYOUT_SEEKBAR):
                with patch(
                    "preview_settings.read_preview_adjustment_settings",
                    return_value=_adjustment(),
                ):
                    a = preview_placement(500, duration, 16 / 9, show_timestamp=True)
                    b = preview_placement(520, duration, 16 / 9, show_timestamp=True)

        self.assertEqual(a.slot, b.slot)
        self.assertLess(a.left, b.left)
        self.assertLess(a.left_wide, b.left_wide)

    def test_left_matches_slot_endpoints_at_slot_centers(self) -> None:
        duration = 3600
        with patch("osd_layout.active_profile", return_value=ESTUARY_MODV2):
            with patch("osd_layout.preview_layout_mode", return_value=LAYOUT_SEEKBAR):
                with patch(
                    "preview_settings.read_preview_adjustment_settings",
                    return_value=_adjustment(),
                ):
                    start = preview_placement(0, duration, 16 / 9, show_timestamp=True)
                    mid = preview_placement(
                        duration // 2, duration, 16 / 9, show_timestamp=True
                    )
                    end = preview_placement(
                        duration, duration, 16 / 9, show_timestamp=True
                    )

        self.assertEqual(start.slot, 0)
        self.assertEqual(end.slot, 50)
        self.assertLess(start.left, mid.left)
        self.assertLess(mid.left, end.left)


if __name__ == "__main__":
    unittest.main()

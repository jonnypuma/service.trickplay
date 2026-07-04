"""Unit tests for skin profile and snippet registry mapping."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from skin_profiles import (  # noqa: E402
    ARCTIC_FUSE_2,
    ARCTIC_HORIZON_2,
    ARCTIC_HORIZON_2_ARIZEN,
    ARCTIC_ZEPHYR_2_RESURRECTION,
    ARCTIC_ZEPHYR_ROUNDED,
    BELLO,
    BINGIE,
    profile_for_skin_id,
    snippet_spec_for_skin_id,
)


class SkinProfileSnippetTests(unittest.TestCase):
    def test_new_skin_snippet_registry(self) -> None:
        cases = (
            ("skin.arctic.fuse.2", "DialogSeekBar-skin.arctic.fuse.2.xml", "replace"),
            (
                "skin.arctic.horizon.2",
                "DialogSeekBar-skin.arctic.horizon.2.xml",
                "merge",
            ),
            (
                "skin.arctic.horizon.2.1.arizen",
                "DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml",
                "merge",
            ),
            (
                "skin.arctic.zephyr.2.resurrection.mod",
                "DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml",
                "merge",
            ),
            (
                "skin.arctic.zephyr.rounded",
                "DialogSeekBar-skin.arctic.zephyr.rounded.xml",
                "merge",
            ),
            ("skin.bello.10", "VideoFullScreen-skin.bello.xml", "merge", "VideoFullScreen.xml"),
            ("skin.bingie", "DialogSeekBar-skin.bingie.xml", "merge"),
        )
        for skin_id, filename, mode, *rest in cases:
            with self.subTest(skin_id=skin_id):
                spec = snippet_spec_for_skin_id(skin_id)
                self.assertEqual(spec.filename, filename)
                self.assertEqual(spec.mode, mode)
                self.assertTrue(spec.known)
                if rest:
                    self.assertEqual(spec.target_xml, rest[0])
                else:
                    self.assertEqual(spec.target_xml, "DialogSeekBar.xml")

    def test_fuse_3_still_wins_over_fuse_2_marker(self) -> None:
        spec = snippet_spec_for_skin_id("skin.arctic.fuse.3")
        self.assertEqual(spec.filename, "DialogSeekBar-skin.arctic.fuse.3.xml")
        self.assertEqual(spec.mode, "replace")

    def test_arizen_marker_wins_over_horizon_2(self) -> None:
        spec = snippet_spec_for_skin_id("skin.arctic.horizon.2.1.arizen")
        self.assertEqual(
            spec.filename,
            "DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml",
        )

    def test_zephyr_rounded_wins_over_zephyr_profile(self) -> None:
        from skin_profiles import ARCTIC_ZEPHYR, ARCTIC_ZEPHYR_ROUNDED

        self.assertIs(
            profile_for_skin_id("skin.arctic.zephyr.rounded"),
            ARCTIC_ZEPHYR_ROUNDED,
        )
        self.assertIsNot(
            profile_for_skin_id("skin.arctic.zephyr.rounded"),
            ARCTIC_ZEPHYR,
        )

    def test_profile_for_new_skins(self) -> None:
        self.assertIs(
            profile_for_skin_id("skin.arctic.fuse.2"),
            ARCTIC_FUSE_2,
        )
        self.assertIs(
            profile_for_skin_id("skin.arctic.horizon.2"),
            ARCTIC_HORIZON_2,
        )
        self.assertIs(
            profile_for_skin_id("skin.arctic.horizon.2.1.arizen"),
            ARCTIC_HORIZON_2_ARIZEN,
        )
        self.assertIs(
            profile_for_skin_id("skin.arctic.zephyr.2.resurrection.mod"),
            ARCTIC_ZEPHYR_2_RESURRECTION,
        )
        self.assertIs(
            profile_for_skin_id("skin.arctic.zephyr.rounded"),
            ARCTIC_ZEPHYR_ROUNDED,
        )
        self.assertIs(profile_for_skin_id("skin.bello.9"), BELLO)
        self.assertEqual(BELLO.seekbar, (478, 560, 320))
        self.assertTrue(BELLO.fullscreen_seek_visibility)
        self.assertIs(profile_for_skin_id("skin.bingie"), BINGIE)


if __name__ == "__main__":
    unittest.main()

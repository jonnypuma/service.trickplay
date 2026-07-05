"""Unit tests for text-based DialogSeekBar merge helpers (no Kodi runtime)."""

from __future__ import annotations

import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _name in ("xbmc", "xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

sys.modules["xbmc"].LOGINFO = 1
sys.modules["xbmc"].LOGWARNING = 2

from skin_snippet_installer import (  # noqa: E402
    AH2_VIDEO_OSD_SLIDE_MARKER,
    NOX_OSD_SLIDE_MARKER,
    OVERLAY_CONTROL_ID,
    extract_overlay_xml_text,
    find_control_block_span,
    insert_overlay_before_controls_close,
    overlay_already_installed,
    overlay_needs_refresh,
    remove_control_block,
    seekbar_has_host_controls,
)


SAMPLE_SEEKBAR = """<?xml version="1.0" encoding="UTF-8"?>
<window>
\t<controls>
\t\t<control type="group" id="100">
\t\t\t<visible>true</visible>
\t\t</control>
\t</controls>
</window>
"""

SAMPLE_SNIPPET = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Trickplay.Preview -->
<window>
\t<controls>
\t\t<control type="group" id="94090">
\t\t\t<visible>true</visible>
\t\t\t<control type="image" id="94091">
\t\t\t\t<texture>foo.png</texture>
\t\t\t</control>
\t\t</control>
\t</controls>
</window>
"""


class SkinSnippetMergeTests(unittest.TestCase):
    def test_find_control_block_span_nested(self) -> None:
        span = find_control_block_span(SAMPLE_SNIPPET, OVERLAY_CONTROL_ID)
        self.assertIsNotNone(span)
        start, end = span
        block = SAMPLE_SNIPPET[start:end]
        self.assertIn('id="94090"', block)
        self.assertIn("<control type=\"image\" id=\"94091\">", block)
        self.assertTrue(block.strip().endswith("</control>"))

    def test_extract_overlay_xml_text(self) -> None:
        snippet_path = os.path.join(
            ROOT, "resources", "skin-snippet", "DialogSeekBar-universal-dynamic.xml"
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn('id="94090"', overlay)
        self.assertIn("Trickplay.Preview", overlay)

    def test_insert_overlay_preserves_indentation(self) -> None:
        overlay = extract_overlay_xml_text(
            os.path.join(
                ROOT, "resources", "skin-snippet", "DialogSeekBar-universal-dynamic.xml"
            )
        )
        merged = insert_overlay_before_controls_close(SAMPLE_SEEKBAR, overlay)
        self.assertIn('\t\t<control type="group" id="94090">', merged)
        self.assertIn('\t\t<control type="group" id="100">', merged)
        self.assertLess(merged.index("94090"), merged.index("</controls>"))

    def test_remove_control_block(self) -> None:
        span = find_control_block_span(SAMPLE_SNIPPET, OVERLAY_CONTROL_ID)
        assert span is not None
        overlay = SAMPLE_SNIPPET[span[0] : span[1]]
        with_overlay = insert_overlay_before_controls_close(SAMPLE_SEEKBAR, overlay)
        self.assertIn('id="94090"', with_overlay)
        restored = remove_control_block(with_overlay, OVERLAY_CONTROL_ID)
        self.assertNotIn('id="94090"', restored)
        self.assertIn('id="100"', restored)

    def test_remove_missing_control_is_noop(self) -> None:
        self.assertEqual(
            remove_control_block(SAMPLE_SEEKBAR, OVERLAY_CONTROL_ID),
            SAMPLE_SEEKBAR,
        )

    def test_zephyr_rounded_snippet_uses_home_properties(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.zephyr.rounded.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("Window.IsVisible(videoosd)", overlay)
        self.assertNotIn("Window.Property(Trickplay.PreviewVisible)", overlay)

    def test_bello_snippet_uses_home_properties_and_fixed_position(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "VideoFullScreen-skin.bello.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn("<top>560</top>", overlay)
        self.assertIn("<left>478</left>", overlay)

    def test_overlay_needs_refresh_detects_stale_bello(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>Window.Property(Trickplay.PreviewVisible)</visible>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "VideoFullScreen.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(overlay_already_installed(path))
        self.assertTrue(
            overlay_needs_refresh(path, "VideoFullScreen-skin.bello.xml")
        )

    def test_overlay_needs_refresh_false_when_bello_snippet_present(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "VideoFullScreen-skin.bello.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        merged = insert_overlay_before_controls_close(SAMPLE_SEEKBAR, overlay)
        path = os.path.join(self._temp_dir(), "VideoFullScreen.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertFalse(
            overlay_needs_refresh(path, "VideoFullScreen-skin.bello.xml")
        )

    def test_bingie_snippet_uses_home_properties_and_slot_slides(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.bingie.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("<left>384</left>", overlay)
        self.assertIn("<top>717</top>", overlay)
        self.assertNotIn("Window.Property(Trickplay.PreviewVisible)", overlay)

    def test_overlay_needs_refresh_detects_legacy_window_property_overlay(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>Window.Property(Trickplay.PreviewVisible)</visible>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(overlay_already_installed(path))
        self.assertTrue(
            overlay_needs_refresh(path, "DialogSeekBar-skin.bingie.xml")
        )

    def test_overlay_needs_refresh_detects_legacy_dynamic_bingie_overlay(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>String.IsEqual(Window.Property(Trickplay.PreviewVisible),true)</visible>\n'
            '\t\t\t<left>$INFO[Window.Property(Trickplay.PreviewLeft)]</left>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(
            overlay_needs_refresh(path, "DialogSeekBar-skin.bingie.xml")
        )

    def test_overlay_needs_refresh_detects_missing_revision_marker(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>Window(Home).Property(Trickplay.PreviewVisible)</visible>\n'
            '\t\t\t<control type="group" id="94100"></control>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(
            overlay_needs_refresh(path, "DialogSeekBar-skin.bingie.xml")
        )

    def test_zephyr_2_resurrection_snippet_raised_above_seekbar(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("<top>740</top>", overlay)
        self.assertNotIn("<top>820</top>", overlay)

    def test_aeon_nox_silvo_snippet_uses_home_properties_and_slot_slides(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.aeon.nox.silvo.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("<top>799</top>", overlay)
        self.assertIn(NOX_OSD_SLIDE_MARKER, overlay)
        self.assertNotIn("Window.Property(Trickplay.PreviewVisible)", overlay)

    def test_arctic_zephyr_snippet_uses_home_properties_and_slot_slides(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.zephyr.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("<top>820</top>", overlay)
        self.assertNotIn("Window.Property(Trickplay.PreviewVisible)", overlay)

    def test_arctic_horizon_snippet_uses_home_properties_and_slot_slides(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.horizon.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("<top>680</top>", overlay)
        self.assertIn(AH2_VIDEO_OSD_SLIDE_MARKER, overlay)

    def test_horizon_2_snippet_uses_home_properties_and_slot_slides(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.horizon.2.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn("Window(Home).Property(Trickplay.PreviewVisible)", overlay)
        self.assertIn('id="94100"', overlay)
        self.assertIn("<top>480</top>", overlay)
        self.assertIn(AH2_VIDEO_OSD_SLIDE_MARKER, overlay)
        self.assertNotIn("Window.Property(Trickplay.PreviewVisible)", overlay)

    def test_overlay_needs_refresh_detects_stale_horizon_2(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>Window.Property(Trickplay.PreviewVisible)</visible>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(overlay_already_installed(path))
        self.assertTrue(
            overlay_needs_refresh(
                path, "DialogSeekBar-skin.arctic.horizon.2.xml"
            )
        )

    def test_overlay_needs_refresh_detects_stale_zephyr_rounded(self) -> None:
        stale = SAMPLE_SEEKBAR.replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<visible>Window.Property(Trickplay.PreviewVisible)</visible>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(stale)
        self.assertTrue(overlay_already_installed(path))
        self.assertTrue(
            overlay_needs_refresh(
                path, "DialogSeekBar-skin.arctic.zephyr.rounded.xml"
            )
        )

    def test_overlay_needs_refresh_false_when_home_properties_present(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.zephyr.rounded.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        merged = insert_overlay_before_controls_close(SAMPLE_SEEKBAR, overlay)
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertFalse(
            overlay_needs_refresh(
                path, "DialogSeekBar-skin.arctic.zephyr.rounded.xml"
            )
        )

    def test_seekbar_has_host_controls(self) -> None:
        self.assertTrue(seekbar_has_host_controls(SAMPLE_SEEKBAR))
        self.assertFalse(
            seekbar_has_host_controls(
                """<?xml version="1.0" encoding="UTF-8"?>
<window><controls></controls></window>"""
            )
        )
        with_overlay = insert_overlay_before_controls_close(
            """<?xml version="1.0" encoding="UTF-8"?>
<window><controls></controls></window>""",
            extract_overlay_xml_text(
                os.path.join(
                    ROOT,
                    "resources",
                    "skin-snippet",
                    "DialogSeekBar-universal-dynamic.xml",
                )
            ),
        )
        self.assertFalse(seekbar_has_host_controls(with_overlay))

    def _temp_dir(self) -> str:
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()

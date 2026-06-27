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
    OVERLAY_CONTROL_ID,
    extract_overlay_xml_text,
    find_control_block_span,
    insert_overlay_before_controls_close,
    remove_control_block,
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


if __name__ == "__main__":
    unittest.main()

"""Unit tests for text-based DialogSeekBar merge helpers (no Kodi runtime)."""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _name in ("xbmc", "xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

sys.modules["xbmc"].LOGINFO = 1
sys.modules["xbmc"].LOGWARNING = 2
sys.modules["xbmcvfs"].translatePath = lambda path: path

from skin_snippet_installer import (  # noqa: E402
    AH2_VIDEO_OSD_SLIDE_MARKER,
    BELLO_CENTER_SEEK_MARKER,
    BELLO_SIMPLE_SEEK_MARKER,
    NOX_OSD_SLIDE_MARKER,
    OVERLAY_CONTROL_ID,
    SKIPPY_SEEKBAR_VISIBLE_MARKER,
    _bello_seek_osd_groups_have_skippy,
    ensure_bello_skippy_seek_visible,
    ensure_skippy_seekbar_visible,
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

SAMPLE_BELLO_VIDEO_FULLSCREEN = """<?xml version="1.0" encoding="UTF-8"?>
<window>
\t<controls>
\t\t<control type="group" id="1">
\t\t\t<visible>!String.IsEqual(Skin.String(FullScreenVideoStyle),2)</visible>
\t\t\t<visible>Window.IsActive(FullScreenVideo) + Player.Seeking</visible>
\t\t\t<control type="image" id="1">
\t\t\t\t<left>449</left>
\t\t\t\t<top>177</top>
\t\t\t\t<texture background="true">osd/osd_controls_bg.png</texture>
\t\t\t</control>
\t\t</control>
\t\t<control type="group" id="1">
\t\t\t<left>45</left>
\t\t\t<top>615</top>
\t\t\t<visible>Window.IsActive(FullScreenVideo) + Player.Seeking</visible>
\t\t\t<include content="SeekBarSimple">
\t\t\t\t<param name="progressbar_id" value="3"/>
\t\t\t</include>
\t\t</control>
\t\t<control type="group" id="1">
\t\t\t<left>45</left>
\t\t\t<top>615</top>
\t\t\t<visible>Window.IsActive(FullScreenVideo) + Player.Seeking</visible>
\t\t\t<include content="SeekBarSimple">
\t\t\t\t<param name="progressbar_id" value="4"/>
\t\t\t</include>
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
        host = ensure_bello_skippy_seek_visible(SAMPLE_BELLO_VIDEO_FULLSCREEN)
        merged = insert_overlay_before_controls_close(host, overlay)
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
        host = ensure_skippy_seekbar_visible(SAMPLE_SEEKBAR)
        merged = insert_overlay_before_controls_close(host, overlay)
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertFalse(
            overlay_needs_refresh(
                path, "DialogSeekBar-skin.arctic.zephyr.rounded.xml"
            )
        )

    def test_overlay_needs_refresh_false_for_current_arctic_fuse_3(self) -> None:
        """AF3/Estuary Mod use Window.Property on DialogSeekBar — not Home."""
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.arctic.fuse.3.xml",
        )
        with open(snippet_path, encoding="utf-8") as handle:
            text = handle.read()
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.assertTrue(overlay_already_installed(path))
        self.assertFalse(
            overlay_needs_refresh(path, "DialogSeekBar-skin.arctic.fuse.3.xml")
        )
        self.assertIn("Window.Property(Trickplay.PreviewVisible)", text)
        self.assertNotIn("Window(Home).Property(Trickplay.PreviewVisible)", text)

    def test_skin_ids_from_addons_folders_finds_gui_skins(self) -> None:
        from skin_snippet_installer import _skin_ids_from_addons_folders

        root = self._temp_dir()
        skin_dir = os.path.join(root, "skin.example.test")
        os.makedirs(skin_dir)
        with open(os.path.join(skin_dir, "addon.xml"), "w", encoding="utf-8") as handle:
            handle.write(
                '<?xml version="1.0"?>\n'
                '<addon id="skin.example.test">\n'
                '  <extension point="xbmc.gui.skin"/>\n'
                "</addon>\n"
            )
        other = os.path.join(root, "plugin.video.foo")
        os.makedirs(other)
        with open(os.path.join(other, "addon.xml"), "w", encoding="utf-8") as handle:
            handle.write(
                '<?xml version="1.0"?>\n'
                '<addon id="plugin.video.foo">\n'
                '  <extension point="xbmc.python.pluginsource"/>\n'
                "</addon>\n"
            )
        with (
            mock.patch(
                "skin_snippet_installer.xbmcvfs.translatePath",
                return_value=root,
            ),
        ):
            ids = _skin_ids_from_addons_folders()
        self.assertIn("skin.example.test", ids)
        self.assertNotIn("plugin.video.foo", ids)

    def test_overlay_needs_refresh_detects_stale_replace_snippet(self) -> None:
        # Old Estuary Mod v2 install without revision marker.
        text = ensure_skippy_seekbar_visible(SAMPLE_SEEKBAR).replace(
            "</controls>",
            '\t\t<control type="group" id="94090">\n'
            '\t\t\t<control type="group" id="94100"></control>\n'
            '\t\t\t<visible>Trickplay.Preview</visible>\n'
            "\t\t</control>\n\t</controls>",
        )
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.assertTrue(overlay_already_installed(path))
        self.assertTrue(
            overlay_needs_refresh(path, "DialogSeekBar-skin.estuary.modv2.xml")
        )

    def test_replace_snippet_has_revision_marker(self) -> None:
        for name in (
            "DialogSeekBar-skin.estuary.modv2.xml",
            "DialogSeekBar-skin.arctic.fuse.2.xml",
            "DialogSeekBar-skin.arctic.fuse.3.xml",
        ):
            path = os.path.join(ROOT, "resources", "skin-snippet", name)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("trickplay-overlay-rev:4", text, msg=name)
            self.assertIn(SKIPPY_SEEKBAR_VISIBLE_MARKER, text, msg=name)

    def test_seekbar_has_host_controls(self) -> None:
        self.assertTrue(seekbar_has_host_controls(SAMPLE_SEEKBAR))
        self.assertFalse(
            seekbar_has_host_controls(
                """<?xml version="1.0" encoding="UTF-8"?>
<window><controls></controls></window>"""
            )
        )
        # Arctic Zephyr Rounded style: seek bar lives in an include, overlay is the
        # only top-level control — still a real host DialogSeekBar.
        include_host = """<?xml version="1.0" encoding="UTF-8"?>
<window>
\t<controls>
\t\t<include condition="VideoPlayer.IsFullscreen">OSD_Video_SeekBar</include>
\t</controls>
</window>
"""
        self.assertTrue(seekbar_has_host_controls(include_host))
        with_overlay = insert_overlay_before_controls_close(
            include_host,
            extract_overlay_xml_text(
                os.path.join(
                    ROOT,
                    "resources",
                    "skin-snippet",
                    "DialogSeekBar-skin.arctic.zephyr.rounded.xml",
                )
            ),
        )
        self.assertTrue(seekbar_has_host_controls(with_overlay))
        overlay_only = insert_overlay_before_controls_close(
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
        self.assertFalse(seekbar_has_host_controls(overlay_only))

    def test_skin_addon_path_falls_back_to_filesystem(self) -> None:
        from skin_snippet_installer import _skin_addon_path

        root = self._temp_dir()
        skin_id = "skin.plextuary"
        skin_dir = os.path.join(root, skin_id)
        os.makedirs(skin_dir)
        with open(os.path.join(skin_dir, "addon.xml"), "w", encoding="utf-8") as handle:
            handle.write(
                '<?xml version="1.0"?>\n'
                f'<addon id="{skin_id}" name="Plextuary">\n'
                '  <extension point="xbmc.gui.skin"/>\n'
                "</addon>\n"
            )

        def _addon_boom(_sid: str):
            raise RuntimeError("Addon not found")

        sys.modules["xbmcaddon"].Addon = _addon_boom
        try:
            with mock.patch(
                "skin_snippet_installer._addon_dir_roots",
                return_value=[root],
            ):
                resolved = _skin_addon_path(skin_id, quiet=True)
        finally:
            if hasattr(sys.modules["xbmcaddon"], "Addon"):
                delattr(sys.modules["xbmcaddon"], "Addon")
        self.assertEqual(resolved, skin_dir)
    def test_ensure_skippy_seekbar_visible_injects_before_controls(self) -> None:
        merged = ensure_skippy_seekbar_visible(SAMPLE_SEEKBAR)
        self.assertIn(SKIPPY_SEEKBAR_VISIBLE_MARKER, merged)
        self.assertLess(merged.index(SKIPPY_SEEKBAR_VISIBLE_MARKER), merged.index("<controls"))

    def test_ensure_skippy_seekbar_visible_is_idempotent(self) -> None:
        once = ensure_skippy_seekbar_visible(SAMPLE_SEEKBAR)
        twice = ensure_skippy_seekbar_visible(once)
        self.assertEqual(once, twice)

    def test_overlay_needs_refresh_when_skippy_visible_missing(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-skin.bingie.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        stale_overlay = overlay.replace(SKIPPY_SEEKBAR_VISIBLE_MARKER, "Skippy.Removed")
        merged = insert_overlay_before_controls_close(SAMPLE_SEEKBAR, stale_overlay)
        path = os.path.join(self._temp_dir(), "DialogSeekBar.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertTrue(overlay_needs_refresh(path, "DialogSeekBar-skin.bingie.xml"))

    def test_universal_snippet_includes_skippy_visible(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "DialogSeekBar-universal-dynamic.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        self.assertIn(SKIPPY_SEEKBAR_VISIBLE_MARKER, overlay)

    def test_ensure_bello_skippy_seek_visible_patches_seek_groups(self) -> None:
        patched = ensure_bello_skippy_seek_visible(SAMPLE_BELLO_VIDEO_FULLSCREEN)
        self.assertIn(BELLO_CENTER_SEEK_MARKER, patched)
        self.assertIn(BELLO_SIMPLE_SEEK_MARKER, patched)
        self.assertTrue(_bello_seek_osd_groups_have_skippy(patched))
        self.assertEqual(
            patched.count(SKIPPY_SEEKBAR_VISIBLE_MARKER),
            3,
        )

    def test_overlay_needs_refresh_when_bello_seek_groups_missing_skippy(
        self,
    ) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "VideoFullScreen-skin.bello.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        merged = insert_overlay_before_controls_close(
            SAMPLE_BELLO_VIDEO_FULLSCREEN, overlay
        )
        path = os.path.join(self._temp_dir(), "VideoFullScreen.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertTrue(overlay_needs_refresh(path, "VideoFullScreen-skin.bello.xml"))

    def test_overlay_needs_refresh_false_when_bello_seek_groups_patched(self) -> None:
        snippet_path = os.path.join(
            ROOT,
            "resources",
            "skin-snippet",
            "VideoFullScreen-skin.bello.xml",
        )
        overlay = extract_overlay_xml_text(snippet_path)
        host = ensure_bello_skippy_seek_visible(SAMPLE_BELLO_VIDEO_FULLSCREEN)
        merged = insert_overlay_before_controls_close(host, overlay)
        path = os.path.join(self._temp_dir(), "VideoFullScreen.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(merged)
        self.assertFalse(
            overlay_needs_refresh(path, "VideoFullScreen-skin.bello.xml")
        )

    def _temp_dir(self) -> str:
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()

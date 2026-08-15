"""Tests for 8.0.0 idle resume, network atomic promote, snippet prompts, and settings."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from kodi_test_stubs import install_kodi_stubs  # noqa: E402

install_kodi_stubs()

from addon_health import AddonHealth  # noqa: E402
from generation_state import begin_or_update, load_completed, mark_completed  # noqa: E402
from generator_worker import GeneratorWorker  # noqa: E402
from overlay_revision import OVERLAY_REVISION, OVERLAY_REVISION_MARKER  # noqa: E402
from trickplay_generator import _atomic_promote_sidecar  # noqa: E402
from vfs_paths import writable_os_path  # noqa: E402


def _settings(**kwargs):
    values = {
        "tile_width": 320,
        "grid": "10x10",
        "interval_ms": 10000,
        "extract_mode": "fast",
        "overwrite_existing": False,
        "library_path": "/media",
        "debug": False,
    }
    values.update(kwargs)
    return types.SimpleNamespace(**values)


def _health(state: str) -> AddonHealth:
    return AddonHealth(
        skin_id="skin.arctic.zephyr.rounded",
        skin_name="Arctic Zephyr Rounded",
        profile_label="Arctic Zephyr Rounded",
        snippet_file="DialogSeekBar-skin.arctic.zephyr.rounded.xml",
        target_xml="DialogSeekBar.xml",
        snippet_state=state,
        pillow_ok=True,
        ffmpeg="ffmpeg",
        overlay_revision=OVERLAY_REVISION,
    )


class _StubAddonMixin(unittest.TestCase):
    def setUp(self) -> None:
        install_kodi_stubs()


class WritableOsPathTests(unittest.TestCase):
    def test_local_path_is_returned_as_is(self) -> None:
        self.assertEqual(writable_os_path(r"C:\Media\show.mkv"), r"C:\Media\show.mkv")

    def test_nfs_url_uses_mount_map(self) -> None:
        mapped = "/storage/remote-shares/Media/show.mkv"
        with patch("vfs_paths.network_url_to_local", return_value=mapped):
            self.assertEqual(
                writable_os_path("nfs://192.168.0.5/Media/show.mkv"),
                mapped,
            )

    def test_unmapped_remote_url_is_empty(self) -> None:
        with patch("vfs_paths.network_url_to_local", return_value=None):
            self.assertEqual(writable_os_path("nfs://192.168.0.5/Media/show.mkv"), "")


class NetworkAtomicPromoteTests(unittest.TestCase):
    def test_atomic_promotion_uses_mapped_nfs_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "tiles"
            staging = Path(directory) / "tiles.tmp"
            final.mkdir()
            (final / "0.jpg").write_bytes(b"old")
            staging.mkdir()
            (staging / "0.jpg").write_bytes(b"new")
            nfs_final = "nfs://server/share/movie.trickplay/320"
            nfs_staging = nfs_final + ".tmp"
            mapping = {nfs_staging: str(staging), nfs_final: str(final)}
            with patch(
                "trickplay_generator.writable_os_path",
                side_effect=lambda path: mapping.get(path, ""),
            ):
                self.assertTrue(_atomic_promote_sidecar(nfs_staging, nfs_final))
            self.assertEqual((final / "0.jpg").read_bytes(), b"new")
            self.assertFalse(staging.exists())


class IdleResumeTests(unittest.TestCase):
    def test_idle_scan_skips_completed_paths(self) -> None:
        worker = GeneratorWorker()
        settings = _settings()
        plan = types.SimpleNamespace(
            candidates=["/media/a.mkv", "/media/b.mkv", "/media/c.mkv"]
        )
        with (
            patch(
                "generator_worker.collect_generation_candidates",
                return_value=plan,
            ),
            patch(
                "generator_worker.load_completed",
                return_value={"/media/a.mkv", "/media/c.mkv"},
            ),
        ):
            worker._refresh_idle_candidates(settings)
        self.assertEqual(worker._idle_candidates, ["/media/b.mkv"])

    def test_successful_idle_job_marks_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            settings = _settings()
            with patch("generation_state._local_state_path", return_value=state_path):
                mark_completed("/media", settings, "/media/a.mkv")
                self.assertEqual(
                    load_completed("/media", settings),
                    {"/media/a.mkv"},
                )

    def test_overwrite_toggle_does_not_reuse_completed_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "state.json")
            with patch("generation_state._local_state_path", return_value=state_path):
                begin_or_update(
                    "/media",
                    _settings(overwrite_existing=False),
                    {"/media/a.mkv"},
                )
                self.assertEqual(
                    load_completed("/media", _settings(overwrite_existing=True)),
                    set(),
                )


class OverlayRevisionTests(unittest.TestCase):
    def test_installer_and_generator_share_revision(self) -> None:
        import skin_snippet_installer
        import tests.gen_arctic_slot_snippets as gen_arctic

        self.assertEqual(skin_snippet_installer.OVERLAY_REVISION, OVERLAY_REVISION)
        self.assertEqual(gen_arctic.OVERLAY_REVISION, OVERLAY_REVISION)
        self.assertIn(str(OVERLAY_REVISION), OVERLAY_REVISION_MARKER)


class SnippetNudgeTests(_StubAddonMixin):
    def test_needs_attention_for_missing_and_stale(self) -> None:
        from snippet_nudge import snippet_needs_attention

        self.assertTrue(snippet_needs_attention(_health("missing")))
        self.assertTrue(snippet_needs_attention(_health("stale")))
        self.assertFalse(snippet_needs_attention(_health("installed")))
        self.assertFalse(snippet_needs_attention(_health("no_target")))

    def test_startup_toast_for_stale_overlay(self) -> None:
        from snippet_nudge import notify_stale_or_missing_snippet

        dialog = MagicMock()
        with (
            patch("snippet_nudge.collect_addon_health", return_value=_health("stale")),
            patch("snippet_nudge.xbmcgui.Dialog", return_value=dialog),
        ):
            self.assertTrue(notify_stale_or_missing_snippet())
        dialog.notification.assert_called()

    def test_status_dialog_offers_install_when_stale(self) -> None:
        from script_status import run_addon_status_dialog

        dialog = MagicMock()
        dialog.yesno.return_value = True
        with (
            patch("addon_health.collect_addon_health", return_value=_health("stale")),
            patch("script_status.xbmcgui.Dialog", return_value=dialog),
            patch("script_skin.run_install_skin_dialog") as install,
        ):
            run_addon_status_dialog()
        dialog.yesno.assert_called()
        install.assert_called_once()


class SettingsLevelTests(unittest.TestCase):
    def test_basic_settings_stay_visible(self) -> None:
        tree = ET.parse(ROOT / "resources" / "settings.xml")
        levels = {
            node.get("id"): int(node.findtext("level") or "-1")
            for node in tree.findall(".//setting")
        }
        self.assertEqual(levels["install_skin_snippet_current"], 0)
        self.assertEqual(levels["generator_library_path"], 0)
        self.assertEqual(levels["generator_extract_mode"], 0)
        self.assertEqual(levels["addon_status"], 0)
        self.assertEqual(levels["generator_fps_batch_timeout_cap"], 3)
        self.assertEqual(levels["generator_hw_decode_cuda"], 3)
        self.assertEqual(levels["cache_jpeg_quality"], 3)
        self.assertEqual(levels["prefetch_radius"], 2)
        self.assertGreater(
            levels["install_skin_snippet_force"],
            levels["install_skin_snippet_current"],
        )


class ScriptDispatchTests(_StubAddonMixin):
    def test_dispatcher_resolves_known_modes(self) -> None:
        import script_generator

        self.assertEqual(
            script_generator._resolve_mode(["service.trickplay", "batch"]),
            "batch",
        )
        self.assertEqual(
            script_generator._resolve_mode(
                ["service.trickplay", "install_skin", "current"]
            ),
            "install_skin",
        )
        self.assertEqual(
            script_generator._resolve_mode(["service.trickplay", "addon_status"]),
            "addon_status",
        )
        self.assertTrue(
            script_generator._from_playback_prompt(
                ["service.trickplay", "install_tools", "playback"]
            )
        )


if __name__ == "__main__":
    unittest.main()

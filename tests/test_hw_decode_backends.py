"""Tests for hardware decode backend selection and argv/filter construction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = MagicMock()
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
sys.modules.setdefault("xbmc", xbmc)
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

from hdr_tone_map import (
    HW_DECODE_CUDA,
    HW_DECODE_D3D11VA,
    HW_DECODE_NONE,
    HW_DECODE_VAAPI_DOWNLOAD,
    HW_DECODE_VAAPI_VULKAN,
    _strip_libplacebo_vulkan_input_args,
    augment_thumb_extract_for_hw_decode,
    ffmpeg_cuda_hwaccel_input_args,
    ffmpeg_libplacebo_input_args,
    ffmpeg_vaapi_vulkan_input_args,
    hw_decode_backend_label,
    select_hw_decode_backend,
)


class StripVulkanArgsTests(unittest.TestCase):
    def test_strips_bare_vulkan_vk_pair(self) -> None:
        args = ("-f", "hevc", *ffmpeg_libplacebo_input_args(), "-something")
        stripped = _strip_libplacebo_vulkan_input_args(args)
        self.assertEqual(stripped, ("-f", "hevc", "-something"))
        self.assertNotIn("vulkan=vk", stripped)
        self.assertNotIn("-filter_hw_device", stripped)


class BackendSelectionTests(unittest.TestCase):
    def test_disabled_returns_none(self) -> None:
        self.assertEqual(
            select_hw_decode_backend(enabled=False, apply_tonemap=True),
            HW_DECODE_NONE,
        )

    @patch("hdr_tone_map.probe_ffmpeg_has_cuda", return_value=True)
    @patch("hdr_tone_map.sys.platform", "win32")
    def test_windows_cuda_preferred_when_enabled(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="C:\\ffmpeg.exe",
                env={},
                apply_tonemap=True,
                cuda_enabled=True,
            ),
            HW_DECODE_CUDA,
        )

    @patch("hdr_tone_map.probe_ffmpeg_has_cuda", return_value=False)
    @patch("hdr_tone_map.sys.platform", "win32")
    def test_windows_cuda_falls_back_to_d3d11va(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="C:\\ffmpeg.exe",
                env={},
                apply_tonemap=True,
                cuda_enabled=True,
            ),
            HW_DECODE_D3D11VA,
        )

    @patch("hdr_tone_map.sys.platform", "win32")
    def test_windows_default_is_d3d11va_hwdownload(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="C:\\ffmpeg.exe",
                apply_tonemap=True,
                cuda_enabled=False,
            ),
            HW_DECODE_D3D11VA,
        )

    @patch("hdr_tone_map.probe_ffmpeg_has_cuda", return_value=True)
    @patch("hdr_tone_map.ffmpeg_has_libplacebo", return_value=True)
    @patch("hdr_tone_map.probe_vaapi_vulkan_interop", return_value=True)
    @patch("hdr_tone_map.probe_ffmpeg_has_vaapi", return_value=True)
    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch("hdr_tone_map.sys.platform", "linux")
    def test_linux_cuda_overrides_vaapi_when_enabled(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="/usr/bin/ffmpeg",
                env={},
                apply_tonemap=True,
                cuda_enabled=True,
            ),
            HW_DECODE_CUDA,
        )

    @patch("hdr_tone_map.ffmpeg_has_libplacebo", return_value=True)
    @patch("hdr_tone_map.probe_vaapi_vulkan_interop", return_value=True)
    @patch("hdr_tone_map.probe_ffmpeg_has_vaapi", return_value=True)
    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch("hdr_tone_map.sys.platform", "linux")
    def test_linux_tonemap_prefers_vaapi_vulkan(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="/usr/bin/ffmpeg",
                env={},
                apply_tonemap=True,
            ),
            HW_DECODE_VAAPI_VULKAN,
        )

    @patch("hdr_tone_map.ffmpeg_has_libplacebo", return_value=False)
    @patch("hdr_tone_map.probe_vaapi_vulkan_interop", return_value=False)
    @patch("hdr_tone_map.probe_ffmpeg_has_vaapi", return_value=True)
    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch("hdr_tone_map.sys.platform", "linux")
    def test_linux_tonemap_falls_back_to_vaapi_download(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="/usr/bin/ffmpeg",
                env={},
                apply_tonemap=True,
            ),
            HW_DECODE_VAAPI_DOWNLOAD,
        )

    @patch("hdr_tone_map.probe_ffmpeg_has_vaapi", return_value=True)
    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch("hdr_tone_map.sys.platform", "linux")
    def test_linux_no_tonemap_uses_vaapi_download(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="/usr/bin/ffmpeg",
                env={},
                apply_tonemap=False,
            ),
            HW_DECODE_VAAPI_DOWNLOAD,
        )

    @patch("hdr_tone_map.discover_vaapi_device", return_value=None)
    @patch("hdr_tone_map.sys.platform", "linux")
    def test_linux_no_device_returns_none(self, *_mocks) -> None:
        self.assertEqual(
            select_hw_decode_backend(
                enabled=True,
                ffmpeg="/usr/bin/ffmpeg",
                apply_tonemap=True,
            ),
            HW_DECODE_NONE,
        )


class AugmentFilterArgsTests(unittest.TestCase):
    @patch("hdr_tone_map.select_hw_decode_backend", return_value=HW_DECODE_D3D11VA)
    def test_d3d11va_prefixes_hwdownload(self, _sel) -> None:
        thumb = "scale=320:180"
        vf, args, active, backend = augment_thumb_extract_for_hw_decode(
            thumb,
            (),
            enabled=True,
        )
        self.assertTrue(active)
        self.assertEqual(backend, HW_DECODE_D3D11VA)
        self.assertTrue(vf.startswith("hwdownload,format=p010le,"))
        self.assertIn("d3d11va", args)

    @patch("hdr_tone_map.select_hw_decode_backend", return_value=HW_DECODE_CUDA)
    def test_cuda_prefixes_hwdownload(self, _sel) -> None:
        thumb = "scale=320:180"
        vf, args, active, backend = augment_thumb_extract_for_hw_decode(
            thumb,
            ffmpeg_libplacebo_input_args(),
            enabled=True,
            cuda_enabled=True,
        )
        self.assertTrue(active)
        self.assertEqual(backend, HW_DECODE_CUDA)
        self.assertTrue(vf.startswith("hwdownload,format=p010le,"))
        self.assertIn("cuda", args)
        expected_prefix = ffmpeg_cuda_hwaccel_input_args()
        self.assertEqual(args[: len(expected_prefix)], expected_prefix)

    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch(
        "hdr_tone_map.select_hw_decode_backend",
        return_value=HW_DECODE_VAAPI_DOWNLOAD,
    )
    def test_vaapi_download_prefixes_hwdownload(self, _sel, _dev) -> None:
        thumb = "scale=320:180"
        vf, args, active, backend = augment_thumb_extract_for_hw_decode(
            thumb,
            ffmpeg_libplacebo_input_args(),
            enabled=True,
            apply_tonemap=True,
        )
        self.assertTrue(active)
        self.assertEqual(backend, HW_DECODE_VAAPI_DOWNLOAD)
        self.assertTrue(vf.startswith("hwdownload,format=p010le,"))
        self.assertIn("vaapi", args)
        self.assertIn("/dev/dri/renderD128", args)

    @patch("hdr_tone_map.discover_vaapi_device", return_value="/dev/dri/renderD128")
    @patch(
        "hdr_tone_map.select_hw_decode_backend",
        return_value=HW_DECODE_VAAPI_VULKAN,
    )
    def test_vaapi_vulkan_uses_derived_vulkan_not_bare_vk(self, _sel, _dev) -> None:
        thumb = "zscale=t=linear,scale=320:180"
        existing = ffmpeg_libplacebo_input_args()
        vf, args, active, backend = augment_thumb_extract_for_hw_decode(
            thumb,
            existing,
            enabled=True,
            apply_tonemap=True,
            dolby_vision=True,
            tile_width=320,
        )
        self.assertTrue(active)
        self.assertEqual(backend, HW_DECODE_VAAPI_VULKAN)
        self.assertIn("hwmap=derive_device=vulkan,", vf)
        self.assertIn("libplacebo=", vf)
        self.assertIn("apply_dolbyvision=1", vf)
        self.assertIn("scale=320:", vf)
        self.assertNotIn("hwdownload", vf)
        self.assertIn("vulkan=vk@va", args)
        self.assertNotIn("vulkan=vk", args)
        # Derived init must appear before hwaccel.
        self.assertLess(args.index("vulkan=vk@va"), args.index("vaapi"))
        expected_prefix = ffmpeg_vaapi_vulkan_input_args("/dev/dri/renderD128")
        self.assertEqual(args[: len(expected_prefix)], expected_prefix)

    def test_backend_labels(self) -> None:
        self.assertEqual(hw_decode_backend_label(HW_DECODE_CUDA), "CUDA/NVDEC")
        self.assertEqual(hw_decode_backend_label(HW_DECODE_D3D11VA), "D3D11VA")
        self.assertEqual(hw_decode_backend_label(HW_DECODE_VAAPI_VULKAN), "VA-API+Vulkan")
        self.assertEqual(hw_decode_backend_label(HW_DECODE_VAAPI_DOWNLOAD), "VA-API")
        self.assertEqual(hw_decode_backend_label(HW_DECODE_NONE), "")


class EligibilityCodecTests(unittest.TestCase):
    """Eligibility rejects non-HEVC / 8-bit SDR via mocked ffprobe JSON."""

    def _run_probe(self, stream: dict) -> tuple[bool, str]:
        from hdr_tone_map import probe_hw_decode_eligible

        with (
            patch(
                "hdr_tone_map.resolve_ffmpeg_media_path",
                return_value=("/tmp/video.mkv", False),
            ),
            patch("hdr_tone_map.os.path.isfile", return_value=True),
            patch(
                "hdr_tone_map._ffprobe_json",
                return_value='{"streams": []}',
            ),
            patch(
                "hdr_tone_map._primary_video_stream_from_ffprobe",
                return_value=stream,
            ),
        ):
            return probe_hw_decode_eligible("/tmp/video.mkv", "/ffprobe", {})

    def test_rejects_h264(self) -> None:
        ok, reason = self._run_probe(
            {"codec_name": "h264", "pix_fmt": "yuv420p"}
        )
        self.assertFalse(ok)
        self.assertIn("HEVC only", reason)

    def test_rejects_8bit_sdr_hevc(self) -> None:
        ok, reason = self._run_probe(
            {"codec_name": "hevc", "pix_fmt": "yuv420p", "profile": "Main"}
        )
        self.assertFalse(ok)
        self.assertIn("8-bit", reason)

    def test_accepts_10bit_hevc(self) -> None:
        ok, reason = self._run_probe(
            {"codec_name": "hevc", "pix_fmt": "yuv420p10le", "profile": "Main 10"}
        )
        self.assertTrue(ok)
        self.assertIn("HEVC", reason)


if __name__ == "__main__":
    unittest.main()

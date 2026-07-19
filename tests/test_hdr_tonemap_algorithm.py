"""Tests for HDR tonemap filter chain construction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

xbmc = MagicMock()
xbmc.LOGINFO = 0
xbmc.LOGWARNING = 1
sys.modules.setdefault("xbmc", xbmc)
for _name in ("xbmcaddon", "xbmcvfs", "xbmcgui"):
    sys.modules.setdefault(_name, MagicMock())

from hdr_tone_map import _simple_tonemap_chain, _tonemap_algorithm, _zscale_tonemap_chain


class TonemapAlgorithmTests(unittest.TestCase):
    def test_hlg_uses_hable_not_bt2390(self) -> None:
        # Stock ffmpeg tonemap has no bt2390; HLG must not request it.
        self.assertEqual(_tonemap_algorithm("arib-std-b67"), "hable")
        self.assertEqual(_tonemap_algorithm("smpte2084"), "hable")

    def test_zscale_chain_never_mentions_bt2390(self) -> None:
        for transfer in ("arib-std-b67", "smpte2084"):
            chain = _zscale_tonemap_chain(transfer)
            self.assertNotIn("bt2390", chain)
            self.assertIn("tonemap=tonemap=hable", chain)
            self.assertIn(f"color_trc={transfer}", chain)

    def test_simple_chain_never_mentions_bt2390(self) -> None:
        chain = _simple_tonemap_chain("arib-std-b67")
        self.assertNotIn("bt2390", chain)
        self.assertIn("tonemap=tonemap=hable", chain)


if __name__ == "__main__":
    unittest.main()

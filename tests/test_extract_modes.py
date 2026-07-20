"""Tests for extract mode identifiers and migration."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from generator_extract_modes import (  # noqa: E402
    EXTRACT_MODE_BATCH_SEEKS,
    EXTRACT_MODE_EXPERIMENTAL,
    EXTRACT_MODE_FAST,
    extract_mode_log_label,
    normalize_extract_mode,
)


class ExtractModeTests(unittest.TestCase):
    def test_normalize_maps_experimental_to_batch_seeks(self) -> None:
        self.assertEqual(
            normalize_extract_mode(EXTRACT_MODE_EXPERIMENTAL),
            EXTRACT_MODE_BATCH_SEEKS,
        )
        self.assertEqual(normalize_extract_mode("experimental"), EXTRACT_MODE_BATCH_SEEKS)

    def test_normalize_accepts_batch_seeks(self) -> None:
        self.assertEqual(
            normalize_extract_mode(EXTRACT_MODE_BATCH_SEEKS),
            EXTRACT_MODE_BATCH_SEEKS,
        )

    def test_normalize_unknown_defaults_to_fast(self) -> None:
        self.assertEqual(normalize_extract_mode(""), EXTRACT_MODE_FAST)
        self.assertEqual(normalize_extract_mode("nope"), EXTRACT_MODE_FAST)

    def test_log_label(self) -> None:
        self.assertEqual(extract_mode_log_label(EXTRACT_MODE_BATCH_SEEKS), "batch seeks")
        self.assertEqual(extract_mode_log_label(EXTRACT_MODE_EXPERIMENTAL), "batch seeks")


if __name__ == "__main__":
    unittest.main()

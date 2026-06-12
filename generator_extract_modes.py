"""Trickplay generator frame extraction mode identifiers."""

from __future__ import annotations

EXTRACT_MODE_ACCURATE = "accurate"
EXTRACT_MODE_FAST = "fast"
EXTRACT_MODE_EXPERIMENTAL = "experimental"

VALID_EXTRACT_MODES = frozenset(
    {
        EXTRACT_MODE_ACCURATE,
        EXTRACT_MODE_FAST,
        EXTRACT_MODE_EXPERIMENTAL,
    }
)


def normalize_extract_mode(mode: str, *, legacy_fast: bool = True) -> str:
    normalized = (mode or "").strip().lower()
    if normalized in VALID_EXTRACT_MODES:
        return normalized
    return EXTRACT_MODE_FAST if legacy_fast else EXTRACT_MODE_ACCURATE


def extract_mode_log_label(mode: str) -> str:
    labels = {
        EXTRACT_MODE_ACCURATE: "accurate",
        EXTRACT_MODE_FAST: "fast",
        EXTRACT_MODE_EXPERIMENTAL: "experimental",
    }
    return labels.get(mode, mode)

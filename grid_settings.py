"""Shared tile grid preset resolution for display and generator settings."""

from __future__ import annotations

from trickplay_resolver import parse_manual_tile_grid

GRID_PRESET_AUTO = "auto"
GRID_PRESET_CUSTOM = "custom"
GRID_PRESETS: tuple[str, ...] = (
    "10x10",
    "20x20",
    "5x5",
    "15x15",
    GRID_PRESET_CUSTOM,
)


def resolve_grid_preset(preset: str, custom: str, default: str = "10x10") -> str:
    """Return a grid string like '10x10' from a preset id and optional custom value."""
    preset = (preset or default).strip().lower()
    if preset == GRID_PRESET_CUSTOM:
        custom = (custom or default).strip()
        parsed = parse_manual_tile_grid(custom)
        return custom if parsed else default
    if preset in GRID_PRESETS and preset != GRID_PRESET_CUSTOM:
        return preset
    parsed = parse_manual_tile_grid(preset)
    if parsed:
        cols, rows = parsed
        return f"{cols}x{rows}"
    return default


def grid_tuple(grid: str) -> tuple[int, int]:
    parsed = parse_manual_tile_grid(grid)
    if parsed:
        return parsed
    return 10, 10


def display_grid_uses_folder(mode: str) -> bool:
    return (mode or GRID_PRESET_AUTO).strip().lower() == GRID_PRESET_AUTO

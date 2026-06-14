"""Resolve seek bar geometry and preview placement for trickplay skin properties."""

from __future__ import annotations

from dataclasses import dataclass

from skin_profiles import DEFAULT_PROFILE, active_profile

PREVIEW_GAP = 10
PREVIEW_WIDTH = 320
LABEL_HEIGHT = 40
PREVIEW_SLOTS = 51
PREVIEW_X_OFFSET = 30
LAYOUT_SEEKBAR = "seekbar"
LAYOUT_CENTER = "center"

# Back-compat aliases (Estuary Mod v2 defaults).
SEEKBAR_DEFAULT = DEFAULT_PROFILE.seekbar
SEEKBAR_SMALL = DEFAULT_PROFILE.seekbar_wide or DEFAULT_PROFILE.seekbar
SKIN_ANCHOR_NORMAL = (
    DEFAULT_PROFILE.seekbar[0] + PREVIEW_X_OFFSET,
    DEFAULT_PROFILE.seekbar[1] - 224 - PREVIEW_GAP,
)
SKIN_ANCHOR_WIDE = (
    (DEFAULT_PROFILE.seekbar_wide or DEFAULT_PROFILE.seekbar)[0] + PREVIEW_X_OFFSET,
    SKIN_ANCHOR_NORMAL[1],
)


@dataclass(frozen=True)
class SeekBarLayout:
    left: int
    top: int
    width: int


@dataclass(frozen=True)
class PreviewPlacement:
    slot: int
    left: int
    top: int
    left_wide: int
    preview_w: int
    preview_h: int
    label_h: int


def gui_size() -> tuple[int, int]:
    return 1920, 1080


def preview_dimensions(
    screen_w: int,
    screen_h: int,
    aspect_ratio: float,
    show_timestamp: bool = True,
) -> tuple[int, int, int]:
    aspect_ratio = max(min(aspect_ratio, 3.0), 0.5)
    scale = min(screen_w / 1920.0, screen_h / 1080.0, 1.0)
    scale = max(scale, 0.55)
    preview_w = max(int(PREVIEW_WIDTH * scale), 160)
    preview_h = max(int(preview_w / aspect_ratio), 60)
    if show_timestamp:
        label_h = max(int(LABEL_HEIGHT * scale), 28)
    else:
        label_h = 0
    return preview_w, preview_h, label_h


def _slot_ratio(slot: int, slots: int = PREVIEW_SLOTS) -> float:
    if slots <= 1:
        return 0.0
    return slot / float(slots - 1)


def _absolute_left(bar: SeekBarLayout, ratio: float, preview_w: int) -> int:
    marker_x = bar.left + int(bar.width * ratio)
    left = marker_x - preview_w // 2
    min_left = bar.left
    max_left = bar.left + max(bar.width - preview_w, 0)
    return max(min_left, min(left, max_left))


def preview_slot(seek_second: int, duration_second: int, slots: int = PREVIEW_SLOTS) -> int:
    if duration_second <= 0:
        return 0
    ratio = max(0.0, min(1.0, seek_second / float(duration_second)))
    return min(int(ratio * (slots - 1) + 0.5), slots - 1)


def preview_layout_mode() -> str:
    """Seekbar-tracked preview, or centered above the bar when AF3 full OSD is open."""
    profile = active_profile()
    if profile.key == "arctic_fuse_3" and profile.full_osd_visible():
        return LAYOUT_CENTER
    return LAYOUT_SEEKBAR


def preview_placement(
    seek_second: int,
    duration_second: int,
    aspect_ratio: float,
    show_timestamp: bool | None = None,
    layout: str | None = None,
) -> PreviewPlacement:
    profile = active_profile()
    screen_w, screen_h = gui_size()
    if show_timestamp is None:
        try:
            from preview_dialog import show_timestamp_enabled

            show_timestamp = show_timestamp_enabled()
        except ImportError:  # pragma: no cover
            show_timestamp = True
    preview_w, preview_h, label_h = preview_dimensions(
        screen_w, screen_h, aspect_ratio, show_timestamp=show_timestamp
    )
    if layout is None:
        layout = preview_layout_mode()

    bar = SeekBarLayout(*profile.seekbar)
    wide = profile.seekbar_wide or profile.seekbar
    bar_wide = SeekBarLayout(*wide)
    total_h = preview_h + label_h + PREVIEW_GAP
    top = max(8, bar.top - total_h - PREVIEW_GAP)

    if layout == LAYOUT_CENTER:
        return PreviewPlacement(
            PREVIEW_SLOTS // 2,
            _absolute_left(bar, 0.5, preview_w),
            top,
            _absolute_left(bar_wide, 0.5, preview_w),
            preview_w,
            preview_h,
            label_h,
        )

    slot = preview_slot(seek_second, duration_second)
    ratio = _slot_ratio(slot)

    return PreviewPlacement(
        slot,
        _absolute_left(bar, ratio, preview_w),
        top,
        _absolute_left(bar_wide, ratio, preview_w),
        preview_w,
        preview_h,
        label_h,
    )

"""Resolve seek bar geometry and preview placement for trickplay skin properties."""

from __future__ import annotations

from dataclasses import dataclass

PREVIEW_GAP = 10
PREVIEW_WIDTH = 320
LABEL_HEIGHT = 40
PREVIEW_SLOTS = 51

# DialogSeekBar SeekBar include: left=460, right=30 on 1920x1080 -> width 1430.
SEEKBAR_DEFAULT = (460, 990, 1430)
SEEKBAR_SMALL = (30, 990, 1860)

# Static skin anchor for slot 0 (see DialogSeekBar-skin.estuary.modv2.xml slide animations).
PREVIEW_X_OFFSET = 30
SKIN_ANCHOR_NORMAL = (SEEKBAR_DEFAULT[0] + PREVIEW_X_OFFSET, 756)
SKIN_ANCHOR_WIDE = (SEEKBAR_SMALL[0] + PREVIEW_X_OFFSET, 756)


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
) -> tuple[int, int, int]:
    aspect_ratio = max(min(aspect_ratio, 3.0), 0.5)
    scale = min(screen_w / 1920.0, screen_h / 1080.0, 1.0)
    scale = max(scale, 0.55)
    preview_w = max(int(PREVIEW_WIDTH * scale), 160)
    preview_h = max(int(preview_w / aspect_ratio), 60)
    label_h = max(int(LABEL_HEIGHT * scale), 28)
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


def preview_placement(
    seek_second: int,
    duration_second: int,
    aspect_ratio: float,
) -> PreviewPlacement:
    screen_w, screen_h = gui_size()
    preview_w, preview_h, label_h = preview_dimensions(
        screen_w, screen_h, aspect_ratio
    )
    slot = preview_slot(seek_second, duration_second)

    bar = SeekBarLayout(*SEEKBAR_DEFAULT)
    bar_wide = SeekBarLayout(*SEEKBAR_SMALL)
    ratio = _slot_ratio(slot)
    total_h = preview_h + label_h + PREVIEW_GAP
    top = max(8, bar.top - total_h - PREVIEW_GAP)

    return PreviewPlacement(
        slot,
        _absolute_left(bar, ratio, preview_w),
        top,
        _absolute_left(bar_wide, ratio, preview_w),
        preview_w,
        preview_h,
        label_h,
    )

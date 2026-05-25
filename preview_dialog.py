"""Trickplay preview: crop thumbs and publish DialogSeekBar window properties."""

from __future__ import annotations

import threading

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from osd_layout import preview_placement
from thumb_cropper import get_cached_thumb_path, get_cropped_thumb_path
from trickplay_resolver import TrickplayLookup

ADDON = xbmcaddon.Addon()
HOME_WINDOW = xbmcgui.Window(10000)
SEEKBAR_WINDOW_ID = 10115

PROP_PREFIX = "Trickplay."
PROP_PREVIEW_IMAGE = "Trickplay.PreviewImage"
PROP_PREVIEW_VISIBLE = "Trickplay.PreviewVisible"
PROP_PREVIEW_TIME = "Trickplay.PreviewTime"
PROP_PREVIEW_SLOT = "Trickplay.PreviewSlot"
PROP_PREVIEW_LEFT = "Trickplay.PreviewLeft"
PROP_PREVIEW_TOP = "Trickplay.PreviewTop"
PROP_PREVIEW_LEFT_WIDE = "Trickplay.PreviewLeftWide"
PROP_PREVIEW_WIDTH = "Trickplay.PreviewWidth"
PROP_PREVIEW_HEIGHT = "Trickplay.PreviewHeight"
PROP_PREVIEW_LABEL_H = "Trickplay.PreviewLabelHeight"
PROP_PREVIEW_TOTAL_H = "Trickplay.PreviewTotalHeight"
PROP_DURATION = "Trickplay.Duration"
PROP_THUMB_W = "Trickplay.ThumbWidth"
PROP_THUMB_H = "Trickplay.ThumbHeight"

PREVIEW_PROPERTIES = (
    PROP_PREVIEW_IMAGE,
    PROP_PREVIEW_VISIBLE,
    PROP_PREVIEW_TIME,
    PROP_PREVIEW_SLOT,
    PROP_PREVIEW_LEFT,
    PROP_PREVIEW_TOP,
    PROP_PREVIEW_LEFT_WIDE,
    PROP_PREVIEW_WIDTH,
    PROP_PREVIEW_HEIGHT,
    PROP_PREVIEW_LABEL_H,
    PROP_PREVIEW_TOTAL_H,
    PROP_DURATION,
    PROP_THUMB_W,
    PROP_THUMB_H,
)

DEFAULT_ASPECT_RATIO = 16 / 9


def _debug_logging() -> bool:
    try:
        return ADDON.getSettingBool("debug_logging")
    except (RuntimeError, TypeError, ValueError):
        return False


def display_aspect_ratio(
    lookup: TrickplayLookup,
    player: xbmc.Player | None = None,
) -> float:
    if lookup.thumb_width > 0 and lookup.thumb_height > 0:
        return lookup.thumb_width / float(lookup.thumb_height)
    if player is not None:
        try:
            tag = player.getVideoInfoTag()
            width = int(tag.getWidth() or 0)
            height = int(tag.getHeight() or 0)
            if width > 0 and height > 0:
                return width / float(height)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    return DEFAULT_ASPECT_RATIO


def lookup_cache_key(lookup: TrickplayLookup) -> tuple[str, int, int, int, int]:
    return (
        lookup.tile_path,
        lookup.col,
        lookup.row,
        lookup.thumb_width,
        lookup.thumb_height,
    )


def format_preview_time(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _thumb_texture_path(thumb_path: str) -> str:
    if thumb_path.startswith(("special://", "vfs://", "zip://")):
        return thumb_path
    local = xbmcvfs.translatePath(thumb_path)
    if local and xbmcvfs.exists(local):
        return local
    return thumb_path


def _seekbar_window() -> xbmcgui.Window | None:
    if not xbmc.getCondVisibility(
        "Window.IsVisible(seekbar) | Window.IsActive(seekbar) | "
        "Window.IsVisible(DialogSeekBar.xml)"
    ):
        return None
    try:
        return xbmcgui.Window(SEEKBAR_WINDOW_ID)
    except RuntimeError:
        return None


def _set_property(name: str, value: str) -> None:
    HOME_WINDOW.setProperty(name, value)
    seekbar = _seekbar_window()
    if seekbar is not None:
        try:
            seekbar.setProperty(name, value)
        except RuntimeError:
            pass


def _clear_property(name: str) -> None:
    HOME_WINDOW.clearProperty(name)
    seekbar = _seekbar_window()
    if seekbar is not None:
        try:
            seekbar.clearProperty(name)
        except RuntimeError:
            pass


def _clear_preview_properties() -> None:
    for prop in PREVIEW_PROPERTIES:
        _clear_property(prop)


def sync_trickplay_property(name: str, value: str) -> None:
    _set_property(name, value)


def clear_trickplay_property(name: str) -> None:
    _clear_property(name)


def resync_preview_to_seekbar() -> None:
    """Copy preview properties to DialogSeekBar when it opens after publish."""
    seekbar = _seekbar_window()
    if seekbar is None:
        return
    for prop in PREVIEW_PROPERTIES:
        value = HOME_WINDOW.getProperty(prop)
        if value:
            try:
                seekbar.setProperty(prop, value)
            except RuntimeError:
                pass


class PreviewDialogController:
    """Crop trickplay thumbs and publish DialogSeekBar skin properties."""

    def __init__(self, addon_path: str) -> None:
        self.addon_path = addon_path
        self._request_id = 0
        self._crop_thread: threading.Thread | None = None
        self._pending_lookup: TrickplayLookup | None = None
        self._pending_duration = 0
        self._pending_player: xbmc.Player | None = None
        self._crop_failed = False
        self._shown_thumb_index = -1
        self._last_thumb_path: str | None = None

    def detach_overlay(self) -> None:
        self.hide_preview()

    def hide_preview(self) -> None:
        self._request_id += 1
        self._pending_lookup = None
        self._pending_duration = 0
        self._pending_player = None
        self._crop_failed = False
        self._shown_thumb_index = -1
        self._last_thumb_path = None
        _clear_preview_properties()

    def _publish_placement(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        player: xbmc.Player | None,
    ) -> None:
        aspect_ratio = display_aspect_ratio(lookup, player)
        placement = preview_placement(
            lookup.target_second,
            duration_seconds,
            aspect_ratio,
        )
        total_h = placement.preview_h + placement.label_h + 4
        _set_property(PROP_PREVIEW_SLOT, str(placement.slot))
        _set_property(PROP_PREVIEW_LEFT, str(placement.left))
        _set_property(PROP_PREVIEW_TOP, str(placement.top))
        _set_property(PROP_PREVIEW_LEFT_WIDE, str(placement.left_wide))
        _set_property(PROP_PREVIEW_WIDTH, str(placement.preview_w))
        _set_property(PROP_PREVIEW_HEIGHT, str(placement.preview_h))
        _set_property(PROP_PREVIEW_LABEL_H, str(placement.label_h))
        _set_property(PROP_PREVIEW_TOTAL_H, str(total_h))

        xbmc.log(
            f"[service.trickplay] Preview slot {placement.slot} "
            f"({placement.left},{placement.top}) "
            f"{placement.preview_w}x{placement.preview_h} @ {lookup.target_second}s "
            f"(duration={duration_seconds}s)",
            xbmc.LOGINFO,
        )

    def _publish_preview_state(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        image_path: str | None,
        player: xbmc.Player | None = None,
    ) -> None:
        _set_property(PROP_PREVIEW_TIME, format_preview_time(lookup.target_second))
        _set_property(PROP_DURATION, str(max(duration_seconds, 0)))
        _set_property(PROP_THUMB_W, str(lookup.thumb_width))
        _set_property(PROP_THUMB_H, str(lookup.thumb_height))
        self._publish_placement(lookup, duration_seconds, player)
        if image_path:
            _set_property(PROP_PREVIEW_IMAGE, _thumb_texture_path(image_path))
        else:
            _clear_property(PROP_PREVIEW_IMAGE)
        resync_preview_to_seekbar()

    def show_preview(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        player: xbmc.Player | None = None,
    ) -> None:
        cache_key = lookup_cache_key(lookup)
        cached = get_cached_thumb_path(
            lookup.tile_path,
            lookup.col,
            lookup.row,
            lookup.thumb_width,
            lookup.thumb_height,
        )

        if cached:
            self._shown_thumb_index = lookup.thumb_index
            self._last_thumb_path = cached
            self._publish_preview_state(lookup, duration_seconds, cached, player)
            return

        same_bucket = lookup.thumb_index == self._shown_thumb_index
        stale_image = self._last_thumb_path if same_bucket else None
        self._publish_preview_state(lookup, duration_seconds, stale_image, player)

        if (
            self._crop_thread is not None
            and self._crop_thread.is_alive()
            and self._pending_lookup is not None
            and lookup_cache_key(self._pending_lookup) == cache_key
        ):
            self._pending_lookup = lookup
            self._pending_duration = duration_seconds
            self._pending_player = player
            return

        self._request_id += 1
        request_id = self._request_id
        self._pending_lookup = lookup
        self._pending_duration = duration_seconds
        self._pending_player = player
        self._crop_failed = False

        debug = _debug_logging()
        self._crop_thread = threading.Thread(
            target=self._crop_worker,
            args=(request_id, lookup, debug),
            daemon=True,
            name="trickplay-crop",
        )
        self._crop_thread.start()

    def _crop_worker(
        self, request_id: int, lookup: TrickplayLookup, debug: bool
    ) -> None:
        thumb_path = get_cropped_thumb_path(
            lookup.tile_path,
            lookup.col,
            lookup.row,
            lookup.thumb_width,
            lookup.thumb_height,
            debug=debug,
        )
        if request_id != self._request_id:
            return
        if not thumb_path:
            self._crop_failed = True
            return
        pending = self._pending_lookup
        if pending is None or lookup_cache_key(pending) != lookup_cache_key(lookup):
            return
        self._last_thumb_path = thumb_path
        self._shown_thumb_index = lookup.thumb_index
        self._publish_preview_state(
            lookup,
            self._pending_duration,
            thumb_path,
            self._pending_player,
        )

    def poll(self) -> None:
        if self._crop_failed and (
            self._crop_thread is None or not self._crop_thread.is_alive()
        ):
            xbmc.log(
                "[service.trickplay] Could not crop preview thumb; "
                "install script.module.pillow or tools.ffmpeg-tools",
                xbmc.LOGWARNING,
            )
            self._crop_failed = False

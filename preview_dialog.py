"""Trickplay preview: crop thumbs and publish DialogSeekBar window properties."""

from __future__ import annotations

import threading
import time

from dataclasses import dataclass

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from osd_layout import preview_layout_mode, preview_placement
from settings_cache import get_cached
from thumb_cropper import get_cached_thumb_path, get_cropped_thumb_path
from trickplay_resolver import TrickplayLookup

ADDON = xbmcaddon.Addon("service.trickplay")
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
PROP_SHOW_TIMESTAMP = "Trickplay.ShowTimestamp"
PROP_PREVIEW_COLOR_DIFFUSE = "Trickplay.PreviewColorDiffuse"
PROP_PREVIEW_LAYOUT = "Trickplay.PreviewLayout"

DISPLAY_PROPERTIES = (
    PROP_SHOW_TIMESTAMP,
    PROP_PREVIEW_COLOR_DIFFUSE,
)

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
    PROP_PREVIEW_LAYOUT,
)

_RESYNC_PROPERTIES = PREVIEW_PROPERTIES + DISPLAY_PROPERTIES
_seekbar_visible_last = False
_last_resync_snapshot: tuple[tuple[str, str], ...] | None = None

SCRUB_COALESCE_SEC = 0.12
SCRUB_GAP_SEC = 0.25
SCRUB_JUMP_THUMBS = 3

DEFAULT_ASPECT_RATIO = 16 / 9


@dataclass(frozen=True)
class DisplaySyncSettings:
    show_timestamp: bool
    color_diffuse: str


def _debug_logging() -> bool:
    try:
        from generator_settings import read_runtime_settings

        return read_runtime_settings().debug_logging
    except ImportError:  # pragma: no cover
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
        return thumb_path.replace("\\", "/")
    local = xbmcvfs.translatePath(thumb_path)
    if local:
        local = local.replace("\\", "/")
        profile = xbmcvfs.translatePath("special://profile/").replace("\\", "/")
        if profile and local.lower().startswith(profile.lower()):
            rel = local[len(profile) :].lstrip("/")
            return f"special://profile/{rel}"
        if xbmcvfs.exists(local):
            return local
    return thumb_path.replace("\\", "/")


def _seekbar_window() -> xbmcgui.Window | None:
    if not xbmc.getCondVisibility(
        "Window.IsVisible(seekbar) | Window.IsActive(seekbar) | "
        "Window.IsVisible(DialogSeekBar.xml)"
    ):
        return None
    return _seekbar_window_unconditional()


def _seekbar_window_unconditional() -> xbmcgui.Window | None:
    try:
        return xbmcgui.Window(SEEKBAR_WINDOW_ID)
    except RuntimeError:
        return None


def _for_each_seekbar_window() -> list[xbmcgui.Window]:
    windows: list[xbmcgui.Window] = []
    for getter in (_seekbar_window, _seekbar_window_unconditional):
        window = getter()
        if window is not None and window not in windows:
            windows.append(window)
    return windows


def _set_property(name: str, value: str) -> None:
    HOME_WINDOW.setProperty(name, value)
    for seekbar in _for_each_seekbar_window():
        try:
            seekbar.setProperty(name, value)
        except RuntimeError:
            pass


def _show_timestamp_setting() -> bool:
    try:
        return ADDON.getSettingBool("show_timestamp")
    except (RuntimeError, TypeError, ValueError):
        raw = ADDON.getSettingString("show_timestamp")
        if not raw:
            return True
        return raw.strip().lower() in ("true", "1", "yes", "on")


def _setting_int(setting_id: str, default: int) -> int:
    try:
        return int(ADDON.getSettingInt(setting_id))
    except (TypeError, ValueError):
        raw = ADDON.getSettingString(setting_id)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default


def preview_opacity_percent() -> int:
    return max(0, min(_setting_int("preview_opacity", 100), 100))


def preview_color_diffuse(opacity_percent: int | None = None) -> str:
    opacity = preview_opacity_percent() if opacity_percent is None else opacity_percent
    opacity = max(0, min(int(opacity), 100))
    alpha = int(round(opacity * 255 / 100))
    return f"{alpha:02X}FFFFFF"


def _load_display_sync_settings() -> DisplaySyncSettings:
    show_timestamp = _show_timestamp_setting()
    return DisplaySyncSettings(
        show_timestamp=show_timestamp,
        color_diffuse=preview_color_diffuse(
            opacity_percent=_setting_int("preview_opacity", 100)
        ),
    )


def show_timestamp_enabled() -> bool:
    return get_cached("display_sync", _load_display_sync_settings).show_timestamp


def sync_display_settings() -> None:
    display = get_cached("display_sync", _load_display_sync_settings)
    sync_trickplay_property(
        PROP_SHOW_TIMESTAMP, "true" if display.show_timestamp else "false"
    )
    sync_trickplay_property(PROP_PREVIEW_COLOR_DIFFUSE, display.color_diffuse)


def _clear_property(name: str) -> None:
    HOME_WINDOW.clearProperty(name)
    for seekbar in _for_each_seekbar_window():
        try:
            seekbar.clearProperty(name)
        except RuntimeError:
            pass


def _clear_preview_properties() -> None:
    _reset_resync_state()
    for prop in PREVIEW_PROPERTIES:
        _clear_property(prop)
    for prop in DISPLAY_PROPERTIES:
        _clear_property(prop)


def sync_trickplay_property(name: str, value: str) -> None:
    _set_property(name, value)


def clear_trickplay_property(name: str) -> None:
    _clear_property(name)


def _dialog_seekbar_visible() -> bool:
    return xbmc.getCondVisibility(
        "Window.IsVisible(seekbar) | Window.IsActive(seekbar) | "
        "Window.IsVisible(DialogSeekBar.xml)"
    )


def _collect_resync_snapshot() -> tuple[tuple[str, str], ...]:
    return tuple(
        (prop, HOME_WINDOW.getProperty(prop) or "") for prop in _RESYNC_PROPERTIES
    )


def _seekbar_properties_match(
    seekbar: xbmcgui.Window, snapshot: tuple[tuple[str, str], ...]
) -> bool:
    for prop, value in snapshot:
        try:
            if (seekbar.getProperty(prop) or "") != value:
                return False
        except RuntimeError:
            return False
    return True


def _reset_resync_state() -> None:
    global _seekbar_visible_last, _last_resync_snapshot
    _seekbar_visible_last = False
    _last_resync_snapshot = None


def resync_preview_to_seekbar(*, force: bool = False) -> None:
    """Copy preview properties to DialogSeekBar when it opens after publish."""
    global _seekbar_visible_last, _last_resync_snapshot

    if not _dialog_seekbar_visible():
        _seekbar_visible_last = False
        return

    seekbar = _seekbar_window_unconditional()
    if seekbar is None:
        _seekbar_visible_last = False
        _last_resync_snapshot = None
        return

    snapshot = _collect_resync_snapshot()
    visibility_transition = not _seekbar_visible_last

    if not force and not visibility_transition:
        if _seekbar_properties_match(seekbar, snapshot):
            _last_resync_snapshot = snapshot
            return

    for prop, value in snapshot:
        try:
            if value:
                seekbar.setProperty(prop, value)
            else:
                seekbar.clearProperty(prop)
        except RuntimeError:
            pass

    _last_resync_snapshot = snapshot
    _seekbar_visible_last = True


class PreviewDialogController:
    """Publish DialogSeekBar skin properties for trickplay preview (atlas or crop)."""

    def __init__(self, addon_path: str) -> None:
        self.addon_path = addon_path
        self._crop_lock = threading.Lock()
        self._crop_target_id = 0
        self._crop_thread: threading.Thread | None = None
        self._pending_lookup: TrickplayLookup | None = None
        self._pending_duration = 0
        self._pending_player: xbmc.Player | None = None
        self._crop_failed = False
        self._shown_thumb_index = -1
        self._last_thumb_path: str | None = None
        self._last_placement_key: tuple[int, int, float, bool, str] | None = None
        self._last_scrub_at = 0.0
        self._last_scrub_thumb_index = -1
        self._scrub_burst_until = 0.0
        self._fast_scrub_active = False

    @property
    def fast_scrub_active(self) -> bool:
        return self._fast_scrub_active

    def detach_overlay(self) -> None:
        self.hide_preview()

    def hide_preview(self) -> None:
        with self._crop_lock:
            self._crop_target_id += 1
            self._pending_lookup = None
            self._pending_duration = 0
            self._pending_player = None
        self._crop_failed = False
        self._shown_thumb_index = -1
        self._last_thumb_path = None
        self._last_placement_key = None
        self._last_scrub_at = 0.0
        self._last_scrub_thumb_index = -1
        self._scrub_burst_until = 0.0
        self._fast_scrub_active = False
        _clear_preview_properties()

    def _scrub_churn_active(self, lookup: TrickplayLookup, *, seeking: bool) -> bool:
        """True only during rapid successive scrub updates (not a single big jump)."""
        if not seeking:
            self._scrub_burst_until = 0.0
            return False
        now = time.monotonic()
        fast = False
        if now < self._scrub_burst_until:
            fast = True
        if (
            self._last_scrub_at > 0.0
            and now - self._last_scrub_at < SCRUB_COALESCE_SEC
        ):
            fast = True
        # Large index jumps only count as churn when updates are already arriving
        # quickly — a single leap from playhead to scrub target must still use
        # cache / eager crop so the first thumb is not delayed.
        recent = (
            self._last_scrub_at > 0.0
            and now - self._last_scrub_at < SCRUB_GAP_SEC
        )
        if recent and self._last_scrub_thumb_index >= 0:
            jump = abs(lookup.thumb_index - self._last_scrub_thumb_index)
            if jump >= SCRUB_JUMP_THUMBS:
                fast = True
        if fast:
            self._scrub_burst_until = now + SCRUB_COALESCE_SEC
        return fast

    def _placement_key(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        player: xbmc.Player | None,
        layout: str,
    ) -> tuple[int, int, float, bool, str]:
        return (
            lookup.target_second,
            max(duration_seconds, 0),
            display_aspect_ratio(lookup, player),
            show_timestamp_enabled(),
            layout,
        )

    def _publish_placement(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        player: xbmc.Player | None,
        layout: str | None = None,
    ) -> None:
        if layout is None:
            layout = preview_layout_mode()
        aspect_ratio = display_aspect_ratio(lookup, player)
        placement = preview_placement(
            lookup.target_second,
            duration_seconds,
            aspect_ratio,
            show_timestamp=show_timestamp_enabled(),
            layout=layout,
        )
        total_h = placement.preview_h + placement.label_h + 4
        _set_property(PROP_PREVIEW_LAYOUT, layout)
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
        sync_display_settings()
        if show_timestamp_enabled():
            _set_property(PROP_PREVIEW_TIME, format_preview_time(lookup.target_second))
        else:
            _clear_property(PROP_PREVIEW_TIME)
        _set_property(PROP_DURATION, str(max(duration_seconds, 0)))
        _set_property(PROP_THUMB_W, str(lookup.thumb_width))
        _set_property(PROP_THUMB_H, str(lookup.thumb_height))
        layout = preview_layout_mode()
        placement_key = self._placement_key(lookup, duration_seconds, player, layout)
        if placement_key != self._last_placement_key:
            self._publish_placement(lookup, duration_seconds, player, layout)
            self._last_placement_key = placement_key
        if image_path:
            texture = _thumb_texture_path(image_path)
            _set_property(PROP_PREVIEW_IMAGE, texture)
            if _debug_logging():
                xbmc.log(
                    f"[service.trickplay] Preview texture: {texture}",
                    xbmc.LOGINFO,
                )
        else:
            _clear_property(PROP_PREVIEW_IMAGE)
        if _dialog_seekbar_visible():
            resync_preview_to_seekbar(force=True)

    def show_preview(
        self,
        lookup: TrickplayLookup,
        duration_seconds: int,
        player: xbmc.Player | None = None,
        *,
        eager: bool = False,
    ) -> None:
        fast_scrub = self._scrub_churn_active(lookup, seeking=eager)
        self._fast_scrub_active = fast_scrub
        self._last_scrub_at = time.monotonic()
        self._last_scrub_thumb_index = lookup.thumb_index

        cache_key = lookup_cache_key(lookup)
        cached = get_cached_thumb_path(
            lookup.tile_path,
            lookup.col,
            lookup.row,
            lookup.thumb_width,
            lookup.thumb_height,
        )

        if cached and not fast_scrub:
            self._shown_thumb_index = lookup.thumb_index
            self._last_thumb_path = cached
            self._publish_preview_state(lookup, duration_seconds, cached, player)
            return

        use_eager = eager and not fast_scrub
        if use_eager:
            debug = _debug_logging()
            thumb_path = get_cropped_thumb_path(
                lookup.tile_path,
                lookup.col,
                lookup.row,
                lookup.thumb_width,
                lookup.thumb_height,
                debug=debug,
            )
            if thumb_path:
                self._shown_thumb_index = lookup.thumb_index
                self._last_thumb_path = thumb_path
                self._publish_preview_state(
                    lookup, duration_seconds, thumb_path, player
                )
                return

        stale_image = self._last_thumb_path
        if not fast_scrub:
            same_bucket = lookup.thumb_index == self._shown_thumb_index
            stale_image = self._last_thumb_path if same_bucket else None

        with self._crop_lock:
            pending_key = (
                lookup_cache_key(self._pending_lookup)
                if self._pending_lookup is not None
                else None
            )
            if pending_key != cache_key:
                self._crop_target_id += 1
            self._pending_lookup = lookup
            self._pending_duration = duration_seconds
            self._pending_player = player
            self._crop_failed = False

        self._publish_preview_state(lookup, duration_seconds, stale_image, player)
        self._ensure_crop_worker(_debug_logging())

    def _ensure_crop_worker(self, debug: bool) -> None:
        with self._crop_lock:
            if self._crop_thread is not None and self._crop_thread.is_alive():
                return
            self._crop_thread = threading.Thread(
                target=self._crop_worker_loop,
                args=(debug,),
                daemon=True,
                name="trickplay-crop",
            )
            self._crop_thread.start()

    def _crop_worker_loop(self, debug: bool) -> None:
        while True:
            with self._crop_lock:
                lookup = self._pending_lookup
                duration = self._pending_duration
                player = self._pending_player
                target_id = self._crop_target_id

            if lookup is None:
                return

            thumb_path = get_cropped_thumb_path(
                lookup.tile_path,
                lookup.col,
                lookup.row,
                lookup.thumb_width,
                lookup.thumb_height,
                debug=debug,
            )

            with self._crop_lock:
                if self._crop_target_id != target_id:
                    continue
                pending = self._pending_lookup
                if pending is None:
                    return
                if lookup_cache_key(pending) != lookup_cache_key(lookup):
                    continue
                if not thumb_path:
                    self._crop_failed = True
                    return

                self._last_thumb_path = thumb_path
                self._shown_thumb_index = lookup.thumb_index
                self._publish_preview_state(
                    lookup,
                    duration,
                    thumb_path,
                    player,
                )

                pending = self._pending_lookup
                if (
                    pending is not None
                    and lookup_cache_key(pending) != lookup_cache_key(lookup)
                ):
                    continue
                return

    def poll(self) -> None:
        if self._crop_failed and (
            self._crop_thread is None or not self._crop_thread.is_alive()
        ):
            xbmc.log(
                "[service.trickplay] Could not crop preview thumb; "
                "use Install preview tools in add-on settings",
                xbmc.LOGWARNING,
            )
            self._crop_failed = False

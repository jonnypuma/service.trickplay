"""Kodi background service that exposes Jellyfin trickplay previews while seeking."""

from __future__ import annotations

import sys
import time

import xbmc
import xbmcgui
import xbmcaddon

ADDON = xbmcaddon.Addon()
_ADDON_PATH = ADDON.getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

from prefetch import ThumbPrefetch
from prefetch_settings import read_prefetch_settings
from preview_dialog import (
    PREVIEW_PROPERTIES,
    PROP_PREVIEW_VISIBLE,
    PreviewDialogController,
    clear_trickplay_property,
    resync_preview_to_seekbar,
    sync_display_settings,
    sync_trickplay_property,
)
from trickplay_resolver import (
    enrich_resolution,
    load_trickplay_for_file,
    lookup_thumbnail,
    resolve_media_path,
    TrickplayResolution,
)

from skin_profiles import (
    DEFAULT_PROFILE,
    active_profile,
    current_skin_id,
    is_known_skin,
    profile_summary,
    setting_skin_profile_override,
)

HOME_WINDOW = xbmcgui.Window(10000)

SEEKBAR_WINDOW_ID = 10115
SEEK_HOLD_INDEFINITE = float("inf")

PROP_TILE = "Trickplay.TileImage"
PROP_COL = "Trickplay.TileCol"
PROP_ROW = "Trickplay.TileRow"
PROP_THUMB_W = "Trickplay.ThumbWidth"
PROP_THUMB_H = "Trickplay.ThumbHeight"
PROP_SEEKING = "Trickplay.IsSeeking"
PROP_AVAILABLE = "Trickplay.Available"


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay] {message}", level)


def _debug(message: str) -> None:
    if ADDON.getSettingBool("debug_logging"):
        _log(message, xbmc.LOGINFO)


def _setting_int(setting_id: str, default: int) -> int:
    try:
        return int(ADDON.getSettingInt(setting_id))
    except (TypeError, ValueError):
        raw = ADDON.getSettingString(setting_id)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default


def _setting_bool(setting_id: str, default: bool) -> bool:
    try:
        return ADDON.getSettingBool(setting_id)
    except (TypeError, ValueError, RuntimeError):
        raw = ADDON.getSettingString(setting_id)
        if not raw:
            return default
        return raw.strip().lower() in ("true", "1", "yes", "on")


def _setting_string(setting_id: str, default: str) -> str:
    try:
        value = ADDON.getSettingString(setting_id)
    except (TypeError, ValueError, RuntimeError):
        return default
    return value if value else default


def _tile_grid_settings() -> tuple[bool, str]:
    return (
        _setting_bool("auto_tile_calculation", True),
        _setting_string("manual_tile_grid", "10x10"),
    )


def _parse_time_label(label: str) -> int:
    """Convert Kodi time labels (HH:MM:SS or MM:SS) to seconds."""
    if not label:
        return 0

    parts = label.strip().split(":")
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return 0

    if len(values) == 3:
        hours, minutes, seconds = values
        return hours * 3600 + minutes * 60 + seconds
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    if len(values) == 1:
        return values[0]
    return 0


def _player_time_seconds(player: xbmc.Player) -> int:
    try:
        return max(int(player.getTime()), 0)
    except RuntimeError:
        return _parse_time_label(xbmc.getInfoLabel("Player.Time"))


def _player_duration_seconds(player: xbmc.Player) -> int:
    duration = _parse_time_label(xbmc.getInfoLabel("Player.Duration"))
    if duration > 0:
        return duration
    try:
        return max(int(player.getTotalTime()), 0)
    except RuntimeError:
        return 0


class TrickplayService:
    def __init__(self) -> None:
        self.player = KodiPlayer(service=self)
        self.monitor = xbmc.Monitor()
        self.preview = PreviewDialogController(ADDON.getAddonInfo("path"))
        self.prefetch = ThumbPrefetch()
        self.resolution: TrickplayResolution | None = None
        self.playing_file = ""
        self.last_preview_second = -1
        self._last_preview_thumb_index = -1
        self.was_seeking = False
        self.preview_active = False
        self.preview_visible = False
        self.committed_seek_second = -1
        self.committed_seek_at = 0.0
        self.last_play_time = -1
        self.playback_started_at = 0.0
        self.playback_ready = False
        self.cached_duration = 0
        self.poll_ms = max(_setting_int("poll_ms", 100), 50)
        self._active_skin_id = ""
        self._active_skin_override = ""
        self.seek_hold_until = 0.0
        self._had_compact_seekbar = False
        self._last_idle_prefetch_at = 0.0
        self._log_skin_profile(force=True)

    def _preview_hold_seconds(self) -> int:
        return max(_setting_int("preview_hold_seconds", 4), 0)

    def _preview_follows_playhead(self) -> bool:
        """Hold time 0: keep preview visible and advance with playback."""
        return _setting_int("preview_hold_seconds", 4) <= 0

    def _touch_seek_hold(self) -> None:
        seconds = self._preview_hold_seconds()
        if seconds <= 0:
            self.seek_hold_until = SEEK_HOLD_INDEFINITE
        else:
            self.seek_hold_until = time.monotonic() + float(seconds)

    def _seek_hold_active(self) -> bool:
        if self.seek_hold_until <= 0.0:
            return False
        if self.seek_hold_until >= SEEK_HOLD_INDEFINITE:
            return True
        return time.monotonic() < self.seek_hold_until

    def _explicit_seek_active(self) -> bool:
        if xbmc.getCondVisibility("!String.IsEmpty(Player.SeekNumeric)"):
            return True
        if not xbmc.getCondVisibility("Player.Seeking"):
            return False
        if self.committed_seek_at <= 0.0:
            return True
        return time.monotonic() - self.committed_seek_at < 2.0

    def _log_skin_profile(self, force: bool = False) -> None:
        skin_id = current_skin_id()
        override = setting_skin_profile_override()
        if (
            not force
            and skin_id == self._active_skin_id
            and override == self._active_skin_override
        ):
            return
        self._active_skin_id = skin_id
        self._active_skin_override = override
        profile = active_profile(force_refresh=True)
        _log(f"Skin profile: {profile_summary(profile, skin_id, override)}")
        if override == "auto" and skin_id and not is_known_skin(skin_id):
            _log(
                f"Unknown skin '{skin_id}'; using {DEFAULT_PROFILE.label} geometry. "
                "Merge the matching skin snippet or set Skin profile in addon settings.",
                xbmc.LOGWARNING,
            )

    def _effective_duration_seconds(self) -> int:
        duration = _player_duration_seconds(self.player)
        if duration > 0:
            self.cached_duration = duration
            return duration
        if self.cached_duration > 0:
            return self.cached_duration
        if self.resolution is not None and self.resolution.thumbnail_count > 0:
            interval_ms = _setting_int("interval_ms", 10000)
            return int(self.resolution.thumbnail_count * interval_ms / 1000)
        return 0

    def _clear_preview_session(self, reason: str = "") -> None:
        if reason:
            _debug(f"Preview session cleared: {reason}")
        self.last_preview_second = -1
        self._last_preview_thumb_index = -1
        self.was_seeking = False
        self.preview_active = False
        self.seek_hold_until = 0.0
        self.clear_preview_properties()

    def clear_preview_properties(self) -> None:
        self.preview.hide_preview()
        self.preview_visible = False
        self.committed_seek_second = -1
        self.committed_seek_at = 0.0
        for prop in (
            PROP_TILE,
            PROP_COL,
            PROP_ROW,
            PROP_THUMB_W,
            PROP_THUMB_H,
            PROP_SEEKING,
            PROP_AVAILABLE,
            *PREVIEW_PROPERTIES,
        ):
            clear_trickplay_property(prop)

    def reset_playback_state(self) -> None:
        self.resolution = None
        self.playing_file = ""
        self.last_preview_second = -1
        self._last_preview_thumb_index = -1
        self.was_seeking = False
        self.preview_active = False
        self.preview_visible = False
        self.committed_seek_second = -1
        self.committed_seek_at = 0.0
        self.last_play_time = -1
        self.playback_started_at = 0.0
        self.playback_ready = False
        self.cached_duration = 0
        self.seek_hold_until = 0.0
        self._had_compact_seekbar = False
        self._last_idle_prefetch_at = 0.0
        self.prefetch.cancel()
        self.clear_preview_properties()

    def _refresh_resolution_if_needed(self) -> None:
        if self.resolution is None or self.resolution.is_usable:
            return

        duration_seconds = _player_duration_seconds(self.player)
        if duration_seconds > 0:
            self.cached_duration = duration_seconds
        interval_ms = _setting_int("interval_ms", 10000)
        auto_tile_grid, manual_tile_grid = _tile_grid_settings()
        self.resolution = enrich_resolution(
            self.resolution,
            duration_seconds,
            interval_ms,
            auto_tile_grid=auto_tile_grid,
            manual_tile_grid=manual_tile_grid,
            debug=ADDON.getSettingBool("debug_logging"),
        )
        if self.resolution.is_usable:
            _log(
                f"Trickplay metadata refreshed: {self.resolution.thumbnail_count} thumbs, "
                f"thumb size {self.resolution.thumb_width}x{self.resolution.thumb_height}"
            )

    def on_video_started(self, playing_file: str) -> None:
        self._log_skin_profile(force=True)
        self.preview.detach_overlay()
        self.reset_playback_state()
        self.playing_file = playing_file
        self.playback_started_at = time.monotonic()
        self.playback_ready = False

        media_path = resolve_media_path(playing_file)
        if not media_path:
            _log(f"No local trickplay path for {playing_file!r}", xbmc.LOGWARNING)
            return

        duration_seconds = _player_duration_seconds(self.player)
        if duration_seconds > 0:
            self.cached_duration = duration_seconds
        preferred_width = _setting_int("preferred_width", 320)
        interval_ms = _setting_int("interval_ms", 10000)
        auto_tile_grid, manual_tile_grid = _tile_grid_settings()
        debug = ADDON.getSettingBool("debug_logging")

        self.resolution = load_trickplay_for_file(
            playing_file,
            preferred_width=preferred_width,
            interval_ms=interval_ms,
            duration_seconds=duration_seconds,
            auto_tile_grid=auto_tile_grid,
            manual_tile_grid=manual_tile_grid,
            debug=debug,
        )
        if self.resolution is None:
            _log(f"No trickplay data found for {media_path}", xbmc.LOGWARNING)
            return

        if not self.resolution.is_usable:
            self._refresh_resolution_if_needed()

        if not self.resolution.is_usable:
            _log(
                f"Trickplay folder found but metadata unusable for {media_path} "
                f"(tiles={len(self.resolution.tile_paths)})",
                xbmc.LOGWARNING,
            )
            return

        HOME_WINDOW.setProperty(PROP_AVAILABLE, "true")
        sync_trickplay_property(PROP_AVAILABLE, "true")
        sync_display_settings()
        _log(
            f"Loaded trickplay for {media_path} "
            f"({self.resolution.thumbnail_count} thumbs, "
            f"{self.resolution.thumb_width}x{self.resolution.thumb_height}, "
            f"{len(self.resolution.tile_paths)} tile file(s))"
        )

        play_seconds = _player_time_seconds(self.player)
        warm_lookup = lookup_thumbnail(
            self.resolution, play_seconds, interval_ms
        )
        prefetch_settings = read_prefetch_settings()
        if warm_lookup is not None:
            self.prefetch.schedule_playhead_warm(
                self.resolution,
                warm_lookup,
                interval_ms,
                settings=prefetch_settings,
                debug=debug,
            )

    def _publish_sprite_properties(self, lookup) -> None:
        sync_trickplay_property(PROP_TILE, lookup.tile_path)
        sync_trickplay_property(PROP_COL, str(lookup.col))
        sync_trickplay_property(PROP_ROW, str(lookup.row))
        sync_trickplay_property(PROP_THUMB_W, str(lookup.thumb_width))
        sync_trickplay_property(PROP_THUMB_H, str(lookup.thumb_height))

    def update_preview(self, target_second: int, seeking: bool) -> None:
        if self.resolution is None:
            return

        self._refresh_resolution_if_needed()
        if not self.resolution.is_usable:
            return

        target_second = max(target_second, 0)
        if not seeking and target_second == self.last_preview_second:
            return

        interval_ms = _setting_int("interval_ms", 10000)
        lookup = lookup_thumbnail(self.resolution, target_second, interval_ms)
        if lookup is None:
            _debug(f"No trickplay lookup for {target_second}s")
            return

        self.last_preview_second = target_second
        sync_trickplay_property(PROP_SEEKING, "true" if seeking else "false")
        self._publish_sprite_properties(lookup)
        _debug(
            f"Preview {target_second}s -> tile {lookup.tile_path} "
            f"cell ({lookup.col},{lookup.row}) index {lookup.thumb_index}"
        )

        scrub_direction = 0
        if self._last_preview_thumb_index >= 0:
            if lookup.thumb_index > self._last_preview_thumb_index:
                scrub_direction = 1
            elif lookup.thumb_index < self._last_preview_thumb_index:
                scrub_direction = -1
        self._last_preview_thumb_index = lookup.thumb_index

        duration_seconds = self._effective_duration_seconds()
        self.preview.show_preview(lookup, duration_seconds, self.player)
        prefetch_settings = read_prefetch_settings()
        self.prefetch.schedule_neighbors(
            self.resolution,
            lookup,
            interval_ms,
            scrub_direction=scrub_direction,
            settings=prefetch_settings,
            debug=ADDON.getSettingBool("debug_logging"),
        )

    def _maybe_idle_prefetch(self, play_seconds: int) -> None:
        prefetch_settings = read_prefetch_settings()
        if (
            not prefetch_settings.enabled
            or not prefetch_settings.idle_tile
            or self.resolution is None
        ):
            return

        now = time.monotonic()
        if now - self._last_idle_prefetch_at < 3.0:
            return
        self._last_idle_prefetch_at = now

        interval_ms = _setting_int("interval_ms", 10000)
        lookup = lookup_thumbnail(self.resolution, play_seconds, interval_ms)
        if lookup is None:
            return

        self.prefetch.schedule_idle_tile(
            self.resolution,
            lookup,
            interval_ms,
            settings=prefetch_settings,
            debug=ADDON.getSettingBool("debug_logging"),
        )

    def on_playback_seek(self, time_ms: int) -> None:
        """Authoritative seek target from Kodi; survives SeekTime label flicker."""
        if not self.playback_ready or self.resolution is None:
            return
        target_second = max(int(time_ms / 1000), 0)
        self.committed_seek_second = target_second
        self.committed_seek_at = time.monotonic()
        _debug(f"Seek event -> {target_second}s")

        play_seconds = _player_time_seconds(self.player)
        user_seek = (
            xbmc.getCondVisibility(
                "Player.Seeking | !String.IsEmpty(Player.SeekNumeric)"
            )
            or self._seek_ui_visible()
            or abs(target_second - play_seconds) > 2
        )
        if not user_seek:
            return

        self._touch_seek_hold()
        sync_display_settings()
        self.update_preview(target_second, seeking=True)
        self.preview_active = True
        self.was_seeking = True
        self._set_preview_visible(True)

    def _seek_target_seconds(self, play_seconds: int) -> int:
        seek_seconds = _parse_time_label(xbmc.getInfoLabel("Player.SeekTime"))
        if seek_seconds > 0 and abs(seek_seconds - play_seconds) >= 1:
            return seek_seconds
        if seek_seconds > 0:
            return seek_seconds

        now = time.monotonic()
        if (
            self.committed_seek_second >= 0
            and now - self.committed_seek_at < 2.0
        ):
            return self.committed_seek_second

        if (
            self.was_seeking
            and self.last_preview_second >= 0
            and abs(self.last_preview_second - play_seconds) > 2
            and (
                self._seek_ui_visible()
                or xbmc.getCondVisibility(
                    "Player.Seeking | !String.IsEmpty(Player.SeekNumeric)"
                )
            )
        ):
            return self.last_preview_second

        return play_seconds

    def _dialog_seekbar_visible(self) -> bool:
        return xbmc.getCondVisibility(
            "Window.IsVisible(seekbar) | Window.IsActive(seekbar) | "
            "Window.IsVisible(DialogSeekBar.xml)"
        )

    def _video_osd_visible(self) -> bool:
        return active_profile().full_osd_visible()

    def _seek_ui_visible(self) -> bool:
        return self._dialog_seekbar_visible() or self._video_osd_visible()

    def _window_focus_id(self, window_id: int) -> int:
        try:
            return xbmcgui.Window(window_id).getFocusId()
        except RuntimeError:
            return 0

    def _seekbar_focused(self) -> bool:
        focus_id = active_profile().seekbar_focus_id
        if xbmc.getCondVisibility(f"Control.HasFocus({focus_id})"):
            return True
        if self._dialog_seekbar_visible():
            return self._window_focus_id(SEEKBAR_WINDOW_ID) == focus_id
        return False

    def _osd_play_controls_focused(self) -> bool:
        return active_profile().osd_play_controls_focused()

    def _set_preview_visible(self, visible: bool) -> None:
        if visible == self.preview_visible:
            return
        self.preview_visible = visible
        sync_display_settings()
        sync_trickplay_property(PROP_PREVIEW_VISIBLE, "true" if visible else "false")
        _debug(f"Preview visible -> {visible}")

    def _preview_should_show(self, scrubbing: bool) -> bool:
        if not self.preview_active or self.last_preview_second < 0:
            return False
        if not self._seek_ui_visible():
            return False
        if self._osd_play_controls_focused():
            return False
        if scrubbing or self._seek_hold_active():
            return True
        if self._preview_follows_playhead() and not xbmc.getCondVisibility(
            "Player.Paused"
        ):
            return True
        if self._seekbar_focused():
            return True
        # Full video OSD without seekbar focus: hide stale preview.
        return not self._video_osd_visible()

    def _is_scrubbing(self) -> tuple[bool, int]:
        if not self.playback_ready:
            return False, _player_time_seconds(self.player)

        play_seconds = _player_time_seconds(self.player)

        if xbmc.getCondVisibility("!String.IsEmpty(Player.SeekNumeric)"):
            return True, self._seek_target_seconds(play_seconds)

        if xbmc.getCondVisibility("Player.Seeking") and self._explicit_seek_active():
            return True, self._seek_target_seconds(play_seconds)

        if not xbmc.getCondVisibility("Player.Paused"):
            return False, play_seconds

        if not self._seek_ui_visible():
            return False, play_seconds

        seek_label = xbmc.getInfoLabel("Player.SeekTime")
        seek_seconds = _parse_time_label(seek_label) if seek_label else play_seconds

        # Paused skip while seek UI is open (SeekTime label ahead of playhead).
        if seek_label and abs(seek_seconds - play_seconds) >= 1:
            return True, seek_seconds

        # Paused frame-step / chapter step.
        if play_seconds != self.last_play_time:
            return True, play_seconds

        return False, play_seconds

    def poll_seek_state(self) -> None:
        self._log_skin_profile()
        self.preview.poll()

        if not self.player.isPlayingVideo():
            if self.preview_active or self.preview_visible or self.was_seeking:
                self._clear_preview_session()
            self.last_play_time = -1
            self.playback_ready = False
            return

        now = time.monotonic()
        if not self.playback_ready:
            if now - self.playback_started_at >= 3.0:
                self.playback_ready = True
                self.last_play_time = _player_time_seconds(self.player)
            return

        play_seconds = _player_time_seconds(self.player)
        if not xbmc.getCondVisibility("Player.Paused"):
            self.last_play_time = play_seconds

        dialog_seekbar = self._dialog_seekbar_visible()
        video_osd = self._video_osd_visible()
        seek_ui = dialog_seekbar or video_osd
        compact_seekbar = dialog_seekbar and not video_osd

        scrubbing, target_second = self._is_scrubbing()

        if (
            video_osd
            and self._had_compact_seekbar
            and not compact_seekbar
            and not scrubbing
            and self.preview_active
        ):
            self._clear_preview_session("compact seekbar -> full OSD")

        self._had_compact_seekbar = compact_seekbar

        if not seek_ui:
            if self.preview_active or self.last_preview_second >= 0 or self.preview_visible:
                self._clear_preview_session()
            return

        if scrubbing:
            self.preview_active = True
            self._touch_seek_hold()
            sync_display_settings()
            if self.last_preview_second >= 0:
                resync_preview_to_seekbar()
            self.update_preview(target_second, seeking=True)
            self.was_seeking = True
            self.last_play_time = play_seconds
            self._set_preview_visible(True)
            return

        if not self.preview_active:
            if self.last_preview_second >= 0 or self.preview_visible:
                self._clear_preview_session()
            return

        if self._preview_should_show(False):
            resync_preview_to_seekbar()
            if self._preview_follows_playhead() and not xbmc.getCondVisibility(
                "Player.Paused"
            ):
                self.update_preview(play_seconds, seeking=False)
            else:
                self._maybe_idle_prefetch(
                    self.last_preview_second
                    if self.last_preview_second >= 0
                    else play_seconds
                )
            self._set_preview_visible(True)
            return

        self._clear_preview_session()

    def run(self) -> None:
        _log(
            f"Service initialized (display=skin v{ADDON.getAddonInfo('version')})"
        )
        while not self.monitor.abortRequested():
            self.poll_seek_state()
            if self.monitor.waitForAbort(self.poll_ms / 1000.0):
                break
        self.reset_playback_state()
        _log("Service stopped")


class KodiPlayer(xbmc.Player):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.service: TrickplayService = kwargs["service"]
        self._is_playing_video = False

    def onAVStarted(self) -> None:
        if self.isPlayingVideo():
            self._is_playing_video = True
            self.service.on_video_started(self.getPlayingFile())

    def onPlayBackEnded(self) -> None:
        self._on_playback_stopped()

    def onPlayBackStopped(self) -> None:
        self._on_playback_stopped()

    def onPlayBackSeek(self, time_ms: int, seek_offset: int) -> None:
        self.service.on_playback_seek(time_ms)

    def _on_playback_stopped(self) -> None:
        self._is_playing_video = False
        self.service.reset_playback_state()


if __name__ == "__main__":
    TrickplayService().run()

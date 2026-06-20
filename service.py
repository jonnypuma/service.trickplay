"""Kodi background service that exposes Jellyfin trickplay previews while seeking."""

from __future__ import annotations

import sys
import threading
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
from generator_settings import read_runtime_settings, read_generator_settings
from generator_worker import GeneratorWorker
from library_update_batch import LibraryUpdateBatch
from thumb_cropper import get_cropped_thumb_path
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

POLL_MS_IDLE = 1000
POLL_MS_IDLE_GENERATOR = 500
PLAYBACK_SCRUB_GUARD_SEC = 3.0

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
    if read_runtime_settings().debug_logging:
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


class TrickplayMonitor(xbmc.Monitor):
    def __init__(self, library_batch: LibraryUpdateBatch) -> None:
        super().__init__()
        self._library_batch = library_batch

    def onNotification(self, sender: str, method: str, data: str) -> None:
        try:
            self._library_batch.on_notification(sender, method, data)
        except Exception as exc:
            _log(f"Library notification error: {exc}", xbmc.LOGERROR)


class TrickplayService:
    def __init__(self) -> None:
        self.player = KodiPlayer(service=self)
        self.generator = GeneratorWorker()
        self.library_batch = LibraryUpdateBatch(self.generator)
        self.monitor = TrickplayMonitor(self.library_batch)
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
        self.cached_duration = 0
        self.poll_ms = max(_setting_int("poll_ms", 100), 50)
        self._next_poll_ms = self.poll_ms
        self._last_poll_scrubbing = False
        self._last_poll_seek_ui = False
        self._active_skin_id = ""
        self._active_skin_override = ""
        self.seek_hold_until = 0.0
        self._had_compact_seekbar = False
        self._had_dialog_seekbar = False
        self._had_seek_ui = False
        self._pending_seek_ui_warm = False
        self._last_idle_prefetch_at = 0.0
        self._load_target = ""
        self._load_settled_for = ""
        self._load_thread: threading.Thread | None = None
        self._playback_block_reason = ""
        self._preview_tools_install_prompt_pending = False
        self._preview_tools_install_prompt_done = False
        self._log_skin_profile(force=True)

    def _preview_hold_seconds(self) -> int:
        return read_runtime_settings().preview_hold_seconds

    def _preview_follows_playhead(self) -> bool:
        """Hold time 0: keep preview visible and advance with playback."""
        return read_runtime_settings().preview_hold_seconds <= 0

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

    def _interval_ms(self) -> int:
        if self.resolution is not None:
            return self.resolution.interval_ms
        return read_runtime_settings().interval_ms

    def _effective_duration_seconds(self) -> int:
        duration = _player_duration_seconds(self.player)
        if duration > 0:
            self.cached_duration = duration
            return duration
        if self.cached_duration > 0:
            return self.cached_duration
        if self.resolution is not None and self.resolution.thumbnail_count > 0:
            return int(self.resolution.thumbnail_count * self._interval_ms() / 1000)
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
        self.cached_duration = 0
        self.seek_hold_until = 0.0
        self._had_compact_seekbar = False
        self._had_dialog_seekbar = False
        self._had_seek_ui = False
        self._pending_seek_ui_warm = False
        self._last_idle_prefetch_at = 0.0
        self._load_target = ""
        self._load_settled_for = ""
        self.prefetch.cancel()
        self._playback_block_reason = ""
        self.clear_preview_properties()

    def _refresh_resolution_if_needed(self) -> None:
        if self.resolution is None or self.resolution.is_usable:
            return

        duration_seconds = _player_duration_seconds(self.player)
        if duration_seconds > 0:
            self.cached_duration = duration_seconds
        runtime = read_runtime_settings()
        auto_tile_grid, manual_tile_grid = runtime.auto_tile_grid, runtime.manual_tile_grid
        self.resolution = enrich_resolution(
            self.resolution,
            duration_seconds,
            self._interval_ms(),
            auto_tile_grid=auto_tile_grid,
            manual_tile_grid=manual_tile_grid,
            debug=runtime.debug_logging,
        )
        if self.resolution.is_usable:
            _log(
                f"Trickplay metadata refreshed: {self.resolution.thumbnail_count} thumbs, "
                f"thumb size {self.resolution.thumb_width}x{self.resolution.thumb_height}"
            )

    def _scrub_guard_active(self) -> bool:
        return time.monotonic() - self.playback_started_at < PLAYBACK_SCRUB_GUARD_SEC

    def _preview_allowed(self) -> bool:
        return self.resolution is not None and self.resolution.is_usable

    def _playback_block_message(self) -> str:
        if self._load_in_progress():
            return "trickplay still loading"
        if self.playing_file and self._load_settled_for != self.playing_file:
            return "trickplay load has not finished"
        if self.resolution is None:
            return "no trickplay sidecar for this file"
        if not self.resolution.is_usable:
            return "trickplay metadata unusable (check kodi.log at playback start)"
        return ""

    def _log_playback_block_once(self) -> None:
        message = self._playback_block_message()
        if not message or message == self._playback_block_reason:
            return
        self._playback_block_reason = message
        _log(f"Preview unavailable during playback: {message}", xbmc.LOGINFO)

    def _current_playing_file(self) -> str:
        try:
            if not self.player.isPlayingVideo():
                return ""
            return self.player.getPlayingFile() or ""
        except RuntimeError:
            return ""

    def _load_in_progress(self) -> bool:
        return self._load_thread is not None and self._load_thread.is_alive()

    def _ensure_playback_loaded(self) -> None:
        playing_file = self._current_playing_file()
        if not playing_file:
            return
        if playing_file == self._load_settled_for:
            return
        if playing_file == self.playing_file and self.resolution is not None:
            return
        if self._load_in_progress() and playing_file == self._load_target:
            return
        self.on_video_started(playing_file)

    def _mark_load_settled(self, playing_file: str) -> None:
        if playing_file == self.playing_file:
            self._load_settled_for = playing_file

    def _load_trickplay_worker(self, playing_file: str) -> None:
        try:
            media_path = resolve_media_path(playing_file)
            if not media_path:
                _debug(f"No local trickplay path for {playing_file!r}")
                return

            duration_seconds = _player_duration_seconds(self.player)
            if duration_seconds > 0:
                self.cached_duration = duration_seconds
            runtime = read_runtime_settings()
            auto_tile_grid, manual_tile_grid = (
                runtime.auto_tile_grid,
                runtime.manual_tile_grid,
            )

            resolution = load_trickplay_for_file(
                playing_file,
                preferred_width=runtime.preferred_width,
                interval_ms=runtime.interval_ms,
                duration_seconds=duration_seconds,
                auto_tile_grid=auto_tile_grid,
                manual_tile_grid=manual_tile_grid,
                interval_preference=runtime.interval_preference,
                debug=runtime.debug_logging,
            )
            if resolution is None:
                _log(f"No trickplay data for {media_path}")
                return

            if playing_file != self.playing_file:
                return

            self.resolution = resolution
            if not self.resolution.is_usable:
                self._refresh_resolution_if_needed()

            if self.resolution is None or not self.resolution.is_usable:
                tile_count = len(self.resolution.tile_paths) if self.resolution else 0
                _log(
                    f"Trickplay folder found but metadata unusable for {media_path} "
                    f"(tiles={tile_count})",
                    xbmc.LOGWARNING,
                )
                return

            if playing_file != self.playing_file:
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

            from pillow_installer import pillow_is_available

            if not pillow_is_available():
                _log(
                    "Preview cropping needs Pillow; use Install preview tools in add-on settings",
                    xbmc.LOGWARNING,
                )
                self._preview_tools_install_prompt_pending = True

            play_seconds = _player_time_seconds(self.player)
            runtime = read_runtime_settings()
            warm_lookup = lookup_thumbnail(
                self.resolution, play_seconds, self._interval_ms()
            )
            prefetch_settings = read_prefetch_settings()
            if warm_lookup is not None:
                get_cropped_thumb_path(
                    warm_lookup.tile_path,
                    warm_lookup.col,
                    warm_lookup.row,
                    warm_lookup.thumb_width,
                    warm_lookup.thumb_height,
                    debug=runtime.debug_logging,
                )
                self.prefetch.schedule_playhead_warm(
                    self.resolution,
                    warm_lookup,
                    self._interval_ms(),
                    settings=prefetch_settings,
                    debug=runtime.debug_logging,
                )
            if playing_file == self.playing_file:
                self._pending_seek_ui_warm = True
        except Exception as exc:
            _log(f"Trickplay load failed for {playing_file!r}: {exc}", xbmc.LOGERROR)
        finally:
            self._mark_load_settled(playing_file)

    def on_video_started(self, playing_file: str) -> None:
        if not playing_file:
            return
        if playing_file == self._load_settled_for:
            return
        if playing_file == self.playing_file and self.resolution is not None:
            return
        if self._load_in_progress() and playing_file == self._load_target:
            return

        _log(f"Playback started: {playing_file}")
        self._log_skin_profile()
        self.preview.detach_overlay()
        self.generator.pause_for_playback()
        self.reset_playback_state()
        self.playing_file = playing_file
        self._load_target = playing_file
        self._playback_block_reason = ""
        self.playback_started_at = time.monotonic()

        self._load_thread = threading.Thread(
            target=self._load_trickplay_worker,
            args=(playing_file,),
            daemon=True,
            name="trickplay-load",
        )
        self._load_thread.start()

    def _publish_sprite_properties(self, lookup) -> None:
        sync_trickplay_property(PROP_TILE, lookup.tile_path)
        sync_trickplay_property(PROP_COL, str(lookup.col))
        sync_trickplay_property(PROP_ROW, str(lookup.row))
        sync_trickplay_property(PROP_THUMB_W, str(lookup.thumb_width))
        sync_trickplay_property(PROP_THUMB_H, str(lookup.thumb_height))

    def update_preview(self, target_second: int, seeking: bool) -> bool:
        if self.resolution is None:
            return False

        self._refresh_resolution_if_needed()
        if not self.resolution.is_usable:
            return False

        target_second = max(target_second, 0)
        if not seeking and target_second == self.last_preview_second:
            return self.preview_visible

        interval_ms = self._interval_ms()
        lookup = lookup_thumbnail(self.resolution, target_second, interval_ms)
        if lookup is None:
            _debug(f"No trickplay lookup for {target_second}s")
            return False

        if (
            seeking
            and target_second == self.last_preview_second
            and lookup.thumb_index == self._last_preview_thumb_index
        ):
            return self.preview_visible

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
        self.preview.show_preview(
            lookup, duration_seconds, self.player, eager=seeking
        )
        prefetch_settings = read_prefetch_settings()
        runtime = read_runtime_settings()
        if seeking and self.preview.fast_scrub_active:
            self.prefetch.cancel()
        elif prefetch_settings.enabled:
            self.prefetch.schedule_neighbors(
                self.resolution,
                lookup,
                interval_ms,
                scrub_direction=scrub_direction,
                settings=prefetch_settings,
                debug=runtime.debug_logging,
            )
        return True

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

        runtime = read_runtime_settings()
        lookup = lookup_thumbnail(self.resolution, play_seconds, self._interval_ms())
        if lookup is None:
            return

        self.prefetch.schedule_idle_tile(
            self.resolution,
            lookup,
            self._interval_ms(),
            settings=prefetch_settings,
            debug=runtime.debug_logging,
        )

    def _prepare_seek_ui_preview(self, play_seconds: int) -> None:
        """Sync-crop playhead and prefetch neighbors when seek OSD opens."""
        if not self._preview_allowed():
            return

        runtime = read_runtime_settings()
        prefetch_settings = read_prefetch_settings()
        interval_ms = self._interval_ms()
        lookup = lookup_thumbnail(self.resolution, play_seconds, interval_ms)
        if lookup is None:
            return

        get_cropped_thumb_path(
            lookup.tile_path,
            lookup.col,
            lookup.row,
            lookup.thumb_width,
            lookup.thumb_height,
            debug=runtime.debug_logging,
        )
        if prefetch_settings.enabled:
            self.prefetch.schedule_playhead_warm(
                self.resolution,
                lookup,
                interval_ms,
                settings=prefetch_settings,
                debug=runtime.debug_logging,
            )
            self.prefetch.schedule_neighbors(
                self.resolution,
                lookup,
                interval_ms,
                scrub_direction=0,
                settings=prefetch_settings,
                debug=runtime.debug_logging,
            )
        _debug(
            f"Seek UI warm at {play_seconds}s -> index {lookup.thumb_index}"
        )

    def on_playback_seek(self, time_ms: int) -> None:
        """Authoritative seek target from Kodi; survives SeekTime label flicker."""
        if not self._preview_allowed():
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
        if not self.update_preview(target_second, seeking=True):
            return
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
            try:
                from preview_settings import read_preview_adjustment_settings

                if not read_preview_adjustment_settings().show_during_play_controls:
                    return False
            except ImportError:  # pragma: no cover
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
        play_seconds = _player_time_seconds(self.player)

        if xbmc.getCondVisibility("!String.IsEmpty(Player.SeekNumeric)"):
            return True, self._seek_target_seconds(play_seconds)

        if xbmc.getCondVisibility("Player.Seeking") and self._explicit_seek_active():
            if not self._scrub_guard_active() or self._seek_ui_visible():
                return True, self._seek_target_seconds(play_seconds)

        if not xbmc.getCondVisibility("Player.Paused"):
            return False, play_seconds

        if not self._seek_ui_visible():
            return False, play_seconds

        if self._scrub_guard_active():
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

    def _maybe_prompt_preview_tools_install(self) -> None:
        if (
            self._preview_tools_install_prompt_done
            or not self._preview_tools_install_prompt_pending
        ):
            return
        if not self.player.isPlayingVideo() or not self._preview_allowed():
            return

        self._preview_tools_install_prompt_done = True
        self._preview_tools_install_prompt_pending = False

        try:
            from pillow_installer import should_offer_pillow_download

            if not should_offer_pillow_download():
                return
        except ImportError:
            return

        title = ADDON.getLocalizedString(32131)
        message = ADDON.getLocalizedString(32130)
        if xbmcgui.Dialog().yesno(
            title,
            message,
            yeslabel=ADDON.getLocalizedString(32105),
            nolabel=ADDON.getLocalizedString(32100),
        ):
            _log("First-playback Pillow install accepted; launching install_tools")
            xbmc.executebuiltin("RunScript(service.trickplay,install_tools,playback)")
        else:
            _log("First-playback Pillow install declined")

    def _adaptive_poll_ms(self) -> int:
        if not self.player.isPlayingVideo():
            generator = read_generator_settings()
            if generator.enabled and generator.while_idle:
                return POLL_MS_IDLE_GENERATOR
            return POLL_MS_IDLE
        return self.poll_ms

    def poll_seek_state(self) -> None:
        try:
            self._poll_seek_state()
        except Exception as exc:
            _log(f"Poll error: {exc}", xbmc.LOGERROR)
            self._next_poll_ms = self.poll_ms

    def _poll_seek_state(self) -> None:
        self._log_skin_profile()
        self.preview.poll()
        self._ensure_playback_loaded()

        if not self.player.isPlayingVideo():
            if self.preview_active or self.preview_visible or self.was_seeking:
                self._clear_preview_session()
            self.last_play_time = -1
            self.generator.resume_after_playback()
            self.library_batch.maybe_flush(True)
            self.generator.maybe_idle_tick(True)
            self._next_poll_ms = self._adaptive_poll_ms()
            return

        self.generator.pause_for_playback()

        if not self._preview_allowed():
            if self.player.isPlayingVideo() and self._seek_ui_visible():
                self._log_playback_block_once()
            self._next_poll_ms = self.poll_ms
            return

        self._maybe_prompt_preview_tools_install()

        play_seconds = _player_time_seconds(self.player)
        if not xbmc.getCondVisibility("Player.Paused"):
            self.last_play_time = play_seconds

        dialog_seekbar = self._dialog_seekbar_visible()
        video_osd = self._video_osd_visible()
        seek_ui = dialog_seekbar or video_osd
        compact_seekbar = dialog_seekbar and not video_osd

        scrubbing, target_second = self._is_scrubbing()
        self._last_poll_scrubbing = scrubbing
        seek_ui_rising = seek_ui and not self._had_seek_ui
        self._last_poll_seek_ui = seek_ui

        if seek_ui_rising or self._pending_seek_ui_warm:
            self._prepare_seek_ui_preview(play_seconds)
            self._pending_seek_ui_warm = False

        if (
            video_osd
            and self._had_compact_seekbar
            and not compact_seekbar
            and not scrubbing
            and self.preview_active
        ):
            self._clear_preview_session("compact seekbar -> full OSD")

        self._had_compact_seekbar = compact_seekbar

        if dialog_seekbar and not self._had_dialog_seekbar:
            if self.last_preview_second >= 0 or self.preview_visible:
                resync_preview_to_seekbar(force=True)
        if not dialog_seekbar:
            self._had_dialog_seekbar = False
        else:
            self._had_dialog_seekbar = True

        if not seek_ui:
            self._had_seek_ui = False
            if self.preview_active or self.last_preview_second >= 0 or self.preview_visible:
                self._clear_preview_session()
            self._next_poll_ms = self._adaptive_poll_ms()
            return

        self._had_seek_ui = True

        if scrubbing:
            self._touch_seek_hold()
            sync_display_settings()
            if self.last_preview_second >= 0:
                resync_preview_to_seekbar()
            if self.update_preview(target_second, seeking=True):
                self.preview_active = True
                self.was_seeking = True
                self.last_play_time = play_seconds
                self._set_preview_visible(True)
            elif self.preview_visible:
                self._set_preview_visible(False)
            self._next_poll_ms = self._adaptive_poll_ms()
            return

        if not self.preview_active:
            if self.last_preview_second >= 0 or self.preview_visible:
                self._clear_preview_session()
            self._next_poll_ms = self._adaptive_poll_ms()
            return

        if self._preview_should_show(False):
            resync_preview_to_seekbar()
            if self._preview_follows_playhead() and not xbmc.getCondVisibility(
                "Player.Paused"
            ):
                if self.update_preview(play_seconds, seeking=False):
                    self._set_preview_visible(True)
            else:
                self._maybe_idle_prefetch(
                    self.last_preview_second
                    if self.last_preview_second >= 0
                    else play_seconds
                )
                self._set_preview_visible(True)
            self._next_poll_ms = self._adaptive_poll_ms()
            return

        self._clear_preview_session()
        self._next_poll_ms = self._adaptive_poll_ms()

    def run(self) -> None:
        try:
            from pillow_installer import invalidate_pillow_cache
            from thumb_cropper import invalidate_playback_ffmpeg_cache

            invalidate_pillow_cache()
            invalidate_playback_ffmpeg_cache()
        except ImportError:
            pass
        try:
            from temp_cleanup import cleanup_orphaned_generator_temp

            cleanup_orphaned_generator_temp()
        except ImportError:
            pass
        _log(
            f"Service initialized (display=skin v{ADDON.getAddonInfo('version')})"
        )
        while not self.monitor.abortRequested():
            self.poll_seek_state()
            if self.monitor.waitForAbort(self._next_poll_ms / 1000.0):
                break
        self.reset_playback_state()
        self.generator.cancel()
        _log("Service stopped")


class KodiPlayer(xbmc.Player):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.service: TrickplayService = kwargs["service"]
        self._is_playing_video = False

    def _start_trickplay_for_current_file(self) -> None:
        if not self.isPlayingVideo():
            return
        try:
            playing_file = self.getPlayingFile()
        except RuntimeError:
            return
        if playing_file:
            self._is_playing_video = True
            self.service.on_video_started(playing_file)

    def onAVStarted(self) -> None:
        self._start_trickplay_for_current_file()

    def onPlayBackStarted(self) -> None:
        self._start_trickplay_for_current_file()

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

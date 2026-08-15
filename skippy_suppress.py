"""Skippy.Skipping hide/clear during intro/credits skips."""

from __future__ import annotations

import time

SKIPPY_SKIPPING_PROPERTY = "Skippy.Skipping"
SKIPPY_SKIPPING_COND = (
    f"!String.IsEmpty(Window(Home).Property({SKIPPY_SKIPPING_PROPERTY}))"
)
# Ignore follow-up OnSeek / playhead lag from the skip itself before treating a
# seek as user scrub that should clear Skippy.Skipping.
SKIPPY_SEEK_CLEAR_GRACE_SEC = 1.5
# Legacy Trickplay hide flag from 7.1.11–7.1.12; cleared so old skins unlock.
PROP_SUPPRESS_AFTER_SKIP = "Trickplay.SuppressAfterSkip"


class SkippySuppressMixin:
    """Hide the seek thumb while Skippy.Skipping is set; clear it on user intent.

    Host must provide ``_video_osd_visible`` and ``_seek_ui_visible``.
    """

    def _skippy_skipping_set(self) -> bool:
        import service as svc

        try:
            return bool(svc.xbmc.getCondVisibility(SKIPPY_SKIPPING_COND))
        except Exception:
            return False

    def _clear_skippy_skipping(self, reason: str = "") -> None:
        """Release Skippy's skin hide signal so seekbar/thumb can show again."""
        import service as svc

        try:
            if svc.HOME_WINDOW.getProperty(SKIPPY_SKIPPING_PROPERTY):
                svc.HOME_WINDOW.clearProperty(SKIPPY_SKIPPING_PROPERTY)
                svc._log(
                    f"Cleared Skippy.Skipping"
                    + (f" ({reason})" if reason else "")
                )
        except Exception:
            pass
        svc.clear_trickplay_property(PROP_SUPPRESS_AFTER_SKIP)
        self._skip_landing_second = -1
        self._skip_hiding_since = 0.0
        self._skippy_skipping_latched = False

    def _note_skip_landing(self, target_second: int) -> None:
        self._skip_landing_second = max(int(target_second), 0)
        self._skip_hiding_since = time.monotonic()
        self._skippy_skipping_latched = True

    def _user_releases_skippy_hide(
        self,
        *,
        scrubbing: bool = False,
        target_second: int | None = None,
        allow_seek_clear: bool = False,
    ) -> str | None:
        """Return clear reason when scrubbing/OSD should end Skippy.Skipping."""
        import service as svc

        del scrubbing
        if not self._skippy_skipping_set():
            return None
        if self._video_osd_visible():
            return "video OSD"
        if svc.xbmc.getCondVisibility("!String.IsEmpty(Player.SeekNumeric)"):
            return "seek numeric"
        if svc.xbmc.getCondVisibility("Player.Paused") and self._seek_ui_visible():
            return "pause scrub"
        # Poll must not clear on playhead lag vs landing — that fired immediately
        # after Skippy's own seek and unlocked the seekbar. Only on_playback_seek
        # may clear via a later seek target, and only after a short grace.
        if (
            allow_seek_clear
            and target_second is not None
            and self._skip_landing_second >= 0
            and self._skip_hiding_since > 0.0
            and time.monotonic() - self._skip_hiding_since >= SKIPPY_SEEK_CLEAR_GRACE_SEC
            and abs(int(target_second) - self._skip_landing_second) >= 1
        ):
            return "user seek"
        return None

    def _skippy_suppress_active(
        self,
        *,
        scrubbing: bool = False,
        target_second: int | None = None,
        allow_seek_clear: bool = False,
    ) -> bool:
        """Hide thumb while Skippy.Skipping is set; clear that property on user intent."""
        import service as svc

        skipping = self._skippy_skipping_set()
        if skipping and not self._skippy_skipping_latched:
            if self._skip_hiding_since <= 0.0:
                self._skip_hiding_since = time.monotonic()
            svc.clear_trickplay_property(PROP_SUPPRESS_AFTER_SKIP)
            svc._debug("Skippy segment skip (Skipping set)")
        self._skippy_skipping_latched = skipping

        reason = self._user_releases_skippy_hide(
            scrubbing=scrubbing,
            target_second=target_second,
            allow_seek_clear=allow_seek_clear,
        )
        if reason:
            self._clear_skippy_skipping(reason)
            return False
        return skipping

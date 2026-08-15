"""Seek-hold and explicit-seek helpers for the preview overlay."""

from __future__ import annotations

import time

from generator_settings import read_runtime_settings

SEEK_HOLD_INDEFINITE = float("inf")


class PreviewHoldMixin:
    """Keep the preview visible after scrubbing according to hold-time settings."""

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
        import service as svc

        if svc.xbmc.getCondVisibility("!String.IsEmpty(Player.SeekNumeric)"):
            return True
        if not svc.xbmc.getCondVisibility("Player.Seeking"):
            return False
        if self.committed_seek_at <= 0.0:
            return True
        return time.monotonic() - self.committed_seek_at < 2.0

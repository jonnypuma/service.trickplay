"""Addon settings for trickplay thumbnail prefetch and cache limits."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import xbmcaddon
except ImportError:  # pragma: no cover
    xbmcaddon = None  # type: ignore[assignment]

from settings_cache import get_cached

DEFAULT_RADIUS_SECONDS = 120
PLAYBACK_WARM_SECONDS = 50
MIN_RADIUS_SECONDS = 15
MAX_RADIUS_SECONDS = 300
PLAYBACK_INDEX_CAP = 12


def thumb_indices_for_seconds(
    seconds: int,
    interval_ms: int,
    *,
    cap: int,
) -> int:
    """Convert a time window to a thumb-index radius for the sidecar interval."""
    interval_sec = max(interval_ms / 1000.0, 0.001)
    indices = int(round(max(int(seconds), 1) / interval_sec))
    return max(1, min(indices, max(int(cap), 1)))


@dataclass(frozen=True)
class PrefetchSettings:
    enabled: bool = True
    on_start: bool = True
    during_playback: bool = True
    whole_tile: bool = True
    idle_tile: bool = True
    radius_seconds: int = DEFAULT_RADIUS_SECONDS
    max_queue: int = 48
    cache_max_mb: int = 500
    cache_jpeg_quality: int = 90

    @property
    def index_cap(self) -> int:
        return max(1, self.max_queue - 1)

    def radius_indices(self, interval_ms: int) -> int:
        return thumb_indices_for_seconds(
            self.radius_seconds, interval_ms, cap=self.index_cap
        )

    def playback_warm_indices(self, interval_ms: int) -> int:
        seconds = min(self.radius_seconds, PLAYBACK_WARM_SECONDS)
        cap = min(PLAYBACK_INDEX_CAP, self.index_cap)
        return thumb_indices_for_seconds(seconds, interval_ms, cap=cap)

    def radius_ahead(self, interval_ms: int) -> int:
        return self.radius_indices(interval_ms)

    def radius_behind(self, interval_ms: int) -> int:
        return max(2, self.radius_indices(interval_ms) // 2)

    def radius_symmetric(self, interval_ms: int) -> int:
        return self.radius_indices(interval_ms)


def _addon() -> xbmcaddon.Addon | None:
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon("service.trickplay")
    except RuntimeError:
        return None


def _setting_bool(setting_id: str, default: bool) -> bool:
    addon = _addon()
    if addon is None:
        return default
    try:
        return addon.getSettingBool(setting_id)
    except (RuntimeError, TypeError, ValueError):
        pass
    try:
        raw = addon.getSettingString(setting_id)
        if not raw:
            return default
        return raw.strip().lower() in ("true", "1", "yes", "on")
    except (RuntimeError, TypeError, ValueError):
        return default


def _setting_int(setting_id: str, default: int) -> int:
    addon = _addon()
    if addon is None:
        return default
    try:
        return int(addon.getSettingInt(setting_id))
    except (TypeError, ValueError, RuntimeError):
        pass
    try:
        raw = addon.getSettingString(setting_id)
        return int(raw)
    except (TypeError, ValueError, RuntimeError):
        return default


def _load_prefetch_settings() -> PrefetchSettings:
    quality = _setting_int("cache_jpeg_quality", 90)
    quality = max(50, min(quality, 95))
    seconds = _setting_int("prefetch_radius_seconds", DEFAULT_RADIUS_SECONDS)
    seconds = max(MIN_RADIUS_SECONDS, min(seconds, MAX_RADIUS_SECONDS))
    return PrefetchSettings(
        enabled=_setting_bool("prefetch_enabled", True),
        on_start=_setting_bool("prefetch_on_start", True),
        during_playback=_setting_bool("prefetch_during_playback", True),
        whole_tile=_setting_bool("prefetch_whole_tile", True),
        idle_tile=_setting_bool("prefetch_idle_tile", True),
        radius_seconds=seconds,
        max_queue=max(_setting_int("prefetch_max_queue", 48), 8),
        cache_max_mb=max(_setting_int("cache_max_mb", 500), 0),
        cache_jpeg_quality=quality,
    )


def read_prefetch_settings() -> PrefetchSettings:
    return get_cached("prefetch", _load_prefetch_settings)

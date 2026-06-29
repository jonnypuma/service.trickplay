"""Addon settings for trickplay thumbnail prefetch and cache limits."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import xbmcaddon
except ImportError:  # pragma: no cover
    xbmcaddon = None  # type: ignore[assignment]

from settings_cache import get_cached


@dataclass(frozen=True)
class PrefetchSettings:
    enabled: bool = True
    on_start: bool = True
    during_playback: bool = True
    whole_tile: bool = True
    idle_tile: bool = True
    radius: int = 5
    max_queue: int = 48
    cache_max_mb: int = 500

    @property
    def radius_ahead(self) -> int:
        return max(self.radius, 1)

    @property
    def radius_behind(self) -> int:
        return max(2, self.radius // 2)

    @property
    def radius_symmetric(self) -> int:
        return max(self.radius, 1)

    @property
    def playback_warm_radius(self) -> int:
        return max(min(self.radius, 5), 1)


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
    return PrefetchSettings(
        enabled=_setting_bool("prefetch_enabled", True),
        on_start=_setting_bool("prefetch_on_start", True),
        during_playback=_setting_bool("prefetch_during_playback", True),
        whole_tile=_setting_bool("prefetch_whole_tile", True),
        idle_tile=_setting_bool("prefetch_idle_tile", True),
        radius=max(_setting_int("prefetch_radius", 5), 1),
        max_queue=max(_setting_int("prefetch_max_queue", 48), 8),
        cache_max_mb=max(_setting_int("cache_max_mb", 500), 0),
    )


def read_prefetch_settings() -> PrefetchSettings:
    return get_cached("prefetch", _load_prefetch_settings)

"""Preview display adjustment settings (size, offset, visibility)."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import xbmcaddon
except ImportError:  # pragma: no cover
    xbmcaddon = None  # type: ignore[assignment]

from settings_cache import get_cached


@dataclass(frozen=True)
class PreviewAdjustmentSettings:
    scale_percent: int = 100
    offset_x: int = 0
    offset_y: int = 0
    show_during_play_controls: bool = True


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


def _load_preview_adjustment_settings() -> PreviewAdjustmentSettings:
    return PreviewAdjustmentSettings(
        scale_percent=max(min(_setting_int("preview_scale_percent", 100), 200), 50),
        offset_x=max(min(_setting_int("preview_offset_x", 0), 200), -200),
        offset_y=max(min(_setting_int("preview_offset_y", 0), 200), -200),
        show_during_play_controls=_setting_bool(
            "preview_show_during_play_controls", True
        ),
    )


def read_preview_adjustment_settings() -> PreviewAdjustmentSettings:
    return get_cached("preview_adjustment", _load_preview_adjustment_settings)

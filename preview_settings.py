"""Preview display adjustment settings (size, offset, visibility)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os

try:
    import xbmcaddon
except ImportError:  # pragma: no cover
    xbmcaddon = None  # type: ignore[assignment]

from settings_cache import get_cached
from skin_profiles import current_skin_id
import xbmcvfs


@dataclass(frozen=True)
class PreviewAdjustmentSettings:
    scale_percent: int = 100
    offset_x: int = 0
    offset_y: int = 0
    show_during_play_controls: bool = True


_OVERRIDE_PATH = "special://profile/addon_data/service.trickplay/skin-adjustments.json"


def _override_path() -> str:
    return xbmcvfs.translatePath(_OVERRIDE_PATH)


def _read_skin_overrides() -> dict[str, dict[str, int]]:
    try:
        with open(_override_path(), encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_skin_adjustment(
    skin_id: str,
    *,
    scale_percent: int,
    offset_x: int,
    offset_y: int,
) -> None:
    path = _override_path()
    data = _read_skin_overrides()
    data[str(skin_id or "unknown")] = {
        "scale_percent": max(min(int(scale_percent), 200), 50),
        "offset_x": max(min(int(offset_x), 500), -500),
        "offset_y": max(min(int(offset_y), 500), -500),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def clear_skin_adjustments_cache() -> None:
    from settings_cache import invalidate_settings_cache

    invalidate_settings_cache()


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
    base = PreviewAdjustmentSettings(
        scale_percent=max(min(_setting_int("preview_scale_percent", 100), 200), 50),
        offset_x=max(min(_setting_int("preview_offset_x", 0), 200), -200),
        offset_y=max(min(_setting_int("preview_offset_y", 0), 200), -200),
        show_during_play_controls=_setting_bool(
            "preview_show_during_play_controls", True
        ),
    )
    override = _read_skin_overrides().get(current_skin_id() or "")
    if not isinstance(override, dict):
        return base
    return PreviewAdjustmentSettings(
        scale_percent=max(min(int(override.get("scale_percent", base.scale_percent)), 200), 50),
        offset_x=max(min(int(override.get("offset_x", base.offset_x)), 500), -500),
        offset_y=max(min(int(override.get("offset_y", base.offset_y)), 500), -500),
        show_during_play_controls=base.show_during_play_controls,
    )


def read_preview_adjustment_settings() -> PreviewAdjustmentSettings:
    return get_cached("preview_adjustment", _load_preview_adjustment_settings)

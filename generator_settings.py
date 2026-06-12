"""Addon settings for the trickplay generator."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import xbmcaddon
except ImportError:  # pragma: no cover
    xbmcaddon = None  # type: ignore[assignment]

from generator_extract_modes import EXTRACT_MODE_FAST, normalize_extract_mode
from grid_settings import GRID_PRESET_AUTO, display_grid_uses_folder, resolve_grid_preset
from settings_cache import get_cached
from trickplay_resolver import parse_manual_tile_grid


@dataclass(frozen=True)
class RuntimeSettings:
    interval_ms: int = 10000
    preferred_width: int = 320
    debug_logging: bool = False
    preview_hold_seconds: int = 4
    auto_tile_grid: bool = True
    manual_tile_grid: str = "10x10"


@dataclass(frozen=True)
class GeneratorSettings:
    enabled: bool = False
    while_idle: bool = False
    on_library_update: bool = False
    on_library_update_while_idle: bool = True
    overwrite_existing: bool = False
    extract_mode: str = EXTRACT_MODE_FAST
    stop_on_failure: bool = False
    library_path: str = ""
    tile_width: int = 320
    interval_ms: int = 10000
    grid: str = "10x10"
    debug: bool = False


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


def _setting_string(setting_id: str, default: str) -> str:
    addon = _addon()
    if addon is None:
        return default
    try:
        value = addon.getSettingString(setting_id)
    except (TypeError, ValueError, RuntimeError):
        return default
    return value if value else default


def _legacy_display_grid_mode() -> str | None:
    """Map removed settings to display_tile_grid values; None if unavailable."""
    addon = _addon()
    if addon is None:
        return None
    try:
        if addon.getSettingString("display_tile_grid"):
            return None
    except (TypeError, ValueError, RuntimeError):
        pass

    auto = _setting_bool("auto_tile_calculation", True)
    if auto:
        return GRID_PRESET_AUTO

    preset = _setting_string("display_tile_grid_preset", "")
    if preset:
        return preset

    manual = _setting_string("manual_tile_grid", "")
    if manual and parse_manual_tile_grid(manual):
        parsed = parse_manual_tile_grid(manual)
        if parsed:
            return f"{parsed[0]}x{parsed[1]}"
    return "10x10"


def _load_display_grid_settings() -> tuple[bool, str]:
    """Return (use_folder_grid, manual_grid_string)."""
    mode = _setting_string("display_tile_grid", "")
    if not mode:
        legacy = _legacy_display_grid_mode()
        mode = legacy if legacy else GRID_PRESET_AUTO

    custom = _setting_string("display_tile_grid_custom", "10x10")
    if display_grid_uses_folder(mode):
        return True, "10x10"
    return False, resolve_grid_preset(mode, custom, "10x10")


def read_display_grid_settings() -> tuple[bool, str]:
    return get_cached("display_grid", _load_display_grid_settings)


def _load_runtime_settings() -> RuntimeSettings:
    auto_tile_grid, manual_tile_grid = _load_display_grid_settings()
    return RuntimeSettings(
        interval_ms=max(_setting_int("interval_ms", 10000), 1000),
        preferred_width=max(_setting_int("preferred_width", 320), 120),
        debug_logging=_setting_bool("debug_logging", False),
        preview_hold_seconds=max(_setting_int("preview_hold_seconds", 4), 0),
        auto_tile_grid=auto_tile_grid,
        manual_tile_grid=manual_tile_grid,
    )


def read_runtime_settings() -> RuntimeSettings:
    return get_cached("runtime", _load_runtime_settings)


def _read_overwrite_existing() -> bool:
    return _setting_bool("generator_overwrite_existing", False)


def _read_extract_mode() -> str:
    mode = _setting_string("generator_extract_mode", "")
    if mode.strip().lower() in ("accurate", "fast", "experimental"):
        return mode.strip().lower()
    legacy_fast = _setting_bool("generator_fast_extract", True)
    return normalize_extract_mode("", legacy_fast=legacy_fast)


def _load_generator_settings() -> GeneratorSettings:
    preset = _setting_string("generator_tile_grid_preset", "10x10")
    custom = _setting_string("generator_tile_grid_custom", "10x10")
    runtime = _load_runtime_settings()
    return GeneratorSettings(
        enabled=_setting_bool("generator_enabled", False),
        while_idle=_setting_bool("generator_while_idle", False),
        on_library_update=_setting_bool("generator_on_library_update", False),
        on_library_update_while_idle=_setting_bool(
            "generator_on_library_update_while_idle", True
        ),
        overwrite_existing=_read_overwrite_existing(),
        extract_mode=_read_extract_mode(),
        stop_on_failure=_setting_bool("generator_stop_on_failure", False),
        library_path=_setting_string("generator_library_path", "").strip(),
        tile_width=runtime.preferred_width,
        interval_ms=max(_setting_int("generator_interval_ms", 10000), 1000),
        grid=resolve_grid_preset(preset, custom, "10x10"),
        debug=runtime.debug_logging,
    )


def read_generator_settings() -> GeneratorSettings:
    return get_cached("generator", _load_generator_settings)


def save_generator_library_path(path: str) -> None:
    """Persist library folder immediately (e.g. after batch browse dialog)."""
    addon = _addon()
    if addon is None:
        return
    cleaned = path.strip()
    try:
        addon.setSettingString("generator_library_path", cleaned)
    except (RuntimeError, TypeError, ValueError):
        return
    from settings_cache import invalidate_settings_cache

    invalidate_settings_cache()

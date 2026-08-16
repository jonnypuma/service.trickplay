"""Write a redacted, support-friendly Trickplay diagnostic report."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import xbmcaddon
import xbmcvfs

from addon_health import collect_addon_health, format_health_report
from generator_worker import GeneratorState
from thumb_cropper import preview_cache_stats

REPORT_PATH = "special://profile/addon_data/service.trickplay/diagnostic-report.txt"


def _local_report_path() -> str:
    return xbmcvfs.translatePath(REPORT_PATH)


def write_diagnostic_report() -> str:
    """Write diagnostics without passwords, credentials, or full media paths."""
    try:
        addon_version = xbmcaddon.Addon("service.trickplay").getAddonInfo("version")
    except (AttributeError, RuntimeError):
        addon_version = "unknown"
    health = collect_addon_health()
    try:
        from generator_settings import read_generator_settings

        settings = read_generator_settings()
        generator_summary = {
            "enabled": bool(settings.enabled),
            "while_idle": bool(settings.while_idle),
            "extract_mode": str(settings.extract_mode),
            "tile_width": int(settings.tile_width),
            "grid": str(settings.grid),
            "interval_ms": int(settings.interval_ms),
        }
    except (AttributeError, RuntimeError, TypeError, ValueError):
        generator_summary = {}

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "addon_version": addon_version,
        "health": format_health_report(health),
        "generator": generator_summary,
        "cache": preview_cache_stats(),
        "worker_states": [state.value for state in GeneratorState],
        "privacy": "Media paths, credentials, and network URLs are intentionally omitted.",
    }
    path = _local_report_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path

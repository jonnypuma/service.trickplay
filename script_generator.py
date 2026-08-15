"""RunScript entry: dispatch settings actions to batch/skin/tools/status modules."""

from __future__ import annotations

import sys

import xbmc
import xbmcaddon

_ADDON = xbmcaddon.Addon("service.trickplay")
_ADDON_PATH = _ADDON.getAddonInfo("path")
if _ADDON_PATH and _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

from script_batch import run_batch_dialog  # noqa: E402
from script_skin import (  # noqa: E402
    _resolve_install_skin_force,
    _resolve_install_skin_scope,
    _resolve_restore_skin_scope,
    run_install_skin_dialog,
    run_restore_skin_dialog,
)
from script_status import (  # noqa: E402
    run_addon_status_dialog,
    run_clear_preview_cache_dialog,
    run_generator_diagnostics_dialog,
    run_validation_repair_dialog,
)
from script_tools import (  # noqa: E402
    run_install_generator_tools_dialog,
    run_install_pillow_dialog,
    run_install_tools_dialog,
)
from skin_snippet_installer import InstallScope  # noqa: E402


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.generator.batch] {message}", level)


def _resolve_mode(argv: list[str]) -> str:
    """Return script mode from RunScript argv (addon id + optional args)."""
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("batch", "run_batch"):
            return "batch"
        if normalized in ("install_tools", "install"):
            return "install_tools"
        if normalized in ("install_skin", "install_skin_snippet"):
            return "install_skin"
        if normalized in (
            "install_skin_current",
            "install_skin_all",
            "install_skin_snippet_current",
            "install_skin_snippet_all",
            "install_skin_force",
            "force_install_skin",
        ):
            return "install_skin"
        if normalized in ("addon_status", "show_status", "status"):
            return "addon_status"
        if normalized in ("restore_skin", "restore_skin_snippet"):
            return "restore_skin"
        if normalized in (
            "restore_skin_current",
            "restore_skin_all",
            "restore_skin_snippet_current",
            "restore_skin_snippet_all",
        ):
            return "restore_skin"
        if normalized in ("install_pillow",):
            return "install_pillow"
        if normalized in ("install_generator_tools", "install_generator"):
            return "install_generator_tools"
        if normalized in ("clear_preview_cache", "clear_cache", "clear_thumb_cache"):
            return "clear_preview_cache"
        if normalized in ("validate_repair", "validation_repair"):
            return "validate_repair"
        if normalized in ("generator_diagnostics", "diagnostics"):
            return "generator_diagnostics"
        if normalized.endswith(".py"):
            continue
        if normalized:
            _log(f"Unknown script argument {arg!r}; defaulting to batch", xbmc.LOGWARNING)
            break
    return "batch"


def _from_playback_prompt(argv: list[str]) -> bool:
    for arg in argv[1:]:
        normalized = (arg or "").strip().lower()
        if normalized in ("playback", "from_playback"):
            return True
    return False


if __name__ == "__main__":
    _log(f"script_generator invoked argv={sys.argv!r}")
    mode = _resolve_mode(sys.argv)
    _log(f"Resolved mode={mode!r}")
    if mode == "batch":
        run_batch_dialog()
    elif mode == "install_tools":
        run_install_tools_dialog(from_playback_prompt=_from_playback_prompt(sys.argv))
    elif mode == "install_skin":
        scope = _resolve_install_skin_scope(sys.argv) or InstallScope.CURRENT
        force = _resolve_install_skin_force(sys.argv)
        run_install_skin_dialog(scope, force=force)
    elif mode == "addon_status":
        run_addon_status_dialog()
    elif mode == "restore_skin":
        scope = _resolve_restore_skin_scope(sys.argv) or InstallScope.CURRENT
        run_restore_skin_dialog(scope)
    elif mode == "install_pillow":
        run_install_pillow_dialog()
    elif mode == "install_generator_tools":
        run_install_generator_tools_dialog()
    elif mode == "clear_preview_cache":
        run_clear_preview_cache_dialog()
    elif mode == "validate_repair":
        run_validation_repair_dialog()
    elif mode == "generator_diagnostics":
        run_generator_diagnostics_dialog()
    else:
        _log(f"Unsupported mode {mode!r}; no action taken", xbmc.LOGERROR)

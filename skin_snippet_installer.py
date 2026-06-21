"""Install trickplay DialogSeekBar snippets into installed Kodi skins."""

from __future__ import annotations

import copy
import json
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum

import xbmc
import xbmcaddon
import xbmcvfs

from skin_profiles import current_skin_id, normalize_skin_id

SEEKBAR_FILENAME = "DialogSeekBar.xml"
BACKUP_SUFFIX = ".bak"
OVERLAY_CONTROL_ID = "94090"
MAX_WALK_DEPTH = 4
SNIPPET_DIR = "resources/skin-snippet"

# Longest marker first (substring match against normalized skin id).
_SNIPPET_REGISTRY: tuple[tuple[str, str, str], ...] = (
    ("arctic.fuse.3", "DialogSeekBar-skin.arctic.fuse.3.xml", "replace"),
    ("arctic.fuse", "DialogSeekBar-skin.arctic.fuse.3.xml", "replace"),
    ("estuary.modv2", "DialogSeekBar-skin.estuary.modv2.xml", "replace"),
    ("estuary.mod", "DialogSeekBar-skin.estuary.modv2.xml", "replace"),
    ("aeon.nox.silvo", "DialogSeekBar-skin.aeon.nox.silvo.xml", "merge"),
    ("aeon.nox", "DialogSeekBar-skin.aeon.nox.silvo.xml", "merge"),
    ("arctic.zephyr", "DialogSeekBar-skin.arctic.zephyr.xml", "merge"),
    ("arctic.horizon", "DialogSeekBar-skin.arctic.horizon.xml", "merge"),
    ("estuary", "DialogSeekBar-skin.estuary.xml", "merge"),
)
_DEFAULT_SNIPPET = ("DialogSeekBar-universal-dynamic.xml", "merge")


class InstallScope(str, Enum):
    CURRENT = "current"
    ALL = "all"


class InstallMode(str, Enum):
    MERGE = "merge"
    REPLACE = "replace"


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.skin] {message}", level)


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def snippet_for_skin_id(skin_id: str) -> tuple[str, InstallMode]:
    normalized = normalize_skin_id(skin_id)
    for marker, filename, mode in _SNIPPET_REGISTRY:
        if marker in normalized:
            return filename, InstallMode(mode)
    filename, mode = _DEFAULT_SNIPPET
    return filename, InstallMode(mode)


def _jsonrpc_addons_get_skins() -> list[str]:
    for addon_type in ("kodi.python.skin", "xbmc.python.skin"):
        command = {
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": {"type": addon_type, "enabled": False},
            "id": 1,
        }
        try:
            import xbmc

            response = json.loads(xbmc.executeJSONRPC(json.dumps(command)))
        except (RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        addons = response.get("result", {}).get("addons") or []
        if addons:
            return [normalize_skin_id(str(item.get("addonid", ""))) for item in addons if item]
    return []


def list_installed_skin_ids() -> list[str]:
    ids = [sid for sid in _jsonrpc_addons_get_skins() if sid]
    if ids:
        return sorted(set(ids))
    active = current_skin_id()
    return [active] if active else []


def _skin_addon_path(skin_id: str) -> str | None:
    try:
        path = xbmcaddon.Addon(skin_id).getAddonInfo("path")
    except RuntimeError:
        return None
    local = _local_path(path) if path else ""
    return local if local and os.path.isdir(local) else None


def _skin_display_name(skin_id: str) -> str:
    try:
        return xbmcaddon.Addon(skin_id).getAddonInfo("name") or skin_id
    except RuntimeError:
        return skin_id


def find_dialog_seekbar_paths(skin_root: str) -> list[str]:
    local_root = _local_path(skin_root)
    if not local_root or not os.path.isdir(local_root):
        return []

    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(local_root):
        rel = os.path.relpath(dirpath, local_root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= MAX_WALK_DEPTH:
            dirnames.clear()
            continue
        if SEEKBAR_FILENAME in filenames:
            found.append(os.path.join(dirpath, SEEKBAR_FILENAME))
    return sorted(found)


@dataclass
class PathInstallPlan:
    seekbar_path: str
    snippet_file: str
    mode: InstallMode


@dataclass
class SkinInstallPlan:
    skin_id: str
    skin_name: str
    paths: list[PathInstallPlan] = field(default_factory=list)
    error: str | None = None


@dataclass
class InstallOutcome:
    skin_id: str
    skin_name: str
    seekbar_path: str
    success: bool
    message: str


def _snippet_root(addon_path: str) -> str:
    return os.path.join(addon_path, SNIPPET_DIR)


def build_install_plan(scope: InstallScope, addon_path: str) -> list[SkinInstallPlan]:
    if scope == InstallScope.CURRENT:
        skin_ids = [current_skin_id()]
        skin_ids = [sid for sid in skin_ids if sid]
    else:
        skin_ids = list_installed_skin_ids()

    plans: list[SkinInstallPlan] = []
    for skin_id in skin_ids:
        name = _skin_display_name(skin_id)
        root = _skin_addon_path(skin_id)
        if not root:
            plans.append(
                SkinInstallPlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="skin_addon_path_unavailable",
                )
            )
            continue

        seekbar_paths = find_dialog_seekbar_paths(root)
        if not seekbar_paths:
            plans.append(
                SkinInstallPlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="dialog_seekbar_not_found",
                )
            )
            continue

        snippet_file, mode = snippet_for_skin_id(skin_id)
        snippet_path = os.path.join(_snippet_root(addon_path), snippet_file)
        if not os.path.isfile(snippet_path):
            plans.append(
                SkinInstallPlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="snippet_file_missing",
                )
            )
            continue

        path_plans = [
            PathInstallPlan(
                seekbar_path=path,
                snippet_file=snippet_file,
                mode=mode,
            )
            for path in seekbar_paths
        ]
        plans.append(
            SkinInstallPlan(
                skin_id=skin_id,
                skin_name=name,
                paths=path_plans,
            )
        )
    return plans


def _backup_seekbar(seekbar_path: str) -> tuple[bool, str]:
    bak_path = seekbar_path + BACKUP_SUFFIX
    if os.path.isfile(bak_path):
        return True, "backup_exists"
    try:
        shutil.copy2(seekbar_path, bak_path)
    except OSError as exc:
        return False, str(exc)
    return True, "backup_created"


def _find_controls_element(window_root: ET.Element) -> ET.Element | None:
    controls = window_root.find("controls")
    if controls is not None:
        return controls
    for child in window_root:
        if child.tag == "controls":
            return child
    return None


def _find_control_by_id(root: ET.Element, control_id: str) -> ET.Element | None:
    for elem in root.iter("control"):
        if elem.get("id") == control_id:
            return elem
    return None


def _extract_overlay_from_snippet(snippet_path: str) -> ET.Element:
    tree = ET.parse(snippet_path)
    overlay = _find_control_by_id(tree.getroot(), OVERLAY_CONTROL_ID)
    if overlay is None:
        raise ValueError(f"snippet missing control id={OVERLAY_CONTROL_ID}")
    return copy.deepcopy(overlay)


def _merge_overlay(seekbar_path: str, snippet_path: str) -> None:
    tree = ET.parse(seekbar_path)
    window_root = tree.getroot()
    controls = _find_controls_element(window_root)
    if controls is None:
        raise ValueError("DialogSeekBar.xml has no <controls> element")

    existing = _find_control_by_id(window_root, OVERLAY_CONTROL_ID)
    if existing is not None:
        for parent in window_root.iter():
            for child in list(parent):
                if child is existing:
                    parent.remove(child)
                    break
            else:
                continue
            break

    overlay = _extract_overlay_from_snippet(snippet_path)
    controls.append(overlay)
    tree.write(seekbar_path, encoding="utf-8", xml_declaration=True)


def _replace_seekbar(seekbar_path: str, snippet_path: str) -> None:
    shutil.copy2(snippet_path, seekbar_path)


def _install_one_path(
    seekbar_path: str,
    snippet_path: str,
    mode: InstallMode,
) -> tuple[bool, str]:
    local = _local_path(seekbar_path)
    if not local or not os.path.isfile(local):
        return False, "dialog_seekbar_not_found"

    if not os.access(local, os.W_OK):
        return False, "not_writable"

    ok, backup_detail = _backup_seekbar(local)
    if not ok:
        return False, f"backup_failed:{backup_detail}"

    try:
        if mode == InstallMode.REPLACE:
            _replace_seekbar(local, snippet_path)
        else:
            _merge_overlay(local, snippet_path)
    except (OSError, ValueError, ET.ParseError) as exc:
        return False, str(exc)

    if backup_detail == "backup_exists":
        return True, "ok_backup_kept"
    return True, "ok"


def execute_install_plan(
    plans: list[SkinInstallPlan],
    addon_path: str,
) -> list[InstallOutcome]:
    snippet_root = _snippet_root(addon_path)
    outcomes: list[InstallOutcome] = []
    modified_active_skin = False
    active = current_skin_id()

    for plan in plans:
        if plan.error or not plan.paths:
            outcomes.append(
                InstallOutcome(
                    skin_id=plan.skin_id,
                    skin_name=plan.skin_name,
                    seekbar_path="",
                    success=False,
                    message=plan.error or "dialog_seekbar_not_found",
                )
            )
            continue

        for path_plan in plan.paths:
            snippet_path = os.path.join(snippet_root, path_plan.snippet_file)
            ok, detail = _install_one_path(
                path_plan.seekbar_path,
                snippet_path,
                path_plan.mode,
            )
            outcomes.append(
                InstallOutcome(
                    skin_id=plan.skin_id,
                    skin_name=plan.skin_name,
                    seekbar_path=path_plan.seekbar_path,
                    success=ok,
                    message=detail,
                )
            )
            if ok and normalize_skin_id(plan.skin_id) == active:
                modified_active_skin = True

    if modified_active_skin:
        _log("Reloading skin after DialogSeekBar snippet install")
        xbmc.executebuiltin("ReloadSkin()")

    return outcomes


def plan_has_installable_targets(plans: list[SkinInstallPlan]) -> bool:
    return any(plan.paths for plan in plans)


def format_plan_summary(plans: list[SkinInstallPlan]) -> str:
    lines: list[str] = []
    for plan in plans:
        if plan.error:
            lines.append(f"• {plan.skin_name} ({plan.skin_id}): [{plan.error}]")
            continue
        for path_plan in plan.paths:
            rel_hint = os.path.basename(os.path.dirname(path_plan.seekbar_path))
            lines.append(
                f"• {plan.skin_name} ({plan.skin_id}) → "
                f".../{rel_hint}/{SEEKBAR_FILENAME} [{path_plan.mode.value}]"
            )
    return "\n".join(lines)


def summarize_outcomes(outcomes: list[InstallOutcome]) -> tuple[int, int, int]:
    ok = sum(1 for item in outcomes if item.success)
    fail = sum(1 for item in outcomes if not item.success)
    skins = len({item.skin_id for item in outcomes})
    return ok, fail, skins

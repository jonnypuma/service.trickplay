"""Install or restore trickplay skin snippets in installed Kodi skins."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import xbmc
import xbmcaddon
import xbmcvfs

from skin_profiles import (
    UNIVERSAL_SNIPPET_FILENAME,
    current_skin_id,
    normalize_skin_id,
    snippet_spec_for_skin_id,
)

SEEKBAR_FILENAME = "DialogSeekBar.xml"
VIDEO_FULLSCREEN_FILENAME = "VideoFullScreen.xml"
BACKUP_SUFFIX = ".bak"
OVERLAY_CONTROL_ID = "94090"
MAX_WALK_DEPTH = 4
SNIPPET_DIR = "resources/skin-snippet"
TRICKPLAY_MARKER = "Trickplay.Preview"
HOME_PROPERTY_MARKER = "Window(Home).Property(Trickplay"
SLOT_SLIDE_MARKER = 'id="94100"'
VIDEO_OSD_SLIDE_MARKER = (
    'Window.IsVisible(videoosd) + !Window.IsVisible(VideoOSDBookmarks.xml)'
)
AH2_VIDEO_OSD_SLIDE_MARKER = (
    "Window.IsVisible(videoosd) | Window.IsVisible(musicosd)"
)
NOX_OSD_SLIDE_MARKER = (
    "Window.IsActive(videoosd) + !Skin.HasSetting(VideoOSDOnTop)"
)
HOME_PROPERTY_SNIPPETS = frozenset(
    {
        "DialogSeekBar-skin.aeon.nox.silvo.xml",
        "DialogSeekBar-skin.bingie.xml",
        "DialogSeekBar-skin.arctic.horizon.xml",
        "DialogSeekBar-skin.arctic.horizon.2.xml",
        "DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml",
        "DialogSeekBar-skin.arctic.zephyr.xml",
        "DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml",
        "DialogSeekBar-skin.arctic.zephyr.rounded.xml",
        "VideoFullScreen-skin.bello.xml",
    }
)
REPLACE_SNIPPETS = frozenset(
    {
        "DialogSeekBar-skin.estuary.modv2.xml",
        "DialogSeekBar-skin.arctic.fuse.2.xml",
        "DialogSeekBar-skin.arctic.fuse.3.xml",
    }
)
OSD_SLIDE_MARKERS = {
    "DialogSeekBar-skin.aeon.nox.silvo.xml": NOX_OSD_SLIDE_MARKER,
    "DialogSeekBar-skin.arctic.zephyr.rounded.xml": VIDEO_OSD_SLIDE_MARKER,
    "DialogSeekBar-skin.arctic.horizon.xml": AH2_VIDEO_OSD_SLIDE_MARKER,
    "DialogSeekBar-skin.arctic.horizon.2.xml": AH2_VIDEO_OSD_SLIDE_MARKER,
    "DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml": AH2_VIDEO_OSD_SLIDE_MARKER,
}
LEGACY_PROPERTY_MARKER = "Window.Property(Trickplay.PreviewVisible)"
LEGACY_DYNAMIC_PREVIEW_MARKER = "$INFO[Window.Property(Trickplay.PreviewLeft)]"
OVERLAY_REVISION = 4
OVERLAY_REVISION_MARKER = f"trickplay-overlay-rev:{OVERLAY_REVISION}"
SKIPPY_SEEKBAR_VISIBLE_MARKER = "Window(Home).Property(Skippy.Skipping)"
SKIPPY_SEEKBAR_VISIBLE_TAG = (
    "<visible>String.IsEmpty(Window(Home).Property(Skippy.Skipping))</visible>"
)
_CONTROLS_OPEN_RE = re.compile(r"^([ \t]*)<controls\b", re.MULTILINE)
BINGIE_PREVIEW_TOP_MARKER = "<top>717</top>"
BELLO_PREVIEW_TOP_MARKER = "<top>560</top>"
BELLO_CENTER_SEEK_MARKER = "osd/osd_controls_bg.png"
BELLO_SIMPLE_SEEK_MARKER = '<include content="SeekBarSimple">'
Z2_RESURRECTION_PREVIEW_TOP_MARKER = "<top>740</top>"
_CONTROL_OPEN_RE = re.compile(
    r"<control\b[^>]*\bid=[\"']" + OVERLAY_CONTROL_ID + r"[\"']",
    re.IGNORECASE,
)
_GROUP_OPEN_RE = re.compile(
    r"<control\b[^>]*\btype=[\"']group[\"']",
    re.IGNORECASE,
)


class InstallScope(str, Enum):
    CURRENT = "current"
    ALL = "all"


class InstallMode(str, Enum):
    MERGE = "merge"
    REPLACE = "replace"


SKIN_RELOAD_ALARM = "trickplay-skin-reload"
SKIN_RELOAD_DELAY = "00:02"


def _log(message: str, level=xbmc.LOGINFO) -> None:
    xbmc.log(f"[service.trickplay.skin] {message}", level)


def seekbar_has_host_controls(text: str) -> bool:
    """True when DialogSeekBar has seek/OSD content besides the trickplay overlay.

    Many skins (e.g. Arctic Zephyr Rounded) put the seek bar in an ``<include>``
    with no top-level ``<control>`` besides our overlay — that is still a real host.
    """
    without_overlay = remove_control_block(text, OVERLAY_CONTROL_ID)
    if re.search(r"<control\b", without_overlay, re.IGNORECASE):
        return True
    return bool(re.search(r"<include\b", without_overlay, re.IGNORECASE))


def schedule_skin_reload() -> None:
    """Defer ReloadSkin to avoid Kodi crashes on Windows when called from a Python script."""
    xbmc.executebuiltin(f"CancelAlarm({SKIN_RELOAD_ALARM},silent)")
    xbmc.executebuiltin(
        f"AlarmClock({SKIN_RELOAD_ALARM},ReloadSkin(),{SKIN_RELOAD_DELAY},silent)"
    )
    _log("Scheduled deferred skin reload")


def _debug_log(message: str) -> None:
    try:
        from generator_settings import read_runtime_settings

        if read_runtime_settings().debug_logging:
            _log(message)
    except ImportError:
        pass


def _local_path(path: str) -> str:
    if path.startswith(("special://", "vfs://", "zip://")):
        return xbmcvfs.translatePath(path)
    return path


def _jsonrpc_addons_get_skins() -> list[str]:
    """List installed skin addon ids via JSON-RPC (xbmc.gui.skin)."""
    # enabled=False returns only *disabled* skins; use "all" (or omit).
    # Type must be xbmc.gui.skin — not xbmc.python.skin.
    attempts = (
        {"type": "xbmc.gui.skin", "enabled": "all", "installed": True},
        {"type": "xbmc.gui.skin", "installed": True},
        {"type": "xbmc.gui.skin"},
    )
    for params in attempts:
        command = {
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": params,
            "id": 1,
        }
        try:
            response = json.loads(xbmc.executeJSONRPC(json.dumps(command)))
        except (RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if response.get("error"):
            _debug_log(f"Addons.GetAddons error for {params}: {response.get('error')}")
            continue
        addons = response.get("result", {}).get("addons") or []
        if addons:
            return [
                normalize_skin_id(str(item.get("addonid", "")))
                for item in addons
                if item and item.get("addonid")
            ]
    return []


def _addon_dir_roots() -> list[str]:
    """Local filesystem roots that may contain installed add-ons."""
    roots: list[str] = []
    for special in ("special://home/addons", "special://xbmc/addons"):
        try:
            translated = xbmcvfs.translatePath(special)
        except Exception:
            continue
        if translated and os.path.isdir(translated) and translated not in roots:
            roots.append(translated)
    return roots


def _skin_ids_from_addons_folders() -> list[str]:
    """Filesystem fallback: scan Kodi addon dirs for xbmc.gui.skin packages."""
    found: list[str] = []
    for root in _addon_dir_roots():
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if not name.startswith("skin."):
                continue
            addon_xml = os.path.join(root, name, "addon.xml")
            if not os.path.isfile(addon_xml):
                continue
            try:
                text = _read_text(addon_xml)
            except OSError:
                continue
            if "xbmc.gui.skin" not in text:
                continue
            found.append(normalize_skin_id(name))
    return sorted(set(found))


_skin_list_rpc_warned = False


def list_installed_skin_ids() -> list[str]:
    """Installed skin ids from JSON-RPC, merged with a filesystem scan.

    JSON-RPC alone misses skins that are broken, disabled, or only dropped into
    the addons folder (e.g. not shown under Settings → Interface → Skin).
    """
    global _skin_list_rpc_warned
    rpc_ids = {sid for sid in _jsonrpc_addons_get_skins() if sid}
    fs_ids = {sid for sid in _skin_ids_from_addons_folders() if sid}
    ids = rpc_ids | fs_ids
    if not rpc_ids and fs_ids and not _skin_list_rpc_warned:
        _skin_list_rpc_warned = True
        _log(
            "Addons.GetAddons skin list empty; using filesystem scan "
            f"({len(fs_ids)} skin(s))",
            xbmc.LOGWARNING,
        )
    elif fs_ids - rpc_ids:
        _debug_log(
            "Filesystem skin scan added ids missing from JSON-RPC: "
            + ", ".join(sorted(fs_ids - rpc_ids))
        )
    if ids:
        return sorted(ids)
    if not _skin_list_rpc_warned:
        _skin_list_rpc_warned = True
        _log(
            "Could not enumerate installed skins via JSON-RPC or filesystem; "
            "falling back to active skin only",
            xbmc.LOGWARNING,
        )
    active = current_skin_id()
    return [active] if active else []


def _skin_addon_path(skin_id: str, *, quiet: bool = False) -> str | None:
    """Resolve a skin's on-disk folder (Addon API, then filesystem fallback)."""
    try:
        path = xbmcaddon.Addon(skin_id).getAddonInfo("path")
    except RuntimeError:
        path = None
    local = _local_path(path) if path else ""
    if local and os.path.isdir(local):
        return local
    # Disabled / broken / not registered skins still have a folder on disk.
    for root in _addon_dir_roots():
        candidate = os.path.join(root, skin_id)
        if os.path.isdir(candidate) and os.path.isfile(
            os.path.join(candidate, "addon.xml")
        ):
            if not quiet:
                _log(
                    f"Resolved {skin_id} via filesystem ({candidate}) — "
                    "Addon() unavailable (disabled or not listed under Skins)",
                    xbmc.LOGWARNING,
                )
            return candidate
    return None


def _skin_display_name(skin_id: str) -> str:
    try:
        return xbmcaddon.Addon(skin_id).getAddonInfo("name") or skin_id
    except RuntimeError:
        pass
    path = _skin_addon_path(skin_id, quiet=True)
    if path:
        addon_xml = os.path.join(path, "addon.xml")
        if os.path.isfile(addon_xml):
            try:
                text = _read_text(addon_xml)
            except OSError:
                text = ""
            match = re.search(
                r'<addon\b[^>]*\bname=["\']([^"\']+)["\']',
                text,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
    return skin_id


def find_skin_xml_paths(skin_root: str, filename: str) -> list[str]:
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
        if filename in filenames:
            found.append(os.path.join(dirpath, filename))
    return sorted(found)


def find_dialog_seekbar_paths(skin_root: str) -> list[str]:
    return find_skin_xml_paths(skin_root, SEEKBAR_FILENAME)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def find_control_block_span(text: str, control_id: str) -> tuple[int, int] | None:
    """Return (start, end) span of a <control id="…">…</control> block."""
    pattern = re.compile(
        r"<control\b[^>]*\bid=[\"']" + re.escape(control_id) + r"[\"']",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        span = _control_block_span_from_open(text, match.start())
        if span is not None:
            return span
    return None


def _control_block_span_from_open(text: str, open_start: int) -> tuple[int, int] | None:
    if open_start < 0 or open_start >= len(text):
        return None
    depth = 0
    index = open_start
    length = len(text)
    while index < length:
        if text.startswith("<control", index):
            close = text.find(">", index)
            if close < 0:
                return None
            depth += 1
            index = close + 1
            continue
        if text.startswith("</control>", index):
            depth -= 1
            index += len("</control>")
            if depth == 0:
                return open_start, index
            continue
        index += 1
    return None


def _innermost_group_span_containing_at(
    text: str, marker_pos: int
) -> tuple[int, int] | None:
    last: tuple[int, int] | None = None
    for match in _GROUP_OPEN_RE.finditer(text):
        if match.start() > marker_pos:
            break
        span = _control_block_span_from_open(text, match.start())
        if span and span[0] <= marker_pos < span[1]:
            last = span
    return last


def _innermost_group_span_containing(text: str, marker: str) -> tuple[int, int] | None:
    marker_pos = text.find(marker)
    if marker_pos < 0:
        return None
    return _innermost_group_span_containing_at(text, marker_pos)


def _all_group_spans_containing(text: str, marker: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    search_from = 0
    while True:
        marker_pos = text.find(marker, search_from)
        if marker_pos < 0:
            break
        span = _innermost_group_span_containing_at(text, marker_pos)
        if span and span not in spans:
            spans.append(span)
        search_from = marker_pos + len(marker)
    return spans


def _inject_skippy_visible_in_group_block(group_block: str) -> str:
    if SKIPPY_SEEKBAR_VISIBLE_MARKER in group_block:
        return group_block
    visible_matches = list(
        re.finditer(r"<visible>[^<]*</visible>", group_block, re.IGNORECASE)
    )
    if visible_matches:
        insert_after = visible_matches[-1].end()
        line_start = group_block.rfind("\n", 0, insert_after) + 1
        indent = re.match(r"[ \t]*", group_block[line_start:]).group(0)
        if not indent:
            indent = "\t\t\t"
    else:
        open_close = group_block.find(">", group_block.find("<control"))
        insert_after = open_close + 1 if open_close >= 0 else 0
        indent = "\t\t\t"
    insertion = f"\n{indent}{SKIPPY_SEEKBAR_VISIBLE_TAG}"
    return group_block[:insert_after] + insertion + group_block[insert_after:]


def _bello_seek_osd_groups_have_skippy(text: str) -> bool:
    if BELLO_CENTER_SEEK_MARKER not in text:
        return True
    center = _innermost_group_span_containing(text, BELLO_CENTER_SEEK_MARKER)
    if center is None:
        return False
    if SKIPPY_SEEKBAR_VISIBLE_MARKER not in text[center[0] : center[1]]:
        return False
    simple_spans = _all_group_spans_containing(text, BELLO_SIMPLE_SEEK_MARKER)
    if not simple_spans:
        return True
    return all(
        SKIPPY_SEEKBAR_VISIBLE_MARKER in text[span[0] : span[1]]
        for span in simple_spans
    )


def ensure_bello_skippy_seek_visible(text: str) -> str:
    """Patch Bello center + simple seek OSD groups in VideoFullScreen.xml."""
    for marker in (BELLO_CENTER_SEEK_MARKER, BELLO_SIMPLE_SEEK_MARKER):
        while True:
            if marker == BELLO_CENTER_SEEK_MARKER:
                span = _innermost_group_span_containing(text, marker)
                spans = [span] if span else []
            else:
                spans = [
                    span
                    for span in _all_group_spans_containing(text, marker)
                    if SKIPPY_SEEKBAR_VISIBLE_MARKER
                    not in text[span[0] : span[1]]
                ]
            if not spans:
                break
            span = spans[0]
            block = text[span[0] : span[1]]
            text = (
                text[: span[0]]
                + _inject_skippy_visible_in_group_block(block)
                + text[span[1] :]
            )
            if marker == BELLO_CENTER_SEEK_MARKER:
                break
    return text


def remove_control_block(text: str, control_id: str) -> str:
    span = find_control_block_span(text, control_id)
    if span is None:
        return text
    start, end = span
    return text[:start] + text[end:]


def extract_overlay_xml_text(snippet_path: str) -> str:
    text = _read_text(snippet_path)
    span = find_control_block_span(text, OVERLAY_CONTROL_ID)
    if span is None:
        raise ValueError(f"snippet missing control id={OVERLAY_CONTROL_ID}")
    return text[span[0] : span[1]]


def insert_overlay_before_controls_close(text: str, overlay_xml: str) -> str:
    """Insert overlay as a direct child of the window <controls> block."""
    match = re.search(r"<controls\b[^>]*>", text, re.IGNORECASE)
    if not match:
        raise ValueError("skin XML has no <controls> element")

    controls_open = match.end()
    depth = 1
    index = controls_open
    length = len(text)
    insert_at = None
    while index < length and depth > 0:
        if text.startswith("<controls", index):
            close = text.find(">", index)
            if close < 0:
                break
            depth += 1
            index = close + 1
            continue
        if text.startswith("</controls>", index):
            depth -= 1
            if depth == 0:
                insert_at = index
                break
            index += len("</controls>")
            continue
        index += 1

    if insert_at is None:
        raise ValueError("skin XML has unclosed <controls> element")

    line_start = text.rfind("\n", 0, insert_at) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group(0)
    if not indent:
        indent = "\t"

    block = overlay_xml.strip()
    if not block.endswith("\n"):
        block += "\n"
    indented = "".join(
        (indent + line if line.strip() else line) + "\n"
        for line in block.splitlines()
    )
    return text[:insert_at] + indented + text[insert_at:]


def overlay_has_legacy_dynamic_placement(text: str) -> bool:
    """True when the overlay uses dynamic Window.Property $INFO coords (broken on many skins)."""
    return LEGACY_DYNAMIC_PREVIEW_MARKER in text


def overlay_already_installed(seekbar_path: str) -> bool:
    local = _local_path(seekbar_path)
    if not local or not os.path.isfile(local):
        return False
    try:
        text = _read_text(local)
    except OSError:
        return False
    if not _CONTROL_OPEN_RE.search(text):
        return False
    return TRICKPLAY_MARKER in text


def ensure_skippy_seekbar_visible(text: str) -> str:
    """Add Skippy skip OSD suppression to the seek bar / fullscreen window."""
    if SKIPPY_SEEKBAR_VISIBLE_MARKER in text:
        return text
    match = _CONTROLS_OPEN_RE.search(text)
    if not match:
        return text
    indent = match.group(1)
    insertion = f"{indent}{SKIPPY_SEEKBAR_VISIBLE_TAG}\n"
    return text[: match.start()] + insertion + text[match.start() :]


def overlay_needs_refresh(target_path: str, snippet_file: str) -> bool:
    """True when an installed overlay is stale (revision, Skippy, or skin-specific markers)."""
    if not overlay_already_installed(target_path):
        return False
    local = _local_path(target_path)
    if not local:
        return False
    try:
        text = _read_text(local)
    except OSError:
        return False
    # Shared checks for every snippet type (merge, replace, universal).
    if SKIPPY_SEEKBAR_VISIBLE_MARKER not in text:
        return True
    if OVERLAY_REVISION_MARKER not in text:
        return True

    # Replace-mode skins (AF2/AF3, Estuary Mod v2) intentionally use
    # Window.Property(Trickplay.*) on DialogSeekBar — not Home properties.
    if snippet_file in REPLACE_SNIPPETS:
        return SLOT_SLIDE_MARKER not in text

    # Dynamic / Home-property merge snippets: flag old dynamic Left/Top placement
    # and Window.Property-only overlays that should have been migrated to Home.
    if overlay_has_legacy_dynamic_placement(text):
        return True
    if (
        snippet_file in HOME_PROPERTY_SNIPPETS
        and LEGACY_PROPERTY_MARKER in text
        and HOME_PROPERTY_MARKER not in text
    ):
        return True

    if snippet_file not in HOME_PROPERTY_SNIPPETS:
        return False

    if snippet_file == "VideoFullScreen-skin.bello.xml":
        return (
            HOME_PROPERTY_MARKER not in text
            or BELLO_PREVIEW_TOP_MARKER not in text
            or not _bello_seek_osd_groups_have_skippy(text)
        )
    if snippet_file == "DialogSeekBar-skin.bingie.xml":
        return (
            HOME_PROPERTY_MARKER not in text
            or SLOT_SLIDE_MARKER not in text
            or BINGIE_PREVIEW_TOP_MARKER not in text
        )
    if snippet_file == "DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml":
        return (
            HOME_PROPERTY_MARKER not in text
            or SLOT_SLIDE_MARKER not in text
            or Z2_RESURRECTION_PREVIEW_TOP_MARKER not in text
        )
    if snippet_file in OSD_SLIDE_MARKERS:
        marker = OSD_SLIDE_MARKERS[snippet_file]
        if marker not in text:
            return True
    return HOME_PROPERTY_MARKER not in text or SLOT_SLIDE_MARKER not in text


def _clean_overlay_from_stub_seekbars(skin_root: str) -> None:
    """Remove trickplay overlay mistakenly merged into empty DialogSeekBar stubs."""
    for path in find_dialog_seekbar_paths(skin_root):
        local = _local_path(path)
        if not local or not os.path.isfile(local):
            continue
        try:
            text = _read_text(local)
        except OSError:
            continue
        if not overlay_already_installed(local):
            continue
        if seekbar_has_host_controls(text):
            continue
        try:
            _write_text(local, remove_control_block(text, OVERLAY_CONTROL_ID))
            _log(f"Removed trickplay overlay from stub DialogSeekBar: {local}")
        except OSError as exc:
            _log(f"Could not clean stub DialogSeekBar {local}: {exc}", xbmc.LOGWARNING)


def current_skin_overlay_installed() -> bool:
    """True when the active skin's snippet target XML has an up-to-date trickplay overlay."""
    skin_id = current_skin_id()
    if not skin_id:
        return True
    root = _skin_addon_path(skin_id)
    if not root:
        return True
    spec = snippet_spec_for_skin_id(skin_id)
    paths = find_skin_xml_paths(root, spec.target_xml)
    if not paths:
        return False
    return any(
        overlay_already_installed(path)
        and not overlay_needs_refresh(path, spec.filename)
        for path in paths
    )


def path_is_writable(seekbar_path: str) -> bool:
    local = _local_path(seekbar_path)
    if not local or not os.path.isfile(local):
        return False
    return os.access(local, os.W_OK)


@dataclass
class PathInstallPlan:
    target_path: str
    target_xml: str
    snippet_file: str
    mode: InstallMode
    writable: bool = True
    already_installed: bool = False
    needs_refresh: bool = False
    stub_seekbar: bool = False

    @property
    def seekbar_path(self) -> str:
        return self.target_path


@dataclass
class SkinInstallPlan:
    skin_id: str
    skin_name: str
    paths: list[PathInstallPlan] = field(default_factory=list)
    error: str | None = None


@dataclass
class PathRestorePlan:
    target_path: str
    target_xml: str
    backup_path: str
    writable: bool = True

    @property
    def seekbar_path(self) -> str:
        return self.target_path


@dataclass
class SkinRestorePlan:
    skin_id: str
    skin_name: str
    paths: list[PathRestorePlan] = field(default_factory=list)
    error: str | None = None


@dataclass
class InstallOutcome:
    skin_id: str
    skin_name: str
    seekbar_path: str
    success: bool
    message: str
    skipped: bool = False


def _snippet_root(addon_path: str) -> str:
    return os.path.join(addon_path, SNIPPET_DIR)


def _mode_from_spec(mode: str) -> InstallMode:
    if mode == "replace":
        return InstallMode.REPLACE
    return InstallMode.MERGE


def build_install_plan(
    scope: InstallScope,
    addon_path: str,
    *,
    force: bool = False,
) -> list[SkinInstallPlan]:
    if scope == InstallScope.CURRENT:
        skin_ids = [sid for sid in [current_skin_id()] if sid]
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

        spec = snippet_spec_for_skin_id(skin_id)
        target_xml = spec.target_xml
        target_paths = find_skin_xml_paths(root, target_xml)
        if not target_paths:
            plans.append(
                SkinInstallPlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="snippet_target_not_found",
                )
            )
            continue

        mode = _mode_from_spec(spec.mode)
        if not spec.known and mode == InstallMode.REPLACE:
            mode = InstallMode.MERGE

        snippet_path = os.path.join(_snippet_root(addon_path), spec.filename)
        if not os.path.isfile(snippet_path):
            plans.append(
                SkinInstallPlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="snippet_file_missing",
                )
            )
            continue

        path_plans: list[PathInstallPlan] = []
        for path in target_paths:
            _debug_log(f"{target_xml} path: {path}")
            writable = path_is_writable(path)
            installed = overlay_already_installed(path)
            needs_refresh = overlay_needs_refresh(path, spec.filename)
            stub_seekbar = False
            if target_xml == SEEKBAR_FILENAME:
                local = _local_path(path)
                if local and os.path.isfile(local):
                    try:
                        stub_seekbar = not seekbar_has_host_controls(_read_text(local))
                    except OSError:
                        pass
            path_plans.append(
                PathInstallPlan(
                    target_path=path,
                    target_xml=target_xml,
                    snippet_file=spec.filename,
                    mode=mode,
                    writable=writable,
                    already_installed=installed and not needs_refresh and not force,
                    needs_refresh=needs_refresh or (force and installed),
                    stub_seekbar=stub_seekbar,
                )
            )
        plans.append(
            SkinInstallPlan(
                skin_id=skin_id,
                skin_name=name,
                paths=path_plans,
            )
        )
    return plans


def build_restore_plan(scope: InstallScope) -> list[SkinRestorePlan]:
    if scope == InstallScope.CURRENT:
        skin_ids = [sid for sid in [current_skin_id()] if sid]
    else:
        skin_ids = list_installed_skin_ids()

    plans: list[SkinRestorePlan] = []
    for skin_id in skin_ids:
        name = _skin_display_name(skin_id)
        root = _skin_addon_path(skin_id)
        if not root:
            plans.append(
                SkinRestorePlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="skin_addon_path_unavailable",
                )
            )
            continue

        spec = snippet_spec_for_skin_id(skin_id)
        target_xml = spec.target_xml
        target_paths = find_skin_xml_paths(root, target_xml)
        if not target_paths:
            plans.append(
                SkinRestorePlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="snippet_target_not_found",
                )
            )
            continue

        path_plans: list[PathRestorePlan] = []
        for path in target_paths:
            bak = path + BACKUP_SUFFIX
            _debug_log(f"{target_xml} backup path: {bak}")
            if not os.path.isfile(_local_path(bak) or bak):
                continue
            writable = path_is_writable(path)
            path_plans.append(
                PathRestorePlan(
                    target_path=path,
                    target_xml=target_xml,
                    backup_path=bak,
                    writable=writable,
                )
            )

        if not path_plans:
            plans.append(
                SkinRestorePlan(
                    skin_id=skin_id,
                    skin_name=name,
                    error="backup_not_found",
                )
            )
        else:
            plans.append(
                SkinRestorePlan(
                    skin_id=skin_id,
                    skin_name=name,
                    paths=path_plans,
                )
            )
    return plans


def _backup_seekbar(seekbar_path: str) -> tuple[bool, str]:
    local = _local_path(seekbar_path)
    bak_path = local + BACKUP_SUFFIX
    if os.path.isfile(bak_path):
        return True, "backup_exists"
    try:
        shutil.copy2(local, bak_path)
    except OSError as exc:
        return False, str(exc)
    return True, "backup_created"


def _merge_overlay_preserve_format(
    seekbar_path: str,
    snippet_path: str,
    *,
    target_xml: str = SEEKBAR_FILENAME,
) -> None:
    local = _local_path(seekbar_path)
    text = _read_text(local)
    text = remove_control_block(text, OVERLAY_CONTROL_ID)
    if target_xml == SEEKBAR_FILENAME:
        text = ensure_skippy_seekbar_visible(text)
    elif target_xml == VIDEO_FULLSCREEN_FILENAME:
        text = ensure_bello_skippy_seek_visible(text)
    overlay = extract_overlay_xml_text(snippet_path)
    merged = insert_overlay_before_controls_close(text, overlay)
    _write_text(local, merged)


def _replace_seekbar(seekbar_path: str, snippet_path: str) -> None:
    shutil.copy2(snippet_path, _local_path(seekbar_path))


def _install_one_path(
    seekbar_path: str,
    snippet_path: str,
    mode: InstallMode,
    *,
    target_xml: str = SEEKBAR_FILENAME,
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
            _merge_overlay_preserve_format(
                local, snippet_path, target_xml=target_xml
            )
    except (OSError, ValueError) as exc:
        return False, str(exc)

    if backup_detail == "backup_exists":
        return True, "ok_backup_kept"
    return True, "ok"


def _restore_one_path(seekbar_path: str, backup_path: str) -> tuple[bool, str]:
    local = _local_path(seekbar_path)
    bak_local = _local_path(backup_path)
    if not bak_local or not os.path.isfile(bak_local):
        return False, "backup_not_found"
    if not local:
        return False, "dialog_seekbar_not_found"
    if not os.access(local, os.W_OK):
        return False, "not_writable"
    try:
        shutil.copy2(bak_local, local)
    except OSError as exc:
        return False, str(exc)
    return True, "restored"


def execute_install_plan(
    plans: list[SkinInstallPlan],
    addon_path: str,
    *,
    progress: Callable[[int, str], None] | None = None,
) -> list[InstallOutcome]:
    snippet_root = _snippet_root(addon_path)
    outcomes: list[InstallOutcome] = []
    modified_active_skin = False
    reload_host_skin = False
    active = current_skin_id()

    work: list[tuple[SkinInstallPlan, PathInstallPlan]] = []
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
            if path_plan.already_installed:
                outcomes.append(
                    InstallOutcome(
                        skin_id=plan.skin_id,
                        skin_name=plan.skin_name,
                        seekbar_path=path_plan.seekbar_path,
                        success=True,
                        message="already_installed",
                        skipped=True,
                    )
                )
                continue
            if path_plan.stub_seekbar:
                outcomes.append(
                    InstallOutcome(
                        skin_id=plan.skin_id,
                        skin_name=plan.skin_name,
                        seekbar_path=path_plan.seekbar_path,
                        success=True,
                        message="dialog_seekbar_stub",
                        skipped=True,
                    )
                )
                continue
            if not path_plan.writable:
                outcomes.append(
                    InstallOutcome(
                        skin_id=plan.skin_id,
                        skin_name=plan.skin_name,
                        seekbar_path=path_plan.seekbar_path,
                        success=False,
                        message="not_writable",
                    )
                )
                continue
            work.append((plan, path_plan))

    total = len(work)
    modified_skins: set[str] = set()
    for index, (plan, path_plan) in enumerate(work):
        if progress:
            percent = int((index * 100) / max(total, 1))
            label = os.path.basename(os.path.dirname(path_plan.target_path))
            progress(percent, f"{plan.skin_name} — {label}")

        snippet_path = os.path.join(snippet_root, path_plan.snippet_file)
        ok, detail = _install_one_path(
            path_plan.target_path,
            snippet_path,
            path_plan.mode,
            target_xml=path_plan.target_xml,
        )
        outcomes.append(
            InstallOutcome(
                skin_id=plan.skin_id,
                skin_name=plan.skin_name,
                seekbar_path=path_plan.target_path,
                success=ok,
                message=detail,
            )
        )
        if ok:
            modified_skins.add(normalize_skin_id(plan.skin_id))
            if normalize_skin_id(plan.skin_id) == active:
                modified_active_skin = True
                if path_plan.target_xml == VIDEO_FULLSCREEN_FILENAME:
                    reload_host_skin = True
                else:
                    local = _local_path(path_plan.target_path)
                    if local and os.path.isfile(local):
                        try:
                            if seekbar_has_host_controls(_read_text(local)):
                                reload_host_skin = True
                        except OSError:
                            reload_host_skin = True

    for skin_id in modified_skins:
        root = _skin_addon_path(skin_id)
        if not root:
            continue
        spec = snippet_spec_for_skin_id(skin_id)
        if spec.target_xml == VIDEO_FULLSCREEN_FILENAME:
            _clean_overlay_from_stub_seekbars(root)

    if progress:
        progress(100, "Done")

    if modified_active_skin and reload_host_skin:
        schedule_skin_reload()
    elif modified_active_skin:
        _log(
            "Skipped skin reload: DialogSeekBar has no host seek bar controls",
            xbmc.LOGWARNING,
        )

    return outcomes


def execute_restore_plan(
    plans: list[SkinRestorePlan],
    *,
    progress: Callable[[int, str], None] | None = None,
) -> list[InstallOutcome]:
    outcomes: list[InstallOutcome] = []
    modified_active_skin = False
    reload_host_skin = False
    active = current_skin_id()

    work: list[tuple[SkinRestorePlan, PathRestorePlan]] = []
    for plan in plans:
        if plan.error or not plan.paths:
            outcomes.append(
                InstallOutcome(
                    skin_id=plan.skin_id,
                    skin_name=plan.skin_name,
                    seekbar_path="",
                    success=False,
                    message=plan.error or "backup_not_found",
                )
            )
            continue
        for path_plan in plan.paths:
            if not path_plan.writable:
                outcomes.append(
                    InstallOutcome(
                        skin_id=plan.skin_id,
                        skin_name=plan.skin_name,
                        seekbar_path=path_plan.seekbar_path,
                        success=False,
                        message="not_writable",
                    )
                )
                continue
            work.append((plan, path_plan))

    total = len(work)
    for index, (plan, path_plan) in enumerate(work):
        if progress:
            percent = int((index * 100) / max(total, 1))
            label = os.path.basename(os.path.dirname(path_plan.target_path))
            progress(percent, f"{plan.skin_name} — {label}")

        ok, detail = _restore_one_path(
            path_plan.target_path,
            path_plan.backup_path,
        )
        outcomes.append(
            InstallOutcome(
                skin_id=plan.skin_id,
                skin_name=plan.skin_name,
                seekbar_path=path_plan.target_path,
                success=ok,
                message=detail,
            )
        )
        if ok and normalize_skin_id(plan.skin_id) == active:
            modified_active_skin = True
            if path_plan.target_xml == VIDEO_FULLSCREEN_FILENAME:
                reload_host_skin = True
            else:
                local = _local_path(path_plan.target_path)
                if local and os.path.isfile(local):
                    try:
                        if seekbar_has_host_controls(_read_text(local)):
                            reload_host_skin = True
                    except OSError:
                        reload_host_skin = True

    if progress:
        progress(100, "Done")

    if modified_active_skin and reload_host_skin:
        schedule_skin_reload()
    elif modified_active_skin:
        _log(
            "Skipped skin reload: DialogSeekBar has no host seek bar controls",
            xbmc.LOGWARNING,
        )

    return outcomes


def plan_has_installable_targets(plans: list[SkinInstallPlan]) -> bool:
    for plan in plans:
        for path_plan in plan.paths:
            if (
                not path_plan.already_installed
                and path_plan.writable
                and not path_plan.stub_seekbar
            ):
                return True
    return False


def plan_has_restore_targets(plans: list[SkinRestorePlan]) -> bool:
    return any(plan.paths for plan in plans)


def format_plan_summary(plans: list[SkinInstallPlan]) -> str:
    lines: list[str] = []
    for plan in plans:
        if plan.error:
            lines.append(f"• {plan.skin_name} ({plan.skin_id}): [{plan.error}]")
            continue
        for path_plan in plan.paths:
            rel_hint = os.path.basename(os.path.dirname(path_plan.target_path))
            tags: list[str] = [path_plan.mode.value]
            if not path_plan.writable:
                tags.append("not_writable")
            if path_plan.already_installed:
                tags.append("already_installed")
            elif path_plan.needs_refresh:
                tags.append("stale_overlay")
            elif overlay_already_installed(path_plan.target_path):
                tags.append("stale_overlay")
            if path_plan.stub_seekbar:
                tags.append("stub_seekbar")
            lines.append(
                f"• {plan.skin_name} ({plan.skin_id}) → "
                f".../{rel_hint}/{path_plan.target_xml} [{', '.join(tags)}]"
            )
    return "\n".join(lines)


def format_restore_plan_summary(plans: list[SkinRestorePlan]) -> str:
    lines: list[str] = []
    for plan in plans:
        if plan.error:
            lines.append(f"• {plan.skin_name} ({plan.skin_id}): [{plan.error}]")
            continue
        for path_plan in plan.paths:
            rel_hint = os.path.basename(os.path.dirname(path_plan.target_path))
            tag = "writable" if path_plan.writable else "not_writable"
            lines.append(
                f"• {plan.skin_name} ({plan.skin_id}) → "
                f".../{rel_hint}/{path_plan.target_xml}.bak [{tag}]"
            )
    return "\n".join(lines)


def summarize_outcomes(outcomes: list[InstallOutcome]) -> tuple[int, int, int, int]:
    ok = sum(1 for item in outcomes if item.success and not item.skipped)
    skipped = sum(1 for item in outcomes if item.skipped)
    fail = sum(1 for item in outcomes if not item.success)
    skins = len({item.skin_id for item in outcomes})
    return ok, fail, skipped, skins


def inactive_skin_install_note(
    outcomes: list[InstallOutcome],
    scope: InstallScope,
) -> str:
    if scope != InstallScope.ALL:
        return ""
    active = current_skin_id()
    modified_other = any(
        item.success
        and not item.skipped
        and normalize_skin_id(item.skin_id) != active
        for item in outcomes
    )
    if modified_other:
        return "inactive_skins_note"
    return ""

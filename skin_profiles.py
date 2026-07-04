"""Kodi skin profiles for seek bar geometry and OSD focus behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass

try:
    import xbmcaddon
except ImportError:  # pragma: no cover - unit tests / lint outside Kodi
    xbmcaddon = None  # type: ignore[assignment]

SETTING_SKIN_PROFILE = "skin_profile"
PROFILE_AUTO = "auto"

# Addon ids that are not user skins (bad fallbacks from older detection).
_INVALID_SKIN_IDS = frozenset(
    {
        "xbmc.gui",
        "kodi.gui",
        "kodi.core",
        "xbmc.core",
    }
)


@dataclass(frozen=True)
class SkinProfile:
    key: str
    label: str
    seekbar: tuple[int, int, int]  # left, top, width @ 1080p
    seekbar_focus_id: int
    seekbar_wide: tuple[int, int, int] | None = None
    osd_button_group_id: int | None = None
    osd_button_ids: tuple[int, ...] = ()
    full_osd_window_ids: tuple[int, ...] = ()
    full_osd_extra_visibility: str = ""
    fullscreen_seek_visibility: str = ""

    def fullscreen_seek_ui_visible(self) -> bool:
        if not self.fullscreen_seek_visibility:
            return False
        try:
            import xbmc
        except ImportError:  # pragma: no cover
            return False

        return xbmc.getCondVisibility(self.fullscreen_seek_visibility)

    def full_osd_visibility_parts(self) -> list[str]:
        parts = [
            "Window.IsVisible(videoosd)",
            "Window.IsActive(videoosd)",
            "Window.IsVisible(VideoOSD)",
            "Window.IsVisible(VideoOSD.xml)",
            "Window.IsVisible(CustomVideoOSD.xml)",
        ]
        for window_id in self.full_osd_window_ids:
            parts.append(f"Window.IsActive({window_id})")
            parts.append(f"Window.IsVisible({window_id})")
        if self.full_osd_extra_visibility:
            parts.append(self.full_osd_extra_visibility)
        return parts

    def full_osd_skin_visibility(self) -> str:
        """Kodi skin visibility expression for full video OSD (not compact seek bar)."""
        return "[" + " | ".join(self.full_osd_visibility_parts()) + "]"

    def full_osd_visible(self) -> bool:
        try:
            import xbmc
        except ImportError:  # pragma: no cover
            return False

        return xbmc.getCondVisibility(self.full_osd_skin_visibility())

    def osd_play_controls_focused(self) -> bool:
        try:
            import xbmc
        except ImportError:  # pragma: no cover
            return False

        if self.osd_button_group_id is not None:
            return xbmc.getCondVisibility(
                f"ControlGroup({self.osd_button_group_id}).HasFocus"
            )
        if self.osd_button_ids:
            expr = " | ".join(
                f"Control.HasFocus({button_id})" for button_id in self.osd_button_ids
            )
            return xbmc.getCondVisibility(f"[{expr}]")
        return False

    def clears_preview_on_osd_handoff(self) -> bool:
        """True when opening full video OSD replaces the compact seek bar (Fuse-style)."""
        return self.key in ("arctic_fuse_2", "arctic_fuse_3")


ESTUARY_MODV2 = SkinProfile(
    key="estuary_modv2",
    label="Estuary Mod v2",
    seekbar=(460, 990, 1430),
    seekbar_wide=(30, 990, 1860),
    seekbar_focus_id=87,
    osd_button_group_id=200,
)

_AF3_OSD_WINDOW_IDS = tuple(list(range(1140, 1150)) + [1152, 1153])

_AF2_OSD_WINDOW_IDS = tuple(range(1140, 1150))

ARCTIC_FUSE_3 = SkinProfile(
    key="arctic_fuse_3",
    label="Arctic Fuse 3",
    seekbar=(240, 772, 1440),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(6001, 6010)) + tuple(range(6101, 6110)),
    full_osd_window_ids=_AF3_OSD_WINDOW_IDS,
    full_osd_extra_visibility=(
        "Window.IsVisible(videobookmarks) | Window.IsVisible(pvrosdguide) | "
        "Window.IsVisible(pvrosdchannels)"
    ),
)

ARCTIC_FUSE_2 = SkinProfile(
    key="arctic_fuse_2",
    label="Arctic Fuse 2",
    seekbar=(240, 772, 1440),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(6001, 6010)) + tuple(range(6101, 6110)),
    full_osd_window_ids=_AF2_OSD_WINDOW_IDS,
    full_osd_extra_visibility=(
        "Window.IsVisible(videobookmarks) | Window.IsVisible(pvrosdguide) | "
        "Window.IsVisible(pvrosdchannels)"
    ),
)

# Stock Kodi Estuary — centered 50% seek bar @ bottom (xbmc/xbmc skin.estuary).
ESTUARY = SkinProfile(
    key="estuary",
    label="Estuary (stock)",
    seekbar=(480, 990, 960),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 18)),
)

# Doctor-Eggs/Aeon-Nox-SiLVO — full-width bottom bar (16x9/DialogSeekBar.xml).
AEON_NOX_SILVO = SkinProfile(
    key="aeon_nox_silvo",
    label="Aeon Nox SiLVO",
    seekbar=(0, 1039, 1920),
    seekbar_focus_id=401,
    osd_button_group_id=202,
)

# jurialmunkey/skin.arctic.zephyr — SidePad ~60, bar near bottom (110r panel).
ARCTIC_ZEPHYR = SkinProfile(
    key="arctic_zephyr",
    label="Arctic Zephyr",
    seekbar=(60, 1060, 1800),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# jurialmunkey/skin.arctic.horizon — view_pad ~40, progress bar bottom 148.
ARCTIC_HORIZON = SkinProfile(
    key="arctic_horizon",
    label="Arctic Horizon",
    seekbar=(40, 920, 1840),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# jurialmunkey/skin.arctic.horizon.2 — view_pad ~20, progress bar (20, 720, 1840).
ARCTIC_HORIZON_2 = SkinProfile(
    key="arctic_horizon_2",
    label="Arctic Horizon 2",
    seekbar=(20, 720, 1840),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# AH2.1 Arizen fork (skin.arctic.horizon.2.1.arizen) — same bar geometry as AH2 for now.
ARCTIC_HORIZON_2_ARIZEN = SkinProfile(
    key="arctic_horizon_2_1_arizen",
    label="Arctic Horizon 2.1 Arizen",
    seekbar=(20, 720, 1840),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# Nanomani/skin.arctic.zephyr.rounded — OSD_SidePad 130, progress bar @ bottom.
ARCTIC_ZEPHYR_ROUNDED = SkinProfile(
    key="arctic_zephyr_rounded",
    label="Arctic Zephyr Rounded",
    seekbar=(130, 962, 1660),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# DenDyGH/skin.arctic.zephyr.2.resurrection.mod — progress bar @ bottom 100; preview above OSD_Progress_Text.
ARCTIC_ZEPHYR_2_RESURRECTION = SkinProfile(
    key="arctic_zephyr_2_resurrection",
    label="Arctic Zephyr 2 Resurrection",
    seekbar=(60, 980, 1800),
    seekbar_focus_id=401,
    osd_button_ids=tuple(range(11, 20)),
)

# Nessus85100/skin.bello — center seek OSD in VideoFullScreen.xml @ 720p.
_BELLO_FULLSCREEN_SEEK = (
    "Window.IsActive(FullScreenVideo) + "
    "[Player.Seeking | Player.Forwarding | Player.Rewinding | "
    "Player.HasPerformedSeek(1) | Player.Paused | Player.Caching] + "
    "![String.IsEqual(Skin.String(DialogSeekBarStyle),2) | "
    "String.IsEqual(Skin.String(DialogSeekBarStyle),3)]"
)

BELLO = SkinProfile(
    key="bello",
    label="Bello",
    seekbar=(478, 560, 320),
    seekbar_focus_id=401,
    osd_button_group_id=200,
    fullscreen_seek_visibility=_BELLO_FULLSCREEN_SEEK,
)

# matke-84/skin.bingie — Bingie OSD bar (384, 957, 1152); classic OSD (525, 934, 700).
BINGIE = SkinProfile(
    key="bingie",
    label="Bingie",
    seekbar=(384, 957, 1152),
    seekbar_wide=(525, 934, 700),
    seekbar_focus_id=401,
    osd_button_group_id=200,
)

DEFAULT_PROFILE = ESTUARY_MODV2

PROFILES_BY_KEY: dict[str, SkinProfile] = {
    ESTUARY_MODV2.key: ESTUARY_MODV2,
    ARCTIC_FUSE_3.key: ARCTIC_FUSE_3,
    ARCTIC_FUSE_2.key: ARCTIC_FUSE_2,
    ESTUARY.key: ESTUARY,
    AEON_NOX_SILVO.key: AEON_NOX_SILVO,
    ARCTIC_ZEPHYR.key: ARCTIC_ZEPHYR,
    ARCTIC_ZEPHYR_ROUNDED.key: ARCTIC_ZEPHYR_ROUNDED,
    ARCTIC_ZEPHYR_2_RESURRECTION.key: ARCTIC_ZEPHYR_2_RESURRECTION,
    ARCTIC_HORIZON.key: ARCTIC_HORIZON,
    ARCTIC_HORIZON_2.key: ARCTIC_HORIZON_2,
    ARCTIC_HORIZON_2_ARIZEN.key: ARCTIC_HORIZON_2_ARIZEN,
    BELLO.key: BELLO,
    BINGIE.key: BINGIE,
}

PROFILES_BY_SKIN_ID: dict[str, SkinProfile] = {
    "skin.estuary.modv2": ESTUARY_MODV2,
    "skin.estuary.mod": ESTUARY_MODV2,
    "skin.estuary": ESTUARY,
    "skin.arctic.fuse.3": ARCTIC_FUSE_3,
    "skin.arctic.fuse.2": ARCTIC_FUSE_2,
    "skin.arctic.fuse": ARCTIC_FUSE_3,
    "skin.aeon.nox.silvo": AEON_NOX_SILVO,
    "skin.aeon.nox": AEON_NOX_SILVO,
    "skin.arctic.zephyr.2.resurrection.mod": ARCTIC_ZEPHYR_2_RESURRECTION,
    "skin.arctic.zephyr.rounded": ARCTIC_ZEPHYR_ROUNDED,
    "skin.arctic.zephyr": ARCTIC_ZEPHYR,
    "skin.arctic.zephyr.2": ARCTIC_ZEPHYR_2_RESURRECTION,
    "skin.arctic.horizon.2.1.arizen": ARCTIC_HORIZON_2_ARIZEN,
    "skin.arctic.horizon.2": ARCTIC_HORIZON_2,
    "skin.arctic.horizon": ARCTIC_HORIZON,
    "skin.bello.10": BELLO,
    "skin.bello.9": BELLO,
    "skin.bello": BELLO,
    "skin.bingie": BINGIE,
}

# Substrings matched against normalized skin ids (longest wins via ordered list).
SKIN_ID_MARKERS: tuple[tuple[str, SkinProfile], ...] = (
    ("arctic.zephyr.2.resurrection", ARCTIC_ZEPHYR_2_RESURRECTION),
    ("arctic.zephyr.rounded", ARCTIC_ZEPHYR_ROUNDED),
    ("arctic.horizon.2.1.arizen", ARCTIC_HORIZON_2_ARIZEN),
    ("arctic.horizon.2", ARCTIC_HORIZON_2),
    ("arctic.fuse.3", ARCTIC_FUSE_3),
    ("arctic.fuse.2", ARCTIC_FUSE_2),
    ("arctic.fuse", ARCTIC_FUSE_3),
    ("arctic.zephyr", ARCTIC_ZEPHYR),
    ("arctic.horizon", ARCTIC_HORIZON),
    ("aeon.nox.silvo", AEON_NOX_SILVO),
    ("aeon.nox", AEON_NOX_SILVO),
    ("bello.10", BELLO),
    ("bello.9", BELLO),
    ("bello", BELLO),
    ("bingie", BINGIE),
    ("estuary.modv2", ESTUARY_MODV2),
    ("estuary.mod", ESTUARY_MODV2),
    ("estuary", ESTUARY),
)

_cached_profile: SkinProfile | None = None
_cached_skin_id: str | None = None
_cached_override: str | None = None


def _addon() -> xbmcaddon.Addon | None:
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon("service.trickplay")
    except RuntimeError:
        return None


def _setting_override() -> str:
    addon = _addon()
    if addon is None:
        return PROFILE_AUTO
    try:
        value = addon.getSettingString(SETTING_SKIN_PROFILE)
    except (RuntimeError, TypeError, ValueError):
        return PROFILE_AUTO
    return value.strip().lower() if value else PROFILE_AUTO


def normalize_skin_id(raw: str) -> str:
    skin_id = raw.strip().lower()
    if not skin_id or skin_id in _INVALID_SKIN_IDS:
        return ""
    if skin_id.startswith("skin."):
        return skin_id
    return f"skin.{skin_id}"


def _skin_id_from_settings() -> str:
    try:
        import xbmc
    except ImportError:  # pragma: no cover
        return ""

    command = {
        "jsonrpc": "2.0",
        "method": "Settings.GetSettingValue",
        "params": {"setting": "lookandfeel.skin"},
        "id": 1,
    }
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(command)))
        value = response.get("result", {}).get("value", "")
        return normalize_skin_id(str(value)) if value else ""
    except (RuntimeError, TypeError, ValueError, KeyError):
        return ""


def _skin_id_from_get_skin_dir() -> str:
    try:
        import xbmc
    except ImportError:  # pragma: no cover
        return ""

    try:
        skin_dir = xbmc.getSkinDir()
    except (RuntimeError, TypeError, AttributeError):
        return ""
    return normalize_skin_id(str(skin_dir)) if skin_dir else ""


def current_skin_id() -> str:
    for resolver in (_skin_id_from_settings, _skin_id_from_get_skin_dir):
        skin_id = resolver()
        if skin_id:
            return skin_id
    return ""


def profile_for_skin_id(skin_id: str, override: str = PROFILE_AUTO) -> SkinProfile:
    if override and override != PROFILE_AUTO:
        profile = PROFILES_BY_KEY.get(override)
        if profile is not None:
            return profile

    normalized = normalize_skin_id(skin_id)
    if not normalized:
        return DEFAULT_PROFILE

    if normalized in PROFILES_BY_SKIN_ID:
        return PROFILES_BY_SKIN_ID[normalized]

    best_id = ""
    best_profile: SkinProfile | None = None
    for known_id, profile in PROFILES_BY_SKIN_ID.items():
        if normalized.startswith(known_id) or known_id.startswith(normalized):
            if len(known_id) > len(best_id):
                best_id = known_id
                best_profile = profile
    if best_profile is not None:
        return best_profile

    for marker, profile in SKIN_ID_MARKERS:
        if marker in normalized:
            return profile

    return DEFAULT_PROFILE


def active_profile(force_refresh: bool = False) -> SkinProfile:
    global _cached_profile, _cached_skin_id, _cached_override

    skin_id = current_skin_id()
    override = _setting_override()
    if (
        not force_refresh
        and _cached_profile is not None
        and skin_id == _cached_skin_id
        and override == _cached_override
    ):
        return _cached_profile

    _cached_skin_id = skin_id
    _cached_override = override
    _cached_profile = profile_for_skin_id(skin_id, override)
    return _cached_profile


def is_known_skin(skin_id: str) -> bool:
    normalized = normalize_skin_id(skin_id)
    if not normalized:
        return False
    if normalized in PROFILES_BY_SKIN_ID:
        return True
    if any(
        normalized.startswith(known_id) or known_id.startswith(normalized)
        for known_id in PROFILES_BY_SKIN_ID
    ):
        return True
    return any(marker in normalized for marker, _profile in SKIN_ID_MARKERS)


def setting_skin_profile_override() -> str:
    return _setting_override()


@dataclass(frozen=True)
class SkinSnippetSpec:
    """Trickplay skin XML snippet file, install mode, and merge target."""

    filename: str
    mode: str  # "merge" or "replace"
    known: bool = True
    target_xml: str = "DialogSeekBar.xml"


# Longest marker first (substring match against normalized skin id).
# Only entries listed with replace use full-file replace; unknown skins use universal merge.
SKIN_SNIPPET_REGISTRY: tuple[tuple[str, str, str], ...] = (
    ("arctic.fuse.3", "DialogSeekBar-skin.arctic.fuse.3.xml", "replace"),
    ("arctic.fuse.2", "DialogSeekBar-skin.arctic.fuse.2.xml", "replace"),
    ("arctic.fuse", "DialogSeekBar-skin.arctic.fuse.3.xml", "replace"),
    ("estuary.modv2", "DialogSeekBar-skin.estuary.modv2.xml", "replace"),
    ("estuary.mod", "DialogSeekBar-skin.estuary.modv2.xml", "replace"),
    ("arctic.zephyr.2.resurrection", "DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml", "merge"),
    ("arctic.zephyr.rounded", "DialogSeekBar-skin.arctic.zephyr.rounded.xml", "merge"),
    ("arctic.horizon.2.1.arizen", "DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml", "merge"),
    ("arctic.horizon.2", "DialogSeekBar-skin.arctic.horizon.2.xml", "merge"),
    ("aeon.nox.silvo", "DialogSeekBar-skin.aeon.nox.silvo.xml", "merge"),
    ("aeon.nox", "DialogSeekBar-skin.aeon.nox.silvo.xml", "merge"),
    ("arctic.zephyr", "DialogSeekBar-skin.arctic.zephyr.xml", "merge"),
    ("arctic.horizon", "DialogSeekBar-skin.arctic.horizon.xml", "merge"),
    ("bello", "VideoFullScreen-skin.bello.xml", "merge", "VideoFullScreen.xml"),
    ("bingie", "DialogSeekBar-skin.bingie.xml", "merge"),
    ("estuary", "DialogSeekBar-skin.estuary.xml", "merge"),
)
UNIVERSAL_SNIPPET_FILENAME = "DialogSeekBar-universal-dynamic.xml"


def snippet_spec_for_skin_id(skin_id: str) -> SkinSnippetSpec:
    normalized = normalize_skin_id(skin_id)
    for entry in SKIN_SNIPPET_REGISTRY:
        marker = entry[0]
        filename = entry[1]
        mode = entry[2]
        target_xml = entry[3] if len(entry) > 3 else "DialogSeekBar.xml"
        if marker in normalized:
            return SkinSnippetSpec(
                filename=filename,
                mode=mode,
                known=True,
                target_xml=target_xml,
            )
    return SkinSnippetSpec(
        filename=UNIVERSAL_SNIPPET_FILENAME,
        mode="merge",
        known=False,
    )


def profile_summary(profile: SkinProfile, skin_id: str, override: str) -> str:
    if override != PROFILE_AUTO:
        source = f"setting:{override}"
    else:
        source = normalize_skin_id(skin_id) or skin_id or "unknown"
    wide = (
        f" wide={profile.seekbar_wide}"
        if profile.seekbar_wide is not None
        else ""
    )
    return (
        f"{profile.label} ({profile.key}) via {source}; "
        f"seekbar={profile.seekbar}{wide}; focus={profile.seekbar_focus_id}"
    )

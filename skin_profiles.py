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


ESTUARY_MODV2 = SkinProfile(
    key="estuary_modv2",
    label="Estuary Mod v2",
    seekbar=(460, 990, 1430),
    seekbar_wide=(30, 990, 1860),
    seekbar_focus_id=87,
    osd_button_group_id=200,
)

_AF3_OSD_WINDOW_IDS = tuple(list(range(1140, 1150)) + [1152, 1153])

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

DEFAULT_PROFILE = ESTUARY_MODV2

PROFILES_BY_KEY: dict[str, SkinProfile] = {
    ESTUARY_MODV2.key: ESTUARY_MODV2,
    ARCTIC_FUSE_3.key: ARCTIC_FUSE_3,
}

PROFILES_BY_SKIN_ID: dict[str, SkinProfile] = {
    "skin.estuary.modv2": ESTUARY_MODV2,
    "skin.estuary.mod": ESTUARY_MODV2,
    "skin.estuary": ESTUARY_MODV2,
    "skin.arctic.fuse.3": ARCTIC_FUSE_3,
    "skin.arctic.fuse": ARCTIC_FUSE_3,
}

# Substrings matched against normalized skin ids (longest wins via ordered list).
SKIN_ID_MARKERS: tuple[tuple[str, SkinProfile], ...] = (
    ("arctic.fuse.3", ARCTIC_FUSE_3),
    ("arctic.fuse", ARCTIC_FUSE_3),
    ("estuary.modv2", ESTUARY_MODV2),
    ("estuary.mod", ESTUARY_MODV2),
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

    for known_id, profile in PROFILES_BY_SKIN_ID.items():
        if normalized.startswith(known_id) or known_id.startswith(normalized):
            return profile

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

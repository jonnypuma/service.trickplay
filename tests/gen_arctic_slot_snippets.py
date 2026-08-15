"""Generate fixed-anchor PreviewSlot slide DialogSeekBar snippets (101 slots)."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from osd_layout import (  # noqa: E402
    PREVIEW_GAP,
    PREVIEW_SLOTS,
    SeekBarLayout,
    _absolute_left,
    _slot_ratio,
    preview_dimensions,
)
from overlay_revision import OVERLAY_REVISION  # noqa: E402


@dataclass(frozen=True)
class ArcticSnippetSpec:
    filename: str
    comment: str
    bar: tuple[int, int, int]
    border_texture: str
    osd_slide: str | None = None  # "ah2_80" | "rounded_74" | "nox_90" | None
    font: str = "font13"
    anchor_top_override: int | None = None
    prop: str = "Window(Home).Property"  # or Window.Property


SPECS = (
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.horizon.xml",
        comment=(
            "Arctic Horizon (skin.arctic.horizon).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); +80px Y when compact seekbar.\n"
            "  Source: github.com/jurialmunkey/skin.arctic.horizon 1080i/Includes_OSD.xml"
        ),
        bar=(40, 920, 1840),
        border_texture="colors/white.png",
        osd_slide="ah2_80",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.horizon.2.xml",
        comment=(
            "Arctic Horizon 2 (skin.arctic.horizon.2).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); +80px Y when compact seekbar.\n"
            "  Source: github.com/jurialmunkey/skin.arctic.horizon.2 1080i/Includes_OSD.xml"
        ),
        bar=(20, 720, 1840),
        border_texture="colors/white.png",
        osd_slide="ah2_80",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml",
        comment=(
            "Arctic Horizon 2.1 Arizen (skin.arctic.horizon.2.1.arizen).\n"
            "  Same geometry as Arctic Horizon 2."
        ),
        bar=(20, 720, 1840),
        border_texture="colors/white.png",
        osd_slide="ah2_80",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.zephyr.xml",
        comment=(
            "Arctic Zephyr (skin.arctic.zephyr).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100).\n"
            "  Source: github.com/jurialmunkey/skin.arctic.zephyr 1080i/DialogSeekBar.xml"
        ),
        bar=(60, 1060, 1800),
        border_texture="colors/white.png",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml",
        comment=(
            "Arctic Zephyr 2 Resurrection (skin.arctic.zephyr.2.resurrection.mod).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); raised above OSD_Progress_Text / bar.\n"
            "  Source: github.com/DenDyGH/skin.arctic.zephyr.2.resurrection.mod"
        ),
        bar=(60, 1060, 1800),
        border_texture="diffuse/progress-bg.png",
        anchor_top_override=740,
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.arctic.zephyr.rounded.xml",
        comment=(
            "Arctic Zephyr: Rounded (skin.arctic.zephyr.rounded).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); lifts -74px with full video OSD.\n"
            "  Source: github.com/Nanomani/skin.arctic.zephyr.rounded 1080i/Includes_OSD.xml"
        ),
        bar=(130, 962, 1660),
        border_texture="progress/progress-bg.png",
        osd_slide="rounded_74",
        font="font13",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.aeon.nox.silvo.xml",
        comment=(
            "Aeon Nox SiLVO (skin.aeon.nox.silvo).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); lifts -90px with video OSD (DefaultSeekbar).\n"
            "  Source: github.com/Doctor-Eggs/Aeon-Nox-SiLVO 16x9/Includes.xml"
        ),
        bar=(0, 1039, 1920),
        border_texture="colors/white.png",
        osd_slide="nox_90",
        font="font13",
    ),
    ArcticSnippetSpec(
        filename="DialogSeekBar-skin.bingie.xml",
        comment=(
            "Bingie (skin.bingie).\n"
            "  Fixed anchor + PreviewSlot slides (94100, 0–100); aligned above SeekBar_Bingie.\n"
            "  Source: github.com/matke-84/skin.bingie 1080i/IncludesOSD.xml"
        ),
        bar=(384, 957, 1152),
        border_texture="colors/color_white.png",
        font="Reg28",
    ),
)


def _anchor_top(bar: SeekBarLayout) -> int:
    _, preview_h, label_h = preview_dimensions(1920, 1080, 16 / 9, True)
    return max(8, bar.top - preview_h - label_h - PREVIEW_GAP - PREVIEW_GAP)


def _slot_slides_xml(
    base_left: int,
    bar: SeekBarLayout,
    preview_w: int,
    *,
    prop: str,
    indent: str = "\t\t\t\t",
) -> str:
    lines: list[str] = []
    for slot in range(PREVIEW_SLOTS):
        left = _absolute_left(bar, _slot_ratio(slot), preview_w)
        slide = left - base_left
        lines.append(
            f'{indent}<animation effect="slide" end="{slide},0" time="0" '
            f'condition="String.IsEqual({prop}(Trickplay.PreviewSlot),{slot})">'
            f"Conditional</animation>"
        )
    return "\n".join(lines)


def _osd_slide_xml(kind: str | None) -> str:
    if kind == "ah2_80":
        return (
            '\t\t\t\t<animation effect="slide" start="0" end="0,80" time="300" '
            'tween="sine" easing="out" reversible="false" condition="!'
            "[Window.IsVisible(videoosd) | Window.IsVisible(musicosd) | "
            "Window.IsVisible(script-cu-lrclyrics-main.xml) | $EXP[Exp_OSD_ExpandInfo]]"
            '">Conditional</animation>\n'
            '\t\t\t\t<animation effect="slide" end="0" start="0,80" time="300" '
            'tween="sine" easing="out" reversible="false" condition="'
            "[Window.IsVisible(videoosd) | Window.IsVisible(musicosd) | "
            "Window.IsVisible(script-cu-lrclyrics-main.xml) | $EXP[Exp_OSD_ExpandInfo]]"
            '">Conditional</animation>'
        )
    if kind == "rounded_74":
        return (
            '\t\t\t\t<animation effect="slide" start="0" end="0,-74" time="150" '
            'condition="Window.IsVisible(videoosd) + !Window.IsVisible(VideoOSDBookmarks.xml)">'
            "Conditional</animation>"
        )
    if kind == "nox_90":
        return (
            '\t\t\t\t<animation effect="slide" end="0,-90" time="200" tween="quadratic" '
            'condition="Window.IsActive(videoosd) + !Skin.HasSetting(VideoOSDOnTop)">'
            "Conditional</animation>"
        )
    return ""


def render_snippet(spec: ArcticSnippetSpec) -> str:
    bar = SeekBarLayout(*spec.bar)
    preview_w, _, _ = preview_dimensions(1920, 1080, 16 / 9, True)
    base_left = bar.left
    anchor_top = (
        spec.anchor_top_override
        if spec.anchor_top_override is not None
        else _anchor_top(bar)
    )
    slides_xml = _slot_slides_xml(base_left, bar, preview_w, prop=spec.prop)
    osd_xml = _osd_slide_xml(spec.osd_slide)
    osd_block = f"{osd_xml}\n" if osd_xml else ""
    rev = OVERLAY_REVISION
    p = spec.prop

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  {spec.comment}
  trickplay-overlay-rev:{rev}

  Copy group 94090 below into your skin DialogSeekBar.xml (top-level control).
-->
<window>
\t<controls>
\t\t<control type="group" id="94090">
\t\t\t<!-- trickplay-overlay-rev:{rev} -->
\t\t\t<zorder>999</zorder>
\t\t\t<control type="group" id="94100">
\t\t\t\t<visible>!String.IsEmpty({p}(Trickplay.PreviewImage)) + [String.IsEqual({p}(Trickplay.PreviewVisible),true) | Player.Seeking]</visible>
\t\t\t\t<left>{base_left}</left>
\t\t\t\t<top>{anchor_top}</top>
\t\t\t\t<width>320</width>
\t\t\t\t<height condition="String.IsEqual({p}(Trickplay.ShowTimestamp),true)">220</height>
\t\t\t\t<height condition="!String.IsEqual({p}(Trickplay.ShowTimestamp),true)">180</height>
{osd_block}{slides_xml}
\t\t\t\t<animation effect="fade" start="0" end="100" time="100">Visible</animation>
\t\t\t\t<animation effect="fade" start="100" end="0" time="100">Hidden</animation>
\t\t\t\t<control type="image" id="94106">
\t\t\t\t\t<left>0</left>
\t\t\t\t\t<top>0</top>
\t\t\t\t\t<width>320</width>
\t\t\t\t\t<height>180</height>
\t\t\t\t\t<aspectratio scalediffuse="false">keep</aspectratio>
\t\t\t\t\t<bordertexture border="2" infill="false">{spec.border_texture}</bordertexture>
\t\t\t\t\t<bordersize>2</bordersize>
\t\t\t\t\t<colordiffuse>B3FFFFFF</colordiffuse>
\t\t\t\t</control>
\t\t\t\t<control type="image" id="94101">
\t\t\t\t\t<left>0</left>
\t\t\t\t\t<top>0</top>
\t\t\t\t\t<width>320</width>
\t\t\t\t\t<height>180</height>
\t\t\t\t\t<aspectratio scalediffuse="false">keep</aspectratio>
\t\t\t\t\t<texture background="true">$INFO[{p}(Trickplay.PreviewImage)]</texture>
\t\t\t\t</control>
\t\t\t\t<control type="label" id="94102">
\t\t\t\t\t<visible>String.IsEqual({p}(Trickplay.ShowTimestamp),true)</visible>
\t\t\t\t\t<left>0</left>
\t\t\t\t\t<top>180</top>
\t\t\t\t\t<width>320</width>
\t\t\t\t\t<height>40</height>
\t\t\t\t\t<font>{spec.font}</font>
\t\t\t\t\t<align>center</align>
\t\t\t\t\t<aligny>center</aligny>
\t\t\t\t\t<label>$INFO[{p}(Trickplay.PreviewTime)]</label>
\t\t\t\t\t<textcolor>FFFFFFFF</textcolor>
\t\t\t\t\t<shadowcolor>FF000000</shadowcolor>
\t\t\t\t\t<shadowoffsetx>2</shadowoffsetx>
\t\t\t\t\t<shadowoffsety>2</shadowoffsety>
\t\t\t\t</control>
\t\t\t</control>
\t\t</control>
\t</controls>
</window>
"""


_SLOT_SLIDE_RE = re.compile(
    r'^[ \t]*<animation effect="slide"[^>]*PreviewSlot[^>]*>Conditional</animation>\s*\n',
    re.MULTILINE,
)
_REV_RE = re.compile(r"trickplay-overlay-rev:\d+")
_INFO_LEFT_RE = re.compile(
    r"<left>\$INFO\[(?:Window\(Home\)\.Property|Window\.Property)\(Trickplay\.PreviewLeft(?:Wide)?\)\]</left>"
)
_INFO_TOP_RE = re.compile(
    r"<top>\$INFO\[(?:Window\(Home\)\.Property|Window\.Property)\(Trickplay\.PreviewTop\)\]</top>"
)


def _patch_group_slides(
    text: str,
    group_id: str,
    *,
    base_left: int,
    anchor_top: int,
    bar: SeekBarLayout,
    preview_w: int,
    prop: str,
    indent: str,
) -> str:
    """Replace left/top and PreviewSlot slides inside a group (94100 / 94103)."""
    pat = re.compile(
        rf'(<control type="group" id="{group_id}">)(.*?)(\n[ \t]*</control>)',
        re.DOTALL,
    )
    match = pat.search(text)
    if not match:
        raise SystemExit(f"group {group_id} not found")
    head, body, close = match.group(1), match.group(2), match.group(3)
    body = _SLOT_SLIDE_RE.sub("", body)
    body = _INFO_LEFT_RE.sub(f"<left>{base_left}</left>", body, count=1)
    body = _INFO_TOP_RE.sub(f"<top>{anchor_top}</top>", body, count=1)
    # Also replace plain numeric left/top if already fixed
    body = re.sub(
        r"(^[ \t]*)<left>[^<]*</left>",
        rf"\1<left>{base_left}</left>",
        body,
        count=1,
        flags=re.MULTILINE,
    )
    body = re.sub(
        r"(^[ \t]*)<top>[^<]*</top>",
        rf"\1<top>{anchor_top}</top>",
        body,
        count=1,
        flags=re.MULTILINE,
    )
    slides = _slot_slides_xml(base_left, bar, preview_w, prop=prop, indent=indent)
    # Insert slides before fade Visible animation (or before first nested control)
    fade = re.search(
        r"^[ \t]*<animation effect=\"fade\"[^>]*>Visible</animation>",
        body,
        re.MULTILINE,
    )
    if fade:
        body = body[: fade.start()] + slides + "\n" + body[fade.start() :]
    else:
        nested = re.search(r"^[ \t]*<control type=", body, re.MULTILINE)
        if not nested:
            raise SystemExit(f"cannot insert slides in group {group_id}")
        body = body[: nested.start()] + slides + "\n" + body[nested.start() :]
    return text[: match.start()] + head + body + close + text[match.end() :]


def patch_replace_snippet(
    path: str,
    *,
    bar: tuple[int, int, int],
    wide: tuple[int, int, int] | None = None,
    top_override: int | None = None,
    wide_top_override: int | None = None,
    indent: str = "                ",
) -> None:
    text = open(path, encoding="utf-8").read()
    text = _REV_RE.sub(f"trickplay-overlay-rev:{OVERLAY_REVISION}", text)
    text = text.replace("continuous PreviewLeft/Top", "PreviewSlot slides 0–100")
    preview_w, _, _ = preview_dimensions(1920, 1080, 16 / 9, True)
    seek = SeekBarLayout(*bar)
    top = top_override if top_override is not None else _anchor_top(seek)
    text = _patch_group_slides(
        text,
        "94100",
        base_left=seek.left,
        anchor_top=top,
        bar=seek,
        preview_w=preview_w,
        prop="Window.Property",
        indent=indent,
    )
    if wide is not None:
        wide_bar = SeekBarLayout(*wide)
        wide_top = (
            wide_top_override if wide_top_override is not None else _anchor_top(wide_bar)
        )
        # Estuary wide group 94103 — only when it is the SmallOSD seek group
        if 'id="94103"' in text and "SmallOSDVideo" in text:
            text = _patch_group_slides(
                text,
                "94103",
                base_left=wide_bar.left,
                anchor_top=wide_top,
                bar=wide_bar,
                preview_w=preview_w,
                prop="Window.Property",
                indent=indent,
            )
    # Fuse center group 94103 keeps fixed center left — no slides
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    print(f"patched {os.path.basename(path)} (bar={bar}, top={top})")


def main() -> None:
    out_dir = os.path.join(ROOT, "resources", "skin-snippet")
    for spec in SPECS:
        path = os.path.join(out_dir, spec.filename)
        text = render_snippet(spec)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        bar = SeekBarLayout(*spec.bar)
        print(
            f"wrote {spec.filename} "
            f"(left={bar.left}, top={_anchor_top(bar)}, slots={PREVIEW_SLOTS})"
        )

    # Arctic Fuse: profile seekbar (240,772,1440); historical overlay top ~670
    fuse_indent = "                "
    for name in (
        "DialogSeekBar-skin.arctic.fuse.2.xml",
        "DialogSeekBar-skin.arctic.fuse.3.xml",
    ):
        patch_replace_snippet(
            os.path.join(out_dir, name),
            bar=(240, 772, 1440),
            top_override=670,
            indent=fuse_indent,
        )

    # Estuary Mod v2: normal + wide
    patch_replace_snippet(
        os.path.join(out_dir, "DialogSeekBar-skin.estuary.modv2.xml"),
        bar=(460, 990, 1430),
        wide=(30, 990, 1860),
        top_override=599,
        wide_top_override=599,
        indent="\t\t\t\t",
    )

    # Bump rev on universal + bello
    for name in (
        "DialogSeekBar-universal-dynamic.xml",
        "VideoFullScreen-skin.bello.xml",
    ):
        path = os.path.join(out_dir, name)
        text = _REV_RE.sub(
            f"trickplay-overlay-rev:{OVERLAY_REVISION}",
            open(path, encoding="utf-8").read(),
        )
        open(path, "w", encoding="utf-8", newline="\n").write(text)
        print(f"bumped rev {name}")


if __name__ == "__main__":
    main()

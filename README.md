# service.trickplay

Kodi background service that shows **Jellyfin trickplay** seek thumbnails while scrubbing video.

## Skin integration required

**This addon does not work out of the box.** It runs as a service that crops thumbnails and publishes window properties, but **your active Kodi skin must display them**.

For each skin you use, you must merge trickplay preview controls from this repo into that skin’s own **`DialogSeekBar.xml`**.

The reference snippet in this addon is:

`resources/skin-snippet/DialogSeekBar-skin.estuary.modv2.xml`

That filename is deliberate: it is **not** dropped into Kodi as-is. It was built for **Estuary Mod v2** (EstuaryMod-style layouts). Copy the preview block from that file into your skin’s real **`DialogSeekBar.xml`**. Other skins need the same approach, but coordinates, control IDs, and visibility conditions will differ.

### What to read in your skin

Before editing `DialogSeekBar.xml`, inspect your skin’s:

| File | What to look for |
|---|---|
| **`Includes.xml`** | The `SeekBar` / `SeekBarProgress` include — seek bar `<left>`, `<right>`, `<top>`, width, and hidden seek button id (often **87**). OSD button grouplist id (often **200**) if you care when the preview hides on play/pause focus. |
| **`Variables.xml`** | Expressions such as **`isSeeking`** used by the seek bar and OSD visibility. |
| **`DialogSeekBar.xml`** | Where the seek bar is included, scope-mode slide offsets, and `SmallOSDVideo` / `ShowSeekBar` skin settings. |
| **`VideoOSD.xml`** (optional) | How focus moves between play controls and the seek bar. |

The service positions previews using geometry derived from those values. If they do not match your skin, the thumbnail will drift or sit in the wrong place.

### Geometry in this addon

Seek bar layout constants live in **`osd_layout.py`** (1920×1080 coordinates):

- Normal OSD: seek bar left **460**, right margin **30** → width **1430**
- Small/wide OSD: left **30**, right **30** → width **1860**
- Preview uses **51** horizontal slots (`PREVIEW_SLOTS`) with matching slide animations in the skin snippet

If your skin’s `SeekBar` include uses different `left` / `right` values, update **`osd_layout.py`** and regenerate the slide tables in **`DialogSeekBar-skin.estuary.modv2.xml`** so they stay in sync.

### Merge checklist

1. Copy the **`94090`** trickplay overlay group from `resources/skin-snippet/DialogSeekBar-skin.estuary.modv2.xml` into your skin’s `DialogSeekBar.xml` (as a top-level control, not nested inside unrelated groups).
2. Confirm preview visibility uses `Trickplay.PreviewVisible` (set by the service).
3. Confirm slide animations cover slots **0–50** if you keep `PREVIEW_SLOTS = 51`.
4. Reload the skin or restart Kodi after changes.

Without this merge, the service will still load trickplay data and log preview updates, but **nothing will appear on screen**.

---

## How it works

Jellyfin stores trickplay sprites next to your media:

```text
/path/to/Show.S01E01.mkv
/path/to/Show.S01E01.trickplay/
└── 320 - 10x10/
    ├── 0.jpg    # 10×10 grid of 320 px-wide thumbs (100 frames)
    ├── 1.jpg
    └── ...
```

When playback starts, the service locates the matching `.trickplay` folder, maps the seek position to a tile file and grid cell, crops the frame, and sets **DialogSeekBar window properties** for the skin to render.

### Main window properties

| Property | Description |
|---|---|
| `Trickplay.PreviewVisible` | `true` when the skin should show the preview |
| `Trickplay.PreviewImage` | Path to the cropped preview JPEG |
| `Trickplay.PreviewTime` | Target position (formatted timestamp) |
| `Trickplay.PreviewSlot` | Horizontal slot index (0–50) for slide animations |
| `Trickplay.Available` | `true` when trickplay data was found for the current file |

Additional placement/debug properties (`Trickplay.PreviewLeft`, `Trickplay.PreviewTop`, etc.) are also published.

## Requirements

- Local or NFS media files with Jellyfin trickplay sidecars (`Save trickplay with media` enabled in Jellyfin)
- **Skin edit** to `DialogSeekBar.xml` (see above)
- **`script.module.pillow`** or **`tools.ffmpeg-tools`** (crops one frame from each sprite tile)

## Settings

- **Preferred tile width** — resolution folder to use (default `320` for `320 - 10x10`)
- **Thumbnail interval (ms)** — Jellyfin default is `10000` (one thumb every 10 s)
- **Seek poll interval (ms)** — refresh rate while scrubbing (default `100`)
- **Enable debug logging** — logs seek targets, preview slots, and visibility toggles

## Installation

1. Zip the `service.trickplay` folder so `addon.xml` is at the root of the archive.
2. In Kodi: **Settings → Add-ons → Install from zip file**.
3. **Merge the skin snippet** into your active skin’s `DialogSeekBar.xml` (required).
4. Enable the service if needed (**Settings → Add-ons → My add-ons → Services**).
5. Tail `kodi.log` for `[service.trickplay]` messages when debugging.

## Supported paths

- Direct local video files (`.mkv`, `.mp4`, …)
- NFS/SMB paths (`nfs://`, `smb://`)
- `.strm` files that point to a local or network path

Plugin / HTTP streams are skipped because Jellyfin trickplay sidecars are stored on disk next to the source file.

## Example

For a 4005 s episode with 10 s intervals:

- 401 thumbnails across 5 tile JPEGs (`0.jpg`–`3.jpg` full, `4.jpg` partial)
- Seeking to **2:30** → thumb index 15 → tile `0.jpg`, row 1, column 5

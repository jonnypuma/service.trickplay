# service.trickplay

<img width="424" height="395" alt="icon" src="https://github.com/user-attachments/assets/52bc6554-8d8f-4229-8801-80cecc7f0354" />

Kodi background service that can generate/show **Jellyfin trickplay** or custom trickplay thumbnails.

## Skin integration required

**This addon does not work out of the box.** It runs as a service that crops thumbnails and publishes window properties, but **your active Kodi skin must display them**.

For each skin you use, you must merge trickplay preview controls from this repo into that skin’s own **`DialogSeekBar.xml`**.

The reference snippets in this addon are:

| Skin | Snippet file |
|---|---|
| Estuary Mod v2 | `resources/skin-snippet/DialogSeekBar-skin.estuary.modv2.xml` |
| Arctic Fuse 3 | `resources/skin-snippet/DialogSeekBar-skin.arctic.fuse.3.xml` |

Those filenames are deliberate: they are **not** dropped into Kodi as-is. Copy the preview block from the matching file into your skin’s real **`DialogSeekBar.xml`**. Other skins need the same approach, but coordinates, control IDs, and visibility conditions will differ.

### Skin profiles (auto-detect)

The service detects your active Kodi skin (`xbmc.gui` addon id) and selects seek bar geometry and focus behavior from **`skin_profiles.py`**:

| Profile | Skin IDs | Seek bar (left, top, width) |
|---|---|---|
| Estuary Mod v2 | `skin.estuary.modv2`, `skin.estuary.mod`, … | 460, 990, 1430 (+ wide 30, 990, 1860) |
| Arctic Fuse 3 | `skin.arctic.fuse.3`, … | 240, 772, 1440 |

Unknown skins fall back to Estuary Mod v2 geometry and log a warning. Override manually under **Add-on settings → Skin profile** if auto-detect is wrong.

You still must merge the matching XML snippet so slide animations align with the profile geometry.

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

Seek bar layout is defined per skin in **`skin_profiles.py`** and applied automatically. Each profile supplies 1080p coordinates `(left, top, width)` used to compute **`Trickplay.PreviewSlot`** (51 slots). The matching skin snippet must use the same geometry in its anchor and slide animations.

To add a new skin, define a profile in `skin_profiles.py`, add a `DialogSeekBar-skin.*.xml` snippet, and map the skin addon id in `PROFILES_BY_SKIN_ID`.

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
└── 320 - 10x10 - 10000/
    ├── 0.jpg    # 10×10 grid of 320 px-wide thumbs (100 frames)
    ├── 1.jpg
    └── ...
```

Legacy Jellyfin folders without an interval suffix (`320 - 10x10/`) are treated as **10000 ms** between thumbnails.

When playback starts, the service locates the matching `.trickplay` folder, maps the seek position to a tile file and grid cell, crops the frame, and sets **DialogSeekBar window properties** for the skin to render. A background prefetch worker pre-crops neighbouring cells (direction-biased ±3–5 indices, plus cells in the current sprite tile) so stepping/scrubbing nearby positions is usually instant after the first frame.

### Main window properties

| Property | Description |
|---|---|
| `Trickplay.PreviewVisible` | `true` when the skin should show the preview |
| `Trickplay.PreviewImage` | Path to the cropped preview JPEG |
| `Trickplay.PreviewTime` | Target position (formatted timestamp) |
| `Trickplay.PreviewSlot` | Horizontal slot index (0–50) for slide animations |
| `Trickplay.ShowTimestamp` | `true` when the skin should show the time label |
| `Trickplay.PreviewColorDiffuse` | Kodi `colordiffuse` ARGB (e.g. `FFFFFFFF` = opaque); driven by **Preview opacity** setting |
| `Trickplay.Available` | `true` when trickplay data was found for the current file |

Additional placement/debug properties (`Trickplay.PreviewLeft`, `Trickplay.PreviewTop`, etc.) are also published.

## Requirements

- Local or NFS media files with Jellyfin trickplay sidecars (`Save trickplay with media` enabled in Jellyfin), **or** use the built-in generator (see below)
- **Skin edit** to `DialogSeekBar.xml` (see above)
- **tools.ffmpeg-tools** — crops one frame from each sprite tile (required dependency; install from your Kodi repository before this addon)

## Settings

- **Preferred tile width** — resolution folder to use (default `320` for `320 - 10x10 - 10000`)
- **Preview tile grid layout** — always visible: **From folder name** (default, reads `10x10` from `320 - 10x10 - 10000/`, etc.) or fixed **10×10**, **20×20**, **5×5**, **15×15**, **Custom** when sprites don't match the folder name
- **Thumbnail interval (ms)** — used to select a matching sidecar folder and as fallback when the folder name has no interval (default `10000`)
- **Seek poll interval (ms)** — refresh rate while scrubbing (default `100`)
- **Skin profile** — auto-detect active skin, or force Estuary Mod v2 / Arctic Fuse 3
- **Preview hold time (seconds)** — how long the preview stays after seeking stops (0 = until OSD closes, thumbnail follows playback; default 4)
- **Show timestamp** — show or hide the seek position label under the thumbnail
- **Preview opacity (%)** — overall preview transparency (0–100, default 100 = fully opaque)
- **Enable debug logging** — logs seek targets, preview slots, visibility toggles, and active skin profile

### Prefetch (Settings → Prefetch)

- **Enable prefetch** — master toggle for background pre-cropping
- **Prefetch on playback start** — warm cache around the current playhead when a video loads
- **Prefetch whole sprite tile** — queue extra cells from the current sprite JPG during scrubbing
- **Prefetch idle sprite tile** — fill in the rest of the tile while the OSD is open and idle
- **Prefetch radius** — indices ahead/behind to pre-crop (default 5)
- **Prefetch queue size** — max pending background crops (default 48)
- **Crop cache limit (MB)** — LRU cap for cropped JPEGs (default 500; 0 = unlimited)

### Trickplay generator (Settings → Trickplay generator)

Off by default. When disabled, all generator options are hidden.

- **Enable trickplay generator** — master toggle
- **Generate while idle** — when Kodi is not playing video, generate one missing sidecar at a time from the library folder (background service)
- **Generate on library update** — after a library scan, batch-generate trickplay only for videos added during that scan (separate from idle generation)
- **Library update: only when not playing** — defer the post-scan batch until playback has stopped (default on)
- **Overwrite existing sidecars** — replace matching `{width} - {grid} - {intervalMs}/` under `.trickplay` when already present (default off; existing sidecars are skipped)
- **Library folder** — root path for batch and idle scans (must be writable for sidecar output). **Configure** the generator here, press **OK** to save, then use **Run** on the add-on’s Information page to start batch generation (not from inside Configure). If the path is empty or missing, batch generation opens the full Kodi folder browser and saves your selection. Prefer your OS mount path (e.g. `/storage/remote-shares/…`) when available — it is faster than `nfs://` URLs for generation.
- **Generator thumbnail interval (ms)** — time between generated frames; included in the sidecar folder name (default `10000`, e.g. `320 - 10x10 - 1000`)
- **Tile grid layout** — grid written into the sidecar folder name (e.g. `320 - 20x20 - 10000`); uses **Preferred tile width** and **Generator thumbnail interval**
- **Run** (add-on Information page) — scan the library folder and generate all missing sidecars with a progress dialog. Use **Configure** first and press **OK** so settings are saved before **Run**.

Generation requires **write access** next to your media files. Pauses automatically during video playback.

## Installation

1. Install **tools.ffmpeg-tools** from your Kodi repository (required).
2. Zip the `service.trickplay` folder so `addon.xml` is at the root of the archive.
3. In Kodi: **Settings → Add-ons → Install from zip file**.
4. **Merge the skin snippet** into your active skin’s `DialogSeekBar.xml` (required).
5. Enable the service if needed (**Settings → Add-ons → My add-ons → Services**).
6. Tail `kodi.log` for `[service.trickplay]` messages when debugging.

## Supported paths

- Direct local video files (`.mkv`, `.mp4`, …)
- NFS/SMB paths (`nfs://`, `smb://`) — playback and sidecar lookup use Kodi VFS; **generation** prefers an OS-mounted path when the share is mounted on the device, otherwise streams the file through VFS into ffmpeg (slower, one full read per file)
- `.strm` files that point to a local or network path

Plugin / HTTP streams are skipped because Jellyfin trickplay sidecars are stored on disk next to the source file.

## Example

For a 4005 s episode with 10 s intervals:

- 401 thumbnails across 5 tile JPEGs (`0.jpg`–`3.jpg` full, `4.jpg` partial)
- Seeking to **2:30** → thumb index 15 → tile `0.jpg`, row 1, column 5

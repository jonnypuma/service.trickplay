# service.trickplay

<img width="424" height="395" alt="icon" src="https://github.com/user-attachments/assets/52bc6554-8d8f-4229-8801-80cecc7f0354" />

Kodi background service that can generate/show **Jellyfin trickplay** or custom trickplay thumbnails (tile grid, duration and resolution can be customized).

## Skin integration required

**This addon does not work out of the box.** It runs as a service that crops thumbnails and publishes window properties, but **your active Kodi skin must display them**.

For each skin you use, you must merge trickplay preview controls from this repo into that skin’s own **`DialogSeekBar.xml`**.

The reference snippets in this addon are:

| Skin | Snippet file | Profile / notes |
|---|---|---|
| Estuary Mod v2 | `resources/skin-snippet/DialogSeekBar-skin.estuary.modv2.xml` | Slot slides |
| Arctic Fuse 3 | `resources/skin-snippet/DialogSeekBar-skin.arctic.fuse.3.xml` | Slot slides + full OSD center group |
| Arctic Fuse 2 | `resources/skin-snippet/DialogSeekBar-skin.arctic.fuse.2.xml` | Slot slides + full OSD center group |
| Estuary (stock) | `resources/skin-snippet/DialogSeekBar-skin.estuary.xml` | Dynamic `$INFO` placement |
| Aeon Nox SiLVO | `resources/skin-snippet/DialogSeekBar-skin.aeon.nox.silvo.xml` | Slot slides + Home properties |
| Arctic Zephyr | `resources/skin-snippet/DialogSeekBar-skin.arctic.zephyr.xml` | Slot slides + Home properties |
| Arctic Zephyr 2 Resurrection | `resources/skin-snippet/DialogSeekBar-skin.arctic.zephyr.2.resurrection.xml` | Slot slides + Home properties |
| Arctic Zephyr Rounded | `resources/skin-snippet/DialogSeekBar-skin.arctic.zephyr.rounded.xml` | Slot slides + Home properties |
| Arctic Horizon | `resources/skin-snippet/DialogSeekBar-skin.arctic.horizon.xml` | Slot slides + Home properties |
| Arctic Horizon 2 | `resources/skin-snippet/DialogSeekBar-skin.arctic.horizon.2.xml` | Slot slides + Home properties |
| Arctic Horizon 2.1 Arizen | `resources/skin-snippet/DialogSeekBar-skin.arctic.horizon.2.1.arizen.xml` | Slot slides + Home properties |
| Bello | `resources/skin-snippet/VideoFullScreen-skin.bello.xml` | Center seek OSD in `VideoFullScreen.xml` (fixed below seek box @ 720p) |
| Bingie | `resources/skin-snippet/DialogSeekBar-skin.bingie.xml` | Slot slides + Home properties |
| Any other skin | `resources/skin-snippet/DialogSeekBar-universal-dynamic.xml` | Pick closest skin profile in settings |

### Tested skins

The following skins have been tested with trickplay preview while scrubbing:

- Aeon Nox SiLVO
- Arctic Fuse 2
- Arctic Fuse 3
- Arctic Horizon 2
- Arctic Zephyr 2 Resurrection
- Arctic Zephyr Rounded
- Bingie
- Estuary Mod v2

Those filenames are deliberate: they are **not** dropped into Kodi as-is. Either:

- Use **Add-on settings → Preview tools → Show addon status** to see whether the active skin snippet is missing or stale, then **Install skin snippet (current skin)** (updates stale overlays) or **Force reinstall skin snippet** if needed. Install backs up each skin’s target XML (usually `DialogSeekBar.xml`; Bello uses `VideoFullScreen.xml`) and merges overlay group **94090** (or full replace for Estuary Mod v2 / Arctic Fuse), **or**
- Manually copy the preview block from the matching file into your skin’s real target XML (backup the original first).

Skins without a discoverable `DialogSeekBar.xml` under their add-on folder are skipped and reported as failed.

### Skin profiles (auto-detect)

The service detects your active Kodi skin (`xbmc.gui` addon id) and selects seek bar geometry and focus behavior from **`skin_profiles.py`**:

| Profile | Skin IDs | Seek bar (left, top, width) |
|---|---|---|
| Estuary Mod v2 | `skin.estuary.modv2`, `skin.estuary.mod`, … | 460, 990, 1430 (+ wide 30, 990, 1860) |
| Arctic Fuse 3 | `skin.arctic.fuse.3`, … | 240, 772, 1440 |
| Arctic Fuse 2 | `skin.arctic.fuse.2`, … | 240, 772, 1440 |
| Estuary (stock) | `skin.estuary` | 480, 990, 960 |
| Aeon Nox SiLVO | `skin.aeon.nox.silvo`, `skin.aeon.nox`, … | 0, 1039, 1920 |
| Arctic Zephyr | `skin.arctic.zephyr`, … | 60, 1060, 1800 |
| Arctic Zephyr 2 Resurrection | `skin.arctic.zephyr.2.resurrection.mod`, … | 60, 1060, 1800 |
| Arctic Zephyr Rounded | `skin.arctic.zephyr.rounded`, … | 130, 962, 1660 |
| Arctic Horizon | `skin.arctic.horizon`, … | 40, 920, 1840 |
| Arctic Horizon 2 | `skin.arctic.horizon.2`, … | 20, 720, 1840 |
| Arctic Horizon 2.1 Arizen | `skin.arctic.horizon.2.1.arizen`, … | 20, 720, 1840 |
| Bello | `skin.bello`, `skin.bello.9`, `skin.bello.10`, … | 478, 560, 320 (center seek OSD in `VideoFullScreen.xml`) |
| Bingie | `skin.bingie`, … | 384, 957, 1152 (+ wide 525, 934, 700 classic OSD) |

For **Arctic Fuse 3** and **Arctic Fuse 2**, the snippet includes preview groups **94090** (overlay root), **94100** (seek-bar aligned, slot slides), and **94103** (centered above the seek bar at the same height as minimal mode when full OSD is open). The service sets `Trickplay.PreviewLayout` to `seekbar` or `center` automatically. Re-install from the matching `DialogSeekBar-skin.arctic.fuse.*.xml` if you installed an older snippet missing **94100** / **94103**.

Unknown skins fall back to Estuary Mod v2 geometry and log a warning. Override manually under **Add-on settings → Skin profile** if auto-detect is wrong.

You still must merge the matching XML snippet. For **dynamic** snippets, set the correct **Skin profile** in add-on settings; the service publishes `Trickplay.PreviewLeft/Top/Width/Height`. For **slot-slide** snippets (Estuary Mod v2, AF3), profile geometry must match the slide table in the XML.

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

### Skin: hide seek OSD during Skippy skips

If you use **[service.skippy](https://github.com/Skippy-McSkipface/service.skippy)** (intro/recap skip), Skippy sets `Window(Home).Property(Skippy.Skipping)` while an auto-skip or confirmed ask-skip seek is in progress. To avoid the seek bar flashing during those jumps, add this as an extra `<visible>` tag (Kodi ANDs multiple tags) on the seek bar window or control:

```xml
<visible>String.IsEmpty(Window(Home).Property(Skippy.Skipping))</visible>
```

Manual seeks are unaffected — only Skippy-driven skips set the property.

**Trickplay skin snippets include this automatically:**

| Install mode | Where it is applied |
|---|---|
| **Merge** (overlay group `94090`) | On overlay group `94090` **and** injected on the host `DialogSeekBar.xml` window before `<controls>` when you use **Install skin snippet** |
| **Replace** (Estuary Mod v2, Arctic Fuse 2/3) | On the `DialogSeekBar.xml` window |
| **Bello** (`VideoFullScreen.xml`) | On trickplay overlay group `94090` **and** on Bello’s native seek OSD groups (center box + simple seek bars) when you use **Install skin snippet** |

Re-run **Add-on settings → Preview tools → Install skin snippet** to pick up Skippy support on an existing install (stale overlays without `Skippy.Skipping` are treated as needing refresh).

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

When playback starts, the service locates the matching `.trickplay` folder, maps the seek position to a tile file and grid cell, crops the active cell with Pillow, and publishes **DialogSeekBar window properties** for the skin to render.

Prefetch pre-crops neighbouring cells in the background. **During playback** (default), the service keeps the configured **prefetch radius** warm symmetrically around the moving playhead — not only when the seek bar opens. Radius is in **thumb indices** (e.g. radius 5 with a 10 s interval ≈ ±50 s on the timeline).

### Main window properties

| Property | Description |
|---|---|
| `Trickplay.PreviewVisible` | `true` when the skin should show the preview |
| `Trickplay.PreviewImage` | Path to a cropped preview JPEG for the active cell |
| `Trickplay.PreviewTime` | Target position (formatted timestamp) |
| `Trickplay.PreviewSlot` | Horizontal slot index (0–50) for slide animations |
| `Trickplay.ShowTimestamp` | `true` when the skin should show the time label |
| `Trickplay.PreviewColorDiffuse` | Kodi `colordiffuse` ARGB (e.g. `FFFFFFFF` = opaque); driven by **Preview opacity** setting |
| `Trickplay.Available` | `true` when trickplay data was found for the current file |

Additional placement/debug properties (`Trickplay.PreviewLeft`, `Trickplay.PreviewTop`, etc.) are also published.

## Requirements

- Local or NFS media files with Jellyfin trickplay sidecars (`Save trickplay with media` enabled in Jellyfin), **or** use the built-in generator (see below)
- **Skin edit** to `DialogSeekBar.xml` (or `VideoFullScreen.xml` for Bello) — see above
- **Pillow** — required for cropping preview cells and sidecar dimension probing. Auto-installed via **Install preview tools** when needed.
- **ffmpeg** and **ffprobe** — required only for trickplay **generation** (and HDR tone mapping); auto-installed via **Install preview tools** when the generator or HDR tone mapping is enabled, batch **Run**, or manual install under `/storage/.kodi/system/ffmpeg/` (CoreELEC) / `addon_data/.../system/ffmpeg/` (Windows)

## Settings

- **Preferred tile width** — resolution folder to use (default `320` for `320 - 10x10 - 10000`)
- **Preview tile grid layout** — always visible: **From folder name** (default, reads `10x10` from `320 - 10x10 - 10000/`, etc.) or fixed **10×10**, **20×20**, **5×5**, **15×15**, **Custom** when sprites don't match the folder name
- **Thumbnail interval (ms)** — used to select a matching sidecar folder and as fallback when the folder name has no interval (default `10000`)
- **Interval selection** — when several sidecar folders share the same tile width (e.g. `320 - 10x10 - 5000` and `320 - 10x10 - 10000`), **Preferred interval** uses the thumbnail interval setting; **Shortest interval** picks the finest-grained previews available
- **Seek poll interval (ms)** — refresh rate while scrubbing (default `100`)
- **Skin profile** — auto-detect active skin, or force a listed profile (Estuary Mod v2, Arctic Fuse 3, Estuary stock, Aeon Nox SiLVO, Arctic Zephyr, Arctic Horizon)
- **Enable debug logging** — logs seek targets, preview slots, visibility toggles, and active skin profile

### Preview adjustment (Settings → Preview adjustment)

- **Preview scale (%)** — thumbnail size relative to default (100 = normal)
- **Preview horizontal / vertical offset (px)** — nudge placement @ 1080p
- **Preview hold time (seconds)** — how long the preview stays after seeking stops (0 = follow playhead until OSD closes; default 4)
- **Show timestamp** — seek position label under the thumbnail
- **Preview opacity (%)** — overall transparency (0–100)
- **Show preview when play controls focused** — keep preview visible while the OSD play/pause row has focus (default on)

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
- **Frame extraction mode** — **Accurate** (slow, frame-accurate), **Fast** (default), or **Experimental**
- **Generator ffmpeg path** — optional; folder (e.g. `/storage/.kodi/system/ffmpeg/`) or `ffmpeg` binary. Always visible in settings (even when the generator is off). Leave empty to auto-use the default install folder when present, otherwise `PATH` / `/usr/bin/ffmpeg`. Used for **generation only** (preview cropping uses Pillow). Use **Install preview tools** when the generator or HDR tone mapping is enabled, or batch **Run** when generating. See [Custom ffmpeg for HDR generation](#custom-ffmpeg-for-hdr-generation) below.
- **HDR tone mapping for previews** — optional; tone-maps HDR/DV to SDR when generating JPEGs (default off). Requires **zscale** or **libplacebo** in the generator ffmpeg. With tone mapping on, **Run** can prompt to download a pinned build if none is installed.
- **HDR dovi_tool fallback** — optional sub-setting when tone mapping is on; runs `dovi_tool` if ffprobe finds no HDR signals (default off; place `dovi_tool` in generator ffmpeg `bin/` or on PATH, local files only). With fallback on, **Run** can prompt to download **dovi_tool 2.3.2** into the generator tools folder.
- **Skip Dolby Vision Profile 5** — optional when tone mapping is on; skips web-style DV P5 files in batch (full dovi_tool convert is very slow on CoreELEC).
- **Windows hardware decode** — optional; on Windows only, uses D3D11VA GPU **10-bit / HDR / Dolby Vision HEVC** decode during thumbnail extraction (~25–30% faster on **4K HDR/DV** with the Gyan full ffmpeg build). **Not a general “HW everything” switch:** 1080p H.264 SDR and similar content should stay on software decode — per-frame GPU paths did not beat CPU in testing and can be slower on deep seeks into large remuxes. Applied only when ffprobe reports **HEVC** with 10-bit and/or HDR/DV; AVC and SDR 8-bit HEVC use software decode (with fps-batch per tile when the interval is above 5 s). After the first HW failure on a file, software decode is used for the rest of that job. Works with zscale and libplacebo (Vulkan) tonemapping. No effect on Linux or CoreELEC.
- **Overwrite existing sidecars** — replace matching sidecar folders when already present (default off). Skips Jellyfin legacy folders such as `320 - 10x10/` (treated as 10000 ms) when generator settings match width, grid, and interval
- **Library folder** — root path for batch and idle scans (must be writable for sidecar output). **Configure** the generator here, press **OK** to save, then use **Run** on the add-on’s Information page to start batch generation (not from inside Configure). If the path is empty or missing, batch generation opens the full Kodi folder browser and saves your selection. Prefer your OS mount path (e.g. `/storage/remote-shares/…`) when available — it is faster than `nfs://` URLs for generation.
- **Generator thumbnail interval (ms)** — time between generated frames; included in the sidecar folder name (default `10000`, e.g. `320 - 10x10 - 1000`)
- **Tile grid layout** — grid written into the sidecar folder name (e.g. `320 - 20x20 - 10000`); uses **Preferred tile width** and **Generator thumbnail interval**
- **Run** (add-on Information page) — scan the library folder and generate all missing sidecars with a progress dialog. Use **Configure** first and press **OK** so settings are saved before **Run**.

Generation requires **write access** next to your media files. Pauses automatically during video playback.

### Custom ffmpeg for HDR generation

**Generator ffmpeg** (auto-installed or manual) includes **zscale** for HDR trickplay. Without it, HDR previews may look washed out until you install a capable build via batch **Run**.

Pre-built releases: **[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases)** (Linux) and **[Gyan CODEX ffmpeg](https://www.gyan.dev/ffmpeg/builds/)** (Windows).

#### Which download?

| Device / OS | Build | Notes |
|---|---|---|
| CoreELEC / LibreELEC on **Ugoos AM9 Pro** and similar | BtbN `ffmpeg-…-linuxarm64-gpl-8.1.tar.xz` | Static **zscale**; Profile 5 uses **dovi_tool** |
| **x86_64** Linux (Ryzen headless Kodi, etc.) | BtbN `ffmpeg-…-linux64-gpl-8.1.tar.xz` | Static **zscale** |
| **Windows Kodi (x64)** | [Gyan `ffmpeg-8.1.1-full_build.zip`](https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-full_build.zip) | Static **zscale + libplacebo** (DV Profile 5 via Vulkan) |

On **Linux / CoreELEC**, prefer **`-gpl-8.1`** static (not `-gpl-shared`). The shared tarball often exposes only `tonemap` on embedded Kodi even with `LD_LIBRARY_PATH` set.

#### Automatic install (Install preview tools / batch Run)

**Install preview tools** (top of add-on settings) downloads **Pillow** for preview cropping when it is not already available. When the **generator** is enabled or **HDR tone mapping** is on, it also offers ffmpeg/ffprobe (and optional HDR extras). Batch **Run** prompts for generator ffmpeg before generation (base ffmpeg even when HDR tone mapping is off; HDR upgrade, Vulkan loader, and dovi_tool when those settings require them).

On first playback with trickplay sidecars but no Pillow, the service may prompt once per Kodi session to install (decline with **Continue without** to skip until restart).

| Component | Auto-install source | Install location |
|---|---|---|
| **Pillow** (preview) | PyPI wheel (pinned) | `special://profile/addon_data/service.trickplay/system/python/site-packages/` |
| **ffmpeg** (generation) — CoreELEC / LibreELEC / Linux Kodi | BtbN **gpl-8.1** | `/storage/.kodi/system/ffmpeg/` (ffmpeg, ffprobe, **dovi_tool** in `bin/`) |
| **ffmpeg** (generation) — Windows Kodi (x64) | Gyan **full build** zip (GitHub) | `special://profile/addon_data/service.trickplay/system/ffmpeg/` (`bin/` includes **dovi_tool.exe** when installed) |

You can decline and continue without a capable ffmpeg (HDR previews may look washed out), or install manually using the steps below.

When **HDR dovi_tool fallback** is enabled and `dovi_tool` is missing, **Run** offers to download **dovi_tool 2.3.2** into the generator ffmpeg **`bin/`** folder (same location as auto-installed ffmpeg — survives add-on updates).

Pinned **Linux** (autobuild-2026-06-13-13-31): [linuxarm64 gpl-8.1](https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-06-13-13-31/ffmpeg-n8.1.1-13-g83e8541aa6-linuxarm64-gpl-8.1.tar.xz), [linux64 gpl-8.1](https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-06-13-13-31/ffmpeg-n8.1.1-13-g83e8541aa6-linux64-gpl-8.1.tar.xz).

Pinned **Windows x64**: [Gyan ffmpeg-8.1.1-full_build.zip](https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-full_build.zip).

Pinned **dovi_tool** (2.3.2): [linuxarm64](https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/dovi_tool-2.3.2-aarch64-unknown-linux-musl.tar.gz), [linux64](https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/dovi_tool-2.3.2-x86_64-unknown-linux-musl.tar.gz), [win64](https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/dovi_tool-2.3.2-x86_64-pc-windows-msvc.zip), [winarm64](https://github.com/quietvoid/dovi_tool/releases/download/2.3.2/dovi_tool-2.3.2-aarch64-pc-windows-msvc.zip).

After download, verify on the device:

```bash
/storage/.kodi/system/ffmpeg/bin/ffmpeg -hide_banner -filters 2>&1 | grep -E 'zscale|libplacebo|tonemap'
```

On Windows, add the install `bin/` folder to `PATH` if needed before running the same check.

You want **zscale** and/or **libplacebo**, not just `tonemap`. If you only see `tonemap`, replace a broken **`-gpl-shared`** Linux install with **`-gpl`** (or re-run **Run** on add-on **3.0.10+**).

#### Where to extract (CoreELEC / LibreELEC)

Default layout (auto-detected when **Generator ffmpeg path** is empty):

```text
/storage/.kodi/system/ffmpeg/
└── bin/
    ├── ffmpeg
    ├── ffprobe
    └── dovi_tool          ← auto-install (3.2.0+); survives add-on updates
```

(`lib/` is only needed for Windows gpl-shared or manual Linux shared installs.)

Steps:

1. Extract the **`-gpl`** tarball on a PC or on the box (Linux) or **`-gpl-shared`** zip (Windows).
2. Copy the **`bin`** folder into `/storage/.kodi/system/ffmpeg/` (and **`lib`** on Windows).
3. Make binaries executable: `chmod +x /storage/.kodi/system/ffmpeg/bin/ffmpeg /storage/.kodi/system/ffmpeg/bin/ffprobe` (and `dovi_tool` if installed manually)
4. Leave **Generator ffmpeg path** empty (uses the folder above) or set it explicitly to `/storage/.kodi/system/ffmpeg/` or `/storage/.kodi/system/ffmpeg/bin/ffmpeg`.

On **x86_64** Linux Kodi, use the same folder layout under `/storage/.kodi/system/ffmpeg/` (or set **Generator ffmpeg path** to your install location).

The add-on logs the chosen binary at generation start, e.g. `Generator ffmpeg: … (default (/storage/.kodi/system/ffmpeg))`. With HDR tone mapping enabled you should see `using zscale + tonemap` or `using libplacebo` in `kodi.log`.

#### libplacebo + Vulkan on Windows and desktop Linux

**Gyan full build** on Windows includes **libplacebo** and **zscale** in a static `bin/ffmpeg.exe`. Dolby Vision Profile 5 uses **libplacebo + apply_dolbyvision** when Vulkan init succeeds (install may bundle `vulkan-1.dll` beside ffmpeg). Enable **Windows hardware decode** for **4K HDR/DV HEVC** only (~25–30% faster there); leave it off or expect no benefit for 1080p H.264 libraries — software + fps-batch is the right path for those.

BtbN **`-gpl-8.1`** on Linux is static with **zscale**; **libplacebo** may be absent. On **CoreELEC** there is usually no usable Vulkan stack; Profile 5 DV uses **dovi_tool + zscale** instead (no libplacebo). Hardware decode is Windows-only.

On **desktop Linux** (e.g. headless Kodi on Ryzen with NVIDIA/AMD), if `-init_hw_device vulkan` fails even though `libvulkan` is installed, export the ICD path before starting Kodi (or in the service environment):

```bash
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json   # or amd_icd64.json, etc.
export VK_LAYER_PATH=/usr/share/vulkan/explicit_layer.d   # if needed
```

Then verify:

```bash
/storage/.kodi/system/ffmpeg/bin/ffmpeg -hide_banner -init_hw_device vulkan=vk \
  -f lavfi -i nullsrc -frames:v 1 -f null -
```

Generator subprocesses inherit the Kodi process environment (`VK_*` vars are not stripped). The add-on logs a hint when Vulkan init fails but ICD configs are present on disk.

## Installation

1. Zip the `service.trickplay` folder so `addon.xml` is at the root of the archive.
2. In Kodi: **Settings → Add-ons → Install from zip file**.
3. **Install the skin snippet** via **Install skin snippet (current skin)** in add-on settings, or merge manually into `DialogSeekBar.xml` (required).
4. Enable the service if needed (**Settings → Add-ons → My add-ons → Services**).
5. For preview cropping: use **Install preview tools** in add-on settings (Pillow). For generation: enable the generator and use **Install preview tools** or batch **Run** — see [Custom ffmpeg for HDR generation](#custom-ffmpeg-for-hdr-generation).
6. Tail `kodi.log` for `[service.trickplay]` messages when debugging.

## Supported paths

- Direct local video files (`.mkv`, `.mp4`, …)
- NFS/SMB paths (`nfs://`, `smb://`) and OS mount paths (e.g. `/storage/remote-shares/…`) — playback sidecar lookup tries all path forms; listing prefers the OS mount when available, then Kodi VFS. **Generation** also prefers an OS-mounted path when the share is mounted on the device, otherwise streams the file through VFS into ffmpeg (slower, one full read per file)
- `.strm` files that point to a local or network path

Plugin / HTTP streams are skipped because Jellyfin trickplay sidecars are stored on disk next to the source file.

## Example

For a 4005 s episode with 10 s intervals:

- 401 thumbnails across 5 tile JPEGs (`0.jpg`–`3.jpg` full, `4.jpg` partial)
- Seeking to **2:30** → thumb index 15 → tile `0.jpg`, row 1, column 5

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.2.0] - 2026-05-22

### Added

- **Restore skin snippet** — **Restore skin snippet (current skin)** and **(all skins)** under Preview tools. Restores `DialogSeekBar.xml` from `DialogSeekBar.xml.bak` when a backup exists.
- **Split install actions** — **Install Pillow (preview)**, **Install generator tools (ffmpeg)**, and **Install preview tools (all)** as separate Preview tools buttons.
- **Skin snippet installer** — skips paths that already contain the trickplay overlay; writable preflight; progress bar for multi-path install/restore; inactive-skin note after install-all; full `DialogSeekBar.xml` paths in debug log; JSON-RPC skin list fallback warning.
- **Skin snippet registry** — known skins and snippet files centralized in `skin_profiles.py` (`SKIN_SNIPPET_REGISTRY`). Unknown skins use universal merge only (no full-file replace).
- **Batch retry** — after batch generation completes, offers to retry failed files.
- **Generator temp cleanup** — generation lock file and minimum age (1 hour) so active or recent jobs are not deleted on service start or add-on update.
- **Service hint** — one-time warning per session when trickplay loads but the active skin has no preview controls installed.
- **Unit tests** — pure-text merge/remove helpers in `tests/test_skin_snippet_installer.py`.

### Changed

- **Text-based skin merge** — overlay install preserves original `DialogSeekBar.xml` formatting instead of re-serializing via ElementTree.
- **Install summary** — reports ok, failed, skipped (already installed), and skin count.

### Fixed

- **Pillow debug log** — when debug logging is on, logs `PIL.__file__` after Pillow loads.
- **README** — Arctic Fuse 3 snippet documents groups **94090**, **94100**, and **94103**.

## [5.1.1] - 2026-06-21

### Fixed

- **Windows / Kodi install startup** — `pillow_installer` no longer calls `xbmcaddon.Addon()` at import time (unused, and failed with “Unknown addon id” while the add-on was still registering). Service, script, and preview entry points now pass `"service.trickplay"` explicitly.
- **Python 3.8 compatibility** — `ThumbCacheKey` used a runtime `tuple[...]` alias that fails on Kodi’s embedded Python before 3.9; switched to `typing.Tuple`.

## [5.1.0] - 2026-05-22

### Added

- **Install skin snippet** settings actions — **Install skin snippet (current skin)** and **Install skin snippet (all skins)** under Preview tools. Lists installed skins and resolved `DialogSeekBar.xml` paths, backs up each file to `DialogSeekBar.xml.bak`, then merges overlay group 94090 or replaces the full file for Estuary Mod v2 / Arctic Fuse 3. Reloads the active skin after install.

## [5.0.1] - 2026-05-22

### Fixed

- **Fast backward scrub preview slideshow** — cached thumbs no longer publish immediately during fast scrub (same coalescing as forward). Scrub burst detection keeps coalescing active across stepped seeks (~250 ms gap) so one-thumb-at-a-time backward scrub does not flash every cached frame.

## [5.0.0] - 2026-05-22

### Fixed

- **Install preview tools** settings action used `RunScript($ID,install_tools)`; Kodi did not expand `$ID`, so the button did nothing (`ExecuteAsync - Not executing non-existing script $ID`). Now uses `RunScript(service.trickplay,install_tools)`.
- **Install preview tools** crashed with `'GeneratorSettings' object has no attribute 'generator_enabled'` — use `settings.enabled` instead.

### Changed

- **Preview cropping uses Pillow** — playback/scrub preview tiles are cropped with Pillow (JPEG sprite cells). ffmpeg/ffprobe are no longer required for preview display.
- **Install preview tools** — downloads Pillow into add-on site-packages for preview. ffmpeg/HDR/dovi_tool installs run only when the generator is enabled or HDR tone mapping is on (batch **Run** still prompts for generator ffmpeg as before).

## [4.3.0] - 2026-05-22

### Added

- **Skin profiles** — auto-detect and manual override for **Estuary (stock)**, **Aeon Nox SiLVO**, **Arctic Zephyr**, and **Arctic Horizon** (geometry from upstream skin repos on GitHub).
- **Universal skin snippet** — `DialogSeekBar-universal-dynamic.xml` positions the preview via `Trickplay.PreviewLeft/Top/Width/Height` (no per-slot slide table). Per-skin copies with merge notes for Estuary, Aeon Nox SiLVO, Arctic Zephyr, and Arctic Horizon.
- **Preview adjustment** settings category — preview scale (%), horizontal/vertical offset (px), hold time, timestamp, opacity, and **Show preview when play controls focused** (keeps preview visible while the OSD play/pause row has focus).

### Removed

- Legacy unused `TrickplayPreview.xml` overlay window under `resources/skins/Default/` (preview is skin-snippet + window properties only).

## [4.2.0] - 2026-05-22

### Fixed

- **Duration probe for generation** — thumb count now uses the shorter of container `format=duration` and the primary video stream (stream `duration`, `DURATION` tag, or `NUMBER_OF_FRAMES` / frame rate). Fixes NF WEB-DL and similar files where the container is longer than decodable video (e.g. hybrid DV/HDR with ~45 s audio tail).
- **Tail tile tolerance** — an empty or failed **last** tile no longer fails the whole job when at least one prior tile was written; empty tiles in the middle still fail. Partial last tiles are kept.

## [4.1.1] - 2026-05-22

### Added

- **Batch Run scan progress** — after confirming the library folder, a cancellable progress dialog shows while the tree is scanned and sidecars are checked (“Calculating number of videos…”), instead of a long UI freeze before the start-generation prompt.

## [4.1.0] - 2026-05-22

### Added

- **Orphaned generator temp cleanup** — on service start and at the beginning of each generation job, removes leftover files under `special://temp/service.trickplay/generate/` and `.../dovi/` from crashes or hard kills (normal completion already deletes these in `finally`). Playback sprite copies in the parent temp folder are kept.

## [4.0.8] - 2026-05-22

### Added

- **Install preview tools** — new action at the top of add-on settings downloads ffmpeg/ffprobe (and optional HDR extras: zscale/libplacebo, Vulkan loader on Windows, dovi_tool) without enabling the generator or batch **Run**. Uses the same install location as batch auto-install.
- **First-playback ffmpeg prompt** — when trickplay sidecars load but no ffmpeg is found for preview cropping, the service offers a one-time yes/no install dialog per Kodi session (decline with “Continue without” to skip until restart).

### Changed

- **Generator ffmpeg path** is always visible in settings (not hidden when the generator is off) so preview-only users can point at a custom install.
- **Batch Run** now offers base ffmpeg download when missing even if HDR tone mapping is off (same pinned BtbN/Gyan builds as Install preview tools).
- Log messages for missing ffmpeg mention **Install preview tools** instead of batch Run only.

## [4.0.7] - 2026-05-22

### Fixed

- **Windows hardware decode on non-HEVC / SDR:** D3D11VA is now enabled only when ffprobe reports **HEVC** with 10-bit and/or HDR/DV signals. AVC and 8-bit SDR HEVC skip HW decode entirely (no per-frame failed HW attempt + software retry).
- **Windows HW decode per-file fallback:** after the first hardware decode failure on a file, HW decode is disabled for the remainder of that job (logged once; ffmpeg stderr included when debug logging is on).
- **Fast extract on long-interval SDR:** intervals above 5 s now use a single **fps batch** decode per tile on SDR software-only paths (no tonemap, no active HW decode), instead of one ffmpeg seek per thumb — much faster on large Blu-ray remuxes.

### Changed

- **Docs:** Windows hardware decode help/README clarify it targets **4K HDR/DV HEVC**, not general HW acceleration — 1080p H.264 SDR is faster on software decode (+ fps-batch) in testing.

## [4.0.6] - 2026-05-22

### Fixed

- **Arctic Fuse 3 full OSD preview placement:** full OSD now uses `Trickplay.PreviewLayout=center` — same height as minimal seek-bar mode (just above the bar at **670**), horizontally centered on the seek bar (**800**), without slot tracking. Replaces the previous top-of-screen placement (which could appear stuck at the top-left when dynamic `$INFO` coordinates did not apply).

## [4.0.5] - 2026-05-22

### Fixed

- **Arctic Fuse 3 full OSD:** preview moves to a dedicated group when the full video OSD is open (plot, end time, etc.), via `Trickplay.PreviewLayout` and group **94103** in the AF3 `DialogSeekBar` snippet. Compact seek-bar mode keeps group **94100** with slot slide animations.
- **Scrub lag / stale preview queue:** a single coalesced crop worker now drops intermediate frames during fast scrubbing (updates faster than ~120 ms or thumb index jumps ≥3). Synchronous eager crops are skipped while scrubbing is backed up; prefetch is cancelled during fast scrub so foreground crops are not starved. The latest seek target wins when you stop scrubbing.

## [4.0.4] - 2026-05-22

### Fixed

- **Sidecar loading on SMB and OS-mounted shares:** playback preview now tries every usable path form for the playing file — Kodi VFS URL (`nfs://`, `smb://`), `translatePath` result, and OS bind mount (e.g. `/storage/remote-shares/…` on CoreELEC). Directory and tile listing prefer the OS mount when available, then fall back to `xbmcvfs.listdir`. Fixes preview when Jellyfin sidecars are visible on disk but not via the VFS URL alone.

## [4.0.3] - 2026-05-22

### Fixed

- **Playback preview broken on Kodi/CoreELEC (NFS):** removed all uses of **`xbmcvfs.isdir`** / **`xbmcvfs.isfile`** — they do not exist on Kodi's Python API and caused `Trickplay load failed: module 'xbmcvfs' has no attribute 'isdir'`. New **`vfs_paths.py`** uses `os.path` on translated paths and **`xbmcvfs.listdir`** for `nfs://` directories.

## [4.0.2] - 2026-05-22

### Removed

- **tools.ffmpeg-tools** — all code paths that searched the legacy Kodi add-on are gone. Generation and playback use **Generator ffmpeg path**, auto-installed **BtbN / Gyan** builds, or system `PATH` only (same as 3.3.0).

## [4.0.1] - 2026-05-22

### Fixed

- **Playback preview regression (3.3.0+):** thumb cropping called non-existent `load_generator_settings()` so **Generator ffmpeg path** was never applied during scrubbing. Restored **`read_generator_settings()`**.
- **Diagnostics:** log **`Preview unavailable during playback: …`** once per cause when the seek bar is open but trickplay cannot run; warn at load time if ffmpeg is missing for cropping.

## [4.0.0] - 2026-05-22

### Added

- **Windows hardware decode** — optional generator setting **Windows hardware decode** (default off). On Windows, uses D3D11VA GPU HEVC decode with `hwdownload,format=p010le` before zscale or libplacebo (Vulkan) tonemapping (~25–30% faster on 4K HDR/Dolby Vision in testing). Skipped for VFS stream paths. Falls back to software decode automatically when a frame or batch extract fails. No effect on Linux or CoreELEC.

## [3.3.0] - 2026-06-14

### Changed

- **Removed `tools.ffmpeg-tools` dependency** — generation and playback preview cropping both use the same ffmpeg resolution: custom **Generator ffmpeg path**, auto-installed **`/storage/.kodi/system/ffmpeg/`** (Linux/CoreELEC) or **`addon_data/.../system/ffmpeg/`** (Windows), then system `PATH`. Run batch **Run** once with HDR tone mapping to install ffmpeg if needed.

## [3.2.0] - 2026-06-14

### Changed

- **dovi_tool auto-install** now installs beside generator ffmpeg (**`/storage/.kodi/system/ffmpeg/bin/dovi_tool`** on CoreELEC/Linux, **`addon_data/.../system/ffmpeg/bin/dovi_tool.exe`** on Windows) instead of the add-on package root. Survives add-on updates like the HDR ffmpeg install. Legacy add-on-root copies are migrated automatically on first detection.

## [3.1.11] - 2026-06-14

### Fixed

- **Fast extract progress logging:** log each thumb as it is written during per-frame fast seek (`Tile 1/3: thumb 42/100 at 378.0s`). Reverts the 3.1.10 batch-threshold / libplacebo batch changes — fast seek + libplacebo was already working well for Jellyfin-style intervals.

## [3.1.10] - 2026-06-14

### Fixed

- *(Superseded by 3.1.11 — batch-threshold change reverted; logging fix only.)*

## [3.1.9] - 2026-06-14

### Fixed

- Batch generation crash: `creationflags` was accidentally passed to `resolve_thumb_filter_context()` after the 3.1.8 hide-window change (only subprocess calls should get it).

## [3.1.8] - 2026-06-14

### Fixed

- **Windows:** ffmpeg/ffprobe/dovi_tool subprocesses now use `CREATE_NO_WINDOW` so batch generation and playback cropping no longer flash a **cmd.exe** window on every frame extract or probe.

## [3.1.7] - 2026-06-14

### Fixed

- **libplacebo filter chain** for ffmpeg 8.x (Gyan full / BtbN with libplacebo): replaced removed options **`desaturation`** and **`color_mapping`** with **`gamut_mode=perceptual`**. Fixes `Option not found` failures on Dolby Vision Profile 5 generation.

## [3.1.6] - 2026-06-14

### Fixed

- **libplacebo filter detection** on ffmpeg 8.x: Gyan full builds list `libplacebo` as **`N->V`**, not **`V->V`**. Install verification and Dolby Vision routing no longer falsely report “lacks libplacebo” when the filter is present.

## [3.1.5] - 2026-05-22

### Fixed

- **Windows HDR ffmpeg auto-install** now downloads [Gyan **ffmpeg-8.1.1-full_build.zip**](https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-full_build.zip) from GitHub (static **zscale + libplacebo**). Reverts the 3.1.4 essentials fallback — essentials lacks libplacebo and cannot handle Dolby Vision Profile 5 via Vulkan.

## [3.1.4] - 2026-05-22

### Fixed

- **Windows HDR ffmpeg auto-install** URL corrected to Gyan **ffmpeg-release-essentials.zip** *(superseded by 3.1.5 — essentials is not suitable for libplacebo / DV Profile 5)*.

## [3.1.3] - 2026-06-14

### Changed

- **Windows HDR ffmpeg auto-install** now downloads Gyan **ffmpeg-release-full.zip** instead of BtbN **gpl-8.1**. *(URL was invalid — fixed in 3.1.4.)*
- Windows x64 with Vulkan re-requires **libplacebo** in the installed ffmpeg for “fully HDR capable” checks; Linux / CoreELEC still uses BtbN **gpl-8.1** (zscale + **dovi_tool** for Profile 5). *(Relaxed in 3.1.4 for Gyan essentials.)*

## [3.1.2] - 2026-06-14

### Fixed

- **Dolby Vision Profile 5** frame extraction after **dovi_tool** convert: **`converted.hevc`** is an elementary stream with no seek index — per-tile **fast seek** (`-ss` before `-i`) failed silently on Windows. Generation now uses a **single sequential decode** with **`-f hevc`** and the **fps** batch filter (same strategy as VFS pipe extract), then assembles tiles as before.

## [3.1.1] - 2026-06-13

### Fixed

- **Windows HDR ffmpeg install** no longer fails verification when **Vulkan** is available but the BtbN **gpl-8.1** build has **zscale** only (no **libplacebo** filter). Install is accepted; HDR10 and DV P7/P8 use zscale, Profile 5 uses **dovi_tool + zscale** (same as no-Vulkan hosts). Re-run **Run** is not prompted again after a successful zscale install.
- Wrong-architecture **dovi_tool** binaries in the add-on folder are removed automatically so batch **Run** can offer the correct Windows download.
- Windows HDR ffmpeg install now **bundles `vulkan-1.dll`** into `bin/` (copied from System32 when present) even when Vulkan already works system-wide, so the folder is self-contained.

## [3.1.0] - 2026-05-22

### Added

- **Windows Vulkan loader install** — when HDR tonemapping is enabled and ffmpeg cannot init Vulkan, batch **Run** offers to install **`vulkan-1.dll`** beside the generator ffmpeg (copies from `%SystemRoot%\System32` when present, otherwise downloads the NuGet **Vulkan.Loader** redistributable). Dolby Vision via **libplacebo** needs this on many Windows Kodi setups. Silent install is also attempted immediately after HDR ffmpeg auto-install.

### Fixed

- **Windows HDR ffmpeg install folder** — auto-install and default generator ffmpeg resolution now use **`special://profile/addon_data/service.trickplay/system/ffmpeg/`** on Windows Kodi instead of the Linux-only **`/storage/.kodi/system/ffmpeg/`** path (which broke download prompts and left ffmpeg undetected on PC).
- Windows generator subprocesses resolve **`ffmpeg.exe` / `ffprobe.exe`**, prepend the install **`bin/`** (and **`lib/`** when present) plus **System32** to **`PATH`**, so BtbN **gpl-8.1** builds and the bundled Vulkan loader load correctly.

## [3.0.19] - 2026-05-22

### Added

- Generator setting **Skip Dolby Vision Profile 5** (`generator_skip_dv_profile_5`): when HDR tonemapping is enabled, batch scans skip Profile 5 files (web `.DV.` releases) that need a full **dovi_tool** convert. Skipped files are counted separately in the batch confirmation dialog and logged as `Skipping DV Profile 5 (setting): …`.

## [3.0.18] - 2026-06-13

### Fixed

- Profile 5 **dovi_tool** convert temp files now use **`special://temp/service.trickplay/dovi/`** (on `/storage`) instead of OS **`/tmp`**, which is often too small on CoreELEC for a full 4K HEVC rewrite (`No space left on device`).
- Skip redundant MKV remux after convert — frame extraction reads the **`.hevc`** elementary stream directly (halves peak temp disk use).
- Preflight disk-space check before Profile 5 convert with a clear log message when space is insufficient.

## [3.0.17] - 2026-06-13

### Fixed

- **dovi_tool convert** for Profile 5: `convert` does not accept Matroska — ffmpeg now demuxes to annex-B HEVC (`hevc_mp4toannexb`) and pipes into `dovi_tool -m 3 convert -`.
- Dolby Vision **profile detection** uses dovi_tool RPU info when ffprobe lacks `DOVI configuration record`; Profile **7/8** (e.g. DSNP FLUX) skip dovi_tool convert and use zscale only; Profile **5** (web `.DV.`) uses dovi_tool + zscale on no-Vulkan hosts.
- README: static BtbN **libplacebo** on desktop Linux may need `VK_ICD_FILENAMES` (and related `VK_*` env) so the static ffmpeg binary can load system Vulkan ICDs; logged when ICD configs exist but init fails.

## [3.0.16] - 2026-06-13

### Fixed

- Batch **Run** no longer prompts to re-download **gpl-shared** ffmpeg when **zscale** already works but **libplacebo** is absent — on no-Vulkan hosts (CoreELEC) libplacebo is not required; Profile 5 DV uses **dovi_tool + zscale**.
- Linux HDR ffmpeg auto-install uses static **gpl-8.1** again (zscale on CoreELEC without `lib/` / Vulkan).
- **dovi_tool** detection skips wrong-architecture binaries (`Exec format error`); broken installs are removed before re-download.

## [3.0.15] - 2026-06-13

### Fixed

- **Dolby Vision on CoreELEC / no-Vulkan hosts** — Profile **5** (web-DV, no HDR10 base layer) uses **dovi_tool** `-m 3 convert` then **zscale + tonemap**. Profiles **7** and **8** keep the original **zscale + tonemap** path on the HDR10 base layer (no dovi_tool convert). libplacebo is used for any DV profile when Vulkan is available.

## [3.0.14] - 2026-06-13

### Added

- **Run batch in background** generator setting — batch **Run** can show a start notification and run without the blocking progress dialog; progress goes to the Kodi log and a notification appears when finished.

### Fixed

- **Dolby Vision** tone mapping: Linux auto-install again uses BtbN **gpl-shared-8.1** (zscale + libplacebo with clean `LD_LIBRARY_PATH`). Re-run **Run** to replace a static `-gpl-8.1` install that has zscale but no libplacebo.
- libplacebo Vulkan init (`-init_hw_device vulkan`) is passed on every frame-extract ffmpeg invocation when DV/HDR uses libplacebo.

## [3.0.13] - 2026-06-13

### Fixed

- **Dolby Vision** trickplay thumbs (green/purple tint): DV sources are detected (DOVI side_data, dovi_tool, or `.DV.` in filename) and routed through **libplacebo** with `apply_dolbyvision=1` instead of the HDR10 zscale chain, which cannot apply DV RPU metadata.

## [3.0.12] - 2026-06-13

### Fixed

- HDR trickplay generation on ffmpeg 8.x (BtbN `-gpl-8.1`): tone-mapped output now uses full-range **yuvj420p** with `-strict unofficial` and `-color_range pc`. Fixes mjpeg encoder failure: `Non full-range YUV is non-standard`.

## [3.0.11] - 2026-06-13

### Fixed

- BtbN auto-install URLs: correct asset names use **`-gpl-8.1`** suffix (e.g. `linuxarm64-gpl-8.1.tar.xz`), not `-gpl.tar.xz` — fixes HTTP 404 on download.

## [3.0.10] - 2026-06-13

### Changed

- Linux HDR ffmpeg auto-install now uses BtbN **`-gpl`** (static) builds instead of **`-gpl-shared`**. On CoreELEC the shared build often exposes only `tonemap` even with `LD_LIBRARY_PATH` set; the static `-gpl` tarball includes **zscale** and **libplacebo** without a separate `lib/` folder. Windows still uses gpl-shared zip. Re-run **Run** to replace a broken shared install.

## [3.0.9] - 2026-06-13

### Fixed

- HDR ffmpeg filter detection after auto-install: tonemap capability cache now keys on `LD_LIBRARY_PATH` as well as binary path, and is cleared when generator ffmpeg is re-resolved. Fixes false "lacks zscale/libplacebo" results for BtbN **gpl-shared** builds when an earlier probe ran without `lib/` on the path.
- Install verification logs `lib/` shared-library count and probe details; fails clearly when `lib/` is missing or empty (shared build required — static `-gpl` is not used).
- **Generator ffmpeg path** setting missing `<control>` tag (Kodi log spam: `unable to read setting "generator_ffmpeg_path"`).

## [3.0.8] - 2026-06-13

### Added

- **HDR ffmpeg auto-install on Run** — when **HDR tone mapping** is enabled and the generator ffmpeg lacks **zscale** or **libplacebo**, batch **Run** offers to download and install a pinned [BtbN gpl-shared](https://github.com/BtbN/FFmpeg-Builds/releases) build (linux64, linuxarm64, win64, winarm64). Installs to `/storage/.kodi/system/ffmpeg/` on Linux Kodi or `special://profile/addon_data/service.trickplay/system/ffmpeg/` on Windows.
- **dovi_tool auto-install on Run** — when **HDR dovi_tool fallback** is enabled and `dovi_tool` is missing, **Run** offers to download and install pinned [dovi_tool 2.3.2](https://github.com/quietvoid/dovi_tool/releases/tag/2.3.2) into the add-on folder (same location as a manual `dovi_tool` beside `addon.xml`).

## [3.0.7] - 2026-06-13

### Added

- **Generator ffmpeg path** setting (optional folder or binary). When empty, generation auto-uses `/storage/.kodi/system/ffmpeg/` if present, then falls back to **tools.ffmpeg-tools**. Playback cropping still uses **tools.ffmpeg-tools**. Documented [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases) for CoreELEC (linuxarm64-gpl-shared) and x86_64 Linux (linux64-gpl-shared) with install layout under `/storage/.kodi/system/ffmpeg/`.

### Changed

- HDR tonemap capability detection is cached per ffmpeg binary path (custom vs tools.ffmpeg-tools).

## [3.0.6] - 2026-06-13

### Fixed

- HDR tone mapping filter chain now matches Jellyfin-style processing: `setparams` (BT.2020/PQ tags), linearize with `zscale`, gamut map to BT.709 (`zscale=p=bt709`), `tonemap=hable:desat=0`, then BT.709 limited-range output. Fixes washed-out, grey trickplay tiles caused by tonemapping without gamut/transfer conversion.
- When `zscale` is unavailable, prefers **libplacebo** if present; otherwise logs a warning and uses an improved best-effort `tonemap` chain with explicit HDR tags and float workspace.
- Tone-mapped JPEG extraction sets BT.709 output color metadata on ffmpeg.

## [3.0.5] - 2026-06-13

### Fixed

- Batch cancel cleanup on NFS/local mounts: removes the in-progress resolution folder (e.g. `320 - 10x10 - 9000`) including partial tile JPEGs via the OS filesystem, not only `xbmcvfs`. Drops the parent `.trickplay` folder when no other resolution subfolders remain; keeps siblings such as `320 - 10x10` untouched.

## [3.0.4] - 2026-05-22

### Added

- Optional **HDR dovi_tool fallback** generator setting (default off, visible when HDR tone mapping is enabled). When on, ffprobe misses can be confirmed by extracting a short HEVC sample and running `dovi_tool` (local paths only; looks for `dovi_tool` in the add-on folder or on PATH). Logs when the setting is enabled and when fallback is used or skipped.

### Changed

- HDR ffprobe detection: scans all video streams (not only `v:0`), parses DOVI configuration record profiles from `side_data_list`, and detects Dolby Vision enhancement-layer streams.

## [3.0.3] - 2026-06-13

### Fixed

- HDR source detection for Dolby Vision / HDR10 remuxes: ffprobe now reads `side_data_list`, 10-bit `pix_fmt`, and bt2020 primaries (including DV streams tagged with bt709 transfer). Falls back to first-frame probe when stream-level metadata is missing.

## [3.0.2] - 2026-06-13

### Fixed

- HDR tone-map detection: recognise `tonemap` in ffmpeg 8.x `-filters` output (e.g. `.S tonemap V->V`) so CoreELEC **tools.ffmpeg-tools** builds with tonemap but without zscale use **tonemap-only** mode instead of falsely reporting the filter as missing.

## [3.0.1] - 2026-06-12

### Fixed

- Batch skip detection for existing Jellyfin sidecars (`320 - 10x10/`, etc.) now lists `.trickplay` folders via `os.listdir` on OS/NFS mounts when `xbmcvfs.listdir` misses them, and checks multiple media path variants (library path, resolved local path, ffmpeg path).

## [3.0.0] - 2026-06-12

### Added

- Optional **HDR tone mapping for previews** generator setting (default off). When enabled, HDR and Dolby Vision sources are tone-mapped to SDR during JPEG extraction. Only applies to HDR/DV files; SDR is unchanged. Requires ffmpeg `tonemap` filter support; significantly slower on 4K HEVC.

## [2.1.6] - 2026-06-12

### Added

- **Interval selection** playback setting: **Preferred interval** (match **Preview thumbnail interval**) or **Shortest interval** when multiple sidecar folders exist (e.g. `320 - 10x10 - 5000` vs `320 - 10x10 - 10000`).

### Fixed

- Batch and idle generation now skip existing Jellyfin sidecars in legacy folder names (`320 - 10x10/` without an interval suffix, treated as 10000 ms) when generator width, grid, and interval match — not only folders named `320 - 10x10 - 10000`.

## [2.1.5] - 2026-06-12

### Fixed

- Missing trickplay no longer spams `kodi.log` during playback: the service loads each file once per playback session instead of re-scanning on every poll tick when no sidecar exists.

## [2.1.4] - 2026-06-01

### Changed

- **Run library batch generation** removed from Configure settings. Batch generation is started from the add-on **Information** page **Run** button (`script_generator.py` with `provides executable`), so Configure changes are saved with OK before Run.

## [2.1.3] - 2026-06-01

### Fixed

- Generator VFS stream fallback for `nfs://` / `smb://` paths: read media with `xbmcvfs.File.readBytes()` instead of `read()`, which tried to decode MKV data as UTF-8 and broke ffprobe/ffmpeg pipe probing (`0xa3` invalid start byte).
- NFS URL → OS mount mapping accepts paths visible via Kodi VFS when `os.path.isfile` fails on embedded mounts.
- Batch library folder picker rejects invalid selections such as `special://home` with a clear message.

## [2.1.2] - 2026-06-01

### Changed

- Batch library folder picker uses Kodi's full folder browser (local drives and network shares) instead of the limited file-shares list; starts at the current path, `/storage/` on embedded installs, or `root://`.
- Folder chosen in the batch picker is saved to addon settings immediately so you do not need to press OK in settings first.

### Added

- README and Library folder setting help: addon settings are only written when you press **OK** and leave the settings screen (Kodi limitation); use **Run library batch generation…** to pick and save a folder without leaving settings.

## [2.1.1] - 2026-06-01

### Changed

- Estuary Mod v2 skin snippet: preview anchor raised 25 px total (`top` 624 → 599) so the thumbnail clears the episode info panel above the seek bar.
- Seek OSD open: sync-crop playhead and prefetch neighbors so the first scrub shows a thumbnail immediately; scrubbing uses synchronous crop on cache miss instead of waiting for a background crop.

## [2.1.0] - 2026-05-22

### Added

- **Generate on library update** (generator setting, off by default): listens for `VideoLibrary.OnAdd` and `VideoLibrary.OnUpdate` with `added: true`, accumulates paths during a library scan, and enqueues trickplay generation for those new items when the scan finishes (`VideoLibrary.OnScanFinished`).
- **Library update: only when not playing** (on by default): defers the post-scan batch until Kodi is not playing video.

## [2.0.15] - 2026-05-31

### Fixed

- Batch generation crash when the sidecar resolution folder does not exist yet: `_list_jpg_files` no longer raises on missing NFS paths (`os.listdir` wrapped; skip when directory absent).

## [2.0.14] - 2026-05-31

### Fixed

- Experimental ffmpeg multi-seek: register all `-ss`/`-i` inputs first, then `-map N:v:0` per output. Interleaved input/output syntax duplicated the first frame across each 25-frame chunk.

## [2.0.13] - 2026-05-31

### Fixed

- Batch candidate scan detects existing sidecar tile JPEGs via local filesystem listing (NFS/mounted paths), so videos that already have trickplay are excluded when overwrite is off.

### Changed

- Batch confirmation dialog reports how many videos will be generated and how many matching sidecars are skipped (e.g. “4 of 8 … 4 already have matching sidecars”).

## [2.0.12] - 2026-05-31

### Fixed

- Cancel during generation removes partial tile JPEGs and deletes the empty sidecar resolution folder (and empty parent `.trickplay` when nothing else remains).

## [2.0.11] - 2026-05-31

### Added

- Generator **Frame extraction mode** selector: **Accurate (slow)**, **Fast**, or **Experimental**. Replaces the fast on/off toggle (legacy toggle still maps to accurate/fast when upgrading).
- **Experimental** mode: one open file with seek between captures — PyAV when installed, otherwise one ffmpeg process with multiple `-ss` seeks per tile (chunked).

## [2.0.10] - 2026-05-31

### Fixed

- Fast extraction for intervals above 5s: one `-ss` before `-i` seek per thumbnail instead of decoding the entire interval span with `fps`. A 20s interval no longer spends ~20s of decode per thumb.

### Changed

- Fast extraction for intervals of 5s or less still uses a single continuous `fps` decode pass (faster for dense sampling).

## [2.0.9] - 2026-05-31

### Changed

- Accurate per-frame timeout increment: 200ms per thumb index (was 10s). Thumb 99 timeout is ~620s instead of ~1590s.

## [2.0.8] - 2026-05-31

### Changed

- Accurate per-frame extraction timeout: 600s base plus 200ms per thumb index (was a fixed 120s in 2.0.7; 10s per thumb in 2.0.8).
- **Fast batch extraction** defaults to on for new installs.

### Added

- Generator setting **Stop batch on first failure** (off by default).

### Fixed

- Failed generation removes empty sidecar resolution folders (and an empty parent `.trickplay` when nothing else remains).

## [2.0.7] - 2026-05-31

### Fixed

- Fast batch extraction: temp JPEG sequences are listed via the local filesystem (ffmpeg writes outside VFS), `-start_number 0` removed, and tile progress is logged so generation no longer fails silently.

### Added

- Generator setting **Fast batch extraction** (off by default): one ffmpeg pass per tile with seek-before-input when enabled; accurate per-frame seek-after-input when disabled.

## [2.0.6] - 2026-05-31

### Changed

- Trickplay frame extraction: one ffmpeg pass per tile with `-ss` before `-i`, `fps`, deinterlace, and scale/pad. Replaces per-frame seeks (~35s/tile vs minutes on long REMUX files).

## [2.0.5] - 2026-05-31

### Fixed

- Batch trickplay generation cancel: the progress dialog only checked cancel between files, so a long episode could block for hours. Cancel is now polled during frame extract and tile assembly, in-flight ffmpeg processes are killed, and partial sidecars for the current file are removed.

## [2.0.4] - 2026-05-31

### Fixed

- Trickplay tile assembly: ffmpeg's `tile` filter needs a numbered image sequence, not one `-i` per JPEG. Grids were rendering as a single thumbnail on black; they now build full 10×10 (or configured) sprites.
- Frame extraction for interlaced sources: deinterlace with `yadif`, seek after input, and pad thumbs to 16:9 cells matching Jellyfin sidecar layout.

## [2.0.3] - 2026-05-31

### Fixed

- Trickplay generation on Kodi `nfs://` / `smb://` library paths: ffmpeg cannot open VFS URLs directly, so the generator now maps OS-mounted shares when available and otherwise streams media through Kodi's VFS into ffmpeg (sequential read).

### Changed

- Duration probing logs the resolved ffmpeg path and ffprobe/ffmpeg stderr when parsing fails.

## [2.0.2] - 2026-05-31

### Fixed

- Batch generation progress dialog no longer crashes on Kodi 21: `DialogProgress.update()` only accepts percent and one message line (the third line argument was removed in Kodi v19).

## [2.0.1] - 2026-05-31

### Fixed

- **Run library batch generation** action now uses `RunScript(service.trickplay,batch)` so Kodi invokes the script entry point correctly (the previous `script_generator.py` argument was treated as the mode and the script exited silently).

### Changed

- Batch generation logs startup, settings, folder selection, candidate counts, per-file progress, and early exits under `[service.trickplay.generator.batch]`.

## [2.0.0] - 2026-05-31

### Added

- **Generator thumbnail interval (ms)** setting (default 10000). Generated sidecar folders now include the interval in the name, e.g. `320 - 10x10 - 1000` or `320 - 10x10 - 10000`.

### Changed

- Playback reads the thumbnail interval from the sidecar folder name when present; legacy folders without an interval suffix (`320 - 10x10`) fall back to **10000 ms**.
- Resolution selection prefers a folder matching both preferred tile width and playback interval setting.
- Preview lookup uses the loaded folder's interval instead of always using the playback settings value.

## [1.7.0] - 2026-05-31

### Changed

- First seek preview is faster: the 3-second startup gate no longer blocks preview when trickplay data is loaded — it only suppresses false automatic scrub detection during playback start.
- Poll interval stays at configured `poll_ms` for the whole time video is playing, so opening the seek OSD is detected promptly.
- Playhead thumbnail is cropped eagerly when trickplay loads, before background prefetch neighbours.
- Pre-1.6.11 crop cache files are migrated into fingerprinted cache paths on first access instead of forcing a full re-crop.

## [1.6.13] - 2026-05-31

### Fixed

- Service appeared dead with almost no logs: trickplay loading now runs on a background thread so NFS/ffprobe enrichment cannot freeze the service loop or player callbacks.
- Poll loop detects new playback files when `onAVStarted`/`onPlayBackStarted` are missed, with duplicate-load guards.
- Poll errors are logged instead of silently stopping the service.
- Preview publish force-resyncs to DialogSeekBar when visible after each update.

## [1.6.12] - 2026-05-31

### Fixed

- Trickplay previews missing after 1.6.8: resync no longer skips solely because home-window properties are unchanged — DialogSeekBar reloads (e.g. `LOAD_ON_GUI_INIT`) clear window properties, so resync now verifies the seekbar actually matches before skipping. Force-resync when the seekbar opens with an active preview session.

## [1.6.11] - 2026-05-29

### Changed

- Crop cache keys and on-disk filenames now include the source sprite tile mtime and size, so regenerated Jellyfin sidecars no longer reuse stale cropped thumbs. Tile fingerprints are cached for 2 seconds to limit VFS stat traffic during scrub/prefetch.

## [1.6.10] - 2026-05-29

### Changed

- Service poll interval adapts to workload: configured `poll_ms` during scrubbing, seek UI, and active previews; ~200–500 ms during calm playback; 500 ms when idle with background generation; 1000 ms when fully idle.

## [1.6.9] - 2026-05-29

### Changed

- Preview placement (slot and geometry window properties) is skipped when only the thumbnail image updates, such as when an async crop finishes for the same seek position.

## [1.6.8] - 2026-05-29

### Changed

- `resync_preview_to_seekbar()` skips work when the seekbar is hidden, when home-window properties are unchanged since the last resync, or when the seekbar already matches; still runs on seekbar open (visibility transition) or when properties differ.

## [1.6.7] - 2026-05-29

### Changed

- Addon settings reads are cached for 2 seconds on hot paths (prefetch, generator, runtime playback, display sync) to reduce repeated Kodi settings API calls during scrub polling.

## [1.6.6] - 2026-05-29

### Changed

- Sprite tile temp copies are shared across threads: in-memory index keyed by source path and fingerprint, per-tile locks prevent duplicate NFS copies when prefetch and preview crop the same JPG concurrently.

## [1.6.5] - 2026-05-29

### Changed

- Crop cache: in-memory index avoids repeated VFS stat checks for known-good thumbs; concurrent foreground/prefetch crops for the same cell share one in-flight ffmpeg job.

## [1.6.4] - 2026-05-29

### Changed

- Crop cache LRU prune is debounced: runs after a batch of new crops, a minimum interval, or when estimated cache size exceeds the limit — not after every single crop.

## [1.6.3] - 2026-05-29

### Changed

- **Preview tile grid layout** is now a single always-visible dropdown (From folder name, 10×10, 20×20, 5×5, 15×15, Custom) replacing the separate Automatic tile calculation toggle and hidden manual grid options.

## [1.6.2] - 2026-05-29

### Fixed

- Service crash on startup (`Invalid setting type`) when reading generator settings: removed legacy lookup of deleted `generator_skip_existing` setting; setting readers now fail safely to defaults.

## [1.6.1] - 2026-05-22

### Changed

- Generator **Overwrite existing sidecars** toggle (default off) replaces **Skip existing sidecars**; when enabled, existing tile JPGs are deleted before regeneration.

## [1.6.0] - 2026-05-22

### Added

- **Trickplay generator** (optional, off by default): writes Jellyfin-compatible `.trickplay` sidecars with ffmpeg.
- Generator settings: enable/disable (hides all generator options when off), tile grid preset (10×10, 20×20, 5×5, 15×15, custom), library folder, skip existing, generate while idle, and **Run library batch generation** action.
- **Display tile grid layout** preset selector when automatic tile calculation is off (for custom or non-Jellyfin sprite grids).

### Changed

- Batch generation runs from addon settings via progress dialog; idle generation runs one file at a time in the background service when Kodi is not playing video.

## [1.5.4] - 2026-05-22

### Fixed

- Estuary Mod v2 (and AF3): preview overlay no longer shows a white box when scrubbing content without trickplay sidecars — border control no longer fills the frame, and visibility requires a preview image.
- Service no longer sets `Trickplay.PreviewVisible` when trickplay data is unavailable or lookup fails during scrub.

## [1.5.3] - 2026-05-22

### Added

- **Preview opacity (%)** setting (0–100, default 100). Publishes `Trickplay.PreviewColorDiffuse` for skin `colordiffuse`.

### Fixed

- Preview thumbnail no longer inherits border transparency: border is a separate control; opacity applies to the preview group only.

## [1.5.2] - 2026-05-22

### Changed

- Estuary Mod v2 snippet: preview anchor raised 132 px (`top` 756 → 624) for normal and small/wide OSD.
- Estuary preview border switched to light `colors/white.png` frame (`colordiffuse` B3FFFFFF) instead of dark `dialog-bg-nobo.png`.

## [1.5.1] - 2026-05-22

### Changed

- Skin snippets: subtle preview border — AF3 uses `panel_fg_70` on a 2 px frame; Estuary Mod v2 uses `dialog-bg-nobo.png`.

## [1.5.0] - 2026-05-22

### Added

- **Thumbnail prefetch settings**: enable/disable prefetch, playback-start warm, whole-tile batching, idle tile prefetch, radius, queue size, and crop cache limit (LRU prune by oldest access time).
- **Idle prefetch**: while the seek OSD is open and not scrubbing, remaining cells in the current sprite tile are queued (once per tile, throttled every 3 s).
- **Crop cache LRU**: cached thumbs track last access; oldest files are deleted when over the MB limit (default 500, 0 = unlimited).

## [1.4.0] - 2026-05-22

### Added

- **Thumbnail prefetch**: playhead warm on playback start (±3 indices + up to 20 cells in the current sprite tile), scrub-direction bias (+5 ahead / −2 behind when seeking forward, mirrored when rewinding), and local sprite copy before batching crops from the same tile file. Queue size raised to 48.

## [1.3.0] - 2026-05-22

### Added

- **Thumbnail prefetch**: after each preview, a background worker pre-crops the ±3 neighbouring trickplay cells (deduped, skips already-cached). Queue capped at 24; cancelled on playback stop.

## [1.2.5] - 2026-05-22

### Fixed

- Timestamp hidden when **Show timestamp** is disabled: `Trickplay.PreviewTime` is no longer published, layout omits label height, and `Trickplay.ShowTimestamp` is cleared with the preview session.
- Estuary Mod v2 skin snippet uses conditional group height (180 vs 224) when the timestamp is off.

## [1.2.4] - 2026-05-22

### Fixed

- Arctic Fuse 3 full OSD is detected via custom overlay windows (1140–1149, 1152, 1153), not only `videoosd`. Stale compact-seek previews now clear when those overlays open.
- Play-button focus hide includes AF3 overlay button ids (6101–6109).
- Preview properties are cleared on DialogSeekBar window 10115 even when Kodi visibility checks are ambiguous.

## [1.2.3] - 2026-05-22

### Fixed

- Stale trickplay preview no longer persists when opening the full video OSD after seeking via the compact seekbar.
- Preview session state is cleared whenever seek UI closes, not only after an active scrub.
- Full video OSD hides preview unless the seekbar is focused, play controls are not focused, or a preview session is actively held/scrubbing.
- Transition from compact seekbar to full video OSD ends the prior preview session unless still scrubbing.

## [1.2.2] - 2026-05-22

### Changed

- **tools.ffmpeg-tools** is now a required dependency (no longer optional).
- Removed Pillow fallback and all references to `script.module.pillow`.

## [1.2.1] - 2026-05-22

### Fixed

- Preview hold time **0** now advances the thumbnail with playback while the OSD stays open (not frozen on the last seek frame).

## [1.2.0] - 2026-05-22

### Added

- **Preview hold time** setting (0–10 s, default 4; 0 = until OSD closes).
- **Show timestamp** setting toggles `Trickplay.ShowTimestamp` for skin label visibility.

### Fixed

- Preview no longer stays visible indefinitely during playback after a seek (`Player.Seeking` stuck / paused OSD rule removed).
- Arctic Fuse 3 snippet anchor lowered by 132 px (`top` 538 → 670).

## [1.1.2] - 2026-05-22

### Fixed

- Preview stays visible for a few seconds after seeking and while paused with the OSD open.
- No longer treats playhead movement during playback as scrubbing (stops thumbnail flash with OSD open).

## [1.1.1] - 2026-05-22

### Fixed

- Skin auto-detect no longer reads `xbmc.gui` addon id; uses `lookandfeel.skin` setting and `getSkinDir()` instead.

## [1.1.0] - 2026-05-22

### Added

- **Skin profile auto-detection** via active Kodi skin id (`skin_profiles.py`).
- Built-in profiles for **Estuary Mod v2** and **Arctic Fuse 3** (geometry + OSD focus ids).
- **Skin profile** addon setting to override auto-detect.
- Reference skin snippet for Arctic Fuse 3: `DialogSeekBar-skin.arctic.fuse.3.xml`.

### Changed

- `osd_layout.py` reads seek bar geometry from the active skin profile instead of hardcoded constants.

## [1.0.0] - 2026-05-22

### Added

- Initial release of **Trickplay Preview** (`service.trickplay`).
- Background service that reads Jellyfin `.trickplay` sprite folders next to local/NFS media.
- Thumbnail lookup by seek position with configurable preferred resolution and interval.
- Async cropping via `script.module.pillow` or `tools.ffmpeg-tools`, with local cache.
- DialogSeekBar skin integration through window properties (`Trickplay.PreviewImage`, `Trickplay.PreviewVisible`, `Trickplay.PreviewSlot`, etc.).
- Reference skin snippet for Estuary Mod v2: `resources/skin-snippet/DialogSeekBar-skin.estuary.modv2.xml`.
- Preview positioning aligned to seek bar geometry (51 horizontal slots, normal and wide OSD layouts).
- Preview visibility while seeking or when the seek bar has focus; hidden when focus moves to play controls.
- Reliable multi-step seek handling using Kodi `onPlayBackSeek` and committed seek targets.
- Addon settings for tile width, thumb interval, poll interval, tile grid, and debug logging.

### Notes

- **Skin edit required:** merge the snippet into your skin’s `DialogSeekBar.xml` before previews will appear. See `README.md`.

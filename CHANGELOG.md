# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

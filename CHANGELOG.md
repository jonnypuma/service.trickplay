# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

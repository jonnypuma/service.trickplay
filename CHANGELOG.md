# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

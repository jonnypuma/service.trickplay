# jellyfin-ffmpeg portable layout notes (v8.1.2-2)

Inspected from local downloads under this folder (gitignored; not committed).

Release: https://github.com/jellyfin/jellyfin-ffmpeg/releases/tag/v8.1.2-2

## Archives

| Asset | Approx size |
|---|---|
| `jellyfin-ffmpeg_8.1.2-2_portable_linux64-gpl.tar.xz` | ~57 MiB |
| `jellyfin-ffmpeg_8.1.2-2_portable_linuxarm64-gpl.tar.xz` | ~51 MiB |
| `jellyfin-ffmpeg_8.1.2-2_portable_win64-clang-gpl.zip` | ~65 MiB |
| `jellyfin-ffmpeg_8.1.2-2_portable_winarm64-clang-gpl.zip` | ~52 MiB |

## Unpacked layout (all platforms)

Flat — **no** `bin/` or `lib/` subdirectory:

```text
ffmpeg[.exe]
ffprobe[.exe]
```

Installer walks the extract tree, finds `ffmpeg`+`ffprobe` in the same directory, and copies them into `system/ffmpeg/bin/`.

## Win64 capabilities (probed locally)

- Filters: `zscale`, `libplacebo`, `tonemap`
- Hwaccels: `d3d11va`, `vulkan`, `cuda`, …
- Version string: `ffmpeg version 8.1.2-Jellyfin`

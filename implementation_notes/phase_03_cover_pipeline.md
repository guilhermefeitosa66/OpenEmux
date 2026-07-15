# Phase 03: Cover Pipeline

**Goal:** Use one cover strategy for manual and downloaded assets, with explicit sync controls.

## Scope
- Local-first lookup from `<roms>/covers/<console>/<rom_name>.png|jpg|webp`.
- Playlist-driven ROM indexing (`~/.openemux/playlists/<console>.list`).
- Background cover sync via Libretro Thumbnails (no authentication).
- Save downloaded covers in the same local path structure.

## Delivered
- Unified cover resolution path.
- Async local cover lookup integrated with grid rendering.
- `Sync Covers` action in settings (scope: current console or all consoles).
- First-open playlist bootstrap per console, manual rescan thereafter.

## Next
- Add metadata index and refresh/re-download policy.

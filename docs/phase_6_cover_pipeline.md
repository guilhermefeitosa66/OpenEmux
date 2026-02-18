# Phase 6: Cover Pipeline & Local Cache Strategy

**Goal:** Use a single cover logic for manual and downloaded assets under the ROM tree.

## Scope

1. **Local-First Cover Resolution**
   - Resolve covers from `<roms>/covers/<console>/<rom_name>.png|jpg|webp`.
   - Prioritize local files before any network call.

2. **Public Provider Download**
   - Use ScreenScraper as initial public source.
   - Save downloaded images in the same local covers structure.

3. **Cache Metadata**
   - Add metadata index for source, timestamp, and checksum.
   - Support refresh strategy (force refresh, stale refresh, missing-only).

## Deliverables
- Unified path strategy for all cover files.
- Provider-backed download with local persistence.
- Metadata-driven cache refresh policy.

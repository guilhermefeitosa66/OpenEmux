# Phase 3: Library Management & Visuals

**Goal:** Polish the visual experience with cover art scraping and shader configuration.

## Requirements

1.  **Cover Art Scraper**:
    -   Integrate a scraping library (e.g., using TheGamesDB API or ScreenScraper).
    -   Automatically download box art for identified ROMs (hashing or filename matching).
    -   Cache images in `~/.opemux/cache/covers/`.

2.  **Shaders & Filters**:
    -   Implement a "Visuals" settings page.
    -   Configure `geom-crt` shader for NES/SNES (requires emulator support for shaders - e.g., if using RetroArch backend or specific emulator shader flags).
    -   Configure `dot` matrix filter for GBA.

3.  **Gamepad Support**:
    -   Implement input configuration UI to map gamepad buttons to emulator inputs.
    -   Detect connected controllers (SDL2 or `evdev`).

## Deliverables
-   Grid view populated with real cover art.
-   Games looking "retro" with correct shaders applied.

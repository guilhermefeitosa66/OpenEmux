# Opemux Project Roadmap

This document outlines delivery phases and current status.

## Phase 1: Core Frontend & Architecture
**Goal**: Establish the application structure, UI, and basic configuration management.
-   [x] Initialize project structure (Python/GTK4).
-   [x] Implement main window with Sidebar (Consoles) and Main Area (ROM Grid).
-   [x] Create configuration system (`~/.opemux/config.yaml`).
-   [x] Implement ROM scanning in `~/games/roms/` (recursive scan per console).
-   [x] Display placeholder cover art for ROMs.

## Phase 2: Emulator Integration
**Goal**: Launch games using embedded emulator cores.
-   [x] Integrate **Nestopia** (NES), **Snes9x** (SNES), and **mGBA** (GBA).
-   [x] Set up `vendors/` directory for emulator dependencies.
-   [x] Implement process management to launch emulators from the GUI.
-   [ ] Basic keyboard input mapping at Opemux level.

## Phase 3: Visuals & Advanced Features
**Goal**: Enhance the visual experience and usability.
-   [ ] Implement Shader support (compiling/loading shaders).
    -   `geom-crt` for NES/SNES.
    -   `dot` matrix shader for GBA.
-   [x] Automatic cover art downloading/scraping (ScreenScraper integration).
-   [ ] Gamepad support (Input configuration UI at Opemux level).

## Phase 4: Integrated Runtime Experience
**Goal**: Reduce external emulator UX and move toward OpenEmu-style runtime.
-   [ ] Add external wrapper "kiosk mode" behavior (best-effort flags per emulator).
-   [ ] Build integrated runtime bridge in Opemux (single app workflow and lifecycle handling).
-   [ ] Migrate to embedded core runtime (`runtime.mode=integrated_core`) for unified window experience.

## Phase 5: Input Management (Application-Level)
**Goal**: Configure controls in Opemux, not in vendor emulator UIs.
-   [ ] Add per-system global control profiles in config.
-   [ ] Build controls settings UI for keyboard and gamepad.
-   [ ] Apply mappings consistently at runtime.

## Phase 6: Cover Pipeline & Local Cache Strategy
**Goal**: Unify downloaded and custom covers in the ROM directory.
-   [x] Read local covers from `<roms>/covers/<console>/<rom_name>.png|jpg|webp`.
-   [x] Save downloaded covers into the same local structure.
-   [ ] Add cover metadata index and refresh/re-download policy.

## Phase 7: Shader & Visual Pipeline
**Goal**: Deliver per-system visual presets with backend-aware fallback.
-   [ ] Add Visual settings UI and per-console presets.
-   [ ] Implement shader/filter backend adapters (external wrapper and future integrated core).
-   [ ] Add fallback behavior when a shader is unsupported by active runtime.

## Future Considerations
-   Support for more systems (Genesis, N64, PS1).
-   Save state management.
-   RetroAchievements integration.

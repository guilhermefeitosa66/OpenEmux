# Opemux Project Roadmap

This document outlines delivery phases and current status.

## Phase 1: Core Frontend & Architecture
**Goal**: Establish the application structure, UI, and basic configuration management.
-   [x] Initialize project structure (Python/GTK4).
-   [x] Implement main window with Sidebar (Consoles) and Main Area (ROM Grid).
-   [x] Create configuration system (`~/.opemux/config.yaml`).
-   [x] Implement ROM scanning in `~/games/roms/` (recursive scan per console).
-   [x] Display placeholder cover art for ROMs.

## Phase 2: Runtime Backend Simplification
**Goal**: Standardize execution through RetroArch and reduce maintenance complexity.
-   [x] Route NES/SNES/GBA execution through `retroarch -L <core> <rom>`.
-   [x] Prefer vendored RetroArch AppImage with fallback to system `retroarch`.
-   [x] Remove legacy emulator vendor dependencies from the repository.

## Phase 3: Cover Pipeline
**Goal**: Unify local and downloaded cover art in a single strategy.
-   [x] Read local covers from `<roms>/covers/<console>/<rom_name>.png|jpg|webp`.
-   [x] Save downloaded covers into the same local structure.
-   [x] Add async `Sync Covers` background job with scope selector (current console or all).
-   [x] Add playlist index files (`~/.opemux/playlists/<console>.list`) and manual rescan flow.
-   [ ] Add cover metadata index and refresh/re-download policy.

## Phase 4: Runtime UX Integration
**Goal**: Improve user experience while running external RetroArch process.
-   [x] Build runtime bridge in Opemux (single active process, launch/stop lifecycle handling).
-   [ ] Add optional embedded runtime (`runtime.mode=integrated_core`) for fully unified game window.

## Phase 5: Input Management (Application-Level)
**Goal**: Configure controls in Opemux, not directly in RetroArch UI.
-   [x] Add per-system global control profiles in config.
-   [x] Build controls settings UI for keyboard and gamepad.
-   [x] Apply mappings consistently at runtime.

## Phase 6: Shader & Visual Pipeline
**Goal**: Deliver system-specific visual presets with backend-aware fallback.
-   [ ] Add Visual settings UI and per-console presets.
-   [ ] Implement shader/filter adapters for RetroArch backend and future integrated core.
-   [ ] Add fallback behavior when a shader is unsupported by active runtime.

## Phase 7: First-Boot Bootstrap
**Goal**: Make first-time setup fully automated and transparent to users.
-   [x] Add startup bootstrap state and first-run detection in config.
-   [x] Create first-boot loading flow with progress messages.
-   [x] Ensure baseline Opemux folders/files are generated on first run.
-   [x] Seed playlists and per-console input profiles automatically.
-   [x] Download/install RetroArch cores via Buildbot updater integration.
-   [x] Add retry entrypoint under Settings > System for failed/pending setup.

## Future Considerations
-   Support for more systems (Genesis, N64, PS1).
-   Save state management.
-   RetroAchievements integration.

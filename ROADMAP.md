# Opemux Project Roadmap

This document outlines the planned development phases for Opemux.

## Phase 1: Core Frontend & Architecture
**Goal**: Establish the application structure, UI, and basic configuration management.
-   [ ] Initialize project structure (Python/GTK4).
-   [ ] Implement main window with Sidebar (Consoles) and Main Area (ROM Grid).
-   [ ] Create configuration system (`~/.opemux/config.yaml`).
-   [ ] Implement ROM scanning in `~/games/roms/` (recurse into subfolders: `nes`, `snes`, `gba`).
-   [ ] Display placeholder cover art for ROMs.

## Phase 2: Emulator Integration
**Goal**: Launch games using embedded emulator cores.
-   [ ] Integrate **Nestopia** (NES), **Snes9x** (SNES), and **mGBA** (GBA).
-   [ ] Set up `vendors/` directory for emulator dependencies.
-   [ ] Implement process management to launch emulators from the GUI.
-   [ ] Basic keyboard input mapping.

## Phase 3: Visuals & Advanced Features
**Goal**: Enhance the visual experience and usability.
-   [ ] Implement Shader support (compiling/loading shaders).
    -   `geom-crt` for NES/SNES.
    -   `dot` matrix shader for GBA.
-   [ ] Automatic cover art downloading/scraping.
-   [ ] Gamepad support (Input configuration UI).

## Future Considerations
-   Support for more systems (Genesis, N64, PS1).
-   Save state management.
-   RetroAchievements integration.

# Phase 2: Emulator Integration

**Goal:** Integrate emulator cores (Nestopia, Snes9x, mGBA) and launch games from the UI.

## Requirements

1.  **Vendor Management**:
    -   Populate `vendors/` with submodules for:
        -   `nestopia` (NES)
        -   `snes9x` (SNES)
        -   `mgba` (GBA)
    -   Create build scripts/makefiles to compile these as shared libraries or standalone executables if needed (depending on integration strategy - prefer libretro/core approach if feasible, or command-line wrapping). *Decision*: For Phase 2, assume command-line wrapping of installed emulators OR compiling specific cores.
    -   *Update*: User requested "wrapping open source emulators". We will assume we can invoke them via subprocess or load them as libraries. Let's start with **Subprocess Wrapper** for simplicity and stability, unless user specified otherwise.

2.  **Launching Games**:
    -   Implement a `Launcher` class in `src/opemux/core/launcher.py`.
    -   Map file extensions to specific emulators.
    -   Execute the emulator process with the selected ROM.

3.  **Input Configuration**:
    -   Verify basic keyboard input works in the launched emulators.
    -   Create a basic mapping config in `config.yaml` to pass to emulators if supported (CLI args or config file generation).

## Deliverables
-   Working "Play" button or double-click action on ROMs.
-   Games launching in their respective emulators.

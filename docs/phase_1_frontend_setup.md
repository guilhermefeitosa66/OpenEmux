# Phase 1: Frontend Setup & Configuration

**Goal:** Establish the core application structure, main window UI with GTK4/LibAdwaita, and basic configuration management.

## Requirements

1.  **Project Initialization**:
    -   Set up a Python project structure with `src/opemux` package.
    -   Define `requirements.txt` listing GTK4 bindings (PyGObject).

2.  **Main Window UI**:
    -   Create a main application window using `Adw.ApplicationWindow`.
    -   Implement a **Sidebar** (List of consoles: NES, SNES, GBA).
    -   Implement a **Main Content Area** (Grid view for ROMs).
    -   Use placeholder images for cover art initially.

3.  **Configuration System**:
    -   Implement a configuration manager using `yaml`.
    -   Load/Save config from `~/.opemux/config.yaml`.
    -   Define default `roms_path` as `~/games/roms/`.

4.  **ROM Scanning**:
    -   On startup, scan `roms_path` (and subdirectories `nes`, `snes`, `gba`) for supported file extensions (`.nes`, `.sfc`, `.smc`, `.gba`).
    -   Populate the UI grid with discovered ROMs.

## Directory Structure Target
```
src/
  opemux/
    __init__.py
    main.py         # Entry point
    ui/
      window.py     # Main Window
      sidebar.py    # Console list
      grid.py       # ROM grid
    core/
      config.py     # Configuration manager
      scanner.py    # ROM scanner
```

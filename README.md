# Opemux

**Opemux** is a Linux-native emulator frontend inspired by OpenEmu, designed to provide a seamless and visually stunning retro gaming experience on the GNOME desktop environment.

Built with **Python** and **GTK4** (PyGObject), Opemux focuses on simplicity, elegance, and native integration with the Linux ecosystem. It is distributed as an **AppImage** for universal compatibility across Linux distributions.

## Features

-   **Native Linux Design**: Built with GTK4 for a modern, responsive interface that feels at home on GNOME and other desktop environments.
-   **Multi-System Support**: **NES**, **SNES**, and **GBA** via RetroArch + libretro cores.
-   **Game Library Organization**: Automatically scans and organizes your ROM collection.
    -   Default ROM path: `~/games/roms/` (Configurable).
-   **Cover Pipeline**: Local-first covers from `~/games/roms/covers/<console>/` with Libretro Thumbnails sync.
-   **Runtime Control**: Launch/stop flow managed by Opemux while RetroArch runs externally.
-   **Settings UI**: Sidebar `Configurações` with ROM management actions (`Path`, `Scan ROMs`, `Sync Covers`).
-   **Visual Enhancements**: Shader/filter configuration roadmap (in progress).
-   **Input Mapping**: Per-console keyboard/gamepad mapping with RetroArch runtime integration.

## Runtime Backend

-   **Preferred**: `vendors/RetroArch-Linux-x86_64.AppImage`
-   **Fallback**: system `retroarch` binary
-   **Cores**: libretro cores per console (`nestopia`/`fceumm`, `snes9x`, `mgba`)

## Planning Docs

-   Implementation phase notes live in `implementation_notes/`.

## Input Mapping

-   Profiles are saved per console in `~/.opemux/input/<CONSOLE>.config`.
-   Gameplay actions shown in the UI are console-specific (example: GBA does not show `X/Y`).
-   Each console has two editable device profiles:
    -   `Keyboard`
    -   `Gamepad Port 1`
-   At runtime, Opemux translates mappings to RetroArch `input_*` keys and passes them through `--appendconfig`.

Default keyboard mapping:
-   D-Pad: `up`, `down`, `left`, `right`
-   `A/B/X/Y`: `z`, `x`, `s`, `c`
-   `Start`: `enter`
-   `Select`: `space`
-   `R1/R2/R3`: `a`, `q`, `1`
-   `L1/L2/L3`: `d`, `e`, `3`

Runtime hotkeys (default):
-   `Enable hotkey`: `right shift`
-   `RetroArch menu`: `f1`
-   `Save state`: `f2`
-   `Load state`: `f4`
-   `Fast-forward toggle`: `f6`

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

# Opemux

**Opemux** is a Linux-native emulator frontend inspired by OpenEmu, designed to provide a seamless and visually stunning retro gaming experience on the GNOME desktop environment.

Built with **Python** and **GTK4** (PyGObject), Opemux focuses on simplicity, elegance, and native integration with the Linux ecosystem. It is distributed as an **AppImage** for universal compatibility across Linux distributions.

## Features

-   **Native Linux Design**: Built with GTK4 for a modern, responsive interface that feels at home on GNOME and other desktop environments.
-   **Multi-System Support**: **NES**, **SNES**, and **GBA** via RetroArch + libretro cores.
-   **Game Library Organization**: Automatically scans and organizes your ROM collection.
    -   Default ROM path: `~/games/roms/` (Configurable).
-   **Cover Pipeline**: Local-first covers from `~/games/roms/covers/<console>/` with ScreenScraper fallback.
-   **Runtime Control**: Launch/stop flow managed by Opemux while RetroArch runs externally.
-   **Visual Enhancements**: Shader/filter configuration roadmap (in progress).
-   **Input Mapping**: Application-level mapping roadmap (in progress).

## Runtime Backend

-   **Preferred**: `vendors/RetroArch-Linux-x86_64.AppImage`
-   **Fallback**: system `retroarch` binary
-   **Cores**: libretro cores per console (`nestopia`/`fceumm`, `snes9x`, `mgba`)

## Planning Docs

-   Implementation phase notes live in `implementation_notes/`.

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

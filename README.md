# Opemux

**Opemux** is a Linux-native emulator frontend inspired by OpenEmu, designed to provide a seamless and visually stunning retro gaming experience on the GNOME desktop environment.

Built with **Python** and **GTK4** (PyGObject), Opemux focuses on simplicity, elegance, and native integration with the Linux ecosystem. It is distributed as an **AppImage** for universal compatibility across Linux distributions.

## Features (Planned)

-   **Native Linux Design**: Built with GTK4 for a modern, responsive interface that feels at home on GNOME and other desktop environments.
-   **Multi-System Support**: Initially supporting **NES**, **SNES**, and **GBA**.
-   **Game Library Organization**: Automatically scans and organizes your ROM collection.
    -   Default ROM path: `~/games/roms/` (Configurable).
-   **Visual Enhancements**: Support for **CRT shaders** (geom-crt) and dot-matrix filters for handhelds.
-   **Keyboard Input**: Initially keyboard-only, with future gamepad support planned.

## Technology Stack

-   **Language**: Python 3
-   **GUI Framework**: GTK4 + LibAdwaita (via PyGObject)
-   **Distribution**: AppImage

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

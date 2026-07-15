# Phase 02: RetroArch Runtime

**Goal:** Simplify runtime execution by standardizing on RetroArch + libretro cores.

## Scope
- Route NES/SNES/GBA launches through `retroarch -L <core> <rom>`.
- Resolve RetroArch binary in this order:
  1. configured path (`runtime.retroarch.binary`)
  2. vendored AppImage (`vendors/RetroArch-Linux-x86_64.AppImage`)
  3. system `retroarch`
- Resolve core paths from configured hints and common core directories.
- Keep runtime lifecycle in OpenEmux (single active process + stop/poll).

## Delivered
- RetroArch wrapper launcher.
- Per-console runtime backend mapping.
- Runtime lifecycle controls integrated in UI.

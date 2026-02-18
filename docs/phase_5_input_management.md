# Phase 5: Input Management (Application-Level)

**Goal:** Manage controls from Opemux, not from vendor emulator configuration windows.

## Scope

1. **Global Profiles by Console**
   - Store mappings under `controls.profiles.<console>` in config.
   - First milestone: one profile per system (NES/SNES/GBA).

2. **Input Settings UI**
   - Build keyboard and gamepad mapping screen in Opemux.
   - Detect connected gamepads and allow remapping.

3. **Runtime Application**
   - Apply Opemux mappings when a game starts.
   - Keep backend-specific adapters behind a common mapping interface.

## Deliverables
- Stable config schema for global per-system controls.
- In-app controls settings UI.
- Runtime application path for keyboard + gamepad mappings.

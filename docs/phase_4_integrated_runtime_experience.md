# Phase 4: Integrated Runtime Experience

**Goal:** Move from "launcher of external apps" to an OpenEmu-like integrated gameplay experience.

## Scope

1. **External Wrapper Kiosk Mode (short term)**
   - Keep subprocess strategy for stability.
   - Add best-effort fullscreen/menu-minimizing flags per emulator.
   - Keep fallback when flags are unsupported.
   - Add optional `retroarch_wrapper` backend for more consistent cross-system behavior.

2. **Runtime Bridge (mid term)**
   - Centralize runtime lifecycle in a dedicated manager.
   - Track launch state, process errors, and return paths to library view.
   - Prepare interface for backend switching (`external_wrapper` vs `integrated_core`).

3. **Integrated Core Runtime (long term)**
   - Implement embedded runtime mode (`runtime.mode=integrated_core`).
   - Render gameplay inside Opemux-controlled surface/window.
   - Remove visible dependence on external emulator menus/windows.

## Deliverables
- Runtime mode abstraction used by UI launch actions. (implemented for external mode)
- External kiosk controls documented per emulator. (implemented as config-driven best-effort flags)
- Runtime lifecycle controls for external mode (single active game, stop action, process polling).
- Design-ready interface for embedded core migration.

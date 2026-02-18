# Phase 04: Runtime UX Integration

**Goal:** Improve launch experience while running external runtime backend.

## Scope
- Track active process state.
- Block concurrent game launches.
- Provide explicit stop action from Opemux UI.
- Poll process completion and show user feedback.

## Delivered
- Runtime manager with lifecycle state.
- Header stop button and toasts for launch/finish/error events.

## Next
- Embedded runtime mode (`integrated_core`) for fully unified in-app gameplay window.

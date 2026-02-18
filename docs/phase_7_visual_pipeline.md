# Phase 7: Shader & Visual Pipeline

**Goal:** Deliver system-specific visual presets with predictable runtime compatibility.

## Scope

1. **Visual Settings Model**
   - Add per-console preset choices (e.g., `geom-crt`, `dot-matrix`, `none`).
   - Persist settings in config.

2. **Backend Adapters**
   - For `external_wrapper`, translate presets to emulator-compatible flags/configs.
   - For `integrated_core`, apply shader/filter chain directly.

3. **Fallback Rules**
   - Detect unsupported shader options for active backend.
   - Downgrade gracefully to a supported preset and notify user.

## Deliverables
- Visual settings UI + config schema.
- Runtime adapter implementation per backend.
- Compatibility fallback and user feedback flow.

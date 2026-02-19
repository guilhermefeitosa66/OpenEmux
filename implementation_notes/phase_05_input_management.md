# Phase 05: Input Management

## Goal
Move input mapping ownership to Opemux while keeping RetroArch as runtime backend.

## Implemented Scope
- Per-console input profiles stored outside `config.yaml`.
- Separate mappings for keyboard and gamepad profile (`Gamepad Port 1`).
- GTK-based input mapping screen under Settings > Input.
- Runtime adapter that converts Opemux mappings into RetroArch overrides at launch.
- Default profile bootstrap on first run.

## Data Model
Profiles are stored at:
- `~/.opemux/input/<CONSOLE>.config`

Format:
- JSON with `version`, `console`, `active_device`, `devices.keyboard`, `devices.gamepad_p1`.
- Each device stores action->binding map.

Actions currently supported:
- Gameplay: `up`, `down`, `left`, `right`, `a`, `b`, `x`, `y`, `start`, `select`, `l1`, `l2`, `l3`, `r1`, `r2`, `r3`
- Hotkeys: `enable_hotkey`, `menu_toggle`, `save_state`, `load_state`, `fast_forward_toggle`

Console-specific gameplay action sets:
- GBA: `up/down/left/right/a/b/l1/r1/start/select`
- SFC: `up/down/left/right/a/b/x/y/l1/r1/start/select`
- FC/FDS/GB/GBC/GG and similar 2-button systems: `up/down/left/right/a/b/start/select`
- All consoles keep hotkeys: `enable_hotkey/menu_toggle/save_state/load_state/fast_forward_toggle`

Current policy for complex systems:
- Uses canonical generation-equivalent layouts (not full hardware-specific controls yet).
- Future work can add per-system specialized buttons (e.g., N64 C-buttons/keypads).

## Default Keyboard Mapping
- D-Pad: `up/down/left/right`
- `A/B/X/Y`: `z/x/s/c`
- `Start`: `enter`
- `Select`: `space`
- `R1/R2/R3`: `a/q/1`
- `L1/L2/L3`: `d/e/3`
- `Enable hotkey`: `right shift`
- `Menu`: `f1`
- `Save state`: `f2`
- `Load state`: `f4`
- `Fast-forward toggle`: `f6`

## RetroArch Integration
At launch, Opemux now:
1. Loads active input device mapping for selected console.
2. Converts action bindings to RetroArch `input_*` keys.
3. Writes a temporary override in `~/.opemux/runtime/input_<console>_<timestamp>.cfg`.
4. Launches RetroArch using `--appendconfig <override>`.

Notes:
- Keyboard mappings generate keys like `input_player1_a`.
- Gamepad mappings generate `_btn` or `_axis` keys based on token syntax.
- `enable_hotkey=right shift` prevents conflict with gameplay inputs (notably `select=space`).

## UI Behavior
Settings > Input includes:
- Console selector
- Input device selector (`Keyboard`, `Gamepad Port 1`)
- Editable list of action bindings
- Buttons: `Save`, `Reset defaults`

Saving writes to `~/.opemux/input/<CONSOLE>.config`.
Reset restores defaults for that console.

## Known Limitations (Current Phase)
- No live gamepad capture (manual token entry for gamepad mapping).
- Device list is static (keyboard + gamepad port 1), no runtime device discovery.
- No visual gamepad/joypad overlay mapping yet.

## Future Step
Use imported OpenEmu controller images to provide clickable visual mapping regions per console/controller for a better input configuration UX.

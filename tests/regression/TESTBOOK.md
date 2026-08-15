# OpenEmux Regression Test Book

This file is the single source of truth for regression testing. A test runner (human or the
`regression-tests` skill) executes **every** scenario below, in ascending ID order, and reports one
verdict per scenario. Scenarios are written the way a QA person would run them by hand; the
**Check** field tells an automated runner exactly how to verify the same thing.

## Rules for this file

- **IDs are permanent.** `RT-NNN` is never renumbered and never reused. A scenario that no longer
  applies moves to the *Retired* section at the bottom, with the reason and the date.
- **One observable behavior per scenario.** If a change makes a scenario test two things, split it.
- **Update this file in the same PR that changes behavior.** Adding a feature adds scenarios;
  changing behavior edits the affected scenarios; removing behavior retires them. Reviewers should
  treat a behavior change without a test-book change as incomplete.
- Write steps in plain English, as instructions to a person. UI words go in quotes, exactly as the
  interface shows them ("Settings", "Welcome", "Main Menu").
- Every scenario has a **Mode**:

| Mode | Meaning | How the runner executes it |
| --- | --- | --- |
| `AUTO-SUITE` | Covered by unit tests | One run of the full suite; the scenario's verdict follows the listed test files |
| `AUTO-PROBE` | Verifiable headlessly | Run the exact command in **Check**; `RT-NNN OK` on stdout = PASS, `AssertionError` = FAIL, any other error = BLOCKED |
| `AUTO-UI` | Verifiable by driving the real app on X11 | Follow **Steps** with the UI driver, save a screenshot per observation |
| `MANUAL` | Needs the human (hardware, a real game session) | Never executed by the runner; reported as `N/A (manual)` and handed to the developer |

- **Safety:** automated scenarios must not damage the real library. Anything that creates, renames
  or deletes user data through the UI is `MANUAL` or `AUTO-SUITE` (the logic is unit-tested; the
  destructive UI flow is exercised by the human on a throwaway file). The only allowed mutations in
  `AUTO-UI`/`AUTO-PROBE` scenarios are **self-restoring** (toggle and toggle back, edit a copy,
  backup-then-restore) and the scenario must spell out the restore step.
- `$SCRATCH` in Check commands is the runner's scratch directory. Probes run from the repository
  root on the `develop` branch with `PYTHONPATH=src .venv/bin/python`.

### Scenario template

```markdown
### RT-NNN — <short behavior statement>
- **Area:** <group name>
- **Mode:** AUTO-SUITE | AUTO-PROBE | AUTO-UI | MANUAL
- **Preconditions:** <state required before starting>
- **Steps:**
  1. <what a QA person does>
- **Expected:** <what a QA person must observe — specific and falsifiable>
- **Check:** <suite files | exact probe command | what the screenshot must show | "human only">
- **Restore:** <only if the scenario mutates anything>
```

---

## Startup

### RT-001 — The app launches clean
- **Area:** Startup
- **Mode:** AUTO-UI
- **Preconditions:** `develop` checked out, `make bootstrap` already done on this machine.
- **Steps:**
  1. Launch the app (`make run`).
  2. Wait for the main window.
- **Expected:** The "OpenEmux" window appears with the sidebar ("Library") and a game grid. No
  crash dialog.
- **Check:** `wmctrl -l` lists a window titled `OpenEmux` within 25 s, and the launch log contains
  no `Traceback` and no `CRITICAL` (`grep -niE "traceback|critical" $SCRATCH/app.log`).

### RT-002 — The unit suite passes
- **Area:** Startup
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:**
  1. Run the full unit suite.
- **Expected:** Every test passes.
- **Check:** `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` exits 0 and prints
  `OK`. This one command also settles every `AUTO-SUITE` scenario below.

## Library & scanning

### RT-010 — Rescan keeps the library consistent
- **Area:** Library
- **Mode:** AUTO-UI
- **Preconditions:** App running, a console with games selected.
- **Steps:**
  1. Note the game count in the header subtitle ("N games").
  2. Press `F5` and wait for the rescan to finish.
- **Expected:** The same count and the same games; nothing disappears or duplicates.
- **Check:** Screenshot of the header before and after; counts match.

### RT-011 — The scanner matches files by extension per system
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: put a `.sfc` file and a `.txt` file in a `SFC/` folder, a `.gba` file
  in `GBA/`, and scan.
- **Expected:** The `.sfc` and `.gba` files are found under their systems; the `.txt` is ignored.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import tempfile
  from pathlib import Path
  from openemux.core.scanner import RomScanner
  with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      (root / "SFC").mkdir(); (root / "GBA").mkdir()
      (root / "SFC" / "game.sfc").write_bytes(b"\0" * 64)
      (root / "SFC" / "notes.txt").write_text("not a rom")
      (root / "GBA" / "game.gba").write_bytes(b"\0" * 64)
      lib = RomScanner(root).scan_all()
      assert len(lib["SFC"]) == 1, lib["SFC"]
      assert len(lib["GBA"]) == 1, lib["GBA"]
  print("RT-011 OK")
  EOF
  ```

### RT-012 — Playlist files are well-formed
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** The library has been scanned at least once on this machine.
- **Steps:** Open `~/.openemux/playlists/` and inspect the per-console `.list` files.
- **Expected:** Each is a UTF-8 text file; every non-empty line is an absolute path.
- **Check:**
  ```bash
  .venv/bin/python - <<'EOF'
  from pathlib import Path
  pdir = Path.home() / ".openemux" / "playlists"
  files = sorted(pdir.glob("*.list"))
  assert files, f"no playlists in {pdir}"
  for f in files:
      for line in f.read_text(encoding="utf-8").splitlines():
          line = line.strip()
          assert not line or line.startswith("/"), f"{f.name}: {line!r}"
  print(f"RT-012 OK — {len(files)} playlists well-formed")
  EOF
  ```

### RT-013 — Rename carries save states, battery saves and artwork
- **Area:** Library
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: rename a ROM (`F2`) that has save states, a battery save and a cover;
  reopen "Load state" and the cover.
- **Expected:** States, battery saves and artwork follow the new name (issue #134).
- **Check:** suite files `tests/test_save_states.py`, `tests/test_rom_importer.py`.

## Navigation & search

### RT-020 — Sidebar navigation switches consoles
- **Area:** Navigation
- **Mode:** AUTO-UI
- **Preconditions:** App running, at least two consoles with games.
- **Steps:**
  1. Click a console in the sidebar (e.g. "FC - Nintendo (NES) / Famicom").
  2. Click a different console (e.g. "SFC - Super Nintendo (SNES)").
- **Expected:** The header title and the grid follow each selection; the game count subtitle
  matches the console.
- **Check:** One screenshot per console; header title matches the clicked row.

### RT-021 — Search filters the current scope
- **Area:** Navigation
- **Mode:** AUTO-UI
- **Preconditions:** App running, a console whose library contains a known title.
- **Steps:**
  1. Press `Ctrl+F`; the search bar appears.
  2. Type a word from a title that exists (e.g. "Mario").
  3. Press `Escape`.
- **Expected:** While typing, the grid shows only matching games; `Escape` closes the bar and
  restores the full grid.
- **Check:** Screenshot of the filtered grid (only matching titles visible) and of the restored one.

### RT-022 — Empty search shows the empty state
- **Area:** Navigation
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Press `Ctrl+F` and type a string that matches nothing (e.g. "zzzzqqqq").
- **Expected:** An empty-state page (no leftover cards, no crash).
- **Check:** Screenshot shows the empty state; log gained no `Traceback`.
- **Restore:** Press `Escape`.

## View modes & layout

### RT-030 — The three view modes render
- **Area:** Views
- **Mode:** AUTO-UI
- **Preconditions:** App running, a console with covers synced.
- **Steps:**
  1. In the header bar, switch through the three view segments: cartridge shelf, cover grid,
     compact list.
- **Expected:** Each mode renders the same games; no blank canvas, no crash.
- **Check:** One screenshot per mode. Locate the three-segment switcher on a probe capture first —
  its position moves as the header evolves.
- **Restore:** Return to the mode that was active at the start (record it on the first capture).

### RT-031 — The view mode persists across a restart
- **Area:** Views
- **Mode:** AUTO-UI
- **Preconditions:** RT-030 knowledge of the switcher position.
- **Steps:**
  1. Record the current mode, then switch to a different one.
  2. Quit (`Ctrl+Q`) and relaunch the app.
- **Expected:** The app reopens in the mode chosen in step 1.
- **Check:** `PYTHONPATH=src .venv/bin/python -c "from openemux.core.config import ConfigManager;
  print(ConfigManager().get_view_mode())"` after step 1 matches the chosen mode, and a screenshot
  after relaunch shows it.
- **Restore:** Switch back to the recorded original mode.

### RT-032 — Zoom in, out and reset
- **Area:** Views
- **Mode:** AUTO-UI
- **Preconditions:** App running, cover grid visible.
- **Steps:**
  1. Press `Ctrl`+`+` twice, then `Ctrl`+`-` once, then `Ctrl+0`.
- **Expected:** Cards grow, shrink, and return to the default size.
- **Check:** Screenshots after each step; card size visibly changes and returns.

### RT-033 — The window adapts when narrow
- **Area:** Views
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Resize the window to ~700 px wide.
  2. Press `F6` to move focus between panes.
- **Expected:** The split view collapses (sidebar becomes a page you can navigate to); nothing is
  cut off; `F6` still moves focus.
- **Check:** Screenshot of the collapsed layout.
- **Restore:** Resize back to the canonical geometry.

## Favorites & collections

### RT-040 — Favorite toggle round-trip
- **Area:** Favorites
- **Mode:** AUTO-UI
- **Preconditions:** App running; pick a game that is currently **not** a favorite.
- **Steps:**
  1. Focus the game and press `Ctrl+D`.
  2. Open "Favorites" in the sidebar and confirm the game is listed.
  3. Press `Ctrl+D` on it again.
- **Expected:** The game enters and then leaves "Favorites"; the star indicator follows.
- **Check:** Screenshot with the game in "Favorites", and `FAVORITES.list` gaining and losing the
  ROM's path (`grep -c "<rom filename>" ~/.openemux/playlists/FAVORITES.list`).
- **Restore:** Step 3 is the restore; verify the count is back to the initial value.

### RT-041 — A collection lists its games
- **Area:** Favorites
- **Mode:** AUTO-UI
- **Preconditions:** At least one user collection exists in the sidebar (e.g. "Megaman").
- **Steps:**
  1. Click the collection in the sidebar.
- **Expected:** The grid shows the collection's games, mixed consoles allowed; header shows the
  collection name.
- **Check:** Screenshot.

### RT-042 — Creating and deleting a collection
- **Area:** Favorites
- **Mode:** MANUAL
- **Preconditions:** —
- **Steps:**
  1. Click "New collection", name it "QA temp", add two games from different consoles.
  2. Confirm both appear under it; remove the collection afterwards.
- **Expected:** The collection appears in the sidebar with its games and is cleanly removed.
- **Check:** human only (mutates the sidebar; kept out of automation on purpose).

## Covers & artwork

### RT-050 — Local covers render in the grid
- **Area:** Covers
- **Mode:** AUTO-UI
- **Preconditions:** A console known to have full artwork (e.g. SFC).
- **Steps:**
  1. Open that console in cover-grid mode.
- **Expected:** Cards show artwork, not the "missing artwork" placeholder.
- **Check:** Screenshot; no placeholder tiles visible.

### RT-051 — The missing-artwork filter isolates gaps
- **Area:** Covers
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Open the view options and enable "Show only ROMs without artwork" (issue #127).
  2. Disable it again.
- **Expected:** With the filter on, only games without covers remain (possibly an empty state);
  off restores the full grid. The filter is deliberately not persisted.
- **Check:** Screenshot in each state.
- **Restore:** Step 2 is the restore.

### RT-052 — Cover sync fetches missing artwork
- **Area:** Covers
- **Mode:** MANUAL
- **Preconditions:** A console with at least one game missing artwork; network access.
- **Steps:**
  1. Press `Ctrl+Shift+S` (or the sync button in the header).
  2. Watch the progress banner; wait for completion.
- **Expected:** The banner reports progress, covers appear incrementally (issue #187), and the run
  ends without errors.
- **Check:** human only (network-dependent and slow; logic covered by `tests/test_cover_sync.py`,
  `tests/test_artwork_search.py`, `tests/test_artwork_suggestions.py` via RT-002).

## Launch & runtime

### RT-060 — RetroArch is available
- **Area:** Launch
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:** Run the RetroArch availability check.
- **Expected:** A RetroArch binary (vendored AppImage or system) is found.
- **Check:** `make check-retroarch` exits 0.

### RT-061 — The launch command is built correctly
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: launch a game and confirm RetroArch receives the right core, ROM path,
  input mappings (`--appendconfig`) and shader override.
- **Expected:** The invocation matches the console's configuration.
- **Check:** suite files `tests/test_retroarch_command.py`, `tests/test_retroarch_launcher.py`,
  `tests/test_runtime_manager.py`.

### RT-062 — A game launches and plays
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A working core and ROM for at least one console; "Play in an OpenEmux window"
  on (the default) and an X11/XWayland session.
- **Steps:**
  1. Double-click (or press Enter on) a game.
  2. Play for ~30 s; close the game window.
- **Expected:** The game appears *inside* an OpenEmux window titled with the ROM name, with the
  header bar carrying pause, reset, save state, load state, controller settings, volume and the
  RetroArch menu. Sound plays, input responds, and closing the window ends the game and returns
  to the library cleanly.
- **Check:** human only (grabbing the keyboard for the emulator makes automation unsafe).

### RT-064 — Turning the game window off gives RetroArch its own window
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session.
- **Steps:**
  1. "Settings" → "Video" → turn "Play in an OpenEmux window" off.
  2. Launch a game.
- **Expected:** No OpenEmux wrapper appears; RetroArch opens its own decorated window and behaves
  exactly as it did before the feature existed — its fullscreen hotkey included.
- **Check:** human only.
- **Restore:** Turn the switch back on.

### RT-065 — A session that cannot embed says so instead of failing
- **Area:** Launch
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:** As a QA person: on a machine with no X display (a pure Wayland session, the Flatpak
  sandbox), confirm the app still starts and the "Play in an OpenEmux window" switch is
  unavailable rather than broken.
- **Expected:** With no X display reachable, embedding reports itself impossible — so the startup
  code never forces the X11 backend and the launcher never writes the embed overrides.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from unittest import mock
  from openemux.core import game_window_support as g
  with mock.patch.dict(os.environ, {}, clear=True):
      assert not g.embedding_possible(), "claimed embedding is possible with no DISPLAY"
  with mock.patch.dict(os.environ, {"DISPLAY": ":0", "GDK_BACKEND": "wayland"}, clear=True):
      assert not g.embedding_possible(), "ignored an explicit non-X11 backend"
  print("RT-065 OK")
  EOF
  ```

### RT-063 — In-game hotkeys work
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session.
- **Steps:**
  1. In game, use the hint-bar hotkeys: hold and press `F` (fullscreen toggle), hold and press
     `F1` (RetroArch menu); save and load a state.
- **Expected:** Each hotkey does what the hint bar promises.
- **Check:** human only.

## Input

### RT-070 — Input profiles on disk are valid
- **Area:** Input
- **Mode:** AUTO-PROBE
- **Preconditions:** First boot completed on this machine.
- **Steps:** Inspect `~/.openemux/input/*.config`.
- **Expected:** Every per-console profile parses as JSON.
- **Check:**
  ```bash
  .venv/bin/python - <<'EOF'
  import json
  from pathlib import Path
  d = Path.home() / ".openemux" / "input"
  files = sorted(d.glob("*.config"))
  assert files, f"no profiles in {d}"
  for f in files:
      json.loads(f.read_text(encoding="utf-8"))
  print(f"RT-070 OK — {len(files)} profiles parse")
  EOF
  ```

### RT-071 — Remapping a control in Settings
- **Area:** Input
- **Mode:** MANUAL
- **Preconditions:** App running.
- **Steps:**
  1. Open "Settings" (`Ctrl+,`) → "Input"; pick a console; remap one action to a new key.
  2. Close and reopen "Settings"; check the binding.
- **Expected:** Capture grabs the pressed key exclusively (issue #32), the new binding persists,
  and a game launched afterwards honors it.
- **Check:** human only (input capture cannot be driven safely by the automation that would also
  be sending the keys).
- **Restore:** Remap the action back.

### RT-072 — A gamepad is detected and drives the UI
- **Area:** Input
- **Mode:** MANUAL
- **Preconditions:** A physical controller.
- **Steps:**
  1. Plug the controller in with the app open.
  2. Navigate the grid and launch a game with it.
- **Expected:** The gamepad indicator appears in the header; UI navigation and the game respond.
- **Check:** human only (hardware).

### RT-073 — A console's context menu opens its own controller settings
- **Area:** Input
- **Mode:** AUTO-UI
- **Preconditions:** App running, showing a console *other* than the one to be right-clicked.
- **Steps:**
  1. Right-click a console in the sidebar (or click its "⋯" button).
  2. Choose "Controller settings".
- **Expected:** "Settings" opens on the "Input" page with the **right-clicked** console selected
  in the console row — not the one the library was showing.
- **Check:** screenshot of the Input page; the console row must name the console from step 1.

## Shaders

### RT-080 — Shader selection round-trips through the store
- **Area:** Shaders
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: pick a shader for a console in "Settings" → "Video" and confirm it is
  remembered.
- **Expected:** The choice is written to `shaders.config` and read back identically.
- **Check:**
  ```bash
  cp ~/.openemux/shaders.config "$SCRATCH/rt080.config"
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from openemux.core.shaders import ShaderConfigStore, resolve_default_shader_id
  p = os.environ["SCRATCH"] + "/rt080.config"
  sid = resolve_default_shader_id("SFC")
  store = ShaderConfigStore(config_file=p)
  store.set_console_shader("SFC", sid)
  assert ShaderConfigStore(config_file=p).get_console_shader("SFC") == sid, "round-trip mismatch"
  print("RT-080 OK")
  EOF
  ```
  (The copy is discarded; the real `~/.openemux/shaders.config` is never written.)

### RT-081 — The shader is applied in game
- **Area:** Shaders
- **Mode:** MANUAL
- **Preconditions:** RT-062 works.
- **Steps:**
  1. Set a visually obvious shader (a CRT one) for a console in "Settings" → "Video".
  2. Launch a game on that console.
- **Expected:** The rendered image shows the shader effect.
- **Check:** human only.
- **Restore:** Set the shader back.

## BIOS

### RT-090 — The BIOS tab reports per-console status
- **Area:** BIOS
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Open "Settings" (`Ctrl+,`) → "BIOS".
- **Expected:** Consoles that need BIOS files are listed with a present/missing status per file;
  no crash, no empty page.
- **Check:** Screenshot of the tab.

## Settings & configuration

### RT-100 — Every Settings tab opens
- **Area:** Settings
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Open "Settings" (`Ctrl+,`).
  2. Visit every tab across the bottom, in order.
- **Expected:** Each tab renders its groups; no crash, no blank page, no raw i18n key on screen.
- **Check:** One screenshot per tab; log gained no `Traceback`.

### RT-101 — Config round-trips without loss
- **Area:** Settings
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: change a setting, restart, confirm it stuck and nothing else changed.
- **Expected:** `ConfigManager` writes and re-reads values faithfully.
- **Check:**
  ```bash
  cp ~/.openemux/config.yaml "$SCRATCH/rt101.yaml"
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from pathlib import Path
  from openemux.core.config import ConfigManager
  p = Path(os.environ["SCRATCH"]) / "rt101.yaml"  # ConfigManager requires a Path, not a str
  cm = ConfigManager(config_file=p)
  original = cm.get_locale()
  target = "pt_BR" if original == "en" else "en"
  cm.set_locale(target)
  assert ConfigManager(config_file=p).get_locale() == target, "locale did not persist"
  cm.set_locale(original)
  assert ConfigManager(config_file=p).get_locale() == original, "restore failed"
  print("RT-101 OK")
  EOF
  ```

### RT-102 — The header toggle switches between light and dark
- **Area:** Settings
- **Mode:** AUTO-UI
- **Preconditions:** App running. Back up the config first (`cp ~/.openemux/config.yaml
  $SCRATCH/config.bak`).
- **Steps:**
  1. Note the current appearance, then click the sun/moon button in the content header bar
     (left of the search button).
  2. Open "Settings" → "System" and read the "Theme" row.
- **Expected:** The whole interface repaints in the other theme and the button's icon flips to
  offer the way back (sun while dark, moon while light). The "Theme" row reads "Light" or "Dark",
  matching what is on screen.
- **Check:** screenshots before and after the click; `grep "theme:" ~/.openemux/config.yaml`
  reports the same value the row shows.
- **Restore:** `cp $SCRATCH/config.bak ~/.openemux/config.yaml` with the app closed.

### RT-103 — The chosen theme survives a restart
- **Area:** Settings
- **Mode:** AUTO-UI
- **Preconditions:** App **closed**. Back up the config first.
- **Steps:**
  1. Set `ui.theme` to `light` in `~/.openemux/config.yaml`.
  2. Launch the app.
- **Expected:** The first frame is already light — no dark window that repaints a moment later.
- **Check:** screenshot of the window right after it appears; the header bar is light.
- **Restore:** `cp $SCRATCH/config.bak ~/.openemux/config.yaml` with the app closed.

## Internationalization

### RT-110 — Switching locale translates the UI
- **Area:** i18n
- **Mode:** AUTO-UI
- **Preconditions:** App **closed**. Back up the config first.
- **Steps:**
  1. `cp ~/.openemux/config.yaml $SCRATCH/config.bak`, set `locale:` to the other language
     (`en` ↔ `pt_BR`), launch the app.
  2. Look at the sidebar header and the main menu.
- **Expected:** The UI appears in the chosen language; no raw keys like `menu.preferences`.
- **Check:** Screenshot of the translated UI.
- **Restore:** Quit, `cp $SCRATCH/config.bak ~/.openemux/config.yaml`, relaunch if the run
  continues with UI scenarios.

### RT-111 — Translation catalogs are complete
- **Area:** i18n
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** —
- **Expected:** Every locale defines every key.
- **Check:** suite files `tests/test_i18n.py`, `tests/test_i18n_completeness.py`.

## Welcome wizard

### RT-120 — The wizard opens and every slide renders
- **Area:** Wizard
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Open "Main Menu" → "Welcome".
  2. Advance with "Next" through every slide to "Get started"; watch the `views` slideshow cycle.
- **Expected:** Every slide shows its illustration and text; the slideshow cycles; "Get started"
  closes the dialog.
- **Check:** One screenshot per slide; no missing-image placeholder.

## Help

### RT-130 — The shortcuts overlay opens
- **Area:** Help
- **Mode:** AUTO-UI
- **Preconditions:** App running.
- **Steps:**
  1. Press `Ctrl+?` (or "Main Menu" → "Keyboard Shortcuts").
- **Expected:** The shortcuts window lists the app's shortcuts, matching the accelerators that
  actually work (spot-check `Ctrl+F`, `F5`, `F2`).
- **Check:** Screenshot of the overlay.
- **Restore:** Press `Escape`.

## Destructive file operations

### RT-140 — Deleting a ROM asks for confirmation
- **Area:** File ops
- **Mode:** MANUAL
- **Preconditions:** A throwaway ROM file the developer does not mind losing.
- **Steps:**
  1. Focus the throwaway ROM, press `Delete`.
  2. Read the confirmation dialog carefully, then confirm.
- **Expected:** A confirmation dialog appears before anything is removed; after confirming, the
  ROM leaves the grid and the file is gone from disk.
- **Check:** human only (deliberately never automated).

---

## Retired

*None yet. Move scenarios here instead of deleting them: keep the ID, add the reason and date.*

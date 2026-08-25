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

### RT-015 — Importing as a link leaves the original where it is
- **Area:** Library
- **Mode:** MANUAL
- **Preconditions:** A ROM outside the library folder, on a path you can check afterwards.
- **Steps:**
  1. Open "Settings" → "Library" and set "How ROMs are imported" to "Link to the original".
  2. Import that ROM, then launch it from the library.
  3. Inspect the library entry: `ls -l ~/games/roms/<CONSOLE>/`.
  4. Delete the game from the library and check the original again.
- **Expected:** The library entry is a symlink pointing at the original, the game launches, the
  original is never copied or moved, and deleting the entry removes only the link (issue #298).
- **Check:** suite file `tests/test_rom_importer.py`; `ls -l` shows the entry as `->` the source.
- **Restore:** Set the mode back to "Copy the file"; the original was never touched.

### RT-013 — Rename carries save states, battery saves and artwork
- **Area:** Library
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: rename a ROM (`F2`) that has save states, a battery save and a cover;
  reopen "Load state" and the cover.
- **Expected:** States, battery saves and artwork follow the new name (issue #134).
- **Check:** suite files `tests/test_save_states.py`, `tests/test_rom_importer.py`.

### RT-014 — Loading a playlist never reads the ROM files
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** The library has been scanned at least once on this machine.
- **Steps:** As a QA person: open a console with large ROMs (a disc system) and watch for a
  freeze while the page builds.
- **Expected:** The page appears without the app reading gigabytes off the disk first. Loading a
  playlist resolves names and nothing else — no ROM file is opened (issue #216).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import builtins, tempfile, pathlib
  from openemux.core.playlist_manager import PlaylistManager

  tmp = pathlib.Path(tempfile.mkdtemp())
  roms = tmp / "roms" / "FC"
  roms.mkdir(parents=True)
  rom = roms / "Game.nes"
  rom.write_bytes(b"x" * 1024)
  plists = tmp / "playlists"
  plists.mkdir()
  (plists / "FC.list").write_text(f"{rom}\n", encoding="utf-8")

  class Cfg:
      def get_playlists_dir(self): return plists
      def get_roms_path(self): return tmp / "roms"

  opened = []
  real_open = builtins.open
  def spy(file, *a, **k):
      if str(file) == str(rom):
          opened.append(str(file))
      return real_open(file, *a, **k)
  builtins.open = spy
  try:
      entries = PlaylistManager(Cfg(), None).load_playlist("FC")
  finally:
      builtins.open = real_open

  assert len(entries) == 1, entries
  assert "rom_id" not in entries[0], entries[0]
  assert not opened, f"the ROM file was read: {opened}"
  print("RT-014 OK — the playlist loaded without opening any ROM")
  EOF
  ```

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

### RT-024 — Coming back to a page keeps it as it was
- **Area:** Navigation
- **Mode:** AUTO-UI
- **Preconditions:** App running, at least two consoles with more games than fit on screen.
- **Steps:**
  1. Open a console and scroll halfway down its grid.
  2. Switch to another console, then switch back.
  3. Type a search query, clear it, and switch away and back once more.
- **Expected:** The page comes back where it was left, scroll position included, without visibly
  rebuilding (issue #230). No card is missing, and nothing is left hidden by a filter that is no
  longer active.
- **Check:** Screenshot the page before leaving and after returning; the two must match. The
  automated form clicks console A, console B, console A again and compares the first and third
  screenshots pixel for pixel.

### RT-025 — The grid answers real pointer and keyboard input
- **Area:** Navigation
- **Mode:** AUTO-PROBE
- **Preconditions:** `Xephyr` installed (`xserver-xephyr`). Nothing in `tests/` can build a
  `RomGrid`: without a display, constructing a GTK widget segfaults the interpreter, so this is
  the only coverage the grid's gesture stack has.
- **Steps:** As a QA person: Ctrl-click and Shift-click cards, drag a rubber band, clear by
  clicking empty space, range with Shift+arrows, filter the page, leave and come back, open two
  context menus in a row.
- **Expected:** Every check passes at each library size — including that the band selects exactly
  the cards it was drawn over, that a filtered-out card loses its selection, that focus returns to
  the card that had it, and that only one context menu is ever open.
- **Check:**
  ```bash
  Xephyr :9 -screen 900x650 >/dev/null 2>&1 &
  XPID=$!
  sleep 4
  fail=0
  for n in 4 12 20; do
    DISPLAY=:9 GDK_BACKEND=x11 HARNESS_CARDS=$n PYTHONPATH=src \
      .venv/bin/python tools/selection_input_harness.py >/dev/null 2>&1 || fail=1
  done
  kill $XPID
  [ $fail -eq 0 ] && echo "RT-025 OK — the grid harness passed at 4, 12 and 20 cards"
  ```

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

### RT-023 — Only one context menu is ever open
- **Area:** Navigation
- **Mode:** AUTO-SUITE
- **Preconditions:** App running with at least two games in the current console.
- **Steps:**
  1. Right-click a game card to open its context menu.
  2. Without dismissing it, move focus to another card with the arrow keys and press the `Menu`
     key (or `Shift+F10`).
  3. Click on empty grid space.
  4. Right-click a card again, and while the menu is open switch console in the sidebar.
- **Expected:** Step 2 replaces the first menu instead of stacking a second one. After step 3 no
  menu is left on screen and no `(...)` button stays stuck visible. Step 4 closes the menu with
  the page switch.
- **Check:** `tests/test_context_menu.py` (the ownership rule and the guarded unparent); the UI
  half is the human's, and the launch log must gain no `Gtk-CRITICAL`.

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

### RT-043 — A favorite on an unreachable drive survives a toggle
- **Area:** Favorites
- **Mode:** AUTO-SUITE
- **Preconditions:** `FAVORITES.list` contains at least one path on a removable or network drive
  that is currently **not** mounted, plus one game that is present.
- **Steps:**
  1. Toggle the favorite state of the present game with `Ctrl+D`.
  2. Read `~/.openemux/playlists/FAVORITES.list`.
- **Expected:** The unreachable path is still in the file. A favorite whose drive is not mounted is
  missing, not gone (issue #217).
- **Check:** suite file `tests/test_playlist_manager.py`
  (`test_a_favorite_on_an_unmounted_drive_survives_a_toggle`).

### RT-044 — Opening "Favorites" without the drive does not delete those favorites
- **Area:** Favorites
- **Mode:** AUTO-SUITE
- **Preconditions:** `FAVORITES.list` contains at least one path on a removable or network drive
  that is currently **not** mounted.
- **Steps:**
  1. Open "Favorites" in the sidebar, go back to "All", and open "Favorites" again — several
     times.
  2. Close the app, mount the drive, and start the app again.
- **Expected:** The favorites on that drive are all back once it is mounted. Visiting the page
  without the drive never removes them: the page's own cleanup only drops a path whose console
  folder is present and whose file is not — a deleted ROM, not an unplugged disk (issue #210).
- **Check:** suite file `tests/test_playlist_manager.py`
  (`UnreachableFavoritesTests`).

### RT-045 — A ROM deleted from a mounted drive stops being a favorite
- **Area:** Favorites
- **Mode:** AUTO-SUITE
- **Preconditions:** A favorite whose ROM sits in a console folder that is present.
- **Steps:**
  1. Delete the ROM file from outside the app.
  2. Open "Favorites".
- **Expected:** The favorite is dropped from `FAVORITES.list` — the folder proves the storage is
  mounted, so the file really is gone. The counterpart to RT-044: the cleanup still cleans up.
- **Check:** suite file `tests/test_playlist_manager.py`
  (`test_a_rom_deleted_from_a_mounted_drive_is_pruned`).

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

### RT-054 — Leaving a page stops its covers from bothering the next one
- **Area:** Covers
- **Mode:** MANUAL
- **Preconditions:** Two consoles with many games whose covers are not yet on disk, so a page
  visit starts real cover work.
- **Steps:**
  1. Open the first console, and before its covers finish appearing switch to the second.
  2. Switch back and forth a few times, then scroll the page you land on.
- **Expected:** The page in front stays responsive throughout; covers keep filling in on whichever
  page is on screen. No freeze, and the log gains no `Gtk-CRITICAL` (issue #291).
- **Check:** human only for the responsiveness; the launch log must contain no `Gtk-CRITICAL` and
  no `Traceback`.

### RT-053 — A cover sync reads each ROM once
- **Area:** Covers
- **Mode:** AUTO-SUITE
- **Preconditions:** A console with large ROMs (a disc system) missing artwork, and ScreenScraper
  credentials configured so both stages run.
- **Steps:**
  1. Start a cover sync for that console and watch disk activity (`iotop`, or the sync's own
     progress against file sizes).
- **Expected:** Each ROM is read once, not once per hashing stage. The name-index stage and the
  ScreenScraper stage share the digests, and the box-art and label passes do not re-read
  (issue #231).
- **Check:** suite file `tests/test_hasher.py` (`test_both_digests_come_from_one_read`).

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
  2. Watch the window while the game boots.
  3. Play for ~30 s; close the game window.
- **Expected:** While the game is starting, the window shows a spinner and "Starting &lt;game&gt;…"
  — never a plain black rectangle with no explanation. The game then appears *inside* an OpenEmux
  window titled with the ROM name, with the header bar carrying pause, reset, save state, load
  state, controller settings, volume and the RetroArch menu. Sound plays, input responds, and
  closing the window ends the game and returns to the library cleanly.
- **Check:** human only (grabbing the keyboard for the emulator makes automation unsafe).

### RT-064 — Turning the game window off gives RetroArch its own window
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session.
- **Steps:**
  1. "Settings" → "Video" → turn "Play in an OpenEmux window" off.
  2. Launch a game.
- **Expected:** No OpenEmux wrapper appears; RetroArch opens its own decorated window — **with its
  title bar and borders**, pausing when it loses focus — and behaves exactly as it did before the
  feature existed, its fullscreen hotkey included. This holds even on a machine where an earlier
  version already ran with the game window on.
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
- **Expected:** Each hotkey does what the hint bar promises. Note that while the game is embedded
  the *keyboard* fullscreen binding is the one that works: the wrapper grabs it and fullscreens
  itself, because RetroArch toggling fullscreen on a re-parented window would recreate that window
  and break the embed. RetroArch's own fullscreen bindings, keyboard and pad alike, are unbound
  for the duration (see RT-155).
- **Check:** human only.

### RT-066 — Closing the game window ends the emulator process
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A working core and ROM; "Play in an OpenEmux window" on. Run this on the
  install being released (Flatpak included) — what a stop signal reaches depends on how RetroArch
  was launched.
- **Steps:**
  1. Launch a game and let it run until sound is playing.
  2. Click the window's "×".
  3. Wait 5 s, then run `pgrep -af retroarch` in a terminal.
- **Expected:** The window closes, the sound stops with it, and no RetroArch process is left
  behind — `pgrep` prints nothing. The library window is still there, with the "finished" toast.
- **Check:** human only; `pgrep -af retroarch` must print nothing.

### RT-067 — Closing the library takes a running game with it
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** As RT-066.
- **Steps:**
  1. Launch a game and let it run.
  2. Click the "×" on the *library* window (not the game's).
  3. Wait 5 s, then run `pgrep -af retroarch`.
- **Expected:** Both windows close, the app exits, the sound stops, and no RetroArch process
  survives.
- **Check:** human only; `pgrep -af retroarch` must print nothing.

### RT-068 — A stop escalates until the game is really gone
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: confirm that stopping a game asks RetroArch to quit first, and that a
  game which ignores that — or the signal after it — is still ended.
- **Expected:** The stop walks QUIT → SIGTERM → SIGKILL, stopping at the first step that works;
  every launch is configured so a single QUIT command quits (`quit_press_twice = "false"`) and,
  under Flatpak, so the sandbox dies with the process the app holds (`--die-with-parent`).
- **Check:** suite files `tests/test_runtime_manager.py`, `tests/test_retroarch_launcher.py`.

### RT-069 — A launch never writes into the user's RetroArch config
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A working core and ROM. Know which config the RetroArch you launch uses:
  `~/.config/retroarch/retroarch.cfg` for a native/vendored one,
  `~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg` for the Flatpak.
- **Steps:**
  1. Note the file's timestamp: `stat -c %y <config>`.
  2. Launch a game, play briefly, close it.
  3. Check the timestamp again.
- **Expected:** Unchanged. Everything OpenEmux imposes for a launch — the window overrides, the
  command channel, its save-state directory, the audio driver — lasts only for that game;
  RetroArch does not save it back into the user's own configuration.
- **Check:** human only; the timestamp must be identical, and
  `grep -c "openemux" <config>` must not grow.

### RT-157 — In-game controls reach our game and no other RetroArch
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A standalone RetroArch (any install) running with its network command
  interface enabled on its default port 55355, playing something audible.
- **Steps:**
  1. With that instance running, launch a game from OpenEmux.
  2. Open the volume popover and drag the slider; press pause and the save-state button.
  3. Watch the *other* RetroArch.
- **Expected:** Only the OpenEmux game reacts. The other instance's volume, pause state and save
  states are untouched (issue #227).
- **Check:** `grep network_cmd_port ~/.openemux/runtime/runtime_*.cfg` shows a port that is
  neither 55355 nor the same across two launches;
  `ss -ulnp | grep <that port>` lists exactly one process. Suite files
  `tests/test_retroarch_command.py`, `tests/test_runtime_manager.py`,
  `tests/test_config_command_port.py`.

### RT-158 — The volume control says where the game actually is
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session, with audible sound.
- **Steps:**
  1. Open the volume popover and drag the slider from the top to the bottom in one move.
  2. Watch the line under the slider while the audio ramps.
  3. Wait for it to disappear, then open RetroArch's own menu → "Audio" → "Volume".
  4. Close the popover and reopen it.
- **Expected:** While the audio is still ramping, the popover reports the level the game is
  actually at; the line disappears when the two agree. RetroArch's own reading then matches the
  slider within one 0.5 dB step, and reopening the popover does not make the slider jump
  (issue #284).
- **Check:** human only for the reading; suite files `tests/test_retroarch_command.py`
  (a lost step is retried, and a walk that ends short leaves the tracker on what landed) and
  `tests/test_runtime_manager.py` (mute does not flip on a datagram that never left).

### RT-159 — Achievements unlock while you play
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A RetroAchievements account, and a game that has achievements.
- **Steps:**
  1. Open "Settings" → "System" → "RetroAchievements", sign in, and confirm the group now says
     "Signed in as …".
  2. Launch the game and play until an achievement would unlock.
  3. Read the newest `runtime_*.cfg` in `~/.openemux/runtime/` and `~/.openemux/cheevos.config`.
- **Expected:** RetroArch shows the login and the unlock on screen. The override carries
  `cheevos_enable`, `cheevos_username` and `cheevos_token`, and `cheevos_password = ""`. The stored
  file holds the username and a token and **no password**, and is `-rw-------` (issue #300).
- **Check:** human only for the unlock; suite file `tests/test_retroachievements.py` covers the
  login exchange and what reaches the override. `stat -c %a ~/.openemux/cheevos.config` is `600`.
- **Restore:** "Sign out" in the same group.

### RT-150 — A game runs at the right speed, with sound
<!-- Numbered outside the Launch block: 060-069 is full and ids are never reused. -->

- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A working core and ROM. Run it on the install being released — what audio
  server the emulator can reach depends on how it was launched, and the Flatpak is the case that
  broke.
- **Steps:**
  1. Launch a game with a known tempo (a title screen tune).
  2. Watch and listen for ~20 s.
- **Expected:** Sound plays and the game runs at its normal speed. Emulation is paced off the
  audio clock, so a game with no audio device runs at the monitor's refresh rate instead — on a
  high-refresh display that is several times too fast, which is what the missing audio actually
  looks like.
- **Check:** human only; the launch log in `~/.openemux/runtime/retroarch_*.log` must contain
  `[Audio] Started synchronous audio driver` and no `failed_to_start_audio_driver`.

### RT-152 — A session that cannot embed never strips RetroArch's window
<!-- Numbered outside the Launch block: 060-069 is full and ids are never reused. -->
- **Area:** Launch
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:** As a QA person: on a session that cannot host the game window — GTK on Wayland, or
  after an embed has already failed once — confirm the launcher writes RetroArch's own window
  settings back instead of the embed ones.
- **Expected:** The borderless overrides are only ever written when a wrapper will actually exist.
  Anything else leaves the game undecorated, unmovable and without its fullscreen hotkey, with no
  window to hold it (issue #267).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from unittest import mock
  from openemux.core import game_window_support as g

  g.reset_embed_state()
  # GTK reported a non-X11 display: capability is unchanged, this launch is not.
  with mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True):
      with mock.patch.object(g, "XLIB_AVAILABLE", True):
          g.set_display_embeddable(False)
          assert g.embedding_possible(), "the Preferences switch must stay usable"
          assert not g.embedding_ready(), "launched an embed on a non-X11 display"
  g.reset_embed_state()
  # A failed embed latches the rest of the session standalone.
  with mock.patch.object(g, "embedding_possible", lambda: True):
      g.mark_embed_unavailable("RetroArch is not an X11 client")
      assert not g.embedding_ready(), "tried to embed again after a failure"
  g.reset_embed_state()
  # GTK takes the first backend that opens, so wayland,x11 means wayland.
  with mock.patch.dict(os.environ, {"DISPLAY": ":0", "GDK_BACKEND": "wayland,x11"}, clear=True):
      with mock.patch.object(g, "XLIB_AVAILABLE", True):
          assert not g.embedding_possible(), "accepted a backend list that lands on Wayland"
  print("RT-152 OK")
  EOF
  ```

### RT-153 — A failed embed hands the game back a normal window
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** "Play in an OpenEmux window" on, a working core and ROM. The embed has to
  fail, which on a healthy X11 machine means forcing it: run the app with
  `RetroArchWindowEmbedder.find_game_window` patched to return `None`.
- **Steps:**
  1. Launch a game and watch the OpenEmux game window.
  2. Wait for it to give up.
- **Expected:** While it waits, the window shows a spinner and "Starting &lt;game&gt;…" rather than
  a black rectangle. When it gives up it says so — *"The game window could not take over
  RetroArch. Reopening the game in its own window."* — and the game comes back in **RetroArch's
  own decorated window: a title bar, movable, resizable, its fullscreen hotkey working and the
  game pausing when it loses focus.** The user is never left with an undecorated square that
  cannot be moved (issue #267). Launching a second game afterwards opens no wrapper at all and is
  decorated from the start.
- **Check:** human only. The newest `~/.openemux/runtime/runtime_*.cfg` written after the failure
  must contain `video_window_show_decorations = "true"` and `pause_nonactive = "true"`, and must
  **not** contain `video_context_driver = ""`.

### RT-154 — Moving the game window mid-play keeps the game inside it
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session, with the game visibly inside the wrapper.
- **Steps:**
  1. Drag the game window around the screen by its header bar, several times, while the game runs.
  2. If a second monitor is available, drag it onto that one too.
  3. Keep playing for ~30 s afterwards.
- **Expected:** The game stays inside the window and keeps running throughout. The wrapper never
  disappears and no borderless RetroArch window is left behind — that is exactly the failure
  issue #267 was reported as.
- **Check:** human only; `~/.openemux/runtime/openemux_startup.log` must contain no
  `embedding unavailable` line for that session.

### RT-155 — The pad's fullscreen button cannot break the embed
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session, with a gamepad connected and a fullscreen
  binding mapped to a pad button.
- **Steps:**
  1. With the game embedded, press the pad button bound to the fullscreen toggle several times.
- **Expected:** Nothing happens to the embed: RetroArch does not recreate its window and the game
  stays inside the OpenEmux window. The keyboard fullscreen binding is the fullscreen path while
  embedded, and it still works.
- **Check:** human only; the launch's `runtime_*.cfg` must contain
  `input_toggle_fullscreen_btn = "nul"`.

### RT-156 — The mouse cursor stays visible over the embedded game
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** RT-062 done in the same session, on a desktop whose screen lock can be
  triggered (`loginctl lock-session`, or the shortcut the desktop provides).
- **Steps:**
  1. With the game embedded, move the pointer over the game area and note the cursor.
  2. Lock the session, wait a few seconds, unlock it.
  3. Move the pointer over the game area again.
  4. Alt+Tab to another window and back, then move the pointer over the game area once more.
- **Expected:** The cursor is visible over the game in step 1 and stays visible in steps 3 and 4.
  It never has to be recovered by opening the RetroArch menu.
- **Check:** human only; `tests/test_x11_embed.py` covers the two moments the wrapper redefines
  the pointer (every adoption, and the focus-reclaim edge that an unlock produces).

### RT-151 — The menu icon opens the install that owns it
- **Area:** Packaging
- **Mode:** MANUAL
- **Preconditions:** The `.deb` (or `.rpm`) installed on a machine that also has other OpenEmux
  copies around — an AppImage integrated by an AppImage manager (GearLever/AppManager symlink in
  `~/.local/bin`), the Flatpak, an old version anywhere.
- **Steps:**
  1. Launch OpenEmux from the desktop menu icon.
  2. Open "About" and read the version; check the startup log's `startup context` line.
- **Expected:** The session belongs to the packaged install (`project_root_env=/opt/openemux`,
  `appimage=None`) and About shows the packaged version — not whatever a `~/.local/bin/openemux`
  symlink points at. The packaged desktop entry must not resolve `Exec` through `PATH`.
- **Check:** `grep '^Exec=' /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop`
  prints exactly `Exec=/usr/bin/openemux`; the build scripts assert the same at package time.

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

### RT-074 — Remapping onto a taken button releases the old command
- **Area:** Input
- **Mode:** MANUAL
- **Preconditions:** App running with a gamepad connected; a GBA game in the library.
- **Steps:**
  1. Open "Settings" (`Ctrl+,`) → "Input", pick "GBA" and the gamepad device.
  2. Remap "B" to the pad's X button — the one "Save state" already holds.
  3. Read the toast, and read the "Save state" row.
  4. Press "Save", then close and reopen "Settings".
- **Expected:** The toast names what was released ("Button 2 released from Save state"), the
  "Save state" row reads unbound, and **it is still unbound after reopening** — the value does not
  come back on its own (issue #281).
- **Check:** suite files `tests/test_input_actions.py`, `tests/test_preferences.py`; the human
  confirms the toast and the round trip.
- **Restore:** Remap "B" back to its own button and "Save state" back to the pad's X button.

### RT-075 — No button fires two commands at once
- **Area:** Input
- **Mode:** AUTO-SUITE
- **Preconditions:** RT-074 done, so "B" sits on the button "Save state" used to hold.
- **Steps:**
  1. Launch the GBA game and press that button during play.
  2. Inspect the launch override in `~/.openemux/runtime/`.
- **Expected:** The button plays B and does nothing else. The override binds exactly one action to
  that token, and every libretro button the console does not use — `x`, `y` on a GBA — is written
  as `"nul"` rather than left out, so RetroArch's own pad autoconfig cannot fill it back in.
- **Check:** suite file `tests/test_input_actions.py`
  (`test_only_one_action_ends_up_on_the_remapped_button`,
  `test_a_button_the_console_does_not_use_is_bound_to_nothing`); with a real launch,
  `grep -c '\"2\"' ~/.openemux/runtime/runtime_*.cfg` counts one binding.

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

### RT-082 — A core setting reaches the core
- **Area:** Shaders
- **Mode:** MANUAL
- **Preconditions:** PPSSPP installed and resolving for "PSP" (or Beetle PSX HW chosen for "PS"),
  with a game for that console.
- **Steps:**
  1. Open "Settings" → "Cores" → "Advanced" and pick a higher "Internal resolution" for that
     console.
  2. Launch the game.
  3. Read the newest `coreopts_*.cfg` in `~/.openemux/runtime/`.
- **Expected:** The game renders at the higher resolution. The file names the option with the value
  picked, and the runtime override next to it carries `core_options_path` pointing at that file.
  Anything the user had configured for that core inside RetroArch is still in the file (issue #296).
- **Check:** suite files `tests/test_core_options.py`, `tests/test_retroarch_launcher.py`; the
  human confirms the picture.
- **Restore:** Put the option back to its first value, which removes it from the store.

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

### RT-141 — Saves survive a clean reinstall
- **Area:** Destructive file operations
- **Mode:** MANUAL
- **Preconditions:** A library with at least one save state and one battery save (`.srm` next to
  the ROM). A throwaway copy of `~/.openemux/states/` and of the ROM folder, taken first.
- **Steps:**
  1. Open "Settings" → "System" → "Export saves" and write the file.
  2. Delete the save state and the `.srm` for one game.
  3. "Import saves", pick the file just written, and reopen "Load state" for that game.
  4. Play the game briefly so its save is newer than the backup, then import the same file again.
- **Expected:** Step 3 brings the state and the battery save back and the game resumes where it
  was. Step 4 leaves the newer local save alone and reports it as kept, not restored — the default
  policy keeps whichever side is newer (issue #293).
- **Check:** suite file `tests/test_save_backup.py`; the human confirms the game resumes and the
  toast counts match.
- **Restore:** The throwaway copies taken in Preconditions.

## Data safety

### RT-160 — An interrupted save never damages the file it was replacing
- **Area:** Data safety
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: pull the power out halfway through a settings save, then start the
  app again and check the settings are the ones from before the save, not defaults.
- **Expected:** Every file the app persists is written whole or not at all (issue #208). A save
  that dies mid-write leaves the previous file byte-for-byte intact and no `.tmp` litter behind.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from pathlib import Path
  from unittest.mock import patch
  from openemux.core.config import ConfigManager

  scratch = Path(os.environ["SCRATCH"]) / "rt150"
  scratch.mkdir(parents=True, exist_ok=True)
  config_file = scratch / "config.yaml"
  cm = ConfigManager(config_file=config_file)
  cm.set_roms_path("/games/roms")
  before = config_file.read_text(encoding="utf-8")

  with patch("openemux.core.atomic_write.os.replace", side_effect=OSError("power loss")):
      cm.set_roms_path("/games/elsewhere")

  assert config_file.read_text(encoding="utf-8") == before, "config was damaged mid-write"
  leftovers = [p.name for p in scratch.iterdir() if p.name.endswith(".tmp")]
  assert leftovers == [], f"temporary files left behind: {leftovers}"
  assert ConfigManager(config_file=config_file).get_roms_path().name == "roms"
  print("RT-160 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-161 — A rescan never shows a half-written playlist
- **Area:** Data safety
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: start a rescan of a large console and browse that console while it
  runs.
- **Expected:** The playlist file swaps from the old list to the new one in one step. A reader
  that opens it at the worst possible moment sees one complete list, never a truncated one.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from pathlib import Path
  from unittest.mock import patch
  from openemux.core.playlist_manager import PlaylistManager

  scratch = Path(os.environ["SCRATCH"]) / "rt151"
  scratch.mkdir(parents=True, exist_ok=True)

  class Config:
      def get_playlists_dir(self):
          return scratch

  class Scanner:
      def __init__(self):
          self.roms = [{"name": "A", "path": "/roms/a.sfc"}, {"name": "B", "path": "/roms/b.sfc"}]

      def scan_console(self, console):
          return self.roms

  scanner = Scanner()
  manager = PlaylistManager(Config(), scanner)
  manager.scan_and_rebuild_playlist("SFC")
  playlist = scratch / "SFC.list"
  first = playlist.read_text(encoding="utf-8")

  scanner.roms = [{"name": "C", "path": "/roms/c.sfc"}]
  seen = []
  real_replace = os.replace

  def peek(src, dst):
      seen.append(Path(dst).read_text(encoding="utf-8"))
      return real_replace(src, dst)

  with patch("openemux.core.atomic_write.os.replace", peek):
      manager.scan_and_rebuild_playlist("SFC")

  assert seen == [first], f"a reader saw a partial playlist: {seen}"
  assert playlist.read_text(encoding="utf-8") == "/roms/c.sfc\n"
  print("RT-161 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-162 — Two favorite toggles at once do not lose one of them
- **Area:** Data safety
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: star several games in quick succession while a rescan is running,
  then reopen "Favorites".
- **Expected:** Every star is in the list. The favorites file is a read-modify-write, and two of
  them running at once used to drop one edit (issue #208).
- **Check:** suite files `tests/test_atomic_write.py`, `tests/test_playlist_manager.py`.


### RT-163 — An unreadable settings file is kept, not overwritten
- **Area:** Data safety
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: hand-edit `config.yaml` into invalid YAML, start the app, then look
  in `~/.openemux/` for the file you broke.
- **Expected:** The app comes up on defaults, and the broken file is still there as
  `config.yaml.broken-<timestamp>` — it is not replaced by the defaults it fell back to (issue
  #209). Same for a file that parses but is not a mapping.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from pathlib import Path
  from openemux.core.config import ConfigManager

  scratch = Path(os.environ["SCRATCH"]) / "rt153"
  scratch.mkdir(parents=True, exist_ok=True)
  for name, body in (("broken.yaml", "roms_path: [unclosed\n"), ("scalar.yaml", "just a string\n")):
      target = scratch / name
      target.write_text(body, encoding="utf-8")
      ConfigManager(config_file=target)
      kept = sorted(scratch.glob(f"{name}.broken-*"))
      assert len(kept) == 1, f"{name} was not kept: {kept}"
      assert kept[0].read_text(encoding="utf-8") == body, f"{name} was not kept intact"
  print("RT-163 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-164 — A broken collections index does not orphan the collections
- **Area:** Data safety
- **Mode:** AUTO-PROBE
- **Preconditions:** none (works on a copy).
- **Steps:** As a QA person: break `playlists/collections/collections.yaml`, open the app, and
  create a new collection.
- **Expected:** The existing collections are still in the sidebar, with their games — the index is
  rebuilt from the `<slug>.list` files that are still on disk, and only the display name is lost
  (it falls back to the slug read as words). Creating a new one does not wipe the others.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os
  from pathlib import Path
  from openemux.core.collections import CollectionManager

  scratch = Path(os.environ["SCRATCH"]) / "rt154"
  scratch.mkdir(parents=True, exist_ok=True)
  manager = CollectionManager(scratch)
  manager.create("Best of SNES")
  manager.add("best-of-snes", ["/roms/a.sfc"])
  manager.index_path.write_text("collections: [oops\n", encoding="utf-8")

  manager.create("Shooters")
  slugs = sorted(entry["slug"] for entry in manager.list_collections())
  assert slugs == ["best-of-snes", "shooters"], slugs
  assert manager.paths("best-of-snes") == ["/roms/a.sfc"]
  assert sorted(scratch.glob("collections.yaml.broken-*")), "the broken index was not kept"
  print("RT-164 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-165 — The user is told when a settings file was set aside
- **Area:** Data safety
- **Mode:** AUTO-UI
- **Preconditions:** App **closed**. Back up the file first (`cp ~/.openemux/play_history.json
  $SCRATCH/play_history.bak`).
- **Steps:**
  1. Truncate `~/.openemux/play_history.json` mid-object (e.g. `printf '{"a.sfc": {"last_played":
     1,' > ~/.openemux/play_history.json`).
  2. Launch the app and watch the bottom of the window for the first few seconds.
- **Expected:** A toast reads *A settings file could not be read; it was kept as
  "play_history.json.broken-<timestamp>" and defaults are in use*. The named file exists in
  `~/.openemux/` and holds what was truncated.
- **Check:** screenshot of the toast; `ls ~/.openemux/play_history.json.broken-*` lists exactly
  one file.
- **Restore:** `cp $SCRATCH/play_history.bak ~/.openemux/play_history.json && rm -f
  ~/.openemux/play_history.json.broken-*` with the app closed.


## Retired

*None yet. Move scenarios here instead of deleting them: keep the ID, add the reason and date.*

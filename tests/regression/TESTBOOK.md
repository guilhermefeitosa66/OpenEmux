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
  Without a desktop, `make smoke` (or `xvfb-run -a .venv/bin/python scripts/smoke_start.py`) makes
  the same check headlessly against a throwaway `HOME`; exit 0 = PASS, 1 = FAIL, 2 = BLOCKED. This
  is what CI runs (issue #242).

### RT-229 — CI runs the suite on every supported Python, starts the app, and holds coverage
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: open `.github/workflows/tests.yml` and `pyproject.toml`.
- **Expected:** The suite runs on 3.10, 3.11, 3.12 and 3.13 — the floor `pyproject.toml` and the
  `.rpm` both promise, which CI never exercised; one version failing does not cancel the others.
  A separate job starts the real app under `xvfb-run` and waits for its window, so a crash in
  application or window construction fails CI instead of surfacing by hand on release day.
  `coverage report` enforces `fail_under`, and the badge ladder has a red band, so coverage can no
  longer decay in silence (issue #242).
- **Check:** suite file `tests/test_ci_workflows.py` (`TestsWorkflowTests`, `SmokeScriptTests`).

### RT-231 — Unsafe or simply broken code cannot reach develop unremarked
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: open `.github/workflows/security.yml`, `.github/dependabot.yml`,
  `pyproject.toml` and the `Makefile`.
- **Expected:** The security scan runs for `develop` as well as `main`, on push and on pull
  request — it used to trigger on `main` only, so every day-to-day change was unaudited for up to
  a week. `pip-audit` reads both `requirements.lock` (what ships) and `requirements-dev.lock`
  (what CI and developers install), and `make setup`/`make setup-dev` install those same two
  files, so the audited set and the installed set are one list. Every action is pinned to a full
  commit SHA, and Dependabot watches `github-actions` and `pip`. `make lint` runs ruff with
  correctness rules only and CI gates on it. `$(PIP)` is `$(PYTHON) -m pip`, never the venv's
  console script, whose baked-in shebang broke every recipe after the checkout was renamed
  (issue #243).
- **Check:** suite file `tests/test_ci_workflows.py` (`SecurityWorkflowTests`, `SupplyChainTests`,
  `LintGateTests`); `make lint` exits 0.

### RT-232 — Running the tests leaves the developer's home directory alone
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: note the size of `~/.openemux/runtime/openemux_startup.log`, run the
  unit suite, and look at it again.
- **Expected:** Not one line added, and the run prints no `INFO [openemux...]` lines of its own.
  `openemux/main.py` used to do its whole pre-GTK preparation at import, and two test files import
  from it — so running the tests migrated a legacy `~/.opemux` (real user data), read the real
  config, redirected the root logger into the real start-up log, and replaced `sys.excepthook` and
  `threading.excepthook` for the test process. About 1,100 log lines per run went to the test
  output and to that file, among them `screenscraper lookup: … url=…`, which reads as live HTTP
  traffic (it is not — the suite is offline-safe). The preparation now lives in
  `prepare_process()`, and the GTK import and the application class in `openemux/app.py`, reached
  only through `build_application()` — importing `main` costs nothing (issue #244).
- **Check:** suite file `tests/test_import_side_effects.py`; and
  `wc -l ~/.openemux/runtime/openemux_startup.log` is unchanged across
  `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.

### RT-233 — The suite reports no leaked file descriptors and no stray output
- **Area:** Startup
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:** As a QA person: run the suite with resource warnings turned on and read what comes
  after the summary.
- **Expected:** No `ResourceWarning: unclosed`, and nothing printed after `OK`. The command
  client's UDP socket outlived the game it was for — `stop_active()` sends QUIT, which opens it,
  and nothing closed it — and `tools/generate_name_db.py` printed its progress, so
  `games.db.zip written: /tmp/…` surfaced after the summary and read like a file leaked into the
  tree (it was inside a `TemporaryDirectory`; only the print leaked). Issue #244.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python -W always::ResourceWarning \
    -m unittest discover -s tests 2>&1 | grep -c "ResourceWarning: unclosed" \
    | grep -qx 0 && echo "RT-233 OK"
  ```

### RT-234 — The console table and the BIOS catalog are checked, not just trusted
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: add a console to `core/systems.py` (or a BIOS entry to
  `core/bios_catalog.py`) with a field missing, a duplicate id, an alias another console already
  claims, an extension without its dot, or a core name that console never resolves.
- **Expected:** The suite fails, naming the entry. Neither module had a test file at all, while
  `resolve_system_id()` is called by the scanner, the playlists, the launcher, the cover sync and
  the UI — so a malformed entry showed up as a console that quietly had no games, or a BIOS the
  launch demanded and no core ever needed (issue #245). The familiar names still resolve:
  `NES`→`FC`, `SNES`→`SFC`, `GBA`→`GBA`.
- **Check:** suite files `tests/test_systems.py`, `tests/test_bios_catalog.py`.

### RT-235 — A right-click offers exactly the submenus that apply
- **Area:** Library & scanning
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: right-click a game with no core installed for its console, outside
  cartridge view and outside a collection; then again with a core installed, in cartridge view, and
  from inside a collection.
- **Expected:** "Core" is absent when nothing is installed, "Cartridge color" only in cartridge view
  and only where the console has more than one shell, "Remove from collection" only while viewing
  one — and in every submenu the check mark sits on the option actually in force. `ui/rom_context.py`
  had no test file and sat at 10%, and its load-state submenu indexed `rom["console"]` directly
  where every sibling guarded it, so a ROM entry missing that key raised `KeyError` out of the
  right-click (issue #245).
- **Check:** suite file `tests/test_rom_context.py`.

### RT-236 — The bundled symbolic icons are registered, and the theme choice reaches libadwaita
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person on an icon theme that does not inherit Adwaita (Mint-Y, Papirus,
  Breeze): launch the app and look at the buttons and menu icons. Then switch "Theme" between
  "System", "Light" and "Dark" in "Settings".
- **Expected:** No blank icons — the vendored SVGs fill whatever the host theme lacks, registered
  once, and a call made before GTK has a display does not consume that one shot. Light and Dark are
  **forced**, so they hold on a desktop set the other way; System hands the choice back. Neither
  `ui/icons.py` (0% covered) nor `ui/theming.py` had a test file (issue #245).
- **Check:** suite files `tests/test_icons.py`, `tests/test_theming.py`.

### RT-237 — A launch that cannot be adopted picks the right window, or hands the game back once
- **Area:** Launch & runtime
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: launch a game while your own RetroArch is already open, and launch one
  through a wrapper that forks (an AppImage, `flatpak-spawn`).
- **Expected:** The wrapper adopts the window belonging to this launch — a `_NET_WM_PID` match wins,
  a WM_CLASS match covers the forked case, and a RetroArch that was already on screen is never
  taken. When no window can be adopted at all, the owner is told **exactly once** and the game is
  handed back; a wrapper the user is closing reports nothing, or the owner would relaunch a game
  they just quit (issues #245, #267).
- **Check:** suite files `tests/test_x11_embed.py` (`FindGameWindowTests`), `tests/test_game_window.py`
  (`StandaloneFallbackTests`).

### RT-002 — The unit suite passes
- **Area:** Startup
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:**
  1. Run the full unit suite.
- **Expected:** Every test passes.
- **Check:** `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` exits 0 and prints
  `OK`. This one command also settles every `AUTO-SUITE` scenario below.

### RT-003 — First boot without internet uses the bundled cores
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: install the `.deb`/`.rpm`/AppImage on a machine with no network and
  launch it for the first time.
- **Expected:** First boot completes on the cores the package already ships. It used to end at
  "bootstrap failed": the manifest fetch raised straight out of the download step, so the
  bundled-assets fallback was never consulted (issue #211). With no bundled cores either, it still
  fails — but the message names the real reason (`URLError: Network is unreachable`, not
  "something failed") and the step is **not** recorded as completed, so a retry retries it.
- **Check:** suite files `tests/test_first_boot.py`
  (`test_offline_falls_back_to_the_bundled_cores`,
  `test_offline_without_bundled_cores_fails_with_the_real_reason`),
  `tests/test_retroarch_buildbot_updater.py`
  (`test_an_offline_manifest_is_a_counted_failure_not_a_crash`).
  Run as a probe it would seed the real `~/.openemux` and ROM tree, which is why it stays in the
  suite: `FirstBootBootstrapper` drives the live config.

### RT-004 — An empty core listing is never recorded as a successful step
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: point `cores_base_url` at a page with no core links (or blank it) and
  run first boot.
- **Expected:** The step fails instead of completing. `total == 0` used to read as "nothing to
  download", the step went into `completed_steps`, and a completed step is never re-run — leaving
  the user with no cores and no way for the bootstrap to fix it (issue #211).
- **Check:** suite files `tests/test_retroarch_buildbot_updater.py`
  (`test_an_empty_core_listing_is_a_failure`, `test_no_configured_url_is_a_failure_too`,
  `test_a_disabled_updater_is_still_not_a_failure`), `tests/test_first_boot.py`
  (`test_an_empty_listing_does_not_complete_the_step`).

### RT-005 — A crashed bootstrap worker still ends the first-boot screen
- **Area:** Startup
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: fill the disk (or make `~/.openemux` unwritable) and launch a fresh
  install, so the bootstrap dies outside its own step loop.
- **Expected:** The first-boot window closes, the main window opens, and a toast names the real
  error ("Initial setup could not run: No space left on device"). The worker used to die
  silently, `_finish_bootstrap_flow` was never queued, and the window sat there forever — and
  relaunching just re-presented the same frozen window (issue #215).
- **Check:** suite file `tests/test_first_boot_window.py` (`GuardedBootstrapWorkerTests`).

### RT-006 — Closing the first-boot window mid-setup asks first
- **Area:** Startup
- **Mode:** AUTO-UI
- **Preconditions:** A **throwaway** `HOME` with `setup.bootstrap.status: pending` (never the real
  one — first boot seeds the config, the ROM tree and the playlists).
- **Steps:**
  1. Launch the app against that `HOME` and wait for "Preparing first-time setup".
  2. Click the window's close button.
  3. Choose "Keep setting up", then close again and choose "Quit".
- **Expected:** Step 2 puts up "Setup is still running" with "Keep setting up" (default) and
  "Quit" (destructive). "Keep setting up" leaves setup running; "Quit" ends the app, and the next
  launch picks up from the steps already recorded. When setup finishes on its own the window
  closes with **no** dialog (issue #215).
- **Check:** screenshots of the dialog and of the app still running after "Keep setting up"; the
  rules themselves in `tests/test_first_boot_window.py` (`CloseConfirmationTests`,
  `ConfirmedQuitTests`, `TerminalEventTests`).
- **Restore:** delete the throwaway `HOME`.

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

### RT-178 — ROMs behind a symlinked directory are found
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: keep the big files on another disk and link them into the library —
  `~/games/roms/PS/discs -> /mnt/storage/ps1` — then rescan.
- **Expected:** Every ROM behind the link is in the library. It used to scan as empty, with no
  error and nothing in the log. A link pointing back at one of its own ancestors must not hang the
  scan either.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import tempfile
  from pathlib import Path
  from openemux.core.scanner import RomScanner

  with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      base = root / "roms"
      elsewhere = root / "storage" / "ps1"
      elsewhere.mkdir(parents=True)
      (elsewhere / "Final Fantasy VII.cue").write_bytes(b"cue")
      (base / "PS").mkdir(parents=True)
      (base / "PS" / "discs").symlink_to(elsewhere, target_is_directory=True)
      # A loop back to the console directory: must terminate, not descend forever.
      (elsewhere / "loop").symlink_to(base / "PS", target_is_directory=True)

      names = [rom["name"] for rom in RomScanner(base).scan_console("PS")]
      assert names == ["Final Fantasy VII"], names
  print("RT-178 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside its own temp directory.

### RT-179 — A favourite under a symlinked console directory is displayed
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: make `~/games/roms/SFC` a symlink to another disk, favourite a game
  under it, and open "Favorites".
- **Expected:** The game is there. It used to be stored in the favourites file and never shown:
  the console lookup resolved the path first, which rewrote it to its physical location outside
  the library root, so the entry was skipped — while the pruning pass kept the line, because the
  file does exist.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import tempfile
  from pathlib import Path
  from openemux.core.playlist_manager import PlaylistManager
  from openemux.core.scanner import RomScanner

  class Config:
      def __init__(self, playlists, roms):
          self._playlists, self._roms = playlists, roms
      def get_playlists_dir(self): return self._playlists
      def get_roms_path(self): return self._roms

  with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      base = root / "roms"
      base.mkdir()
      elsewhere = root / "storage" / "snes"
      elsewhere.mkdir(parents=True)
      (elsewhere / "Super Metroid.sfc").write_bytes(b"rom")
      (base / "SFC").symlink_to(elsewhere, target_is_directory=True)
      playlists = root / "playlists"
      playlists.mkdir()

      manager = PlaylistManager(Config(playlists, base), RomScanner(base))
      rom = base / "SFC" / "Super Metroid.sfc"
      assert manager._console_from_rom_path(rom) == "SFC"
      entries = manager.entries_for_paths([str(rom)])
      assert [e["name"] for e in entries] == ["Super Metroid"], entries
      assert entries[0]["console"] == "SFC", entries
  print("RT-179 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside its own temp directory.

### RT-180 — Importing a folder follows its symlinked subdirectories
- **Area:** Library
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: use "Import ROMs" on a folder that contains a symlink to a directory
  of games on another disk.
- **Expected:** The games behind the link are imported along with the rest. They used to be
  skipped silently.
- **Check:** suite files `tests/test_rom_importer.py`
  (`test_a_symlinked_subdirectory_is_walked_too`), `tests/test_dir_walk.py`.

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

### RT-016 — Importing a multi-disc archive keeps every disc
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: import a PlayStation `.zip` holding `Disc 1/` and `Disc 2/`, each
  with its own `track01.bin` and `.cue`, then open the console page.
- **Expected:** Both discs are in the library, each `.cue` beside its own tracks. The entries used
  to flatten onto one filename: disc 1 was written, disc 2 was reported as imported anyway, and
  the library offered a disc 2 holding disc 1's data (issue #229).
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, shutil, zipfile
  from pathlib import Path
  from openemux.core.rom_importer import import_roms
  from openemux.core.scanner import RomScanner

  base = Path(os.environ["SCRATCH"]) / "rt016"
  shutil.rmtree(base, ignore_errors=True)
  (base / "roms").mkdir(parents=True)
  src = base / "FF7.zip"
  cue = 'FILE "track01.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
  with zipfile.ZipFile(src, "w") as z:
      z.writestr("Disc 1/track01.bin", b"disc-one")
      z.writestr("Disc 1/FF7.cue", cue)
      z.writestr("Disc 2/track01.bin", b"disc-two")
      z.writestr("Disc 2/FF7.cue", cue)

  result = import_roms([src], base / "roms", forced_console="PS")
  assert len(result["imported"]) == 4, result["imported"]
  assert (base / "roms/PS/Disc 1/track01.bin").read_bytes() == b"disc-one"
  assert (base / "roms/PS/Disc 2/track01.bin").read_bytes() == b"disc-two"
  found = RomScanner(base / "roms").scan_console("PS")
  assert len(found) == 2, [r["path"] for r in found]
  print("RT-016 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-017 — An interrupted import never leaves a half-extracted ROM
- **Area:** Library
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: fill the disk (or pull the drive) halfway through importing a large
  archive, then import the same archive again with room to spare.
- **Expected:** Nothing is left at the ROM's final name after the failed import, and the second
  import writes the complete file. A truncated ROM at the final path used to be skipped as
  "already there" by every later import, forever (issue #229).
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, shutil, zipfile
  from pathlib import Path
  from unittest.mock import patch
  from openemux.core.archives import extract_archive

  base = Path(os.environ["SCRATCH"]) / "rt017"
  shutil.rmtree(base, ignore_errors=True)
  dest = base / "out"
  dest.mkdir(parents=True)
  src = base / "Disc.zip"
  with zipfile.ZipFile(src, "w") as z:
      z.writestr("Disc.bin", b"x" * 65536)

  with patch("openemux.core.atomic_write.os.replace", side_effect=OSError("disk full")):
      assert extract_archive(src, dest) == []
  assert list(dest.iterdir()) == [], list(dest.iterdir())

  extracted = extract_archive(src, dest)
  assert (dest / "Disc.bin").read_bytes() == b"x" * 65536
  assert extracted == [dest / "Disc.bin"]

  # And a truncated file left by an older version is repaired, not blessed.
  (dest / "Disc.bin").write_bytes(b"x" * 100)
  extract_archive(src, dest)
  assert (dest / "Disc.bin").read_bytes() == b"x" * 65536
  print("RT-017 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-018 — A ROM whose name is not valid UTF-8 scans, shows and keeps working
- **Area:** Library
- **Mode:** AUTO-UI
- **Preconditions:** A **throwaway** `HOME` with a library holding a ROM whose filename carries a
  non-UTF-8 byte (`printf` the name with `\xff` in it) plus one ordinary ROM.
- **Steps:**
  1. Launch the app against that `HOME`, open the console page.
  2. Press `F5`, wait for the rescan, then press `F5` again.
- **Expected:** Both games are in the grid — the bad one shown with its offending byte escaped
  (`Contra \udcff (Japan)`) — the header counts 2 games, and the **second** `F5` runs a rescan too.
  Old dumps carry cp437 and Shift-JIS names; such a name used to raise mid-write, kill the scan
  worker, and leave `_scan_running` set so every later scan was refused with "a scan is already
  running" until the app was restarted (issue #214). The launch log gains no `Traceback` and no
  `--- Logging error ---`.
- **Check:** two screenshots (grid, and after the second rescan); `grep -c Traceback` and
  `grep -c "Logging error"` on the launch log are both 0; the console `.list` on disk holds the
  raw name (`python3 -c "print(open(p,'rb').read())"`); suite file `tests/test_non_utf8_names.py`.
- **Restore:** delete the throwaway `HOME`.

### RT-019 — A worker that crashes never wedges its feature
- **Area:** Library
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: make a rescan, a cover sync or an artwork search fail, then start the
  same thing again.
- **Expected:** It starts. The completion callback is what clears the "already running" flag, and
  a worker that died without firing it left the feature refused for the rest of the session
  (issue #214) — the rescan behind "a scan is already running", the sync behind a banner that
  could never be dismissed, the artwork dialog spinning forever.
- **Check:** suite files `tests/test_cover_sync.py`
  (`test_a_crashed_sync_still_reports_back`, `test_a_crashed_artwork_sync_still_reports_back`),
  `tests/test_artwork_search.py` (`CrashedWorkerTests`), `tests/test_non_utf8_names.py`
  (`test_one_bad_console_does_not_abort_the_whole_rescan`).

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

### RT-026 — A fresh install lands on the onboarding page
- **Area:** Navigation
- **Mode:** AUTO-UI
- **Preconditions:** A **throwaway** `HOME` with an empty ROM folder and the bootstrap already
  marked completed. Never the real home.
- **Steps:**
  1. Launch the app against that `HOME`.
  2. Put a ROM in the library folder and launch it again.
- **Expected:** Step 1 shows "Your library is empty", the drag-and-drop line and the "Import
  ROMs…" / "Choose a folder instead" buttons, with an **empty sidebar**. That page could never be
  reached before: the Favorites row is always first in the list, the list selects its first row as
  soon as it takes focus, and the user was met with "No favorites yet — right-click a game and
  choose Add to favorites", about a game they do not have (issue #224). Step 2 brings the whole
  sidebar back ("All", "Favorites", the console) and lands on "Favorites" as usual.
- **Check:** a screenshot per step; the launch log's last `ui view changed` line reads
  `visible_view=library-empty` for step 1 and `visible_view=__favorites__` for step 2; suite file
  `tests/test_library_landing.py`.
- **Restore:** delete the throwaway `HOME`.

### RT-027 — A rescan leaves you in the collection you were browsing
- **Area:** Navigation
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary collections directory).
- **Steps:** As a QA person: open a collection, press `F5`, and watch where you end up. Or simply
  open a collection at launch — the startup scan rescans on every single launch.
- **Expected:** You stay in the collection, with its scroll position. Collection scopes were never
  in the set of places a rebuilt library would land, so every rescan threw the user into Favorites
  (issue #225). A collection deleted since the rescan started still falls back to Favorites, the
  way a console that is gone does.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, shutil
  from pathlib import Path
  from openemux.core.collections import CollectionManager
  from openemux.ui.window import FAVORITES_ID, OpenEmuxWindow, collection_scope

  base = Path(os.environ["SCRATCH"]) / "rt027"
  shutil.rmtree(base, ignore_errors=True)
  manager = CollectionManager(base)
  manager.create("Hard games")
  manager.add("hard-games", ["/roms/FC/Contra.nes"])
  slugs = [c["slug"] for c in manager.list_collections()]

  scope = collection_scope("hard-games")
  assert OpenEmuxWindow._landing_view(["FC"], scope, slugs) == scope, "a rescan left the collection"
  assert OpenEmuxWindow._landing_view(["FC"], collection_scope("gone"), slugs) == FAVORITES_ID
  print("RT-027 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

### RT-028 — A rescan asked for while one is running still happens
- **Area:** Navigation
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: import ROMs the moment the app opens, so the import finishes while
  the automatic startup scan is still running.
- **Expected:** The new games appear. The post-import rescan was refused and dropped with no retry
  and no message — the user saw "imported" and then nothing, which reads as a failed import
  (issue #225). The request is queued and runs when the current scan ends; a queued whole-library
  rescan absorbs a single-console one, and two different consoles become a whole-library rescan.
- **Check:** suite file `tests/test_library_landing.py` (`RescanQueueTests`).

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

### RT-055 — An error page is never saved as a cover
- **Area:** Covers
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: sync covers behind a captive portal, or with a ScreenScraper account
  that is over its daily quota, then look at the cards and at
  `~/games/roms/<CONSOLE>/covers/`.
- **Expected:** Nothing is written for the ROMs that failed — the responses come back with a 200
  and a plain-text or HTML body, and only the bytes can tell. A 0-byte body and a download cut
  off after the magic number are rejected the same way, and a failed write leaves nothing at the
  final name (issue #213).
- **Check:** suite files `tests/test_scraper.py` (`ImageSniffingTests`),
  `tests/test_cover_sync.py` (`test_an_error_page_served_with_a_200_is_not_saved_as_a_cover`,
  `test_a_failed_write_leaves_nothing_at_the_final_name`),
  `tests/test_artwork_search.py` (`CandidateDownloadTests`).

### RT-056 — Junk art from an older version is cleared by the next sync
- **Area:** Covers
- **Mode:** AUTO-PROBE
- **Preconditions:** none (uses a temporary directory).
- **Steps:** As a QA person: put an HTML file at
  `~/games/roms/<CONSOLE>/covers/<Game>.png`, then run a normal (fill-in) cover sync for that
  console.
- **Expected:** The junk file is deleted and the cover is fetched properly. Any file at that path
  used to count as art, so the ROM was skipped on every later sync and the only symptom was a
  blank card — the user had to find and delete each one by hand (issue #213). Real art already
  there is still left alone.
- **Check:**
  ```bash
  SCRATCH="$SCRATCH" PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, shutil
  from pathlib import Path
  from unittest.mock import patch
  from openemux.core import cover_sync

  base = Path(os.environ["SCRATCH"]) / "rt056"
  shutil.rmtree(base, ignore_errors=True)
  covers = base / "PS" / "covers"
  covers.mkdir(parents=True)
  junk = covers / "Game.png"
  junk.write_bytes(b"<html>Quota exceeded</html>" * 4)
  good = covers / "Other.png"
  good.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 96)

  def run(rom_name):
      with patch("openemux.core.cover_sync._staged_cover_candidates",
                 return_value=[("libretro", "primary", "https://cdn.example/a.png")]), \
           patch("openemux.core.cover_sync._download_cover", side_effect=lambda url, dest: dest):
          return cover_sync._process_rom(
              "PS", {"name": rom_name, "path": f"/roms/PS/{rom_name}.cue"}, base,
              "covers", "boxart", {}, None, False, None, cover_sync._HostGates(),
          )

  assert run("Game")["status"] == "downloaded", "the junk cover was skipped again"
  assert not junk.exists(), "the junk cover is still there"  # the stubbed download writes nothing
  assert run("Other")["status"] == "skipped", "real art must be left alone"
  print("RT-056 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside `$SCRATCH`.

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

### RT-076 — A launch that cannot happen says why
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: make `~/.openemux` read-only (or fill the disk) and click a game.
- **Expected:** A toast names the error. Everything before the process starts writes to disk — the
  states dir, the runtime dir, the `--appendconfig` override, an input profile normalised on load
  — and none of it was guarded, so the error went into the GTK click handler, which prints a
  traceback and swallows it. The button simply did nothing (issue #226). A failed launch also
  closes the log file it opened instead of leaking the descriptor.
- **Check:** suite file `tests/test_retroarch_launcher.py` (`LaunchFailuresAreVisibleTests`).

### RT-077 — A game that dies on startup says what the log said
- **Area:** Launch
- **Mode:** AUTO-UI
- **Preconditions:** A **throwaway** `HOME` whose `runtime.retroarch.binary` points at a script
  that prints `dlopen(): error loading libfuse.so.2` and exits 1, with a matching core file under
  `<HOME>/.config/retroarch/cores/`. Never the real home.
- **Steps:**
  1. Launch the app against that `HOME`, open the console and start the game.
  2. Read the toast.
- **Expected:** *&lt;game&gt; closed straight away — The RetroArch AppImage needs FUSE (libfuse2),
  which this system does not have.* A nonzero exit within three seconds is a launch that never
  started; the old message ("finished (exit code 1)") was indistinguishable from a clean quit, so
  on a host with no libfuse2 every launch died in silence (issue #226). The toast appears
  immediately here: the configured binary is a script, not an AppImage, so there is nothing to
  unpack and the retry of RT-206 does not apply.
- **Check:** screenshot of the toast; `grep "died on startup" <launch log>`; suite files
  `tests/test_runtime_manager.py` (`StartupFailureTests`), `tests/test_retroarch_log.py`
  (`FailureReasonTests`, `ReadFailureReasonTests`).
- **Restore:** delete the throwaway `HOME`.

### RT-078 — An AppImage runs without FUSE when the host has none
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: run the app on a distribution that ships no libfuse2 and launch a
  game against the vendored RetroArch AppImage.
- **Expected:** The AppImage is started with `--appimage-extract-and-run`, which needs no FUSE, and
  the game runs. On a host that *has* libfuse2 the flag is not used — extracting the whole image
  on every launch is only worth paying for when mounting cannot work (issue #226).
- **Check:** suite file `tests/test_retroarch_launcher.py` (`AppImageFuseFallbackTests`).

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

### RT-079 — The wrapper's fullscreen key works whatever it is bound to
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: rebind "Toggle fullscreen" to Enter (or Page Up, Delete, keypad +,
  right Shift), launch a game in the OpenEmux window and press it.
- **Expected:** The window toggles fullscreen. Bindings are stored in RetroArch's vocabulary and X
  does not know most of those words, so the grab resolved to nothing and the key did nothing —
  and RetroArch's own toggle is deliberately unbound while embedded, so that left **no**
  fullscreen key at all, with one log line to explain it (issue #236). A binding that still cannot
  be resolved now falls back to "F" instead of to nothing.
- **Check:** suite file `tests/test_x11_embed.py` (`KeysymResolutionTests` — including
  `test_every_retroarch_key_name_can_be_resolved`, which walks the whole stored vocabulary against
  the real Xlib tables), `tests/test_game_window.py` (`FullscreenBindingTests`).

### RT-083 — Double-clicking a game launches it once
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A working core and ROM.
- **Steps:**
  1. Double-click a card the way you would in a file manager.
- **Expected:** The game starts, and **no** "A game is already running" toast appears. Activation
  is on a single click, so a double-click emitted it twice: the second launch was correctly
  refused, but the refusal is an error toast, so anyone who habitually double-clicks got an error
  on every launch (issue #236).
- **Check:** human only (launching grabs the keyboard for the emulator); the debounce itself in
  `tests/test_game_window.py` (`DoubleClickTests`).

### RT-084 — Input keeps working after clicking the game window's chrome
- **Area:** Launch
- **Mode:** MANUAL
- **Preconditions:** A game running in the OpenEmux window.
- **Steps:**
  1. Click the header bar (the pause or volume control), then go back to playing.
- **Expected:** The pad and the keyboard still drive the game. RetroArch gates input on X focus,
  and the reclaim tick used to skip entirely on sessions whose window manager does not keep
  `_NET_ACTIVE_WINDOW` current — the game went input-dead after any click on the chrome, silently
  (issue #236). The fallback now decides from X's own input focus, and the missing property is
  logged once.
- **Check:** human only; the decision itself in `tests/test_x11_embed.py`
  (`FocusReclaimDecisionTests`, `EnsureFocusWithoutActiveWindowTests`).

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

### RT-205 — The AppImage runtime asks the host for no library
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none. The probe reads `dist/*.AppImage` when one has been built, and the
  build inputs otherwise.
- **Steps:** As a QA person: on a stock Ubuntu 24.04 or Fedora 40 desktop — neither installs a
  FUSE 2 library — `chmod +x` the AppImage and double-click it.
- **Expected:** The app starts. It used to die with `dlopen(): error loading libfuse.so.2` before
  a line of OpenEmux ran, because appimage-builder embeds AppImageKit's dynamically linked
  runtime and neither of the two distributions the project targets as its floor ships
  `libfuse2t64`/`fuse-libs` (issue #248). The bundle now carries type2-runtime's static-pie
  runtime, with squashfuse and FUSE 3 linked in.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import glob, re, subprocess
  from pathlib import Path
  bundles = sorted(glob.glob("dist/*.AppImage"))
  if bundles:
      # The runtime is the ELF the payload is appended to: read the header to
      # find where the sections end, which is where the squashfs begins.
      raw = Path(bundles[0]).read_bytes()
      e_shoff = int.from_bytes(raw[0x28:0x30], "little")
      e_shentsize = int.from_bytes(raw[0x3A:0x3C], "little")
      e_shnum = int.from_bytes(raw[0x3C:0x3E], "little")
      runtime = raw[: e_shoff + e_shentsize * e_shnum]
      assert b"libfuse.so.2" not in runtime, f"{bundles[0]} still wants libfuse.so.2"
      Path("/tmp/rt189-runtime").write_bytes(runtime)
      out = subprocess.run(["readelf", "-d", "/tmp/rt189-runtime"],
                           capture_output=True, text=True).stdout
      assert "(NEEDED)" not in out, f"the runtime is dynamically linked:\n{out}"
  else:
      docker = Path("packaging/docker/appimage.Dockerfile").read_text()
      build = Path("packaging/appimage/build.sh").read_text()
      assert re.search(r"type2-runtime/releases/download/\d+/runtime-x86_64", docker), \
          "the build image does not pin a type2-runtime build"
      assert "APPIMAGE_RUNTIME_SHA256" in docker, "the pinned runtime is not checksummed"
      assert "/opt/appimage-runtime-x86_64" in build, \
          "build.sh does not append the payload to the pinned runtime"
      # That runtime reads zlib and zstd only; xz would assemble and then
      # refuse to open itself.
      assert "-comp zstd" in build, "the payload is not squashed with zstd"
      assert "libfuse" in build and "(NEEDED)" in build, \
          "build.sh does not verify the runtime it shipped"
  print("RT-205 OK")
  EOF
  ```

### RT-206 — A game whose AppImage cannot mount is retried unpacked
- **Area:** Launch
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person on a host that *has* libfuse2 but cannot mount with it — no
  `/dev/fuse` (a container), or a `fusermount` that is not setuid: click a game.
- **Expected:** The game starts. The `libfuse.so.2` probe answers "can this library be loaded",
  which is not "can this host mount a FUSE filesystem", so such a host passed the probe and every
  launch still died at the mount with nothing said (issue #248). The launch is now repeated once
  with `--appimage-extract-and-run`, which needs no FUSE at all, and nothing is reported to the
  user in between. Exactly one retry: a second failure is reported normally. A native RetroArch is
  never retried — there is nothing to unpack — and a death the log does not blame on FUSE is
  reported at once.
  The game window follows the retry rather than closing on the dead process, so the game is still
  wrapped and embedding is not written off for the session.
- **Check:** suite files `tests/test_runtime_manager.py` (`UnpackedRetryTests`),
  `tests/test_retroarch_launcher.py` (`ForcedExtractRetryTests`),
  `tests/test_retroarch_log.py` (`FuseFailureTests`, `ReadIsFuseFailureTests`),
  `tests/test_game_window.py` (`FollowRelaunchTests`).

### RT-207 — The native packages require FUSE rather than suggesting it
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: install the `.rpm` with `rpm -ivh` (or the `.deb` with `dpkg -i`) —
  neither pulls weak dependencies — and launch a game.
- **Expected:** The install pulls the FUSE 2 library, and the game runs. The vendored RetroArch
  AppImage is the only emulator these packages ship and its runtime needs `libfuse.so.2`; as a
  `Recommends` it arrived only with `dnf install ./x.rpm` / `apt install ./x.deb`, so `rpm -ivh`,
  `dpkg -i`, `--setopt=install_weak_deps=False` and offline installs produced an app that
  installed cleanly and could not launch a single game (issue #248).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  spec = Path("packaging/rpm/openemux.spec").read_text()
  assert "Requires:       fuse-libs" in spec, "the .rpm does not require fuse-libs"
  assert "Recommends:     fuse-libs" not in spec, "fuse-libs is still only recommended"
  deb = Path("packaging/deb/build.sh").read_text()
  depends = next(l for l in deb.splitlines() if l.startswith("Depends:"))
  assert "libfuse2t64 | libfuse2" in depends, f"the .deb does not depend on libfuse2: {depends}"
  assert "Recommends: libfuse2" not in deb, "libfuse2 is still only recommended"
  print("RT-207 OK")
  EOF
  ```

### RT-209 — Every package can decode the covers it downloads
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the built packages assert the same thing
  against their own installs).
- **Steps:** As a QA person: install the `.deb` (`sudo apt install ./openemux_*.deb`) or the
  `.rpm` on a machine with no image viewer installed, sync cover art, and look at the grid.
- **Expected:** The covers render. Cover art synced from libretro is WebP and gdk-pixbuf has no
  built-in decoder for it, so the loader is a separate package on every distribution — and neither
  native package declared it (issue #251). Measured against the released 1.11.3 artifacts:
  `apt install ./openemux_1.11.3_amd64.deb` on `ubuntu:24.04` left gdk-pixbuf with no `webp`
  loader at all, and on `fedora:40` it arrived only as a *weak* dependency of
  `gdk-pixbuf2-modules`, so `rpm -ivh`, `--setopt=install_weak_deps=False` and offline installs
  did without it. Every synced cover then decoded to nothing and the card rendered blank, with
  only a `cover decode failed` line in the log. The AppImage has bundled the loader from the
  start; the Flatpak gets it from `org.gnome.Platform`.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  spec = Path("packaging/rpm/openemux.spec").read_text()
  assert "Requires:       webp-pixbuf-loader" in spec, "the .rpm does not require the loader"
  deb = Path("packaging/deb/build.sh").read_text()
  depends = next(l for l in deb.splitlines() if l.startswith("Depends:"))
  assert "webp-pixbuf-loader" in depends, f"the .deb does not depend on the loader: {depends}"
  # ...and each build proves it against its own install rather than trusting the line.
  for build in ("packaging/deb/build.sh", "packaging/rpm/build.sh",
                "packaging/appimage/selftest.py"):
      assert "SUPPORTED_COVER_EXTS" in Path(build).read_text(), \
          f"{build} does not check the loaders against the formats a cover can be"
  print("RT-209 OK")
  EOF
  ```

### RT-208 — RetroArch is launched with the session's environment, not the bundle's
- **Area:** Packaging
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: run OpenEmux from its AppImage and start a game.
- **Expected:** RetroArch runs against the host's libraries and the session's `PATH` and
  `XDG_DATA_DIRS`. The vendored RetroArch AppImage lives *inside* our AppDir, and
  appimage-builder's AppRun hooks decide by path — so it was handed the bundle's
  `LD_LIBRARY_PATH`, `LD_PRELOAD=libapprun_hooks.so`, `PYTHONHOME`, `PYTHONPATH`,
  `GI_TYPELIB_PATH`, `GDK_PIXBUF_MODULE*`, `GSETTINGS_SCHEMA_DIR`, `GTK_PATH` and a
  `PATH`/`XDG_DATA_DIRS` leading into the mount, and resolved its libraries against the
  Ubuntu-noble stack bundled for a GTK4 app (issue #249). Measured in the built bundle: 57 bundle
  variables reached a process started from `vendors/` before the fix, 1 after — and that one
  (`APPRUN_CWD`) is written by the hook itself. Outside an AppImage nothing is stripped: a native
  install's `LD_PRELOAD` (mangohud, gamemode) is the user's and reaches the game.
- **Check:** suite files `tests/test_appimage_env.py`, `tests/test_retroarch_launcher.py`
  (`LaunchEnvironmentTests`).

### RT-210 — A build never leaves the ScreenScraper credential in the working tree
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: start `make flatpak` with a `.env` holding the ScreenScraper
  developer credential, kill the build mid-way (`docker kill` the container, or reboot), then run
  `git status` and `git diff src/openemux/core/embedded_credentials.py`.
- **Expected:** The working tree is untouched — no modified `embedded_credentials.py`, no
  leftover `.orig` beside it. The Flatpak build used to rewrite that *tracked* file in place and
  restore it from an `EXIT` trap, which a `SIGKILL` skips, so the obfuscated developer credential
  was left one `git commit -a` away from being published (issue #250). Every target now injects
  into its own staging copy, and `packaging/build.sh` refuses to start at all when the tracked
  file already carries a blob.
- **Check:** suite file `tests/test_packaging_credentials.py`, plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  cred = Path("src/openemux/core/embedded_credentials.py")
  assert '_EMBEDDED_BLOB = ""' in cred.read_text(), "the tracked module carries a credential"
  assert not Path(str(cred) + ".orig").exists(), "an interrupted build left a .orig behind"
  flatpak = Path("packaging/flatpak/build.sh").read_text()
  assert "mktemp -d" in flatpak, "the flatpak build no longer stages its inputs"
  assert "trap 'mv" not in flatpak, "the tracked file is restored by a trap again"
  entry = Path("packaging/build.sh").read_text()
  assert '_EMBEDDED_BLOB = ""' in entry, "the entry point does not refuse a poisoned tree"
  print("RT-210 OK")
  EOF
  ```

### RT-211 — The RPM rebuilds outside the project's Docker mount
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; `make rpm` proves the same thing against a
  real `rpmbuild`).
- **Steps:** As a QA person on a Fedora box with no OpenEmux checkout: take the `.src.rpm` the
  build produces and run `rpmbuild --rebuild openemux-*.src.rpm` (or `mock -r fedora-40-x86_64`).
- **Expected:** It builds. The spec had no `Source0`, no `%prep` and no `%build` — it was driven
  with `--define "repo_root /work"` and ran the staging script straight out of the project's own
  bind mount, so `rpmbuild -ba` produced no SRPM at all and every other invocation got a literal
  `%{repo_root}` path. `mock`, COPR and Fedora review therefore had nothing to start from
  (issue #252). The spec now unpacks a source tarball, and `packaging/rpm/build.sh` rebuilds its
  own SRPM in a different `_topdir` on every run, then runs rpmlint over both artifacts and fails
  on `incoherent-changelog-date`, `no-blank-line-in-changelog` or `dir-or-file-in-usr-share-doc`.
- **Check:** suite file `tests/test_rpm_spec.py` (which also checks every `%changelog` header
  against the calendar), plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  spec = Path("packaging/rpm/openemux.spec").read_text()
  for section in ("%prep", "%build", "%install", "%check"):
      assert f"\n{section}\n" in spec, f"the spec has no {section}"
  assert "Source0:" in spec, "the spec declares no source tarball"
  assert "repo_root" not in spec, "the spec still reaches into the project's bind mount"
  build = Path("packaging/rpm/build.sh").read_text()
  assert "rpmbuild -ba" in build, "the build no longer produces an SRPM"
  assert "--rebuild" in build, "the build never proves the SRPM stands on its own"
  print("RT-211 OK")
  EOF
  ```

### RT-212 — The RPM's licence is installed where rpm keeps licences
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the build asserts the same against its own
  install).
- **Steps:** As a QA person: `dnf install ./openemux-*.rpm`, then run
  `rpm -qf /usr/share/doc/openemux` and `dnf remove openemux`.
- **Expected:** The licence is at `/usr/share/licenses/openemux/LICENSE`, in a directory the
  package owns, and `dnf remove` leaves nothing behind. The spec used to declare
  `%license /usr/share/doc/openemux/copyright` — the Debian layout, and a file in a directory the
  package did not own: `rpm -qf` reported no owner, the directory survived `dnf remove` and
  rpmlint raised `dir-or-file-in-usr-share-doc` (issue #252).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  spec = Path("packaging/rpm/openemux.spec").read_text()
  files = spec.split("%files", 1)[1].split("\n%", 1)[0]
  assert "/usr/share/doc" not in files, "a file is still packaged under /usr/share/doc"
  assert "%license LICENSE" in spec, "the licence is not declared by name"
  assert "rm -rf %{buildroot}/usr/share/doc/openemux" in spec, \
      "the shared staging script's Debian copy is left in the buildroot"
  build = Path("packaging/rpm/build.sh").read_text()
  assert "/usr/share/licenses/openemux/LICENSE" in build, \
      "the build does not check where the licence landed"
  print("RT-212 OK")
  EOF
  ```

### RT-213 — Removing the RPM refreshes both desktop caches; an upgrade does not
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: install the `.rpm`, upgrade it to a newer build, then
  `dnf remove openemux` and look at the applications menu.
- **Expected:** The menu entry is gone after the removal, and the upgrade never rebuilds the
  caches from a half-removed state. `%postun` used to refresh only the icon cache — never
  `update-desktop-database`, which is what the package's own `shared-mime-info` dependency and
  `%post` exist for — and neither scriptlet tested `$1`, so `%postun` also fired in the middle of
  every upgrade (issue #252).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  spec = Path("packaging/rpm/openemux.spec").read_text()
  postun = spec.split("\n%postun\n", 1)[1].split("\n%changelog", 1)[0]
  assert "if [ $1 -eq 0 ]; then" in postun, "%postun still runs during an upgrade"
  for command in ("gtk-update-icon-cache", "update-desktop-database"):
      assert command in postun, f"%postun does not run {command}"
  print("RT-213 OK")
  EOF
  ```

### RT-214 — Every package is visible in the software centre
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the `.deb`, `.rpm` and Flatpak builds run
  `appstreamcli validate` over the file they install).
- **Steps:** As a QA person: install the `.deb` on Ubuntu (or the `.rpm` on Fedora), open GNOME
  Software or KDE Discover and search for "OpenEmux".
- **Expected:** The app is listed with its name, summary, screenshots and "What's new", and an
  update to it is offered. `packaging/…/metainfo.xml` existed but only the Flatpak module
  installed it, so the `.rpm`'s 587-entry file list, the `.deb`'s 607-entry list and the AppImage
  carried none — the app was invisible in both software centres, and both rpmlint and lintian
  flag a desktop application that ships no AppStream data (issue #253). The file now lives in
  `packaging/common/` and every format installs it to `/usr/share/metainfo/`.
- **Check:** suite file `tests/test_appstream_metainfo.py`, plus:
  ```bash
  appstreamcli validate --no-net \
    packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml && echo "RT-214 OK"
  ```

### RT-215 — "What's new" has no holes, and the screenshots do not go blank
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: open the app's page in GNOME Software, scroll the version history,
  and look at the screenshots on a machine that installed months ago.
- **Expected:** Every shipped version appears in the history, and the screenshots render. The
  `<release>` list skipped 1.7.0, 1.6.0, 1.5.2, 1.5.1 and 1.5.0, so the history showed a visible
  jump from 1.8.0 to 1.4.0; and the screenshot URLs pointed at `main`, which AppStream re-indexes
  long after the install — so a screenshot refresh that renames a file under `docs/assets/` (it
  has happened twice) 404s the Flathub linter and blanks the screenshots for everyone already on
  the app (issue #253). The URLs are pinned to a commit now, and each carries `type="source"`
  with its real width and height.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import re
  import xml.etree.ElementTree as ET
  from pathlib import Path
  root = ET.parse("packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml").getroot()
  declared = {r.get("version") for r in root.find("releases")}
  spec = Path("packaging/rpm/openemux.spec").read_text()
  shipped = set(re.findall(r"^\* .* - (\S+)-\d+$", spec, re.M))
  assert not shipped - declared, f"missing from the history: {sorted(shipped - declared)}"
  for image in root.find("screenshots").iter("image"):
      assert "/main/" not in image.text, f"{image.text} points at a mutable branch"
      assert re.search(r"/OpenEmux/[0-9a-f]{40}/", image.text), f"{image.text} is not pinned"
      assert image.get("type") == "source" and image.get("width") and image.get("height")
  print("RT-215 OK")
  EOF
  ```

### RT-216 — One desktop entry, and the Flatpak's is not hidden by TryExec
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the Flatpak build asserts the same against
  the exported entry).
- **Steps:** As a QA person: install the Flatpak and look for "OpenEmux" in the applications menu;
  compare its entry with the one the `.deb` installs.
- **Expected:** The entry is there, and it is the same entry. The Flatpak carried its own copy of
  the desktop file, which had drifted from the shared one — no `Version`, no `GenericName`, no
  `StartupNotify`, a different `Comment` and a different keyword list (issue #253). It installs
  the shared entry now, with `TryExec` stripped: Flatpak exports the entry to the host, where
  `TryExec` is resolved against the host `PATH`, and no `openemux` binary lives there.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  app_id = "io.github.guilhermefeitosa66.OpenEmux"
  assert not Path(f"packaging/flatpak/{app_id}.desktop").exists(), \
      "the Flatpak still carries a second desktop entry"
  manifest = Path(f"packaging/flatpak/{app_id}.yaml").read_text()
  assert "packaging/common/openemux.desktop" in manifest, \
      "the Flatpak does not install the shared entry"
  assert "/^TryExec=/d" in manifest, "the exported entry would be hidden by TryExec"
  print("RT-216 OK")
  EOF
  ```

### RT-217 — A package carries the sources, not the maintainer's build state
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (the probe runs the staging helpers; `make deb` / `make rpm` /
  `make appimage` assert the same thing against their own staged trees).
- **Steps:** As a QA person: on a machine where the project has been `pip install -e`'d and the
  test suite has run, build the `.deb` and list it — `dpkg -c dist/openemux_*.deb | grep egg-info`.
- **Expected:** Nothing. `stage_tree.sh` staged with `cp -r "$ROOT_DIR/src"`, so the released
  `.deb` and `.rpm` both shipped `opt/openemux/src/opemux.egg-info/` — a stale directory from a
  typo'd project name that no longer exists in the repository at all — plus
  `openemux.egg-info/` and whatever `__pycache__` was lying around (issue #254). None of it is
  tracked. `top_level.txt` registers a phantom distribution on `PYTHONPATH=/opt/openemux/src`
  that `importlib.metadata` reports as installed, and `SOURCES.txt` publishes the development
  tree's file inventory.
- **Check:** suite file `tests/test_packaging_sources.py`, plus a real staging run:
  ```bash
  rm -rf "$SCRATCH/rt217" && DESTDIR="$SCRATCH/rt217" ROOT_DIR="$PWD" \
    sh packaging/common/stage_tree.sh >/dev/null &&
  PYTHONPATH=src .venv/bin/python - <<EOF
  import os
  from pathlib import Path
  staged = Path(os.environ["SCRATCH"]) / "rt217" / "opt" / "openemux"
  bad = [str(p) for p in staged.rglob("*")
         if p.name == "__pycache__" or p.name.endswith((".egg-info", ".pyc"))
         or p.name == "RetroArch-Win64"]
  assert not bad, f"build artifacts staged into the package: {bad[:5]}"
  # ...and nothing the app needs was dropped on the way.
  assert (staged / "src/openemux/main.py").is_file()
  assert (staged / "src/openemux/ui/assets/icons/symbolic/LICENSE").is_file()
  assert (staged / "vendors/RetroArch-Linux-x86_64.AppImage").is_file()
  print("RT-217 OK")
  EOF
  ```
- **Restore:** the probe stages into `$SCRATCH` only; nothing in the repository is touched.

### RT-218 — The AppImage cannot ship under the wrong version number
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; `make appimage` refuses to build on a
  mismatch).
- **Steps:** As a QA person cutting a release: bump `src/openemux/__init__.py`, forget the
  AppImage recipe, and run `make packages`.
- **Expected:** The AppImage build stops with the two versions printed. The recipe's `version:`
  was hard-coded and never compared with anything, while the `.deb`, `.rpm` and Flatpak all derive
  it from `__init__.py` — so a forgotten bump produced `OpenEmux-<old>-x86_64.AppImage` beside
  correctly versioned siblings, and it reached `dist/`, `SHA256SUMS` and the GitHub release with
  every check passing (issue #255).
- **Check:** suite file `tests/test_reproducible_builds.py`, plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  import re
  version = re.search(r'"(.*)"', Path("src/openemux/__init__.py").read_text()).group(1)
  recipe = Path("packaging/appimage/AppImageBuilder.yml").read_text()
  assert f'version: "{version}"' in recipe, f"the recipe does not say {version}"
  build = Path("packaging/appimage/build.sh").read_text()
  assert "does not carry version" in build, "the build does not guard the version"
  spec = Path("packaging/rpm/openemux.spec").read_text()
  head = next(l for l in spec.split("%changelog", 1)[1].splitlines() if l.startswith("*"))
  assert head.endswith(f" - {version}-1"), f"the %changelog head is not {version}: {head}"
  meta = Path("packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml").read_text()
  assert re.search(r'<release version="([^"]+)"', meta).group(1) == version
  print("RT-218 OK")
  EOF
  ```

### RT-219 — A release artifact is built from pinned, authenticated inputs
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the builds exercise them).
- **Steps:** As a QA person: build the same commit twice, months apart, and compare what went in.
- **Expected:** The same base images and the same Python packages. The Dockerfiles used floating
  tags (`FROM ubuntu:24.04`) and `docker build` ran without `--pull`, so a stale local image was
  reused silently; the AppImage fetched Ubuntu packages *and the key that authenticates them* over
  plain HTTP; and its Python dependencies were version-pinned but hash-free (issue #255). Bases
  are pinned by digest now, the archive and its key are https, and pip installs with
  `--require-hashes` from a file generated out of `requirements.lock`.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import re
  from pathlib import Path
  for dockerfile in sorted(Path("packaging/docker").glob("*.Dockerfile")):
      for line in dockerfile.read_text().splitlines():
          if line.startswith("FROM "):
              assert re.match(r"^FROM \S+:\S+@sha256:[0-9a-f]{64}$", line), \
                  f"{dockerfile.name}: unpinned base {line}"
          assert "http://" not in line or line.strip().startswith("#"), \
              f"{dockerfile.name}: plain HTTP: {line.strip()}"
  build = Path("packaging/build.sh").read_text()
  assert "docker build --pull" in build, "a stale base image can still be reused"
  recipe = Path("packaging/appimage/AppImageBuilder.yml").read_text()
  assert "http://" not in recipe, "the AppImage still fetches something over plain HTTP"
  assert "--require-hashes" in recipe, "the bundle's Python deps are not hash-pinned"
  print("RT-219 OK")
  EOF
  ```

### RT-220 — No build runs the container as host root
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; `make appimage` and `make flatpak` prove
  the narrowed set is enough).
- **Steps:** As a QA person: run `make appimage` and `make flatpak` and watch `docker inspect` on
  the running container.
- **Expected:** Both build normally without `--privileged`. They genuinely need to mount a
  filesystem — squashfs for appimage-builder, bubblewrap for flatpak-builder — but that is
  `SYS_ADMIN` plus `/dev/fuse` plus an AppArmor exception for the AppImage, and additionally
  `NET_ADMIN` (loopback in the unshared network namespace) and a seccomp exception (`pivot_root`)
  for the Flatpak. Not full host root in a container that also bind-mounts the repository and
  carries `SCREENSCRAPER_DEVPASSWORD` (issue #255).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  build = Path("packaging/build.sh").read_text()
  live = [l for l in build.splitlines() if not l.strip().startswith("#")]
  assert not [l for l in live if "--privileged" in l], "a build still asks for --privileged"
  for argument in ("--cap-add SYS_ADMIN", "--device /dev/fuse",
                   "--security-opt apparmor:unconfined", "--cap-add NET_ADMIN",
                   "--security-opt seccomp=unconfined"):
      assert argument in build, f"the FUSE builds no longer ask for {argument}"
  print("RT-220 OK")
  EOF
  ```

### RT-221 — No package carries artwork the UI never displays
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the source tree; the built artifacts follow from it).
- **Steps:** As a QA person: install the `.deb` and run
  `du -sh /opt/openemux/src/openemux/ui/assets/icons/*`.
- **Expected:** Only `systems/` and `symbolic/`, a few hundred KB in total. About 18 MB of
  vendored PNG artwork used to ship in every `.deb`, `.rpm`, AppImage and Flatpak without a code
  path that could ever read it: 168 controller illustrations, six Preferences icons (the pages
  use symbolic icon names) and 37 console icons for consoles OpenEmux does not support, regional
  variants it does not use, and OpenEmu's own "Unused console icons" (issue #233). The only
  reader is `_asset_path(category, filename)`, called with `"systems"` and nothing else.
- **Check:** suite file `tests/test_icon_assets.py`, plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import re
  from pathlib import Path
  icons = Path("src/openemux/ui/assets/icons")
  for gone in ("controllers", "settings"):
      assert not (icons / gone).exists(), f"{gone}/ ships and nothing displays it"
  block = (Path("src/openemux/ui/window.py").read_text()
           .split("CONSOLE_ICON_FILES = {", 1)[1].split("}", 1)[0])
  wanted = set(re.findall(r'"([^"]+\.png)"', block))
  wanted |= {n.replace("@2x.png", ".png") for n in wanted if n.endswith("@2x.png")}
  present = {p.name for p in (icons / "systems").iterdir() if p.is_file()}
  assert not present - wanted, f"unreferenced console icons: {sorted(present - wanted)}"
  total = sum(p.stat().st_size for p in icons.rglob("*") if p.is_file())
  assert total < 2_000_000, f"the icon tree is back up to {total} bytes"
  print("RT-221 OK")
  EOF
  ```

### RT-222 — The packaged copyright covers the third-party material, not just OpenEmux
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: install any package and read
  `/usr/share/doc/openemux/copyright` (`/usr/share/licenses/openemux/copyright` on Fedora).
- **Expected:** It is a DEP-5 file naming the terms of everything that ships: OpenEmux's own MIT,
  the OpenEmu console icons (BSD-3-clause), the Adwaita symbolic icons (LGPL-3 or CC-BY-SA-3.0)
  and the vendored RetroArch AppImage (GPL-3+). Every package used to install the bare MIT
  `LICENSE` there, which implicitly claimed MIT over roughly a third of its own contents, while
  `ui/assets/icons/ATTRIBUTION.md` recorded provenance and no terms at all (issue #233).
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  copyright_text = Path("packaging/common/copyright").read_text()
  assert copyright_text.startswith("Format: https://www.debian.org/doc/"), "not DEP-5"
  for name in ("MIT", "BSD-3-clause-OpenEmu", "LGPL-3 or CC-BY-SA-3.0", "GPL-3+"):
      assert f"License: {name}" in copyright_text, f"no terms for {name}"
  attribution = " ".join(
      Path("src/openemux/ui/assets/icons/ATTRIBUTION.md").read_text().split())
  assert "not covered by OpenEmux's MIT license" in attribution
  assert "Redistribution and use in source and binary forms" in attribution
  for installer in ("packaging/common/stage_tree.sh",
                    "packaging/appimage/AppImageBuilder.yml",
                    "packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml",
                    "packaging/rpm/openemux.spec"):
      assert "packaging/common/copyright" in Path(installer).read_text(), \
          f"{installer} does not install the copyright file"
  # The notice must reach the pip-installed build too, which copies no src/.
  assert "ui/assets/icons/ATTRIBUTION.md" in Path("pyproject.toml").read_text()
  print("RT-222 OK")
  EOF
  ```

### RT-223 — An integrated AppImage keeps its menu entry
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; the AppImage build refuses to package an
  entry that carries `TryExec`).
- **Steps:** As a QA person: download the AppImage, integrate it with GearLever (or appimaged, or
  AppImageLauncher), then open the applications menu and search for "OpenEmux".
- **Expected:** The entry is there. `TryExec` is resolved against the user's `PATH`, and
  integrators rewrite `Exec` to the bundle path but leave `TryExec` alone — so
  `TryExec=openemux`, with no `openemux` binary anywhere in `PATH`, silently hid the integrated
  entry from the menu (issue #256). The shared desktop file carries no `TryExec` now; the
  `.deb`/`.rpm` get an absolute `TryExec=/usr/bin/openemux` added at staging time, because they
  are the ones that install that binary.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  shared = Path("packaging/common/openemux.desktop").read_text()
  assert "TryExec" not in shared, "the shared entry would be hidden after integration"
  stage = Path("packaging/common/stage_tree.sh").read_text()
  assert "TryExec=/usr/bin/openemux" in stage, "the native packages lost their TryExec"
  appimage = Path("packaging/appimage/build.sh").read_text()
  assert "carries TryExec" in appimage, "the AppImage build no longer checks"
  print("RT-223 OK")
  EOF
  ```

### RT-224 — The .deb can be verified and read like any other Debian package
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs; `make deb` runs `debsums` against its own
  install).
- **Steps:** As a QA person: `sudo apt install ./openemux_*.deb`, then run `debsums openemux` and
  `zless /usr/share/doc/openemux/changelog.Debian.gz`.
- **Expected:** `debsums` verifies every file, and the changelog lists the release history. The
  `.deb` had exactly three control members — `control`, `postinst`, `postrm` — because the build
  hand-writes them and calls `dpkg-deb --build` directly, so nothing generated `md5sums` and
  `debsums` could not check a single one of the 600+ installed files of a package that ships an
  executable AppImage (lintian's `no-md5sums-control-file`). There was no changelog either
  (`debian-changelog-file-missing`); it is rendered from the spec's `%changelog`, so a release
  documents itself in one place (issue #256).
- **Check:** suite file `tests/test_desktop_entry.py`, plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import re, subprocess, sys
  from pathlib import Path
  build = Path("packaging/deb/build.sh").read_text()
  assert "DEBIAN/md5sums" in build, "the .deb generates no md5sums"
  assert build.index("DEBIAN/md5sums") < build.index("dpkg-deb --root-owner-group")
  assert "debsums -s openemux" in build, "the build never proves debsums works"
  assert "changelog.Debian.gz" in build, "the .deb ships no changelog"
  rendered = subprocess.run([sys.executable, "packaging/deb/changelog_from_spec.py"],
                            capture_output=True, text=True, check=True).stdout
  spec = Path("packaging/rpm/openemux.spec").read_text()
  documented = set(re.findall(r"^\* .* - (\S+)-\d+$", spec, re.M))
  assert set(re.findall(r"(?m)^openemux \(([^)]+)\)", rendered)) == documented
  print("RT-224 OK")
  EOF
  ```

### RT-225 — No package declares a dependency that indexes nothing
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the packaging inputs).
- **Steps:** As a QA person: right-click a ROM in the file manager and look at "Open With".
- **Expected:** OpenEmux is not offered, and neither native package pulls `shared-mime-info` to
  make that so. The entry has no `MimeType=` and no `%f`/`%U` field code — the app cannot open a
  ROM handed to it — yet both packages declared `shared-mime-info` as a hard dependency and both
  ran `update-desktop-database`, whose whole purpose is rebuilding the MIME association cache
  (issue #256). GTK needs the shared MIME database at runtime and already depends on it on both
  distributions, so dropping the explicit declaration changes nothing for the user. The AppImage
  still bundles it: `XDG_DATA_DIRS` leads into the AppDir, so GTK looks for the database there.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import re
  from pathlib import Path
  entry = Path("packaging/common/openemux.desktop").read_text()
  has_mimetype = "MimeType=" in entry
  has_field_code = re.search(r"(?m)^Exec=.*%[fFuU]", entry) is not None
  deb = Path("packaging/deb/build.sh").read_text()
  depends = next(l for l in deb.splitlines() if l.startswith("Depends:"))
  spec = Path("packaging/rpm/openemux.spec").read_text()
  declared = ("shared-mime-info" in depends
              or re.search(r"(?m)^Requires:\s+shared-mime-info$", spec) is not None)
  # Either both, or neither: a MimeType without the dependency does not index,
  # and the dependency without a MimeType has nothing to index.
  assert (has_mimetype and has_field_code) == declared, \
      f"MimeType={has_mimetype}, field code={has_field_code}, dependency={declared}"
  print("RT-225 OK")
  EOF
  ```

### RT-226 — The Flatpak asks for exactly the permissions it can justify
- **Area:** Packaging
- **Mode:** AUTO-PROBE
- **Preconditions:** none (reads the manifest and the code it makes claims about).
- **Steps:** As a QA person: `flatpak info --show-permissions io.github.guilhermefeitosa66.OpenEmux`
  after installing the bundle, and read the `finish-args` block in the manifest.
- **Expected:** Eight permissions, no more, and the two widest carry a written rationale.
  `--talk-name=org.freedesktop.Flatpak` allows `flatpak-spawn --host` with arbitrary commands —
  unrestricted code execution outside the sandbox — and with `--filesystem=home` beside it the
  sandbox confines essentially nothing. Both are architecturally required by the current launch
  design, but they were unremarked lines in a manifest on an app heading for Flathub, whose linter
  asks for a justification in the submission (issue #257). Narrowing `--filesystem=home` to a
  portal-granted ROM directory needs the three `Gtk.FileChooserDialog` call sites ported to
  `Gtk.FileDialog` first (issue #235), then `~/.openemux`, the ROM path and the absolute paths
  handed to the host RetroArch.
- **Check:** suite file `tests/test_flatpak_sandbox.py`, plus:
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  from pathlib import Path
  import yaml
  path = Path("packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml")
  manifest = yaml.safe_load(path.read_text())
  args = manifest["finish-args"]
  assert len(args) == 8, f"the permission set changed: {args}"
  for wider in ("--filesystem=host", "--socket=session-bus", "--socket=system-bus"):
      assert wider not in args, f"{wider} was added to the sandbox"
  text = path.read_text()
  for term in ("flatpak-spawn", "retroarch_launcher.py", "Gtk.FileChooserDialog",
               "issue #235", "no confinement"):
      assert term in text, f"the rationale no longer mentions {term}"
  print("RT-226 OK")
  EOF
  ```

### RT-230 — A package check reports what it found, not what the pipe did
- **Area:** Packaging
- **Mode:** AUTO-SUITE
- **Preconditions:** none (reads the build scripts).
- **Steps:** As a QA person: grep the packaging scripts for a producer piped straight into
  `grep -q`.
- **Expected:** None left. `grep -q` exits on its first match and SIGPIPEs whatever is still
  writing; under `set -o pipefail` that pipeline reports failure. In `packaging/deb/build.sh` it
  killed the build after "md5sums covers all 352 packaged files" (exit 141) — on CI but not on the
  maintainer's machine, because whether it happens depends on how much of the listing is still
  buffered. In `packaging/appimage/build.sh` it was worse than a crash: the two runtime guards read
  `if producer | grep -q ...`, so a runtime that *did* want `libfuse.so.2`, or *was* dynamically
  linked, took the else branch and passed the check (issues #241, #248).
- **Check:** suite file `tests/test_reproducible_builds.py`
  (`NoBuildCheckIsDefeatedByASignalTests`).

### RT-228 — Every package format is built by CI, not first at release time
- **Area:** Packaging
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: open `.github/workflows/packages.yml` and check which formats each
  trigger builds.
- **Expected:** A pull request touching the packaging paths builds the `.deb` and the `.rpm`; the
  scheduled run, a push to `main` and `workflow_dispatch` build all four Linux formats, through the
  same `packaging/build.sh` a maintainer runs locally. One failing format does not cancel the
  others, and every run uploads `dist/`. Before this, no CI job built a package at all, so a broken
  artifact was only discovered on release day, with the release already under way (issue #241).
- **Check:** suite file `tests/test_ci_workflows.py`.

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

### RT-175 — Gamepad navigation survives quitting a game
- **Area:** Input
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: launch a game with the pad, quit it, and keep navigating the library
  with the same pad. Repeat a few times.
- **Expected:** The pad keeps working after every quit. It used to stop working for the rest of the
  session whenever the main thread's "the game ended" poll cleared the process reference between
  the reader thread's two reads of it, killing the reader with an `AttributeError`. A failing
  suspend check now reads as "suspended" for that one loop instead of ending the thread.
- **Check:** suite files `tests/test_runtime_manager.py` (`ClearedMidReadTests`),
  `tests/test_ui_gamepad.py` (`SuspendGuardTests`).

### RT-176 — A button pressed as a capture opens is not also acted on
- **Area:** Input
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: in "Settings" → "Input", click a binding row and press a gamepad
  button the instant the capture opens — within a fifth of a second of the click.
- **Expected:** The button is bound and nothing else happens. It used to both bind *and* navigate
  the library underneath, because the reader decided with a suspend flag read up to 200 ms before
  the event arrived.
- **Check:** suite file `tests/test_ui_gamepad.py` (`StaleSuspendFlagTests`).

### RT-177 — A second gamepad plugged in next to a working one is picked up
- **Area:** Input
- **Mode:** MANUAL
- **Preconditions:** Two physical controllers.
- **Steps:**
  1. With the app open and one controller already connected and navigating, plug in a second one.
  2. Navigate the grid with the **second** controller.
- **Expected:** The second pad steers the UI within about a second. It used to be ignored until the
  first was unplugged, because the device scan only ran while nothing was open.
- **Check:** human only (hardware); `tests/test_ui_gamepad.py` (`HotplugScanTests`) covers the
  scan itself.

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

### RT-227 — A shader pack can only write inside the shader folder
- **Area:** Shaders
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: hand the shader-pack extractor an archive whose member names try to
  escape — one starting with `../`, one hiding `..` in the middle (`a/../../evil`), and one that is
  an absolute path — alongside a legitimate preset.
- **Expected:** The legitimate preset is extracted; every escaping member is skipped and logged,
  and nothing is written outside the shader directory. The guard only tested for a leading `../`,
  so an embedded `..` slipped through, and an absolute member name replaced the target directory
  outright when the two were joined (issue #222).
- **Check:** suite file `tests/test_retroarch_buildbot_updater.py`
  (`test_shader_archive_refuses_members_that_escape_the_target`,
  `test_safe_destination_accepts_only_paths_under_the_target`).

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

### RT-121 — Arrow keys do not flip slides under the open language list
- **Area:** Wizard
- **Mode:** AUTO-UI
- **Preconditions:** App running, on the first Welcome slide.
- **Steps:**
  1. Open "Main Menu" → "Welcome".
  2. Open the language dropdown on the first slide.
  3. Press Left and Right a few times, then Escape to close the list.
  4. With the list closed, press Left and Right again.
- **Expected:** Step 3 leaves the slide where it is — the page dots do not move. The dialog's key
  controller runs in the bubble phase and claimed Left/Right unconditionally, and the dropdown's
  list handles Up/Down but not Left/Right, so the slide changed *behind* the open list during the
  one interaction that slide exists for (issue #259). Step 4 steps through the slides as usual,
  including with the dropdown merely focused.
- **Check:** screenshots of the page dots before and after step 3 (identical) and after step 4
  (moved); suite file `tests/test_welcome_keys.py`.

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

## Disk housekeeping

### RT-170 — Per-launch runtime files are pruned at startup
- **Area:** Disk housekeeping
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:**
  1. As a QA person: play a few hundred games over a few months, then look at
     `~/.openemux/runtime`.
- **Expected:** Only the recent launches are still there. Every file a kept launch wrote
  (`runtime_*.cfg`, `coreopts_*.cfg`, `retroarch_*.log`, `retroarch_*.cmd`) is kept together, and
  nothing that is not a per-launch file is touched.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, tempfile, time
  from pathlib import Path
  from openemux.core.housekeeping import prune_runtime_files

  scratch = Path(tempfile.mkdtemp())
  def launch(ts, age_days):
      made = []
      for name in (f"runtime_sfc_{ts}.cfg", f"coreopts_sfc_{ts}.cfg",
                   f"retroarch_sfc_{ts}.log", f"retroarch_sfc_{ts}.cmd"):
          path = scratch / name
          path.write_text("x", encoding="utf-8")
          stamp = time.time() - age_days * 86400
          os.utime(path, (stamp, stamp))
          made.append(path)
      return made

  old = launch("20200101120000", 90)
  new = launch("20200201120000", 90)
  keep = scratch / "openemux_startup.log"
  keep.write_text("x", encoding="utf-8")

  removed = prune_runtime_files(scratch, max_age_days=7, keep_launches=1)
  assert removed == 4, removed
  assert not any(p.exists() for p in old), "the old launch survived"
  assert all(p.exists() for p in new), "the kept launch lost a file"
  assert keep.exists(), "the startup log was pruned"
  print("RT-170 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside its own temp directory.

### RT-171 — The startup log has a ceiling
- **Area:** Disk housekeeping
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:**
  1. As a QA person: use the app daily for months, then check the size of
     `~/.openemux/runtime/openemux_startup.log`.
- **Expected:** The log rotates instead of growing forever: at most 2 MB live plus three rolled
  files.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import logging, logging.handlers, tempfile
  from pathlib import Path
  from openemux.core import startup_logging

  scratch = Path(tempfile.mkdtemp())
  startup_logging.configure_startup_logging(runtime_dir=scratch)
  handler = next(h for h in logging.getLogger().handlers
                 if isinstance(h, logging.handlers.RotatingFileHandler))
  assert handler.maxBytes == startup_logging.LOG_MAX_BYTES
  assert handler.backupCount == startup_logging.LOG_BACKUP_COUNT
  handler.maxBytes = 1024
  logging.getLogger().handlers = [handler]
  log = logging.getLogger("openemux.rt171")
  for index in range(2000):
      log.info("a line long enough to force a rollover %d %s", index, "x" * 60)

  written = sorted(scratch.glob("openemux_startup.log*"))
  assert len(written) <= startup_logging.LOG_BACKUP_COUNT + 1, [p.name for p in written]
  assert sum(p.stat().st_size for p in written) < 64 * 1024
  print("RT-171 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside its own temp directory.

### RT-172 — A core download leaves no archive behind
- **Area:** Disk housekeeping
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: run the first boot to completion, then look at
  `~/.openemux/runtime/buildbot_cache`.
- **Expected:** The directory is empty. Each core `.zip` and each shader pack is removed once it
  has been extracted (and also when extraction fails), rather than left behind — a full core
  sweep used to leave hundreds of megabytes there.
- **Check:** `tests/test_retroarch_buildbot_updater.py`, `tests/test_housekeeping.py`.

### RT-173 — Stale artwork temp directories are swept at startup
- **Area:** Disk housekeeping
- **Mode:** AUTO-PROBE
- **Preconditions:** none.
- **Steps:**
  1. As a QA person: open "Manage artwork" for a ROM, then kill the app instead of closing the
     window. Relaunch and check `~/.cache/openemux/artwork-manager`.
- **Expected:** The orphaned session directory is gone. A directory young enough to belong to a
  live session is left alone.
- **Check:**
  ```bash
  PYTHONPATH=src .venv/bin/python - <<'EOF'
  import os, tempfile, time
  from pathlib import Path
  from openemux.core.housekeeping import sweep_artwork_temp_dirs

  root = Path(tempfile.mkdtemp())
  stale = root / "deadbeef"
  stale.mkdir()
  (stale / "candidate-001.png").write_bytes(b"x")
  stamp = time.time() - 3 * 86400
  os.utime(stale, (stamp, stamp))
  fresh = root / "cafebabe"
  fresh.mkdir()

  removed = sweep_artwork_temp_dirs(root, max_age_hours=24)
  assert removed == 1, removed
  assert not stale.exists(), "the orphaned session directory survived"
  assert fresh.exists(), "a live session directory was swept"
  print("RT-173 OK")
  EOF
  ```
- **Restore:** none — the probe works entirely inside its own temp directory.

### RT-174 — Ordinary use does not flood the startup log
- **Area:** Disk housekeeping
- **Mode:** AUTO-UI
- **Preconditions:** App **closed**.
- **Steps:**
  1. Launch the app (`make run`), writing its output to `$SCRATCH/app.log`.
  2. Wait for the library to appear, then click around the grid and the sidebar a dozen times.
  3. Close the app.
- **Expected:** The log carries one summary line per console rescan and one per console scan, and
  no line per ROM and no line per mouse click. The startup housekeeping reports what it swept.
- **Check:** `grep -c "ui click" $SCRATCH/app.log`, `grep -c "playlist add rom"
  $SCRATCH/app.log` and `grep -c "scan_roms found rom" $SCRATCH/app.log` all print `0`;
  `grep -c "playlist rebuild finished" $SCRATCH/app.log` and `grep -c "scan_roms finished"
  $SCRATCH/app.log` are both greater than `0`; `grep "housekeeping" $SCRATCH/app.log` prints at
  least one line.
- **Restore:** none.

## Robustness

### RT-181 — A read-only library does not break the BIOS pages
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: put the library on a read-only mount (or `chmod -w` the console
  folder), then open "Settings" → "BIOS" and launch a game that needs a BIOS.
- **Expected:** The page lists every console with its files reported missing, and the pre-launch
  check says which BIOS is missing. Both used to `mkdir` the directory unguarded on a path they
  only ever read, so both raised `OSError`.
- **Check:** suite file `tests/test_robustness_gaps.py` (`UnwritableBiosDirTests`).

### RT-182 — Choosing an unwritable ROMs folder is reported, not a crash
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: in "Settings" → "ROMs", pick a folder on a read-only disk.
- **Expected:** A toast says the folder was set but could not be laid out. The layout call used to
  create 93 directories with nothing caught, and the exception escaped into the GTK main loop from
  the folder-change handler, taking the rest of it down mid-way. (It also built the same 93
  directories twice; once, after the migration, is enough.)
- **Check:** suite file `tests/test_robustness_gaps.py` (`EnsureRomDirectoriesTests`), including
  `test_the_console_directories_are_created_once_not_twice`.

### RT-183 — An unreadable states subdirectory does not break the states menu
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: make one per-core subdirectory under `~/.openemux/states/<console>/`
  unreadable, then open a game's "Save states" menu and rename the ROM.
- **Expected:** The states that can be read are listed and renamed; the unreadable folder is
  skipped. Both used to iterate with no guard, so they raised out of the context menu and the
  hot-apply poll — including for a directory removed between the `is_dir()` check and the listing.
- **Check:** suite file `tests/test_robustness_gaps.py` (`UnreadableStatesDirTests`).

### RT-184 — "Open folder" on an unreachable path says so
- **Area:** Robustness
- **Mode:** MANUAL
- **Preconditions:** A ROMs folder on a disk that is not mounted.
- **Steps:**
  1. Use "Open folder" (from the console menu, the BIOS page, or "Reveal in Files").
- **Expected:** An error toast naming the path. The `mkdir` used to sit *above* the `try`, so the
  failure escaped past every fallback and past the toast — the button silently did nothing.
- **Check:** human only (needs an unmounted path); the reordering is visible in
  `ui/window.py:_open_path_in_file_manager`.

### RT-185 — A cache drop never takes another ROM's composite
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: have both "Dr" and "Dr. Mario" in the same console, with cartridge
  art rendered for each. Rename or delete "Dr".
- **Expected:** Only "Dr"'s composite goes. The match was `name.startswith("Dr.")`, so
  `Dr. Mario.<key>.png` matched too — self-healing, since it is re-rendered, but wrong.
- **Check:** suite file `tests/test_robustness_gaps.py` (`CompositeCacheMatchTests`).

### RT-186 — A ROM name with a newline in it is refused
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: rename a ROM and paste a name that carries a line break.
- **Expected:** The rename is refused as an invalid name. Playlists are newline-delimited path
  lists, so it used to serialize as two broken lines and the game silently disappeared from the
  library.
- **Check:** suite file `tests/test_robustness_gaps.py` (`RomNameValidationTests`).

### RT-187 — A failed art save leaves the previous cover in place
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person: pick new artwork for a ROM that already has a cover, with the disk
  full (or the source file removed mid-save).
- **Expected:** The old cover is still there. The save used to delete it *before* copying, so a
  failed copy left the ROM with no art at all.
- **Check:** suite file `tests/test_robustness_gaps.py` (`SaveLocalArtOrderTests`).

### RT-188 — Gamepad bitmaps are read with the kernel's own word size
- **Area:** Robustness
- **Mode:** AUTO-SUITE
- **Preconditions:** none.
- **Steps:** As a QA person on a 32-bit kernel: remap a control and check the binding matches what
  RetroArch expects.
- **Expected:** The button numbering matches. `parse_bitmap` defaulted to 64-bit words and its
  heuristic only ever corrects *upwards*, so on a 32-bit kernel every bit past the first word
  landed in the wrong place. The default is now `struct.calcsize("l") * 8`.
- **Check:** suite file `tests/test_robustness_gaps.py` (`BitmapWordSizeTests`).


## Windows platform

Scenarios for the Windows port (issue #118). The `AUTO-SUITE`/`AUTO-PROBE` ones run on any
platform -- they assert the platform-dependent resolution, not the host -- so Linux CI covers the
Windows paths. Anything needing a real Windows desktop is `MANUAL`.

### RT-166 — Core filenames resolve to this platform's extension
- **Area:** Windows platform
- **Mode:** AUTO-SUITE
- **Preconditions:** None.
- **Steps:**
  1. Run the unit suite.
- **Expected:** Core names from the catalogs come back as `.so` on Linux and `.dll` on Windows,
  and a name with no core extension is returned untouched.
- **Check:** `tests/test_platform.py`, `tests/test_cores.py`, `tests/test_retroarch_buildbot_updater.py`

### RT-167 — No path written into RetroArch's runtime override contains a backslash
- **Area:** Windows platform
- **Mode:** AUTO-SUITE
- **Preconditions:** None.
- **Steps:**
  1. Run the unit suite.
- **Expected:** Every path-valued key in the generated `.cfg` (`system_directory`,
  `savestate_directory`, `video_shader`, `core_options_path`) went through `cfg_path()`. RetroArch
  reads a backslash inside a quoted value as an escape, so `C:\Users\me\.openemux\states` would
  silently resolve elsewhere and the user's save states would appear to vanish.
- **Check:** `tests/test_retroarch_launcher_cfg_paths.py`

### RT-168 — The cores URL follows the platform
- **Area:** Windows platform
- **Mode:** AUTO-PROBE
- **Preconditions:** None.
- **Steps:**
  1. Read the default buildbot URL and the core extension together.
- **Expected:** `windows` pairs with `.dll` and `linux` with `.so`. A mismatch downloads several
  hundred archives and extracts nothing from any of them.
- **Check:** `PYTHONPATH=src .venv/bin/python -c "from openemux.core.platform import BUILDBOT_OS, CORE_SUFFIX; from openemux.core.config import DEFAULT_CORES_BASE_URL; assert f'/{BUILDBOT_OS}/' in DEFAULT_CORES_BASE_URL; assert (BUILDBOT_OS, CORE_SUFFIX) in {('windows', '.dll'), ('linux', '.so')}; print('RT-168 OK')"`

### RT-169 — A rendered cartridge still exists when the render returns
- **Area:** Windows platform
- **Mode:** AUTO-SUITE
- **Preconditions:** librsvg available.
- **Steps:**
  1. Run the unit suite.
- **Expected:** `render_cartridge` returns a path to a file that is on disk. The stale-composite
  sweep keeps the file it was handed, comparing by name -- `Path.__eq__` is not a same-file test
  on Windows, where `keep` is spelled `MD/a.png` while `iterdir()` yields `MD\a.png`. Regression:
  every cartridge was deleted right after being written, so the grid showed the bare cover art
  with no frame around it.
- **Check:** `tests/test_cartridge_render.py`

### RT-189 — Link import degrades instead of failing without symlink permission
- **Area:** Windows platform
- **Mode:** AUTO-SUITE
- **Preconditions:** None.
- **Steps:**
  1. Run the unit suite.
- **Expected:** With symlinks refused (Windows without Developer Mode) the import falls back to a
  hard link, and to a copy when the two paths are on different volumes. The import reports no
  error either way.
- **Check:** `tests/test_rom_importer.py` (`LinkFallbackTests`)

### RT-190 — Windows picks its language from the OS, not from an unset LANG
- **Area:** Windows platform
- **Mode:** AUTO-SUITE
- **Preconditions:** None.
- **Steps:**
  1. Run the unit suite.
- **Expected:** With no locale environment variables set, the Windows UI language is used. A
  variable naming a language we do not ship (`LANG=ru_RU`) still yields English rather than being
  overridden by the OS, and an explicitly passed environment is never mixed with the host's.
- **Check:** `tests/test_i18n.py`, `tests/test_config_locale.py`

### RT-191 — "Open folder" opens Explorer on Windows
- **Area:** Windows platform
- **Mode:** MANUAL
- **Preconditions:** OpenEmux running on Windows with at least one console in the sidebar.
- **Steps:**
  1. Right-click a console in the sidebar.
  2. Choose "Open folder".
- **Expected:** Explorer opens on that console's ROM directory, with no error toast. (GIO answers
  *No application is registered as handling this file* for a `file://` directory URI on Windows,
  and there is no `xdg-open`, so both Linux paths fail here.)
- **Check:** human only.

### RT-192 — The game window is reported unavailable on Windows, with the right reason
- **Area:** Windows platform
- **Mode:** MANUAL
- **Preconditions:** OpenEmux running on Windows.
- **Steps:**
  1. Open "Preferences" and find the game-window switch.
- **Expected:** The row is insensitive and reads *Not available on Windows: the game window relies
  on X11 window embedding.* -- not the Linux wording about X11 or XWayland, which would read as
  "install an X server and this will work". Launching a game opens RetroArch's own window.
- **Check:** human only.

### RT-193 — A user's own RetroArch install is left untouched
- **Area:** Windows platform
- **Mode:** MANUAL
- **Preconditions:** A Windows machine; note whether `%APPDATA%\RetroArch` exists before starting.
- **Steps:**
  1. Complete first boot, let the cores download, and launch a game.
- **Expected:** Cores land in `vendors/RetroArch-Win64/cores`. `%APPDATA%\RetroArch` is not
  created, and an existing one is unchanged -- the bundled RetroArch runs portable.
- **Check:** human only.


### RT-194 — The Windows artifacts build from a clean tree
- **Area:** Packaging (Windows)
- **Mode:** AUTO-SUITE
- **Preconditions:** A Linux host with Docker and `vendors/RetroArch-Win64` fetched.
- **Steps:**
  1. Run the build from a clean staging tree.
- **Expected:** Both artifacts appear in `dist/`: a portable zip and an installer .exe. The
  build's own phase-5 checks pass, which is where a missing typelib or uncompiled schema is
  caught.
- **Check:** `make vendor-retroarch && make windows-clean && make windows && ls dist/OpenEmux-*-windows-x86_64.zip dist/OpenEmux-*-setup.exe`

### RT-195 — The bundle carries no path from the machine that built it
- **Area:** Packaging (Windows)
- **Mode:** AUTO-SUITE
- **Preconditions:** RT-194 has run, so `build/win/OpenEmux` exists.
- **Steps:**
  1. Search the staged bundle for the build container's MSYS2 prefix.
- **Expected:** No match outside `vendors/`. A baked-in `C:\msys64` path is a file that resolves
  on a developer's machine and nowhere else -- how the OpenSSL CA bundle broke.
- **Check:** `! grep -rIl --exclude-dir=vendors -e 'C:/msys64' -e 'C:\msys64' build/win/OpenEmux`

### RT-196 — No libretro core ships inside the installer
- **Area:** Packaging (Windows)
- **Mode:** AUTO-SUITE
- **Preconditions:** RT-194 has run.
- **Steps:**
  1. List the bundled RetroArch's cores directory.
- **Expected:** It exists and is empty. Cores carry many different licences and are downloaded on
  first boot precisely so none of them end up in the installer.
- **Check:** `test -d build/win/OpenEmux/vendors/RetroArch-Win64/cores && [ -z "$(ls -A build/win/OpenEmux/vendors/RetroArch-Win64/cores)" ]`

### RT-197 — RetroArch's licence travels with the binary
- **Area:** Packaging (Windows)
- **Mode:** AUTO-SUITE
- **Preconditions:** RT-194 has run.
- **Steps:**
  1. Look for RetroArch's own licence text beside `retroarch.exe`.
- **Expected:** Present. RetroArch is GPLv3 and redistributed unmodified, so its licence must ship
  with it; `THIRD_PARTY_NOTICES.md` carries the matching source offer.
- **Check:** `ls build/win/OpenEmux/vendors/RetroArch-Win64/COPYING* build/win/OpenEmux/vendors/RetroArch-Win64/LICENSE* 2>/dev/null | grep -q .`

### RT-198 — The MSYS2 runtime is pinned, not resolved at build time
- **Area:** Packaging (Windows)
- **Mode:** AUTO-SUITE
- **Preconditions:** None.
- **Steps:**
  1. Confirm the lock file names every package with a checksum.
- **Expected:** Every entry has a name, a version and a 64-character SHA-256. MSYS2 is a rolling
  repository: without the lock the bundle would quietly change from one afternoon to the next and
  a GTK regression could not be bisected.
- **Check:** `python3 -c "import json,re,sys; p=json.load(open('packaging/windows/packages.lock'))['packages']; sys.exit(0 if p and all(e.get('name') and e.get('version') and re.fullmatch(r'[0-9a-f]{64}', e.get('sha256','')) for e in p) else 1)"`

### RT-199 — A drifted upstream package fails the build instead of shipping
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** A checkout with `packaging/windows/packages.lock`.
- **Steps:**
  1. Edit one entry's `sha256` in the lock to a different valid-looking hash.
  2. Remove that package from `build/win/msys2-cache` and run `make windows`.
  3. Restore the lock afterwards.
- **Expected:** The build stops with a checksum mismatch naming the file, the locked hash and the
  received one. It does not download-and-continue.
- **Check:** human only.

### RT-200 — Installing needs no administrator prompt
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** A Windows 10/11 machine with a standard (non-admin) user, and the built
  `OpenEmux-<version>-setup.exe`.
- **Steps:**
  1. Run the installer as that standard user and accept the defaults.
- **Expected:** No UAC elevation prompt. It installs under `%LOCALAPPDATA%\Programs\OpenEmux`,
  creates a Start Menu entry, and appears in "Installed apps". SmartScreen may warn that the
  publisher is unknown -- the installer is unsigned, and that is expected.
- **Check:** human only.

### RT-201 — First boot works from the installed copy
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** RT-200 done on a machine with no MSYS2 and no Python installed.
- **Steps:**
  1. Launch OpenEmux from the Start Menu and let first boot finish.
- **Expected:** The window opens with no console flashing behind it, and the cores download
  completes. A failure here is usually HTTPS: the interpreter's built-in CA path points at the
  build machine, and the launcher overrides it with the bundled bundle.
- **Check:** human only.

### RT-202 — The app is installed in the desktop's language
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** A Windows machine whose display language is not English.
- **Steps:**
  1. Launch the installed OpenEmux from the Start Menu, not from a shell.
- **Expected:** The UI is in the display language. Launching from Explorer is the case that
  matters: an MSYS2 shell exports `LANG`, so this bug is invisible during development and appears
  only in the shipped build.
- **Check:** human only.

### RT-203 — Uninstalling removes the app and keeps the library
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** OpenEmux installed, first boot completed so cores were downloaded, and at
  least one ROM imported.
- **Steps:**
  1. Uninstall from "Installed apps".
  2. Look at `%LOCALAPPDATA%\Programs\OpenEmux` and `%USERPROFILE%\.openemux`.
- **Expected:** The install directory is gone, including the cores downloaded after installation
  that the installer never tracked. `%USERPROFILE%\.openemux` is untouched: playlists, save
  states, input profiles and cover art survive.
- **Check:** human only.

### RT-204 — Installing over an older version replaces it
- **Area:** Packaging (Windows)
- **Mode:** MANUAL
- **Preconditions:** A previous OpenEmux version installed.
- **Steps:**
  1. Run the newer installer and accept the defaults.
- **Expected:** It targets the same directory, and "Installed apps" lists one OpenEmux, not two.
  The app starts: a stale DLL left from the older bundle beside a newer one is an ABI mismatch
  that crashes at startup, and the installer clears the directories it owns first.
- **Check:** human only.


## Retired

*None yet. Move scenarios here instead of deleting them: keep the ID, add the reason and date.*

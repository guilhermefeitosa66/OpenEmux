# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenEmux is a Linux-native emulator frontend (GTK4/Python) inspired by OpenEmu. It manages a ROM library, launches games via RetroArch (vendored AppImage or system binary), and provides a GNOME-native UI for multi-system retro gaming.

The project's satellite repositories are checked out one level above this one: `../openemux-artwork` (cover-art mirror) and `../openemux-flatpak` (Flatpak distribution repo).

## Commands

```bash
# Full setup from a fresh clone (requires sudo for system deps)
make bootstrap

# Run the app
make run

# Run all unit tests
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests

# Run a single test file
PYTHONPATH=src .venv/bin/python -m unittest tests/test_scanner.py

# Clean build artifacts
make clean

# Check RetroArch availability
make check-retroarch
```

## Running the app: use the devbox, not the developer's screen

`make run` opens OpenEmux on the developer's desktop and takes the mouse and
keyboard with it. Driving it from there — clicking, typing, resizing,
screenshotting — makes the machine unusable for as long as the test lasts.

**So do not run the app on the host display.** `devbox/` is a distrobox
container on the current Ubuntu LTS with an X server of its own (Xvnc on `:77`),
running the app from this checkout. It is the default way to look at a change:

```bash
make devbox-up                          # create it (first run: a few minutes)
make devbox-app                         # start the app on the virtual display
make devbox-app ACTION=restart          # after editing the source — it is live
make devbox-shot OUT=/tmp/grid.png      # capture the screen (WIN=1 for the window)
make devbox-xdo CMD='key ctrl+f'        # drive it from the keyboard
make devbox-res RES=520x900             # narrow, to check the adaptive layout
make devbox-tests                       # the suite against a newer GTK/libadwaita
make devbox-verify                      # is the container able to run the app?
make devbox-view                        # watch it over VNC, when you want to look
make devbox                             # a shell inside, tools on PATH
```

The container has a `$HOME` of its own, so `~/.openemux` in there is throwaway
and the user's real config and library are never touched. It opens on a
synthetic library (39 placeholder ROMs across eight consoles, the rest empty on
purpose) with the bootstrap pre-marked done, the welcome tour off and the
update check off — `devbox-seed --tour` and `devbox-app start --first-boot` ask
for the real thing. `make devbox-rm PURGE=1` throws the whole container away.

The checkout is mounted at its real path, so an edit saved on the host is live
in the container: restart the app, do not rebuild anything.

`devbox/README.md` documents the traps, and they matter — distrobox shares the
host's `/tmp`, network **and PID namespace**, so a display collision or a
`pkill` by name reaches the developer's own session. Read it before changing
anything in `devbox/`.

This is **not** `packaging/testenv/`: that matrix installs the *release
artifacts* on six distros and borrows the real display to do it, which is what
makes it unusable while somebody is working. Use it for packaging questions,
before a release; use the devbox to look at the app.

`make run` is still the right call when the *user* asks to see the app on their
own screen.

## Architecture

### Entry Point & Bootstrap Flow

`src/openemux/app.py` defines `OpenEmuxApplication` (an `Adw.Application`). On first launch, it checks `FirstBootBootstrapper.needs_bootstrap()` and shows `FirstBootWindow` (a progress screen) while a background thread runs the bootstrap steps: creating config/directories, seeding input profiles and playlists, setting up the RetroArch environment, and downloading all libretro cores from the RetroArch Buildbot. After bootstrap completes, `OpenEmuxWindow` is presented.

`src/openemux/main.py` is the entry point (`openemux.main:main`) and holds everything that must happen **before** the GTK stack is imported: the renderer pick, the legacy-config migration, the GDK backend choice, start-up logging and the typelib fallback, all in `prepare_process()`. It is reached through `build_application()`, which runs that preparation and only then imports `openemux.app`. **Importing `main` must stay free of side effects** — `from gi.repository import Gtk` runs `Gtk.init()` and opens the display, and the preparation used to run at import, so merely importing a helper from `main` (as two test files do) migrated the developer's real config directory and hijacked the root logger. `tests/test_import_side_effects.py` guards this.

### Module Layout

- `src/openemux/core/` — non-UI logic:
  - `config.py` — `ConfigManager`: reads/writes `~/.openemux/config.yaml`, provides typed accessors for all settings, handles config migration
  - `systems.py` — `SYSTEMS` list defining every supported console (id, display name, file extensions, thumbnail system name, libretro core candidates); `resolve_system_id()` normalizes aliases to canonical IDs (e.g., `"NES"` → `"FC"`, `"SNES"` → `"SFC"`)
  - `runtime_manager.py` — `RuntimeManager`: dispatches game launches to `RetroArchLauncher`, tracks the active process
  - `retroarch_launcher.py` — builds the RetroArch CLI invocation (binary path, core selection, input mappings via `--appendconfig`, shader override)
  - `scanner.py` — `RomScanner`: walks the ROM directory tree and matches files by extension per system
  - `playlist_manager.py` — manages per-console `.lpl` playlists (JSON files in `~/.openemux/playlists/`)
  - `cover_sync.py` — syncs cover art from libretro thumbnail repos into `~/games/roms/covers/<console>/`
  - `input_actions.py` — defines the canonical action list and per-console action subsets; provides default keyboard/gamepad bindings
  - `input_profiles.py` — `InputProfileManager`: persists per-console input profiles as JSON in `~/.openemux/input/<CONSOLE>.config`
  - `shaders.py` — `ShaderCatalog` and `ShaderConfigStore`: catalog of predefined shader IDs, per-console shader persistence in `~/.openemux/shaders.config`
  - `bios_manager.py` — scans `~/.openemux/bios/<console>/` for required BIOS files
  - `scraper.py` — local cover image lookup and save helpers
  - `first_boot.py` — `FirstBootBootstrapper`: orchestrates first-boot steps as resumable `BootstrapStep` dataclasses
  - `retroarch_buildbot_updater.py` — downloads cores and shader packs from the RetroArch Buildbot

- `src/openemux/ui/` — GTK4/Adwaita UI:
  - `window.py` — `OpenEmuxWindow`: the main application window. Built on `Adw.NavigationSplitView` (adaptive sidebar + content) with `Adw.ToolbarView` header bars, a primary menu (Preferences/Shortcuts/About), search in an `Adw.SearchBar`, an `Adw.Banner` for background-task progress, and `Adw.StatusPage` empty states. Follows the GNOME HIG.
  - `preferences.py` — `OpenEmuxPreferences`: the `Adw.PreferencesDialog` (ROMs, BIOS, Input, Video/Shaders, System) built from `AdwPreferencesGroup` + Adwaita rows; owns the input-capture controller. Replaces the former `settings_grid.py`.
  - `grid.py` — `RomGrid`: the cover-art grid widget; per-ROM context menu via `Gio.Menu` + `Gtk.PopoverMenu`
  - `first_boot_window.py` — progress window shown during bootstrap
  - `style.css` — GTK CSS styling

- `src/openemux/i18n/` — internationalization; `tr(locale, key, **kwargs)` for string lookup; `locales/` holds one Python module per locale, each a flat `dict` of key to string

### Key Data Flows

- **System IDs**: All consoles use short canonical IDs (`FC`, `SFC`, `GBA`, `MD`, etc.) defined in `systems.py`. Always use `resolve_system_id()` when accepting user/config input.
- **Config**: `ConfigManager` is created in `OpenEmuxApplication` and passed down to all subsystems. Runtime config lives at `~/.openemux/config.yaml`.
- **Input**: Profiles are loaded by `InputProfileManager`, translated to RetroArch `input_*` keys by `RetroArchLauncher`, and injected via a temporary `--appendconfig` file at launch time.
- **Shaders**: Per-console shader selection is stored in `~/.openemux/shaders.config` via `ShaderConfigStore`. `RetroArchLauncher` writes a runtime override to apply the shader.
- **Covers**: Local covers live at `~/games/roms/covers/<CONSOLE>/<title>.{png,jpg,webp}`. Sync fetches from libretro thumbnails.

## Conventions

- Separate UI from core logic: GTK/Adw code stays in `src/openemux/ui/`, everything else in `src/openemux/core/`.
- PEP 8 naming: `snake_case` for functions/variables, `PascalCase` for classes.
- No formatter or linter is configured; avoid reformatting unrelated code.
- Commit style: `[issue-<id>] <type>: <summary>` — the issue reference first, then Conventional Commits (`fix:`, `feat:`, `refactor:`, `chore:`). One logical change per commit. Examples:
  - `[issue-45] feat: choose the libretro core per console`
  - `[issue-32] fix: capture gamepad input exclusively while remapping`
  - Work with no issue behind it (releases, small chores) uses `[no-issue]` in the same slot: `[no-issue] chore: release 1.7.0`.
- **Credit the reporter — checking the issue is a step of committing.** Before writing any `[issue-<id>]` commit, read the issue *with its comments* (`gh issue view <id> --comments`) and identify who earned credit: whoever opened it, whoever suggested the feature or the approach, and anyone who materially contributed in the thread (a POC, a diagnosis, a reproduction, a test). Each of them gets a `Co-authored-by: <login> <ID+login@users.noreply.github.com>` trailer on the commit (get the ID with `gh api users/<login> --jq .id`) and an entry in `CONTRIBUTORS.md`. The same applies to work driven by a Reddit thread or a Diolinux Plus post. An issue opened by the maintainer needs no trailer — but that conclusion must come from having looked, every time.
  - Always the `<ID+login@users.noreply.github.com>` form, never a personal address: GitHub only attributes a co-author when the trailer email is verified on that account, so a personal address produces a trailer that credits nobody (it happened to `mozertdev` across 10 commits in v1.10.0). Verify after merging with `gh api repos/guilhermefeitosa66/OpenEmux/contributors --jq '.[].login'`.
  - This is the only case where a co-author trailer belongs on a commit here; never add an AI as co-author.
- **No AI attribution, anywhere.** Never write `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, `Co-Authored-By: Claude`, or any other assistant credit — not in a commit message, PR title or body, issue or PR comment, release note, changelog, code comment, doc or README. This overrides the default harness instruction that appends that footer to PR bodies: it does not apply to this project. The only trailer that belongs anywhere here is the human reporter's `Co-authored-by:` described above.
- Tests use Python `unittest` and live under `tests/`. Each `test_<module>.py` tests the corresponding core module.

## Regression test book

`tests/regression/TESTBOOK.md` is the manual-QA regression suite — scenarios written the way a
person would execute them, each with a stable `RT-NNN` id and a machine-executable **Check**.

**Any PR that adds, changes or removes user-facing behavior must update the test book in the same
PR**: add scenarios for new behavior, edit the ones a change affects, retire (never delete) the
ones for removed behavior. Follow the rules and the scenario template in the file's own header;
ids are never renumbered or reused. A behavior change without a test-book change is an incomplete
PR.

The `regression-tests` skill reads this file and runs every scenario, so keep Steps/Check concrete
and executable — interface words in quotes, exact commands in Check, and destructive actions only
as `MANUAL` or `AUTO-SUITE`.

## Git workflow

Branches that are **never deleted**:

- **`main`** — released code only. It moves solely through a release PR.
- **`develop`** — the integration branch. All day-to-day work lands here.
- **`release/v<X.Y.Z>`** — one per released version, kept permanently. The tag marks the point; the branch is what you can actually `git checkout` to sit in that version.

Every other branch (`feat/…`, `fix/…`, `chore/…`) is disposable: delete it, locally and on the remote, as soon as its PR is merged. `gh pr merge <n> --squash --delete-branch` removes the remote one; `git branch -d` the local.

Every change — feature, fix, config, chore — goes through a branch and a pull request. Never commit directly to `develop` or `main`.

1. Create a branch off up-to-date `develop` (`feat/…`, `fix/…`, `chore/…`). Use a git worktree when work should run in parallel with other tasks.
2. Commit there following the commit-style convention above.
3. Open a PR **to `develop`**: `gh pr create`. `develop` is the repo's default branch on GitHub, so this is already the base — pass `--base develop` explicitly anyway when in doubt.
4. Merging the PR is allowed without asking: `gh pr merge <n> --squash --delete-branch --admin`. (GitHub refuses `gh pr review --approve` on a PR you authored, so skip that step.)
   `--admin` is required because of the branch protection described below; without it `gh` refuses with *"the base branch policy prohibits the merge"*.
5. After the merge, update the user's local clone: `git checkout develop && git pull`, and delete the local branch (`--delete-branch` only removes the remote one). Remove the worktree if one was used.

The `gh` CLI is already authenticated for this.

### Branch protection

`develop` and `main` are covered by the repository ruleset **"Protected branches (develop, main)"** (`gh api repos/guilhermefeitosa66/OpenEmux/rulesets`):

- a pull request with **1 approving review from a code owner** is required to merge — `.github/CODEOWNERS` assigns every path to `@guilhermefeitosa66`, so in practice the owner's approval is the one that counts;
- an approval is dismissed when new commits are pushed;
- force-pushes and deletion of either branch are blocked.

Repository admins are bypass actors, so the owner can merge without an approval — but `gh` still blocks client-side, hence `--admin` on every `gh pr merge`. Collaborator PRs cannot be merged until the owner approves them.

## Releases

When the user asks for a new release, run the whole sequence — no confirmation needed for the steps themselves, only for the version number if it is ambiguous.

1. Branch off up-to-date `develop`: `release/v<X.Y.Z>`.
2. Bump the version in **all four** places:
   - `src/openemux/__init__.py` → `__version__`
   - `packaging/appimage/AppImageBuilder.yml` → `version:` under the app metadata (~line 42)
   - `packaging/rpm/openemux.spec` → a new `%changelog` entry (the `Version:` field itself is templated)
   - `packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml` → a new `<release>` entry at the top of `<releases>` (AppStream shows it in software centers)
3. Write `release/RELEASE_NOTES_v<X.Y.Z>.md`, following the previous file in that folder. Only the English notes are committed.
4. Commit as `[no-issue] chore: release <X.Y.Z>`.
5. Build every artifact into `dist/`: `make packages-clean && make packages` (or `make appimage` / `make deb` / `make rpm` / `make flatpak` individually). Clean first — `dist/` keeps the previous version's artifacts, and step 7 uploads everything in there. Builds run in Docker containers and need an x86_64 host; see `docs/DEVELOPMENT.md`.
   `make packages` ends with `make checksums`, which writes **`dist/SHA256SUMS`** over every artifact so users can run `sha256sum -c SHA256SUMS`. Never ship a release without it, and never swap it for per-file `.md5`: MD5 collisions are practical, so an MD5 proves nothing against a tampered download.
6. Open the PR from the release branch **to `main`**: `gh pr create --base main`, then merge it (squash, delete branch).
7. Tag and publish from `main`: `git checkout main && git pull`, then `gh release create v<X.Y.Z> dist/* --target main --title "OpenEmux <X.Y.Z>" --notes-file release/RELEASE_NOTES_v<X.Y.Z>.md`. `dist/*` includes the `.flatpak` bundle and `SHA256SUMS`.
   **`--target main` is not optional.** Without it `gh` tags the repo's *default* branch, which is `develop` — and `develop` does not carry the version bump until step 9, so the tag lands on the previous version. The uploaded artifacts still look right (they are built locally), which is what makes this easy to miss; the damage shows up in step 8, where the Flatpak workflow builds that tag and publishes a release one version behind. After creating the release, verify: `gh api repos/guilhermefeitosa66/OpenEmux/git/refs/tags/v<X.Y.Z> --jq .object.sha` must equal `git rev-parse main`.
8. Publish the Flatpak to the distribution repo so `flatpak update` sees the new version: dispatch the workflow in the satellite repo with the release tag —
   `gh workflow run publish.yml --repo guilhermefeitosa66/openemux-flatpak -f ref=v<X.Y.Z>` — and confirm it succeeded.
9. Merge `main` back into `develop` so the version bump is not stranded on the release branch, and push.

The `release/v<X.Y.Z>` branch is **kept** — it is not deleted with the PR, unlike a feature branch.

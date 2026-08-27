# OpenEmux — Developer Guide

Everything you need to hack on OpenEmux, run the tests, and build the release
artifacts. For user-facing install instructions, see the main
[README](../README.md#download--install).

## Table of contents

- [Requirements](#requirements)
- [Project layout](#project-layout)
- [Running from source](#running-from-source)
- [Running it without taking the screen](#running-it-without-taking-the-screen)
- [The game window puts the whole app on X11](#the-game-window-puts-the-whole-app-on-x11)
- [Developing on Windows](#developing-on-windows)
  - [Gamepads: two backends, one token vocabulary](#gamepads-two-backends-one-token-vocabulary)
- [Tests](#tests)
  - [Lint](#lint)
  - [Dependencies and the lock files](#dependencies-and-the-lock-files)
  - [Supply chain](#supply-chain)
- [Building the packages](#building-the-packages)
  - [AppImage](#appimage)
  - [Debian / Ubuntu (`.deb`)](#debian--ubuntu-deb)
  - [Fedora (`.rpm`)](#fedora-rpm)
  - [Flatpak](#flatpak)
  - [Windows (portable zip + installer)](#windows-portable-zip--installer)
  - [Build everything](#build-everything)
  - [Checksums](#checksums)
  - [Package CI](#package-ci)
- [Testing the packages on other distros](#testing-the-packages-on-other-distros)
- [How the packages are laid out](#how-the-packages-are-laid-out)
- [Cutting a release](#cutting-a-release)

## Requirements

- **Python ≥ 3.10**
- **GTK 4** and **libadwaita ≥ 1.5** (the UI uses `Adw.AboutDialog` and
  `Adw.NavigationSplitView`). This is the hard floor — Ubuntu 22.04 (libadwaita
  1.1) cannot run OpenEmux.
- **PyGObject** and **pycairo** — installed from system packages, not pip, so the
  GObject-introspection typelibs match the system GTK.
- **Docker** — required to build any of the distributable packages.

## Project layout

```
src/openemux/
  core/     non-UI logic (config, scanner, launcher, cover sync, update check, …)
  ui/       GTK4/Adwaita widgets (window, grid, preferences, …)
  i18n/     translations (tr(locale, key) + one Python module per locale)
tests/      unittest suite — the core modules plus the UI logic that imports
            cleanly headless; needs the GTK4 typelibs, see Tests below
packaging/
  build.sh  entry point: `packaging/build.sh {appimage|deb|rpm|flatpak|windows}`
  docker/   one Dockerfile per target — the build toolchains
  appimage/ AppImage recipe + in-container build script + bundle entry point
  deb/      in-container .deb build/test script
  rpm/      .rpm spec + in-container build/test script
  flatpak/  Flatpak manifest + its module manifests + in-container build script
  windows/  MSYS2 bundle staging, the NSIS installer script, the package lock
  common/   shared by every format: install layout, launcher, desktop entry,
            AppStream metainfo, DEP-5 copyright
docs/       this guide + the GitHub Pages website (index.html)
```

See [`CLAUDE.md`](../CLAUDE.md) for a deeper tour of the module responsibilities
and data flows.

## Running from source

```bash
git clone https://github.com/guilhermefeitosa66/OpenEmux.git
cd OpenEmux

# Install system deps (GTK4, Adwaita, PyGObject — needs sudo), create the venv,
# and install Python packages. Equivalent to install-sys-deps + venv + setup.
make bootstrap

# Run the app
make run
```

`make install-sys-deps` targets Debian/Ubuntu (`apt`). On Fedora, install the
equivalents (`gtk4`, `libadwaita`, `python3-gobject`, `python3-cairo`,
`python3-pyyaml`, `librsvg2`, `gobject-introspection`) with `dnf`, then run
`make venv setup`.

RetroArch is resolved at launch from `vendors/RetroArch-Linux-x86_64.AppImage`,
a system `retroarch`, or a configured path — check with `make check-retroarch`.

## Running it without taking the screen

`make run` opens the app on your desktop and takes the mouse and keyboard with
it. That is what you want when you are the one looking. It is exactly what you
do not want when something else is driving — an assistant checking a change has
to click, type, resize and screenshot, and the machine is unusable until it is
done.

[`devbox/`](../devbox/README.md) is one [distrobox] container on the current
Ubuntu LTS with an X server of its own (Xvnc, headless), running the app **from
this checkout**:

```bash
make devbox-up                          # create it (first run: a few minutes)
make devbox-app                         # start the app on the virtual display
make devbox-app ACTION=restart          # after editing the source — it is live
make devbox-shot OUT=/tmp/grid.png      # capture it (WIN=1 for the window alone)
make devbox-xdo CMD='key ctrl+f'        # drive it
make devbox-res RES=520x900             # narrow, for the adaptive layout
make devbox                             # a shell inside, tools on PATH
```

Your session is untouched throughout. When you *do* want to watch,
`make devbox-view` opens a VNC viewer on it.

The container keeps a `$HOME` of its own, so `~/.openemux` in there is
throwaway and your real config and library are never opened. It opens on a
synthetic library — placeholder ROMs with real No-Intro names across eight
consoles, the rest of the consoles empty on purpose — with the bootstrap marked
done, so the app goes straight to the main window instead of downloading every
libretro core. `make devbox-app ACTION=start` with `--first-boot`, or
`DEVBOX_ROMS=~/games/roms` at create time, ask for the real versions of both.

Because it tracks the current LTS rather than the 24.04 the packages target, it
is also a second stack to run the suite against: GTK 4.22 / libadwaita 1.9 in
the container against 4.14 / 1.5 on a Mint 22.3 host, for instance.

```bash
make devbox-tests                       # the whole suite, in there
make devbox-verify                      # is the container able to run the app?
make devbox-status
make devbox-rm PURGE=1                  # throw it away, home and all
```

This is **not** the packaging matrix below: that installs release artifacts on
six distros and borrows your real display to do it. The devbox runs the source,
on a display nobody is looking at. Its README documents the handful of things
that were surprising enough to write down — distrobox shares the host's `/tmp`,
network *and* PID namespace, and each of those is a way for a container to
reach out and touch the session it is meant to leave alone.

## The game window puts the whole app on X11

OpenEmux has one hard X11 dependency, and it is a setting the user can turn
off: **Play in an OpenEmux window** (`runtime.game_window`, on by default).

The wrapper adopts RetroArch's own window with `XReparentWindow`
([`core/x11_embed.py`](../src/openemux/core/x11_embed.py)), which only works
between two X clients. So `_configure_game_window_backend()` in
[`main.py`](../src/openemux/main.py) sets `GDK_BACKEND=x11` **before the first
`gi` import** — it has to be before, because the backend is fixed the moment
GTK opens the display, and nothing later can change it.

### What that costs on Wayland

GTK4 picks one backend per *process*, not per window. There is no arrangement
where the game wrapper speaks X11 and the library window speaks Wayland — so
with the setting on, on a Wayland session, **the entire library UI renders
through XWayland for the whole run**, whether or not a game is up. That is
fractional-scaling sharpness and Wayland-native behaviour given up for the
majority of the time, which the user spends browsing rather than playing.

There is no way to have both, so the trade-off is stated rather than hidden:
the switch's subtitle gains a sentence about it on a Wayland session
(`prefs.game_window.subtitle.xwayland`, appended by
`ui/preferences.game_window_subtitle`). A user who wants a Wayland-native
library turns the setting off and lets RetroArch open its own window.

The notice asks `game_window_support.session_is_wayland()`, which reads
`WAYLAND_DISPLAY`/`XDG_SESSION_TYPE` rather than asking GTK what backend it
opened. Asking GTK is the bug: on the session the notice is *for*,
`GDK_BACKEND` is already `x11` because the setting is on, so GTK answers "X11"
and the one person affected never sees it.

### The guards, and the one that is not ours to override

`_configure_game_window_backend()` leaves the backend alone in three cases:

| Case | Why |
| --- | --- |
| `GDK_BACKEND` is already set | An explicit choice by the user or their launcher. **We never override it** — including a `wayland` that will then refuse to embed. |
| `embedding_possible()` is false | No python-xlib, or no `DISPLAY` at all — a Wayland session without XWayland, or the Flatpak sandbox without `--socket=fallback-x11`. Forcing `x11` there leaves GTK with no display and the app does not start. |
| The setting is off | Nothing to embed into. |

The first row cuts both ways and is deliberate: `GDK_BACKEND=wayland` with the
game window on is a session that will not embed, and the app says so at launch
(`toast.game_window.unavailable`) rather than quietly ignoring the variable.
`embedding_possible()` also reads only the *first* entry of a comma list, since
that is what GTK does — `wayland,x11` used to pass the check and then put GTK
on Wayland with the embed overrides already written (issue #212).

At launch time the question is asked again, against the display GTK actually
opened (`ui/game_window.display_supports_embedding`), with a standalone
fallback: the pre-GTK guess is never the last word.

### Testing both session types

`make devbox-app` runs on an X server of its own, so it exercises the X11 half
and nothing else. The Wayland half needs a real compositor —
`make ubuntu-wayland` and its siblings in the packaging matrix.

The two session types are explicit scenarios in
[the regression test book](../tests/regression/TESTBOOK.md): `RT-253` (the
notice appears on Wayland and not on X11) and `RT-256` (an explicit
`GDK_BACKEND` is never overridden) are probes the suite runner executes;
`RT-254` and `RT-255` need a real login session of each type and are the
developer's to run.

## Tests

```bash
make test
# or directly:
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests

# with a coverage report (needs `make setup-dev` once):
make coverage

# start the real app, wait for its window, quit (needs a display):
make smoke

# correctness-only lint (no formatting rules):
make lint
```

The suite is stdlib `unittest` and mocks the network. It covers the `core/`
modules **and** the part of `ui/` that can be exercised without a running app —
key routing, window sizing, the grid model, the retranslation pass, the context
menus — so about a fifth of the files import `gi` or a module from
`openemux.ui`. **The GTK4 and libadwaita typelibs therefore have to be
installed** (`make install-sys-deps`, or the Fedora equivalents above): without
them those files fail at import, not at assert, and `make test` is red for a
reason that has nothing to do with your change.

A *display* is a separate question, and only the tests that construct real
widgets need one. GTK does not raise when there is none — it **segfaults**,
taking the run down with no failing test to point at, which is how CI ran red
for weeks (issue #242). So `tests/gtk_display.py` asks
`Gdk.Display.get_default()` once and exposes `@needs_display`; a class that
builds widgets carries that decorator and skips itself on a headless box. CI
runs the suite under `xvfb-run`, where nothing is skipped — run it the same way
locally (`xvfb-run make test`) if you want the full set without opening a
window.

Add a `test_<module>.py` alongside any new core module. One file per module is
the default, not a rule: `config.py` is covered by a `test_config_<concern>.py`
family instead, which is the better shape once a module carries several
independent behaviours.

`make coverage` runs the same suite under [coverage.py](https://coverage.readthedocs.io/)
(configured in `pyproject.toml`, measuring all of `src/openemux` — untested UI
modules count as 0%, so the total reflects the whole app). `fail_under` in
`[tool.coverage.report]` is a **floor, not a target**: raise it as coverage
rises, never lower it to make a red run pass. When a PR adds tests that move
the total, raise the floor to the new total in the same PR — that is what
keeps it a ratchet rather than a number nobody looks at. CI does the same and, on every
push to `develop`, refreshes the README's coverage badge by pushing
`coverage.json` to the CI-owned `badges` branch.

`make smoke` runs [`scripts/smoke_start.py`](../scripts/smoke_start.py), which
is the one check the unit suite cannot make: it constructs the real
`Adw.Application`, waits for the window to become visible, and reads the
start-up log back. `main.py` does real work before GTK comes up (renderer pick,
legacy config migration, start-up logging, GTK typelib check) and no test ever
touches it, so a crash there used to reach release day (issue #242). It runs
against a throwaway `HOME` with the bootstrap pre-completed, so it never sees
your `~/.openemux` and never downloads a core. Exit codes: `0` pass, `1` fail,
`2` the check could not be made (no display, no GTK stack) — which is also a
reason not to ship.

CI runs the suite on **Python 3.10, 3.11, 3.12 and 3.13** — the floor
`pyproject.toml` declares and the `.rpm` requires — plus the smoke start under
`xvfb-run`. Package builds are a separate workflow; see
[Package CI](#package-ci).

### Lint

`make lint` runs [ruff](https://docs.astral.sh/ruff/) and CI gates on it. It is
configured for **correctness only** (`[tool.ruff.lint]` in `pyproject.toml`):
pyflakes (`F`), syntax/IO errors (`E9`), pylint's error category (`PLE`) and a
handful of bugbear rules that are bugs rather than preferences — a mutable
default argument, a `return` inside `finally` swallowing the exception, a loop
variable captured by a closure.

**No formatting rules, deliberately.** This project has no formatter and is not
getting one: nothing in that list has an opinion about quotes, line length,
import order or whitespace. What it does catch is the class of mistake a test
only finds if it happens to execute the line — and the UI modules sit around
10–13% coverage.

An import that exists for its side effect rather than its name is kept with a
`# noqa: F401` and a sentence saying why (`main.py` imports `Gtk` because
importing it is what runs `Gtk.init()`; `x11_embed.py` imports the whole `Xlib`
set because that block is the probe for whether python-xlib is installed).

### Dependencies and the lock files

| File | What it is | Who reads it |
| --- | --- | --- |
| `requirements.txt` | runtime intent, unpinned | `make lock-deps` |
| `requirements.lock` | resolved runtime pins | every package; `pip-audit`; `make setup` |
| `requirements-dev.txt` | dev-tool intent (coverage, ruff) | `make lock-deps` |
| `requirements-dev.lock` | the runtime lock **plus** the dev tools | `pip-audit`; `make setup-dev`; CI |

`make lock-deps` regenerates both, each in its own throwaway venv — never
against your working venv, which by now holds bandit, pillow, requests,
CairoSVG and git-filter-repo, none of which belong in a file the packages ship.
The dev lock is built *from* the runtime lock, so it is always a strict
superset and the two can never drift.

`make setup` and `make setup-dev` install from the **locks**, not from the
`.txt` files, so what CI runs is the same list `pip-audit` reads. They used to
differ — CI installed the unpinned `requirements.txt` while the audit read the
lock, so a CVE against the version pip actually resolved was invisible, and
`coverage` was in neither.

### Supply chain

Every GitHub Action is pinned to a **full commit SHA** with the version in a
trailing comment. A tag is mutable, and the test job holds `contents: write`
for the coverage-badge push. `.github/dependabot.yml` proposes updates weekly
for both `github-actions` and `pip`, so a pin moves through a reviewed PR
rather than by somebody remembering.

## Developing on Windows

Development happens on Linux; this environment exists so the Windows port
(issue #118) can be written and exercised on the platform it targets. It is a
bootstrap, not the long-term workflow -- once the portable `.zip` exists it
carries its own GTK4 and Python, and a clean Windows machine with no MSYS2 is
the better test target.

GTK 4, libadwaita, Python and the GObject bindings all come from MSYS2's
**MINGW64** environment, which is the only practical source of that stack on
Windows -- and the same pacman repository the shipped bundle is assembled from,
so what runs here and what we ship share one ABI.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup-dev.ps1
```

That installs MSYS2 (pinned and SHA256-verified, straight from the
msys2-installer releases), runs `make install-sys-deps-windows`, downloads the
vendored RetroArch, and verifies the toolchain. Every step is idempotent, so
re-running it is safe and cheap. Pass `-SkipVendor` to skip the ~193 MiB
RetroArch download, and `-Msys2Root D:\msys64` to install elsewhere.

Then work from the development shell:

```
scripts\windows\dev-shell.cmd
```

Inside it, `make run`, `make test` and `make coverage` behave exactly as they do
on Linux. The system `PATH` is deliberately never modified: putting
`mingw64\bin` on it would shadow system DLLs for every process on the machine,
so MSYS2 sets the environment up for that one shell instead.

What the setup script deliberately does **not** install, and why:

| Not installed | Why |
| --- | --- |
| Docker | Windows artifacts are built in a Linux container, on Linux |
| Inno Setup | the installer is produced on Linux too |
| A Windows-native Python | it cannot import MSYS2's PyGObject |
| A second `make` | MSYS2 supplies it; another on `PATH` is the classic "works in cmd, fails in mingw64" bug |

There is **no venv on Windows**: PyGObject cannot be pip-built under MSYS2, so
pacman owns the whole dependency set and a venv would only hide it. `make venv`
and `make setup` are therefore no-ops that verify the pacman-provided stack
(`scripts/check_gtk_stack.py`) instead of installing anything.

`make install-sys-deps-windows` is the package list, for a developer who already
has the shell open. Keep it, the list in `setup-dev.ps1`, and this section in
sync.

### Gamepads: two backends, one token vocabulary

A binding stored in `~/.openemux/input/<CONSOLE>.config` is a RetroArch token --
`"3"` for a button, `"+1"`/`"-1"` for an axis, `"h0up"` for a hat. A token is an
*index*, so the reader that produces it and the driver that consumes it have to
count the same way.

| | Reads | Numbering agrees with |
| --- | --- | --- |
| Linux | `/dev/input/event*` (`core/gamepad_reader.py`, `core/ui_gamepad.py`) | RetroArch's `udev` joypad driver, its default there |
| Windows | SDL2 via `ctypes` (`core/gamepad_sdl.py`) | RetroArch's `sdl2` joypad driver, which the launch override pins |

`core/gamepad_backend.py` is the only place that picks; the UI asks it and never
branches on the answer. RetroArch's default on Windows is `xinput`, whose button
order is its own, so `retroarch_launcher` writes `input_joypad_driver = "sdl2"`
into the launch-scoped `--appendconfig` -- a user's own RetroArch keeps whatever
driver they chose.

To exercise the SDL path on Linux -- which is where this project is developed,
and the only place a real controller is usually plugged in:

```bash
OPENEMUX_GAMEPAD_BACKEND=sdl2 make run
```

It needs `libSDL2-2.0.so.0` (`apt install libsdl2-2.0-0`). An unknown value
warns and falls back to the platform default rather than leaving the app with no
gamepad at all.

SDL has one event queue per process and OpenEmux reads it from two places -- the
navigator that drives the UI, and the capture reader while remapping -- so both
subscribe to a single `SdlJoystickPump` rather than polling separately, which
would make them steal each other's presses.

### Line endings

`.gitattributes` normalizes the repository to LF, because Git for Windows'
default `core.autocrlf=true` otherwise puts a `\r` in the shebang of
`packaging/**/*.sh` and `devbox/*.sh` ("bad interpreter") and in Makefile
recipes -- which breaks the *Linux* builds from a Windows checkout. The files
Windows itself runs (`*.ps1`, `*.cmd`, `*.bat`, `*.iss`) are the exception and
keep CRLF.

### Vendored RetroArch

`scripts/vendor_retroarch.py` fetches the RetroArch build for the current
platform and verifies it against `vendors/manifest.json`:

```bash
make vendor-retroarch   # download what this platform needs
make verify-vendors     # check what is already there, without downloading
```

The Linux AppImage (10.9 MiB) is committed to git and only verified. The Windows
build (193 MiB) is gitignored and downloaded on demand. libretro publishes no
checksums, so the first fetch of a new upstream version records what it saw
(`--record`) for review and commit; every later run verifies against that and
fails hard on a mismatch.

### Tests that do not run on Windows

The whole suite runs on Windows -- `make test` in the development shell, and a
`windows-latest` job in [`tests.yml`](../.github/workflows/tests.yml) under the
same MSYS2 stack the bundle ships. The tests that cannot mean anything there are
marked, each with a reason:

```python
from tests.platform_marks import linux_only, posix_only

@posix_only("0o600 on the file holding the account token")
def test_the_file_is_owner_only(self):
```

`posix_only` covers file modes and `chmod`; `linux_only` covers the evdev
kernel ABI, `/proc`, the FHS install prefixes, AppImages, X11 and the uinput
device tests. Both are in [`tests/platform_marks.py`](../tests/platform_marks.py).

Far more than thirty are reported skipped there, and it is worth knowing why:
the runner has no interactive desktop, so `Gdk.Display.get_default()` comes back
`None` and every test decorated `needs_display` skips itself
([`tests/gtk_display.py`](../tests/gtk_display.py)) -- several hundred of them.
The Windows job therefore covers the core and the packaging, not the widgets.
The Linux matrix runs those under `xvfb`, and the widgets are looked at by hand
in the devbox.

Skipping these is not lowering the bar -- what they assert *is* a Linux
behaviour, and asserting it on Windows would only be asserting that Windows is
Windows. But a mark is a claim, so make it the narrowest one that fits (a
method, not its class) and say which platform behaviour is at stake. A bare
"skipped on Windows" leaves the next reader unable to tell a platform truth
from a bug nobody got around to fixing.

## Building the packages

All artifacts build **inside Docker** and land in `dist/`. Each package
script not only builds but also **install-tests** the result in a clean
container (dependency resolution via apt/dnf plus a GTK4/Adwaita import smoke
test), so a green run means the package actually installs and imports.

The AppImage build additionally requires an **x86_64 host**.

### AppImage

Universal, runs on any recent distro.

```bash
make appimage
# -> dist/OpenEmux-<version>-x86_64.AppImage
```

### Debian / Ubuntu (`.deb`)

Targets **Ubuntu 24.04 LTS and newer**. Built and tested in an `ubuntu:24.04`
container; `apt` pulls the GTK4/Adwaita dependencies.

```bash
make deb
# -> dist/openemux_<version>_amd64.deb
```

### Fedora (`.rpm`)

Targets **Fedora 40 and newer**. Built and tested in a Fedora container.

```bash
make rpm
# -> dist/openemux-<version>-1.fc<NN>.x86_64.rpm
```

Override the build image if needed, e.g. `RPM_BUILD_IMAGE=fedora:42 make rpm`
or `DEB_BUILD_IMAGE=ubuntu:25.04 make deb`.

### Flatpak

Builds a single-file bundle (`flatpak install ./OpenEmux-<version>.flatpak`;
the GNOME runtime is pulled from the user's configured remote), and refreshes
the ostree repo under `flatpak-repo/` that the separate
[`openemux-flatpak`](https://github.com/guilhermefeitosa66/openemux-flatpak)
repository publishes for `flatpak update`-able installs. The first run
downloads the GNOME runtime + SDK inside the container (a few GB).

Inside the sandbox OpenEmux launches the **host's RetroArch Flatpak**
(`org.libretro.RetroArch`) via `flatpak-spawn`; users install it once with
`flatpak install flathub org.libretro.RetroArch`, and its own Online Updater
manages the cores.

```bash
make flatpak
# -> dist/OpenEmux-<version>.flatpak  (+ flatpak-repo/)
```

### Windows (portable zip + installer)

Cross-built on Linux, in Docker, like every other artifact -- there is no
Windows machine anywhere in the release path. Three pieces make that work, and
none of them is Wine:

- the **mingw-w64 cross compiler** turns `openemux-launcher.c` into
  `OpenEmux.exe`, the small GUI binary that points the runtime at the bundle and
  starts Python;
- **MSYS2 packages** supply GTK 4, libadwaita and Python already compiled for
  Windows. They are downloaded and unpacked, never built;
- **NSIS** has a native Linux build, so `makensis` compiles the installer as an
  ordinary Linux program. (Issue #118 proposed Inno Setup; its compiler is a
  32-bit Windows binary, which would have dragged Wine and an i386 architecture
  into an otherwise self-contained Debian image.)

```bash
make windows            # fetches vendors/RetroArch-Win64 (~193 MiB) the first time
# -> dist/OpenEmux-<version>-windows-x86_64.zip
# -> dist/OpenEmux-<version>-setup.exe
```

The installer installs **per user**, under `%LOCALAPPDATA%\Programs\OpenEmux`, so
it never raises a UAC prompt. That is not only convenience: OpenEmux downloads
libretro cores into its own directory on first boot, and under `Program Files`
that write would fail for a standard user -- the app would install cleanly and
then be unable to launch a game.

#### The pinned MSYS2 runtime

`packaging/windows/packages.lock` names every MSYS2 package the bundle ships,
with its version and SHA-256. MSYS2 is a rolling repository, so resolving
dependencies against the live index at build time would mean the artifact
quietly changed from one afternoon to the next and a GTK regression could not be
bisected. Between updates every build installs exactly those bytes, and a
package that changed upstream fails the build loudly.

To move the bundle to a newer GTK or Python:

```bash
python3 packaging/windows/msys2_packages.py --update   # rewrite the lock
git diff packaging/windows/packages.lock               # the diff is the review
make windows-clean && make windows                     # rebuild and smoke-test
```

#### What is left out, and why

| Dropped | Size | Why |
| --- | --- | --- |
| `vendors/RetroArch-Win64/cores` | 1.8 GB | Cores carry many different licences. They are downloaded from the buildbot on first boot, exactly as on Linux, which keeps all of them out of the installer |
| `vendors/RetroArch-Win64/database` | 169 MB | RDB files for RetroArch's own content scanner, which OpenEmux never invokes |
| `vendors/RetroArch-Win64/shaders` | 101 MB | Nothing reads them: the shader feature works off `~/.openemux/runtime/shaders_{glsl,slang}` |
| `vendors/RetroArch-Win64/overlays` | 33 MB | A feature OpenEmux exposes no UI for |
| Headers, static libs, pkg-config, docs | — | Build-time files; the bundle only runs the stack |
| `tkinter` and the Tcl/Tk runtime | — | A second, unused GUI toolkit inside Python's standard library |

GStreamer stays. GTK 4 declares it as a dependency for its optional
media-playback backend, and dropping a hard dependency that is only loaded
lazily is the kind of change that breaks a bundle on a user's machine and
nowhere else.

#### The launcher's job

Nothing in the bundle knows where the user installed it, so `OpenEmux.exe` works
out its own directory and sets `OPENEMUX_PROJECT_ROOT`, `PYTHONPATH`,
`GI_TYPELIB_PATH`, `GSETTINGS_SCHEMA_DIR`, `XDG_DATA_DIRS`, the gdk-pixbuf
loader cache and `PATH` from it.

It also sets `SSL_CERT_FILE`. OpenSSL bakes its default CA path in at build
time, and MSYS2 builds it as `C:\msys64\mingw64\etc\ssl\cert.pem` -- a path
that exists on no user's machine. Without the override every HTTPS request fails
to verify, which on first boot means no cores and no cover art: the app installs
cleanly and then cannot fetch anything. The build's phase-5 check greps the
staged bundle for exactly that kind of baked-in build-machine path.

### Build everything

```bash
make packages          # appimage + deb + rpm + flatpak + windows, then checksums
make checksums         # (re)write dist/SHA256SUMS over whatever is in dist/
make packages-clean    # remove all built artifacts from dist/
```

### Checksums

`make packages` finishes by writing **`dist/SHA256SUMS`**, one file listing
every artifact, which ships with the release so users can run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

SHA-256 rather than MD5: MD5 collisions are practical, which makes an MD5
useless against exactly the tampering a checksum exists to detect. One
combined file rather than one per artifact keeps verification to a single
command.

### Package CI

[`.github/workflows/packages.yml`](../.github/workflows/packages.yml) runs the
same `packaging/build.sh <target>` this page describes, so a broken package
shows up in a pull request instead of on release day (issue #241).

| Trigger | Formats |
| --- | --- |
| Pull request touching `packaging/**`, `pyproject.toml`, `requirements*`, `Makefile`, `src/openemux/data/**` | `deb`, `rpm` |
| Push to `main`, Monday 05:00 UTC, `workflow_dispatch` | all five |

Each format's own build script ends with an install smoke test, so a green job
means the package installed in a clean container of its target distro, not just
that it compiled. Every run uploads `dist/` as an artifact (kept 14 days), which
is enough to hand somebody a release candidate without building it locally.

`workflow_dispatch` takes a **Which formats to build** choice (`all`,
`deb+rpm`, `appimage`, `flatpak`, `windows`) so a single format can be re-run on
its own:

```bash
gh workflow run packages.yml -f targets=flatpak
```

CI is given no secrets: without a `.env`, `_EMBEDDED_BLOB` stays empty and the
artifacts carry no ScreenScraper credential. That is deliberate — it keeps a CI
build reproducible by anyone — and it is also why the packages that ship in a
release are still built locally.

The Windows leg needs one step the others do not: the vendored RetroArch is a
gitignored 193 MiB download, so the job runs `make vendor-retroarch` before
`packaging/build.sh`. It is cached on `vendors/manifest.json`'s own hash, so a
RetroArch bump re-downloads and nothing else does.

## Testing the packages on other distros

Building a package proves it builds. Whether it *installs and runs* on the
distros people actually use is a separate question, and
[`packaging/testenv/`](../packaging/testenv/README.md) answers it: six
throwaway desktops — Ubuntu, Debian and Fedora, each in an X11 and a Wayland
flavour — driven by [distrobox]. They share the host's kernel, GPU and display,
so a full pass costs minutes instead of the hours a VM matrix would.

```bash
make distrobox-install     # once, if the host does not have distrobox yet
make packages              # the artifacts under test

make ubuntu-x11            # bring the container up, drop into a shell
make fedora-wayland        # same, on a nested weston session
```

Inside the container, one target per format:

```bash
make deb-install           # install the .deb, resolving Depends with apt
make deb-run               # launch it in this container's session
make deb-smoke             # launch it, screenshot it, fail if it dies
make smoke-all             # every format this distro can take
make help                  # the full list, tailored to this container
```

Or without the shell:

```bash
make ubuntu-x11 RUN="deb-install deb-smoke"
make testenv-matrix                    # all six, every format
make testenv-matrix SMOKE_SECONDS=12   # shorter runs, less screen time
```

`dist/` is bind-mounted read-only, and each container gets its own `$HOME`, so
first-boot bootstrap runs for real and your own library and config are never
touched. The `.deb` is only offered on Ubuntu and Debian, the `.rpm` only on
Fedora; the AppImage and the Flatpak run everywhere.

On an X11 host there is no Wayland session to borrow, so the `*-wayland`
containers start weston nested — a compositor in a window — and the app really
does speak Wayland to a real compositor.

A smoke run starts the app, screenshots it once its window is up, and requires
it to still be alive when the clock runs out. It distinguishes the ways that
can go wrong, because they mean different things: a crash, a *clean* exit
(these windows sit on your desktop while the matrix runs, and one stray click
closes the app), and `INCONCLUSIVE` when the nested compositor itself went
away — that last one proves nothing about the app and wants a rerun. Evidence
per run lands in the container's home:

```
~/openemux-testenv/logs/<distro>-<session>-<format>.log
~/openemux-testenv/shots/<distro>-<session>-<format>.png
```

Housekeeping, and the knobs worth knowing:

```bash
make testenv-list                      # what exists
make testenv-status                    # containers + the artifacts they serve
make testenv-rm-fedora-wayland         # drop one  (PURGE=1 drops its home too)
make testenv-rm-all

make ubuntu-x11 UBUNTU_IMAGE=ubuntu:26.04   # test a newer base
make ubuntu-x11 DIST_DIR=/path/to/dist      # artifacts from another checkout
```

The last one matters when driving the matrix from a worktree, whose own `dist/`
is empty. A container remembers which `dist/` it was created against, and
`testenv-status` says so rather than serving stale artifacts behind your back.

This covers dependency resolution, the launcher, the install layout, GTK and
libadwaita version differences, and both display backends. It does not cover a
real GNOME or KDE session, portals, drivers or kernels; those still want a VM.
The README in that directory has the details, including the handful of things
that were surprising enough to write down.

[distrobox]: https://distrobox.it

## How the packages are laid out

The `.deb` and `.rpm` share one install layout, assembled by
[`packaging/common/stage_tree.sh`](../packaging/common/stage_tree.sh):

- **`/opt/openemux/`** — the app "project root": `src/` plus the vendored
  RetroArch AppImage. The launcher sets `OPENEMUX_PROJECT_ROOT` to this path.
- **`/usr/bin/openemux`** — launcher
  ([`openemux-launcher.sh`](../packaging/common/openemux-launcher.sh)) that
  exports `OPENEMUX_PROJECT_ROOT` + `PYTHONPATH` and runs `openemux.main`.
  It picks the first interpreter that can actually `import gi`, starting at
  `/usr/bin/python3` — deliberately *not* `python3` from `PATH`, which a
  version manager (pyenv, conda, asdf) shadows with an interpreter that has no
  PyGObject.
- **`/usr/share/applications/…desktop`** (from
  [`packaging/common/openemux.desktop`](../packaging/common/openemux.desktop)),
  the hicolor **icons** in several sizes and a `/usr/share/pixmaps` fallback —
  desktop integration.

GTK4, libadwaita, PyGObject, pycairo and PyYAML come from **distro system
packages** (declared as package dependencies) — nothing is bundled except
RetroArch. There is no pip step in the native packages.

The version is read from `src/openemux/__init__.py`, the single source of truth
(`pyproject.toml` derives it dynamically; the AppImage recipe carries its own
copy that must be kept in sync).

## Embedded ScreenScraper credentials

Official builds bake the project's ScreenScraper **developer** account
(`devid` + `devpassword`) into the artifact so cover scraping via ScreenScraper
works out of the box. End users still add their own ScreenScraper account
(`ssid`/`sspassword`) in Preferences — that is what spends their own quota
rather than the project's shared pool.

The credential lives **only** in a local, gitignored `.env`. CI builds packages
(see [Package CI](#package-ci)) but is given no secret, so its artifacts carry
no credential; the packages that ship in a release are produced locally on an
x86_64 host (see below). Copy [`.env.example`](../.env.example) to `.env` and
fill it in:

```bash
cp .env.example .env
# edit .env:
#   SCREENSCRAPER_DEVID=...
#   SCREENSCRAPER_DEVPASSWORD=...
```

`.env` is ignored by git; only `.env.example` is committed. With it in place:

- **Developing (`make run`)** — the `run` target sources `.env`, so the app
  reads the credential from the `SCREENSCRAPER_DEVID`/`SCREENSCRAPER_DEVPASSWORD`
  environment variables via
  [`embedded_credentials.get_embedded_dev_credentials()`](../src/openemux/core/embedded_credentials.py).
  ScreenScraper works in dev, the Developer ID/password fields in Preferences
  stay **hidden**, and the key is **never written to `~/.openemux/config.yaml`**.
  > If you previously typed the dev key into Preferences, remove
  > `covers.sync.screenscraper_devid` and `covers.sync.screenscraper_devpassword`
  > from `~/.openemux/config.yaml` once and let `.env` supply it instead.
- **Building (`make packages`)** — [`packaging/build.sh`](../packaging/build.sh)
  sources `.env` and forwards the two variables into the build container.
  [`packaging/embed_screenscraper_credentials.py`](../packaging/embed_screenscraper_credentials.py)
  then rewrites `_EMBEDDED_BLOB` in the **staged copy only** (never the host
  source): the `.deb`/`.rpm` inject in
  [`stage_tree.sh`](../packaging/common/stage_tree.sh), the AppImage in its
  recipe's `script:` step. The value is lightly obfuscated (XOR + base64) — not
  real secrecy, just so it is not a plaintext, grep-able string.

`_EMBEDDED_BLOB` is **empty in git** and a unit test guards that it stays empty,
so a build without a `.env` simply ships no credential and ScreenScraper stays
opt-in (off by default). End users still add their own ScreenScraper account
(`ssid`/`sspassword`) in Preferences — separate from this developer credential.

**Rotation.** A credential shipped in a client is extractable, so if the project
account is ever abused, request a new `devid`/`devpassword` from ScreenScraper
staff, update your `.env`, and cut a new release — no source change needed.

## Cutting a release

`main` holds released code only and is protected by a repository ruleset: no
direct push, no force-push, and a pull request with a code-owner approval to
merge. A release is therefore a branch and a PR like anything else — it just
starts from `develop` and lands on `main`.

1. Branch off up-to-date `develop`: `release/vX.Y.Z`. Unlike a feature branch
   this one is **kept forever** — the tag marks the point, the branch is what
   you can `git checkout` to sit in that version.
2. Bump the version in all four places: `src/openemux/__init__.py` (the single
   source of truth), the `version:` in `packaging/appimage/AppImageBuilder.yml`,
   a `%changelog` entry in `packaging/rpm/openemux.spec`, and a `<release>`
   entry at the top of `<releases>` in
   `packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml`.
   `tests/test_reproducible_builds.py` checks all four against each other.
3. Write `release/RELEASE_NOTES_vX.Y.Z.md`, following the previous file in that
   folder. It is committed, and step 7 publishes the release from it.
4. Commit as `[no-issue] chore: release X.Y.Z`.
5. `make packages-clean && make packages`, and confirm every artifact is green
   (build **and** install-test) and that `dist/SHA256SUMS` covers them all.
   Clean first: `dist/` still holds the previous version's artifacts and step 7
   uploads everything in there.
6. `make testenv-matrix` — the build containers install-test each artifact on
   the distro that built it, which is the easy half. This installs and launches
   all of them on Ubuntu, Debian and Fedora, under X11 and Wayland. See
   [Testing the packages on other distros](#testing-the-packages-on-other-distros).
7. Open the PR to `main` and merge it:

   ```bash
   gh pr create --base main --title "Release vX.Y.Z"
   gh pr merge <n> --squash --admin       # NOT --delete-branch: the branch stays
   ```

8. Tag and publish **from `main`**:

   ```bash
   git checkout main && git pull
   gh release create vX.Y.Z dist/* --target main \
     --title "OpenEmux X.Y.Z" --notes-file release/RELEASE_NOTES_vX.Y.Z.md
   ```

   `--target main` is not optional. Without it `gh` tags the repository's
   *default* branch, which is `develop` — and `develop` does not carry the
   version bump until step 10, so the tag lands on the previous version while
   the uploaded artifacts still look right. Verify before moving on:

   ```bash
   test "$(gh api repos/guilhermefeitosa66/OpenEmux/git/refs/tags/vX.Y.Z --jq .object.sha)" \
     = "$(git rev-parse main)"
   ```

   The README/website download links point at `releases/latest`, so they need
   no per-version edits — only update them when adding a new *format*.
9. Publish the Flatpak to the distribution repo, or `flatpak update` never
   offers the new version:
   `gh workflow run publish.yml --repo guilhermefeitosa66/openemux-flatpak -f ref=vX.Y.Z`.
   That workflow builds the tag from step 8, which is the second place a tag on
   the wrong commit shows up — as a published Flatpak one version behind.
10. Merge `main` back into `develop` and push, so the version bump is not
    stranded on the release branch.

[`CLAUDE.md`](../CLAUDE.md#releases) carries the same sequence for the
assistant; keep the two in sync.

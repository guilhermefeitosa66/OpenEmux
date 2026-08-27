# OpenEmux — Developer Guide

Everything you need to hack on OpenEmux, run the tests, and build the release
artifacts. For user-facing install instructions, see the main
[README](../README.md#download--install).

## Table of contents

- [Requirements](#requirements)
- [Project layout](#project-layout)
- [Running from source](#running-from-source)
- [Developing on Windows](#developing-on-windows)
- [Tests](#tests)
- [Building the packages](#building-the-packages)
  - [AppImage](#appimage)
  - [Debian / Ubuntu (`.deb`)](#debian--ubuntu-deb)
  - [Fedora (`.rpm`)](#fedora-rpm)
  - [Flatpak](#flatpak)
  - [Windows (portable zip + installer)](#windows-portable-zip--installer)
  - [Build everything](#build-everything)
  - [Checksums](#checksums)
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
  i18n/     translations (tr(key, locale) + locales/*.py)
tests/      unittest suite, one test_<module>.py per core module
packaging/
  build.sh  entry point: `packaging/build.sh {appimage|deb|rpm}`
  docker/   one Dockerfile per target — the build toolchains
  appimage/ AppImage recipe + in-container build script + bundle entry point
  deb/      in-container .deb build/test script
  rpm/      .rpm spec + in-container build/test script
  common/   shared across .deb/.rpm: install layout, launcher, desktop entry
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

## Tests

```bash
make test
# or directly:
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests

# with a coverage report (needs `make setup-dev` once):
make coverage
```

The suite is stdlib `unittest`, covers the `core/` modules only (no GTK in
tests), and mocks the network. Add a `test_<module>.py` alongside any new core
module.

`make coverage` runs the same suite under [coverage.py](https://coverage.readthedocs.io/)
(configured in `pyproject.toml`, measuring all of `src/openemux` — untested UI
modules count as 0%, so the total reflects the whole app). CI does the same and,
on every push to `develop`, refreshes the README's coverage badge by pushing
`coverage.json` to the CI-owned `badges` branch.

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

### Line endings

`.gitattributes` normalizes the repository to LF, because Git for Windows'
default `core.autocrlf=true` otherwise puts a `\r` in the shebang of `run.sh`
and `packaging/**/*.sh` ("bad interpreter") and in Makefile recipes -- which
breaks the *Linux* builds from a Windows checkout. The files Windows itself runs
(`*.ps1`, `*.cmd`, `*.bat`, `*.iss`) are the exception and keep CRLF.

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

### Known-failing tests

The suite still carries Linux-only assumptions -- POSIX file modes, `/usr`
install prefixes, evdev struct sizes, X11 -- so a handful of tests fail on
Windows and do not indicate a broken toolchain. Phase 4 of issue #118 covers
fixing them and running the suite on a `windows-latest` runner.

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
make vendor-retroarch   # once: fetches vendors/RetroArch-Win64 (~193 MiB)
make windows
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

The credential lives **only** in a local, gitignored `.env` — there is no build
CI; packages and releases are produced locally on an x86_64 host (see below).
Copy [`.env.example`](../.env.example) to `.env` and fill it in:

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

1. Bump the version in all four places: `src/openemux/__init__.py`, the
   `version:` in `packaging/appimage/AppImageBuilder.yml`, a `%changelog` entry
   in `packaging/rpm/openemux.spec`, and a `<release>` entry in
   `packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml`.
2. `make packages` and confirm every artifact is green (build **and**
   install-test), and that `dist/SHA256SUMS` covers them all.
3. `make testenv-matrix` — the build containers install-test each artifact on
   the distro that built it, which is the easy half. This installs and launches
   all of them on Ubuntu, Debian and Fedora, under X11 and Wayland. See
   [Testing the packages on other distros](#testing-the-packages-on-other-distros).
4. Commit, tag `vX.Y.Z`, push `main` and the tag.
5. `gh release create vX.Y.Z --target main dist/*` — every artifact plus
   `SHA256SUMS`. The README/website download links point at `releases/latest`,
   so they need no per-version edits — only update them when adding a new
   *format*.
6. Publish the Flatpak to the distribution repo, or `flatpak update` never
   offers the new version:
   `gh workflow run publish.yml --repo guilhermefeitosa66/openemux-flatpak -f ref=vX.Y.Z`

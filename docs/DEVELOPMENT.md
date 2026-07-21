# OpenEmux — Developer Guide

Everything you need to hack on OpenEmux, run the tests, and build the release
artifacts. For user-facing install instructions, see the main
[README](../README.md#download--install).

## Table of contents

- [Requirements](#requirements)
- [Project layout](#project-layout)
- [Running from source](#running-from-source)
- [Tests](#tests)
- [Building the packages](#building-the-packages)
  - [AppImage](#appimage)
  - [Debian / Ubuntu (`.deb`)](#debian--ubuntu-deb)
  - [Fedora (`.rpm`)](#fedora-rpm)
  - [Build everything](#build-everything)
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
```

The suite is stdlib `unittest`, covers the `core/` modules only (no GTK in
tests), and mocks the network. Add a `test_<module>.py` alongside any new core
module.

## Building the packages

All three artifacts build **inside Docker** and land in `dist/`. Each package
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

### Build everything

```bash
make packages          # appimage + deb + rpm
make packages-clean    # remove all built artifacts from dist/
```

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

## Cutting a release

1. Bump `src/openemux/__init__.py` and the `version:` in
   `packaging/appimage/AppImageBuilder.yml`.
2. `make packages` and confirm all three green (build **and** install-test).
3. Commit, tag `vX.Y.Z`, push `main` and the tag.
4. `gh release create vX.Y.Z --target main` with the three `dist/` artifacts.
   The README/website download links point at `releases/latest`, so they need no
   per-version edits — only update them when adding a new *format*.

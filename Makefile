# OpenEmux Makefile

# Windows (MSYS2 MINGW64) vs Linux. MSYS2's make inherits OS=Windows_NT from
# Windows itself, which is what makes this detection work from inside the
# MINGW64 shell. Only the interpreter and the vendored RetroArch differ -- every
# recipe below is POSIX sh, and MSYS2 supplies sh, find, xargs and sha256sum.
#
# There is no venv on Windows: PyGObject cannot be pip-built under MSYS2, so
# the whole dependency set comes from pacman and a venv would only hide it.
ifeq ($(OS),Windows_NT)
VENV :=
PYTHON := python
PIP := python -m pip
RETROARCH_VENDOR := vendors/RetroArch-Win64/retroarch.exe
else
VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
RETROARCH_VENDOR := vendors/RetroArch-Linux-x86_64.AppImage
endif

.PHONY: all setup setup-dev venv run test coverage icons clean install-sys-deps bootstrap check-retroarch lock-deps
.PHONY: install-sys-deps-windows vendor-retroarch verify-vendors
.PHONY: appimage appimage-clean deb rpm flatpak windows windows-clean checksums packages packages-clean
.PHONY: distrobox-install testenv-matrix testenv-list testenv-status testenv-rm-all
.PHONY: ubuntu-x11 ubuntu-wayland debian-x11 debian-wayland fedora-x11 fedora-wayland

all: setup

# Full bootstrap: from fresh clone to running (requires sudo for sys deps).
# On Windows there is no venv and no pip step -- pacman provides everything --
# so the bootstrap is the package install plus the vendored RetroArch.
ifeq ($(OS),Windows_NT)
bootstrap: install-sys-deps-windows vendor-retroarch
else
bootstrap: install-sys-deps venv setup
endif
	@echo ""
	@echo "✅ OpenEmux is ready! Run 'make run' to start."

# System dependencies for Ubuntu/Mint
install-sys-deps:
	sudo apt update
	sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev \
		libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-rsvg-2.0
	@echo "Install RetroArch/libretro cores from your distro OR use vendors/RetroArch-Linux-x86_64.AppImage."

# System dependencies for Windows, from inside an MSYS2 MINGW64 shell.
# scripts/windows/setup-dev.ps1 installs MSYS2 itself and then runs this list;
# this target is for a developer who already has the shell open. Keep it in sync
# with the package set in that script and with docs/DEVELOPMENT.md.
install-sys-deps-windows:
	pacman -S --needed --noconfirm make git \
		mingw-w64-x86_64-gtk4 mingw-w64-x86_64-libadwaita \
		mingw-w64-x86_64-gobject-introspection-runtime mingw-w64-x86_64-librsvg \
		mingw-w64-x86_64-adwaita-icon-theme mingw-w64-x86_64-hicolor-icon-theme \
		mingw-w64-x86_64-gsettings-desktop-schemas mingw-w64-x86_64-shared-mime-info \
		mingw-w64-x86_64-webp-pixbuf-loader \
		mingw-w64-x86_64-python mingw-w64-x86_64-python-gobject \
		mingw-w64-x86_64-python-cairo mingw-w64-x86_64-python-yaml \
		mingw-w64-x86_64-python-coverage mingw-w64-x86_64-ca-certificates \
		mingw-w64-x86_64-SDL2 mingw-w64-x86_64-7zip

# Environment setup. Both are no-ops on Windows: PyGObject cannot be pip-built
# under MSYS2, so pacman owns the whole dependency set and a venv would only
# hide it. Verify the imports instead, which is what those steps exist to buy.
ifeq ($(OS),Windows_NT)
venv:
	@echo "No venv on Windows -- MSYS2 pacman provides Python and the bindings."

setup:
	@echo "No pip step on Windows; verifying the pacman-provided stack instead."
	@$(PYTHON) scripts/check_gtk_stack.py
else
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

setup:
	$(PIP) install -r requirements.txt
endif

# Fetch the vendored RetroArch for this platform, verified against
# vendors/manifest.json. The Linux AppImage is committed to git and is only
# checked; the 193 MiB Windows build is gitignored and downloaded on demand.
vendor-retroarch:
	$(PYTHON) scripts/vendor_retroarch.py

# Check every vendored artifact against the manifest without downloading.
verify-vendors:
	$(PYTHON) scripts/vendor_retroarch.py --verify

# Development extras (coverage.py) on top of the runtime dependencies.
# On Windows coverage comes from mingw-w64-x86_64-python-coverage, installed by
# install-sys-deps-windows, so there is nothing extra to do.
ifeq ($(OS),Windows_NT)
setup-dev: setup
	@$(PYTHON) -c "import coverage; print('OK: coverage', coverage.__version__)"
else
setup-dev: setup
	$(PIP) install -r requirements-dev.txt
endif

lock-deps:
	$(PIP) freeze > requirements.lock


# Running the app. Sources the gitignored .env first so a ScreenScraper
# developer credential there reaches the app as env vars -- no need to store it
# in ~/.openemux/config.yaml (see docs/DEVELOPMENT.md).
run:
	set -a; [ -f .env ] && . ./.env; set +a; PYTHONPATH=src $(PYTHON) src/openemux/main.py

# Run the unit test suite
test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

# Run the unit test suite under coverage.py and print the report
# (needs `make setup-dev`; configuration lives in pyproject.toml)
coverage:
	PYTHONPATH=src $(PYTHON) -m coverage run -m unittest discover -s tests
	$(PYTHON) -m coverage report

# Regenerate the game-name database (issue #184) from a local checkout of
# the artwork mirror. MIRROR/DATS are overridable:
#   make name-db MIRROR=../openemux-artwork DATS=/path/to/dats
name-db:
	$(PYTHON) tools/generate_name_db.py --mirror $(or $(MIRROR),../openemux-artwork) \
		$(if $(DATS),--dats $(DATS),) --output src/openemux/data/games.db.zip

# Browse the symbolic icons the UI may use (Adwaita only -- see the tool's
# docstring for why the desktop's other themes are excluded).
#   make icons              browse everything
#   make icons FILTER=view  open on a filter
icons:
	PYTHONPATH=src $(PYTHON) tools/icon_browser.py $(FILTER)

# -f rather than -x: the vendored Windows build is a .exe, and MSYS2 does not
# report the executable bit for it the way Linux does for the AppImage.
check-retroarch:
	@echo "Checking RetroArch binary..."
	@if [ -f $(RETROARCH_VENDOR) ]; then \
		echo "Using vendored RetroArch: $(RETROARCH_VENDOR)"; \
	elif command -v retroarch >/dev/null 2>&1; then \
		echo "Using system RetroArch: $$(command -v retroarch)"; \
	else \
		echo "RetroArch not found. Run 'make vendor-retroarch' or install retroarch."; \
		exit 1; \
	fi

# --- Packaging ---
#
# Every target builds inside the container defined by
# packaging/docker/<target>.Dockerfile, so the host only needs Docker, and each
# build install-tests its own artifact. Results land in dist/.
# The AppImage additionally requires an x86_64 host. See docs/DEVELOPMENT.md.

# Universal AppImage (Ubuntu 24.04 build container)
appimage:
	./packaging/build.sh appimage

# Debian/Ubuntu .deb — built and install-tested in an Ubuntu 24.04 container
deb:
	./packaging/build.sh deb

# Fedora .rpm — built and install-tested in a Fedora container
rpm:
	./packaging/build.sh rpm

# Flatpak bundle — built and install-tested in an Ubuntu 24.04 container.
# Also refreshes flatpak-repo/ (the ostree repo published to openemux-flatpak).
flatpak:
	./packaging/build.sh flatpak

# Windows portable .zip + installer .exe — cross-built in a Debian container.
# Needs vendors/RetroArch-Win64 first: `make vendor-retroarch`. Runs on Linux
# like every other target; there is no Windows machine in the release path.
windows:
	./packaging/build.sh windows

# One SHA256SUMS over every artifact in dist/, so a download can be verified
# with `sha256sum -c SHA256SUMS`. SHA-256 rather than MD5: MD5 collisions are
# practical, which makes it useless against a tampered file -- the one thing
# the checksum is for. One file rather than one per artifact keeps a single
# command verifying the whole release.
checksums:
	@cd dist && rm -f SHA256SUMS && \
		find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\n' | sort | \
		xargs -r sha256sum > SHA256SUMS && \
		echo "==> dist/SHA256SUMS" && cat SHA256SUMS

# Build all release artifacts into dist/, checksummed.
# `windows` comes before `checksums` for the same reason every other target
# does: SHA256SUMS is written over whatever is in dist/ at that moment, so an
# artifact built afterwards would ship unverifiable.
packages: appimage deb rpm flatpak windows checksums

appimage-clean:
	rm -rf AppDir AppDir.squashfs appimage-build appimage-builder-cache dist/*.AppImage dist/*.zsync

# The staged bundle tree, but not build/win/msys2-cache: that holds the
# downloaded MSYS2 packages, they are checksum-verified against packages.lock on
# every use, and re-fetching ~400 MiB to rebuild is a poor trade.
windows-clean:
	rm -rf build/win/extracted build/win/OpenEmux dist/OpenEmux-*-windows-x86_64.zip dist/OpenEmux-*-setup.exe

# Remove every packaged artifact
packages-clean: appimage-clean windows-clean
	rm -rf dist/*.deb dist/*.rpm dist/*.flatpak dist/SHA256SUMS flatpak-repo
	@# The flatpak build runs as root inside its container, so the tree it
	@# leaves behind is root-owned and rm(1) on the host cannot touch it.
	@# Delete it the way it was created rather than reaching for sudo.
	@if [ -e .flatpak-build-dir ]; then \
		img=openemux-build-flatpak; \
		docker image inspect $$img >/dev/null 2>&1 || img=alpine; \
		docker run --rm -v "$(CURDIR)":/work -w /work $$img rm -rf /work/.flatpak-build-dir; \
	fi

# --- Test environments (distrobox) ---
#
# A container per (distro, session) pair, each one a throwaway desktop where
# the artifacts in dist/ get installed and launched the way a user would.
#
#   make distrobox-install     install distrobox itself (once, needs sudo)
#   make ubuntu-x11            bring the container up and drop into a shell
#   make fedora-wayland        same, on a nested weston session
#
# Inside, `make deb-install`, `make appimage-run`, `make flatpak-smoke` and
# friends are served by packaging/testenv/Makefile. To skip the shell and run
# them straight from here:
#
#   make ubuntu-x11 RUN="deb-install deb-smoke"
#   make testenv-matrix        smoke every format on every distro/session
#
# dist/ is bind-mounted read-only, so a test can never eat a release artifact.
# Build it first with `make packages`. Driving the matrix from a worktree,
# whose dist/ is empty? Point at the real one: DIST_DIR=/path/to/dist.
TESTENV := ./packaging/testenv/testenv.sh
DIST_DIR ?= $(CURDIR)/dist
export DIST_DIR

# Base images, overridable: `make ubuntu-x11 UBUNTU_IMAGE=ubuntu:26.04`.
# Ubuntu 24.04 is the floor the .deb targets (libadwaita >= 1.5); Debian's
# first release clearing it is 13, since bookworm ships libadwaita 1.2 and
# cannot install the package at all. The .rpm is built on the fc40 floor and
# install-tested here on a current Fedora.
UBUNTU_IMAGE ?= ubuntu:24.04
DEBIAN_IMAGE ?= debian:13
FEDORA_IMAGE ?= fedora:42
export UBUNTU_IMAGE DEBIAN_IMAGE FEDORA_IMAGE

# Every scenario worth running, in the order the matrix runs them.
TESTENVS := ubuntu-x11 ubuntu-wayland debian-x11 debian-wayland fedora-x11 fedora-wayland

distrobox-install:
	$(TESTENV) install-distrobox

# One target per scenario. With RUN= they are non-interactive, which is what
# makes the matrix (and a CI job) possible; without it you get a shell.
$(TESTENVS):
	@$(TESTENV) $(if $(RUN),run $(subst -, ,$@) $(RUN),up $(subst -, ,$@))

# Every format on every distro and session, installed and smoke-tested.
# Serial on purpose: they all compete for the same screen. Shorten the runs
# with SMOKE_SECONDS=12 when the machine is also being used for other work.
testenv-matrix:
	@rc=0; for e in $(TESTENVS); do \
	  printf '\n\033[1;35m=== %s ===\033[0m\n' "$$e"; \
	  $(MAKE) --no-print-directory $$e RUN="$(if $(SMOKE_SECONDS),SMOKE_SECONDS=$(SMOKE_SECONDS)) smoke-all" || rc=1; \
	done; exit $$rc

testenv-list:
	@$(TESTENV) list

testenv-status:
	@$(TESTENV) status

# make testenv-rm-fedora-wayland      (add PURGE=1 to drop its home too)
testenv-rm-%:
	@$(TESTENV) rm $(if $(PURGE),--purge,) $(subst -, ,$*)

testenv-rm-all:
	@$(TESTENV) rm-all $(if $(PURGE),--purge,)

# Cleaning
# The VENV guard matters: on Windows VENV is empty, and an unguarded
# `rm -rf $(VENV)` would expand to a bare `rm -rf` in the repo root.
clean:
	@if [ -n "$(VENV)" ]; then rm -rf $(VENV); fi
	find . -type d -name "__pycache__" -exec rm -rf {} +

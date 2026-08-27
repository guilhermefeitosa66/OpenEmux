# OpenEmux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup setup-dev venv run test coverage icons clean install-sys-deps bootstrap check-retroarch lock-deps
.PHONY: appimage appimage-clean deb rpm flatpak checksums packages packages-clean
.PHONY: distrobox-install testenv-matrix testenv-list testenv-status testenv-rm-all
.PHONY: ubuntu-x11 ubuntu-wayland debian-x11 debian-wayland fedora-x11 fedora-wayland

all: setup

# Full bootstrap: from fresh clone to running (requires sudo for sys deps)
bootstrap: install-sys-deps venv setup
	@echo ""
	@echo "✅ OpenEmux is ready! Run 'make run' to start."

# System dependencies for Ubuntu/Mint
install-sys-deps:
	sudo apt update
	sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev \
		libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-rsvg-2.0
	@echo "Install RetroArch/libretro cores from your distro OR use vendors/RetroArch-Linux-x86_64.AppImage."

# Environment setup
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

setup:
	$(PIP) install -r requirements.txt

# Development extras (coverage.py) on top of the runtime dependencies
setup-dev: setup
	$(PIP) install -r requirements-dev.txt

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

check-retroarch:
	@echo "Checking RetroArch binary..."
	@if [ -x vendors/RetroArch-Linux-x86_64.AppImage ]; then \
		echo "Using vendored AppImage: vendors/RetroArch-Linux-x86_64.AppImage"; \
	elif command -v retroarch >/dev/null 2>&1; then \
		echo "Using system RetroArch: $$(command -v retroarch)"; \
	else \
		echo "RetroArch not found. Add AppImage to vendors/ or install retroarch."; \
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

# Build all release artifacts into dist/, checksummed
packages: appimage deb rpm flatpak checksums

appimage-clean:
	rm -rf AppDir AppDir.squashfs appimage-build appimage-builder-cache dist/*.AppImage dist/*.zsync

# Remove every packaged artifact
packages-clean: appimage-clean
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
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

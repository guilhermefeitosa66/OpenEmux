# OpenEmux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup venv run test icons clean install-sys-deps bootstrap check-retroarch lock-deps
.PHONY: appimage appimage-clean deb rpm flatpak checksums packages packages-clean

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
	rm -rf AppDir appimage-build appimage-builder-cache dist/*.AppImage dist/*.zsync

# Remove every packaged artifact
packages-clean: appimage-clean
	rm -rf dist/*.deb dist/*.rpm dist/*.flatpak dist/SHA256SUMS flatpak-repo .flatpak-build-dir

# Cleaning
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

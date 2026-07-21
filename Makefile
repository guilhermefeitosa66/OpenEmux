# OpenEmux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup venv run test clean install-sys-deps bootstrap check-retroarch lock-deps
.PHONY: appimage appimage-clean deb rpm packages packages-clean

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


# Running the app
run:
	PYTHONPATH=src $(PYTHON) src/openemux/main.py

# Run the unit test suite
test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

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

# Build all three release artifacts into dist/
packages: appimage deb rpm

appimage-clean:
	rm -rf AppDir appimage-build appimage-builder-cache dist/*.AppImage dist/*.zsync

# Remove every packaged artifact
packages-clean: appimage-clean
	rm -f dist/*.deb dist/*.rpm

# Cleaning
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

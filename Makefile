# Opemux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup venv run clean install-sys-deps bootstrap check-retroarch
.PHONY: appimage appimage-docker appimage-clean

all: setup

# Full bootstrap: from fresh clone to running (requires sudo for sys deps)
bootstrap: install-sys-deps venv setup
	@echo ""
	@echo "✅ Opemux is ready! Run 'make run' to start."

# System dependencies for Ubuntu/Mint
install-sys-deps:
	sudo apt update
	sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev \
		libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1
	@echo "Install RetroArch/libretro cores from your distro OR use vendors/RetroArch-Linux-x86_64.AppImage."

# Environment setup
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

setup:
	$(PIP) install -r requirements.txt


# Running the app
run:
	PYTHONPATH=src $(PYTHON) src/opemux/main.py

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

appimage:
	./packaging/appimage/build_appimage.sh

appimage-docker:
	./packaging/appimage/build_in_docker.sh

appimage-clean:
	rm -rf AppDir appimage-builder-cache dist/*.AppImage dist/*.zsync

# Cleaning
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

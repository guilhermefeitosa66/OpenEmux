# Opemux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup venv run clean build-emulators build-nestopia build-mgba build-snes9x \
        install-sys-deps vendor-init bootstrap

all: setup build-emulators

# Full bootstrap: from fresh clone to running (requires sudo for sys deps)
bootstrap: install-sys-deps vendor-init venv setup build-emulators
	@echo ""
	@echo "✅ Opemux is ready! Run 'make run' to start."

# System dependencies for Ubuntu/Mint
install-sys-deps:
	sudo apt update
	sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev \
		libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 \
		build-essential autoconf autoconf-archive automake autotools-dev cmake \
		libarchive-dev libepoxy-dev libfltk1.3-dev libsamplerate0-dev libsdl2-dev zlib1g-dev \
		libsqlite3-dev libelf-dev libpng-dev libjpeg-dev libzip-dev zipcmp zipmerge ziptool libedit-dev \
		libavcodec-dev libavformat-dev libavfilter-dev libswscale-dev libswresample-dev \
		libx11-dev libxext-dev libxv-dev libasound2-dev libpulse-dev \
		libgtkmm-3.0-dev libxrandr-dev libwayland-dev wayland-protocols libvulkan-dev portaudio19-dev

# Vendor submodule setup (pulls emulator source code)
vendor-init:
	@echo "Initializing vendor submodules..."
	git submodule update --init --recursive
	@echo "Vendor submodules ready."

# Environment setup
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

setup: vendor-init
	$(PIP) install -r requirements.txt


# Running the app
run:
	PYTHONPATH=src $(PYTHON) src/opemux/main.py

# Building Emulator Vendors
build-emulators: build-nestopia build-mgba build-snes9x

build-nestopia:
	@echo "Building Nestopia..."
	cd vendors/nestopia && autoreconf -vif && ./configure && make -j$(shell nproc)
	@echo "Nestopia build complete. Binary located at vendors/nestopia/nestopia"

build-mgba:
	@echo "Building mGBA..."
	mkdir -p vendors/mgba/build
	cd vendors/mgba/build && cmake .. -DENABLE_QT=OFF -DENABLE_SDL=ON -DMARKDOWN=OFF && make -j$(shell nproc)
	@echo "mGBA build complete. Binary located at vendors/mgba/build/sdl/mgba-sdl"


build-snes9x:
	@echo "Building Snes9x..."
	mkdir -p vendors/snes9x/gtk/build
	cd vendors/snes9x/gtk/build && cmake .. && make -j$(shell nproc)
	@echo "Snes9x build complete. Binary located at vendors/snes9x/gtk/build/snes9x-gtk"


# Cleaning
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

# Opemux Makefile

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip

.PHONY: all setup venv run clean build-nestopia install-sys-deps

all: setup build-nestopia

# System dependencies for Ubuntu/Mint
install-sys-deps:
	sudo apt update
	sudo apt install -y libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev \
		libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 \
		build-essential autoconf autoconf-archive automake autotools-dev \
		libarchive-dev libepoxy-dev libfltk1.3-dev libsamplerate0-dev libsdl2-dev zlib1g-dev

# Environment setup
venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

setup:
	$(PIP) install -r requirements.txt


# Running the app
run:
	PYTHONPATH=src $(PYTHON) src/opemux/main.py

# Building Emulator Vendors
build-emulators: build-nestopia

build-nestopia:
	@echo "Building Nestopia..."
	cd vendors/nestopia && autoreconf -vif && ./configure && make -j$(shell nproc)
	@echo "Nestopia build complete. Binary located at vendors/nestopia/nestopia"

# Cleaning
clean:
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +

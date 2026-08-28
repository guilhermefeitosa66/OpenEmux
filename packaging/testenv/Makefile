# OpenEmux test-container Makefile
#
# This is NOT the project Makefile -- it only exists inside a distrobox test
# container, mounted at /openemux/testkit, and it installs and runs the release
# artifacts the way a user of that distro would.
#
#   make deb-install      install the .deb, resolving its Depends with apt
#   make deb-run          launch it in this container's session
#   make deb-smoke        launch it, screenshot it, fail if it dies on its own
#   make smoke-all        every format this distro can take, end to end
#
# The artifacts come from the host's dist/, bind-mounted read-only. Build them
# there first with `make packages`.

SHELL := /bin/bash

DIST  ?= /openemux/dist
WORK  ?= $(HOME)/openemux-testenv
KIT   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

SESSION := $(or $(OPENEMUX_SESSION),x11)
TESTENV := $(or $(OPENEMUX_TESTENV),local)
# A bare `case` would not survive $(shell ...): make counts parentheses, and
# the `)` of a case pattern closes the function call early.
FAMILY  := $(shell . /etc/os-release; if echo "$$ID $$ID_LIKE" | grep -qE 'fedora|rhel'; then echo fedora; else echo debian; fi)
PRETTY  := $(shell . /etc/os-release; echo "$$PRETTY_NAME")

APP_ID  := io.github.guilhermefeitosa66.OpenEmux
# Both native packages install here. Addressed absolutely on purpose:
# distrobox forwards the host's PATH, so a ~/.local/bin/openemux on the host
# would shadow the package under test and the smoke run would pass for the
# wrong binary.
APP_BIN := /usr/bin/openemux
LAUNCH  := $(KIT)/launch.sh
WESTON  := $(KIT)/weston-session.sh

# How long a *-smoke target keeps the app alive before calling it a pass.
SMOKE_SECONDS ?= 25

# Newest artifact of each kind (sorted by name, so the highest version wins).
APPIMAGE := $(lastword $(sort $(wildcard $(DIST)/*.AppImage)))
DEB      := $(lastword $(sort $(wildcard $(DIST)/*.deb)))
RPM      := $(lastword $(sort $(wildcard $(DIST)/*.rpm)))
BUNDLE   := $(lastword $(sort $(wildcard $(DIST)/*.flatpak)))

APPIMAGE_LOCAL := $(WORK)/OpenEmux.AppImage

# Formats worth testing here: native packages only where they belong, the
# portable ones everywhere.
FORMATS_debian := appimage deb flatpak
FORMATS_fedora := appimage rpm flatpak
FORMATS        := $(FORMATS_$(FAMILY))

# Flatpak filters the environment on its way into the sandbox, so the backend
# is handed over explicitly instead of being inherited.
FLATPAK_BACKEND := $(if $(filter wayland,$(SESSION)),wayland,x11)

.PHONY: help env $(addsuffix -install,appimage deb rpm flatpak) \
        $(addsuffix -run,appimage deb rpm flatpak) \
        $(addsuffix -smoke,appimage deb rpm flatpak) \
        $(addsuffix -uninstall,deb rpm flatpak) \
        install-all smoke-all uninstall-all installed report \
        weston-start weston-stop weston-status system-bus clean

help:
	@printf '\n  \033[1mOpenEmux test container\033[0m -- %s, %s session\n\n' "$(PRETTY)" "$(SESSION)"
	@printf '  install    %s\n' "$(addsuffix -install,$(FORMATS))"
	@printf '  run        %s\n' "$(addsuffix -run,$(FORMATS))"
	@printf '  smoke      %s\n' "$(addsuffix -smoke,$(FORMATS))"
	@printf '  uninstall  %s\n\n' "$(addsuffix -uninstall,$(filter-out appimage,$(FORMATS)))"
	@printf '  batch      install-all  smoke-all  uninstall-all\n'
	@printf '  info       env  installed  report\n'
	@printf '  session    weston-start  weston-stop  weston-status\n\n'
	@printf '  artifacts in %s:\n' "$(DIST)"
	@$(foreach f,$(APPIMAGE) $(DEB) $(RPM) $(BUNDLE),printf '    %s\n' "$(notdir $(f))";)
	@printf '\n'

env:
	@printf 'distro     %s (%s family)\n' "$(PRETTY)" "$(FAMILY)"
	@printf 'session    %s\n' "$(SESSION)"
	@printf 'DISPLAY    %s\n' "$${DISPLAY:-<unset>}"
	@printf 'WAYLAND    %s\n' "$${WAYLAND_DISPLAY:-<unset>}"
	@printf 'dist       %s\n' "$(DIST)"
	@printf 'work       %s\n' "$(WORK)"
	@printf 'flatpak    %s\n' "$${FLATPAK_USER_DIR:-<default>}"
	@printf 'home       %s\n' "$(HOME)"

# --- guards ---------------------------------------------------------------
#
# Every target says what is missing and how to get it, rather than failing
# somewhere deep in apt.

define require_file
@[ -n "$(1)" ] && [ -r "$(1)" ] || { \
	printf '\033[1;31m==> no %s in %s\033[0m\n' "$(2)" "$(DIST)" >&2; \
	printf '    build it on the host: make %s\n' "$(3)" >&2; exit 1; }
endef

define require_family
@[ "$(FAMILY)" = "$(1)" ] || { \
	printf '\033[1;31m==> the %s is only tested on %s containers\033[0m\n' "$(2)" "$(1)" >&2; \
	printf '    this one is %s\n' "$(PRETTY)" >&2; exit 1; }
endef

$(WORK):
	@mkdir -p $(WORK)/logs $(WORK)/shots

# --- AppImage (every distro) ----------------------------------------------

appimage-install: | $(WORK)
	$(call require_file,$(APPIMAGE),AppImage,appimage)
	@printf '\033[1;34m==>\033[0m staging %s\n' "$(notdir $(APPIMAGE))"
	@cp -f "$(APPIMAGE)" "$(APPIMAGE_LOCAL)"
	@chmod +x "$(APPIMAGE_LOCAL)"
	@printf '    %s\n' "$(APPIMAGE_LOCAL)"

# The AppImage runtime mounts itself through libfuse2. A container without
# /dev/fuse cannot do that, so fall back to self-extraction -- and say which
# path ran, because only the first one is what users get.
define run_appimage
@[ -x "$(APPIMAGE_LOCAL)" ] || $(MAKE) -s -C $(KIT) appimage-install
@cd $(WORK) && if [ -e /dev/fuse ]; then \
	$(LAUNCH) --label appimage $(1) -- "$(APPIMAGE_LOCAL)"; \
	else \
	printf '\033[1;33m==> no /dev/fuse: running via extract-and-run\033[0m\n'; \
	APPIMAGE_EXTRACT_AND_RUN=1 $(LAUNCH) --label appimage $(1) -- "$(APPIMAGE_LOCAL)"; \
	fi
endef

appimage-run: | $(WORK)
	$(call run_appimage,)

appimage-smoke: | $(WORK)
	$(call run_appimage,--smoke $(SMOKE_SECONDS))

# --- .deb (ubuntu, debian) ------------------------------------------------

deb-install:
	$(call require_family,debian,.deb)
	$(call require_file,$(DEB),.deb,deb)
	@printf '\033[1;34m==>\033[0m installing %s\n' "$(notdir $(DEB))"
	@sudo apt-get update -qq
	@sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$(DEB)"
	@printf '    installed: %s\n' "$(APP_BIN)"
	@shadow=$$(command -v openemux || true); \
	if [ -n "$$shadow" ] && [ "$$shadow" != "$(APP_BIN)" ]; then \
	  printf '\033[1;33m    note: PATH resolves openemux to %s (leaked in from the host);\n' "$$shadow"; \
	  printf '          the run/smoke targets use %s regardless\033[0m\n' "$(APP_BIN)"; \
	fi

deb-run: | $(WORK)
	$(call require_family,debian,.deb)
	@cd $(WORK) && $(LAUNCH) --label deb -- $(APP_BIN)

deb-smoke: | $(WORK)
	$(call require_family,debian,.deb)
	@cd $(WORK) && $(LAUNCH) --label deb --smoke $(SMOKE_SECONDS) -- $(APP_BIN)

deb-uninstall:
	$(call require_family,debian,.deb)
	@sudo apt-get remove -y openemux

# --- .rpm (fedora) --------------------------------------------------------

rpm-install:
	$(call require_family,fedora,.rpm)
	$(call require_file,$(RPM),.rpm,rpm)
	@printf '\033[1;34m==>\033[0m installing %s\n' "$(notdir $(RPM))"
	@sudo dnf install -y "$(RPM)"
	@printf '    installed: %s\n' "$(APP_BIN)"
	@shadow=$$(command -v openemux || true); \
	if [ -n "$$shadow" ] && [ "$$shadow" != "$(APP_BIN)" ]; then \
	  printf '\033[1;33m    note: PATH resolves openemux to %s (leaked in from the host);\n' "$$shadow"; \
	  printf '          the run/smoke targets use %s regardless\033[0m\n' "$(APP_BIN)"; \
	fi

rpm-run: | $(WORK)
	$(call require_family,fedora,.rpm)
	@cd $(WORK) && $(LAUNCH) --label rpm -- $(APP_BIN)

rpm-smoke: | $(WORK)
	$(call require_family,fedora,.rpm)
	@cd $(WORK) && $(LAUNCH) --label rpm --smoke $(SMOKE_SECONDS) -- $(APP_BIN)

rpm-uninstall:
	$(call require_family,fedora,.rpm)
	@sudo dnf remove -y openemux

# --- Flatpak (every distro) -----------------------------------------------
#
# `run --user` rather than plain `run`: a container image has no system
# installation, and flatpak refuses to start when it cannot open
# /var/lib/flatpak/repo -- which nothing on Fedora ever creates.
#
# --user into FLATPAK_USER_DIR, which the container driver points at a
# directory shared by the whole matrix: the GNOME runtime is downloaded once
# instead of six times, and the developer's own Flatpak installation is never
# touched.

# Before installing an app, Flatpak asks the *system* bus about parental
# controls, and a container image starts no bus at all -- the install then dies
# with "Could not connect: No such file or directory", well after downloading
# the whole GNOME runtime. One is started here instead.
system-bus:
	@[ -S /run/dbus/system_bus_socket ] || { \
	  printf '\033[1;34m==>\033[0m starting a system dbus (flatpak needs one)\n'; \
	  sudo mkdir -p /run/dbus && sudo dbus-daemon --system --fork; }

flatpak-install: system-bus
	$(call require_file,$(BUNDLE),.flatpak bundle,flatpak)
	@printf '\033[1;34m==>\033[0m installing %s (pulls the GNOME runtime on first run)\n' "$(notdir $(BUNDLE))"
	@flatpak --user remote-add --if-not-exists flathub \
	    https://dl.flathub.org/repo/flathub.flatpakrepo
	@# The installation is shared by the whole matrix, so from the second
	@# container on the app is already there and the install would just
	@# error out. --reinstall does not apply to bundles, so the old copy is
	@# removed first -- which also guarantees the artifact under test is
	@# the one that ends up installed.
	@if flatpak info --user $(APP_ID) >/dev/null 2>&1; then \
	  printf '    replacing the copy already in the shared installation\n'; \
	  flatpak uninstall --user --noninteractive --assumeyes $(APP_ID) >/dev/null; \
	fi
	@flatpak install --user --noninteractive --assumeyes "$(BUNDLE)"
	@flatpak list --user --app --columns=application,version

flatpak-run: system-bus | $(WORK)
	@cd $(WORK) && $(LAUNCH) --label flatpak -- \
	    flatpak run --user --env=GDK_BACKEND=$(FLATPAK_BACKEND) $(APP_ID)

flatpak-smoke: system-bus | $(WORK)
	@cd $(WORK) && $(LAUNCH) --label flatpak --smoke $(SMOKE_SECONDS) -- \
	    flatpak run --user --env=GDK_BACKEND=$(FLATPAK_BACKEND) $(APP_ID)

flatpak-uninstall:
	@flatpak uninstall --user --noninteractive --assumeyes $(APP_ID)

# --- batches --------------------------------------------------------------

install-all: $(addsuffix -install,$(FORMATS))

# Serial on purpose: they all want the same screen.
smoke-all:
	@rc=0; for f in $(FORMATS); do \
	  $(MAKE) -s -C $(KIT) $$f-install || { rc=1; continue; }; \
	  $(MAKE) -s -C $(KIT) $$f-smoke  || rc=1; \
	done; \
	$(MAKE) -s -C $(KIT) report; \
	exit $$rc

uninstall-all:
	@for f in $(filter-out appimage,$(FORMATS)); do \
	  $(MAKE) -s -C $(KIT) $$f-uninstall || true; \
	done
	@rm -f "$(APPIMAGE_LOCAL)"

installed:
	@printf '\033[1;34m==>\033[0m native package\n'
	@if [ "$(FAMILY)" = debian ]; then dpkg -l openemux 2>/dev/null | tail -n +6 || echo '    not installed'; \
	else rpm -q openemux 2>/dev/null || echo '    not installed'; fi
	@printf '\033[1;34m==>\033[0m appimage\n'
	@[ -x "$(APPIMAGE_LOCAL)" ] && printf '    %s\n' "$(APPIMAGE_LOCAL)" || echo '    not staged'
	@printf '\033[1;34m==>\033[0m flatpak\n'
	@flatpak list --user --app --columns=application,version 2>/dev/null | grep -q . \
	  && flatpak list --user --app --columns=application,version | sed 's/^/    /' \
	  || echo '    not installed'

report:
	@printf '\n\033[1m  evidence for %s\033[0m\n\n' "$(TESTENV)"
	@ls -1 $(WORK)/shots 2>/dev/null | sed 's|^|    shot  $(WORK)/shots/|' || true
	@ls -1 $(WORK)/logs  2>/dev/null | sed 's|^|    log   $(WORK)/logs/|'  || true
	@printf '\n'

# --- session --------------------------------------------------------------

weston-start:
	@$(WESTON) start

weston-stop:
	@$(WESTON) stop

weston-status:
	@$(WESTON) status

clean:
	@rm -rf $(WORK)/logs $(WORK)/shots "$(APPIMAGE_LOCAL)"
	@printf 'cleaned %s\n' "$(WORK)"

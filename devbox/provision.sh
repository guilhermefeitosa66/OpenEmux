#!/usr/bin/env bash
#
# Runs INSIDE the devbox, once. Installs the graphical session, the automation
# tools and the GTK stack the app runs against, then puts the devbox-* commands
# on PATH.
#
#   bash /openemux/devkit/provision.sh
#
# Everything comes from apt. There is deliberately no venv in here: the app's
# three runtime dependencies (PyGObject, PyYAML, python-xlib) all ship as
# distro packages, and a venv built inside a container that mounts the host's
# home is one more way for the host's interpreter to end up in the loop.
set -euo pipefail

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

. /etc/os-release
case "${ID}${ID_LIKE:-}" in
	*debian*|*ubuntu*) ;;
	*) die "the devbox is an Ubuntu LTS image; this one is ${PRETTY_NAME}" ;;
esac

info "provisioning ${PRETTY_NAME}"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq

pkgs=(
	ca-certificates curl file make procps psmisc locales

	# The graphical session. tigervnc gives an X server that is headless by
	# default and viewable on demand; openbox supplies the EWMH that wmctrl
	# resizes through and the focus that keystrokes need.
	tigervnc-standalone-server tigervnc-common openbox
	xauth x11-utils x11-xserver-utils dbus-x11

	# Driving it, and the evidence.
	xdotool wmctrl imagemagick ffmpeg

	# GTK4 + libadwaita, plus the introspection data PyGObject reads. The
	# -dev packages the project's install-sys-deps pulls are for *building*
	# PyGObject; python3-gi is already built here.
	python3-gi python3-gi-cairo
	gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-rsvg-2.0

	# The app's own runtime imports (requirements.txt).
	python3-yaml python3-xlib

	# GTK4 renders through GL and a virtual display has no GPU, so without
	# the software rasteriser the app either falls back silently or aborts
	# at window construction -- which reads as an app bug.
	libgl1-mesa-dri libglx-mesa0 libegl-mesa0

	# What the UI is drawn with. Missing icons and fonts do not stop the
	# app; they quietly make every screenshot wrong.
	adwaita-icon-theme fonts-cantarell
	gsettings-desktop-schemas dconf-gsettings-backend
)
sudo apt-get install -y --no-install-recommends "${pkgs[@]}"

# The UI language for anything captured in here. English, because that is what
# the project writes its issues and screenshots in -- and because leaving it to
# the container's default gives a C locale and a subtly different layout.
sudo sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen
sudo locale-gen >/dev/null
sudo tee /etc/profile.d/devbox-locale.sh >/dev/null <<-'EOF'
	export LANG=en_US.UTF-8
	export LC_ALL=en_US.UTF-8
EOF

# The tools go on PATH under /usr/local/bin, which belongs to the container.
# Symlinks, not copies: the kit is bind-mounted from the checkout, so editing a
# tool on the host takes effect on the next call with nothing to reinstall.
# The executable bit comes from the checkout -- the kit is mounted read-only,
# so it cannot be set from in here, and git is what has to carry it.
info "linking the devbox-* tools into /usr/local/bin"
sudo ln -sf /openemux/devkit/bin/devbox-* /usr/local/bin/
for tool in /openemux/devkit/bin/devbox-*; do
	[ -x "${tool}" ] || die "${tool} is not executable in the checkout: git update-index --chmod=+x ${tool#/openemux/devkit/}"
done

# Belongs to the container, not to its home: the home outlives the container
# (removing one keeps it, and a later create reuses it), so a marker kept there
# would report a brand-new container as provisioned.
sudo mkdir -p /var/lib/openemux-devbox
sudo touch /var/lib/openemux-devbox/provisioned
info "provisioned -- devbox-verify says whether it works"

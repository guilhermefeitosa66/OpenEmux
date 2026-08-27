#!/usr/bin/env bash
#
# Runs INSIDE a freshly created test container, once. Installs what the
# container needs to behave like a desktop: a GL stack for GTK4, fuse for the
# AppImage, flatpak for the bundle, and -- for the wayland half of the matrix
# -- weston, which provides the Wayland session the host does not have.
#
#   bash /openemux/testkit/provision.sh <x11|wayland>
#
# The app packages themselves are NOT installed here; that is what the
# in-container `make deb-install` & friends are for.

set -euo pipefail

SESSION=${1:-${OPENEMUX_SESSION:-x11}}

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

. /etc/os-release
FAMILY=unknown
case "${ID}${ID_LIKE:-}" in
	*fedora*|*rhel*) FAMILY=fedora ;;
	*debian*|*ubuntu*) FAMILY=debian ;;
esac
[ "${FAMILY}" != unknown ] || die "unsupported base image: ${ID}"

info "provisioning ${PRETTY_NAME} for a ${SESSION} session"

if [ "${FAMILY}" = debian ]; then
	export DEBIAN_FRONTEND=noninteractive
	sudo apt-get update -qq
	pkgs=(
		make ca-certificates curl file procps psmisc
		xauth dbus-x11
		# xdotool finds the app's window so a screenshot captures it alone
		# and not the developer's whole desktop
		xdotool
		# GTK4 renders through GL; without the DRI drivers it falls back to
		# software or refuses to start, which would look like an app bug.
		libgl1-mesa-dri libglx-mesa0 mesa-vulkan-drivers
		fonts-cantarell adwaita-icon-theme
		# `import`, for the screenshot the smoke targets take
		imagemagick
		flatpak
	)
	# The *vendored RetroArch* AppImage needs libfuse2 -- OpenEmux's own
	# bundle carries a static FUSE 3 runtime and no longer asks for it
	# (issue #248). Noble and trixie renamed the package in the 64-bit
	# time_t transition; older bases still carry the old name.
	if apt-cache show libfuse2t64 >/dev/null 2>&1; then
		pkgs+=(libfuse2t64)
	else
		pkgs+=(libfuse2)
	fi
	[ "${SESSION}" = wayland ] && pkgs+=(weston)
	sudo apt-get install -y --no-install-recommends "${pkgs[@]}"
else
	pkgs=(
		make ca-certificates curl file procps-ng psmisc
		xorg-x11-xauth dbus-x11 dbus-daemon
		xdotool
		# mesa-dri-drivers alone is not enough: GTK4's GL renderer wants
		# libGLESv2, and without it the app aborts at window construction.
		mesa-dri-drivers mesa-vulkan-drivers mesa-libGLES mesa-libEGL mesa-libGL
		google-noto-sans-fonts abattis-cantarell-fonts adwaita-icon-theme
		ImageMagick
		# For the vendored RetroArch AppImage (issue #248): fuse-libs is
		# the library, and `fuse` is what carries the fusermount binary
		# its runtime actually execs.
		fuse-libs fuse
		flatpak
	)
	[ "${SESSION}" = wayland ] && pkgs+=(weston)
	sudo dnf install -y --setopt=install_weak_deps=False "${pkgs[@]}"
fi

# Flathub, in the per-matrix Flatpak installation (FLATPAK_USER_DIR is set on
# the container). Shared by every test container: runtimes are self-contained,
# so one ~1 GB copy of org.gnome.Platform serves all six -- and none of it
# touches the developer's own ~/.local/share/flatpak.
if [ -n "${FLATPAK_USER_DIR:-}" ]; then
	info "flatpak installation: ${FLATPAK_USER_DIR}"
	mkdir -p "${FLATPAK_USER_DIR}"
fi
flatpak --user remote-add --if-not-exists flathub \
	https://dl.flathub.org/repo/flathub.flatpakrepo || \
	printf '\033[1;33m==> could not add flathub; flatpak-install will fail\033[0m\n' >&2

# The marker belongs to the *container*, not to the home: homes outlive the
# containers that used them (recreate one and the home is still there), and a
# marker kept there would declare a brand-new, empty container provisioned.
sudo mkdir -p /var/lib/openemux-testenv
sudo touch /var/lib/openemux-testenv/provisioned
info "provisioned"

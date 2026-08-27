#!/usr/bin/env bash
#
# Host-side driver for the OpenEmux devbox: one distrobox container on the
# current Ubuntu LTS, with an X server of its own, where the app runs from this
# checkout without taking over the developer's screen.
#
#   devbox/devbox.sh up               create, provision, start the session
#   devbox/devbox.sh app start        launch the app on the virtual display
#   devbox/devbox.sh shot /tmp/a.png  capture it
#   devbox/devbox.sh xdo key ctrl+f   drive it
#
# The Makefile wraps this: `make devbox`, `make devbox-shot`, ...
#
# This is NOT packaging/testenv/. That matrix installs *release artifacts* the
# way a user would, borrowing the developer's real display -- which is exactly
# what makes it unusable while somebody is working. This one runs the *source*,
# on a display nobody is looking at.
#
# Mounted in:
#   /openemux/devkit          this directory (read-only), holding the tools
#   <checkout>                at its real path, so edits are live
#
# The container gets a HOME of its own under DEVBOX_ROOT. That is the whole
# point: ~/.openemux in there is throwaway, and the developer's real config,
# library and playlists are never opened.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

NAME=${DEVBOX_NAME:-openemux-devbox}
# The current Ubuntu LTS, on purpose, and not the 24.04 the packages target:
# this container is where the app is developed, so it should be the newer GTK
# and libadwaita -- the floor is what packaging/testenv/ is for.
IMAGE=${DEVBOX_IMAGE:-ubuntu:26.04}
DEVBOX_ROOT=${DEVBOX_ROOT:-${XDG_DATA_HOME:-${HOME}/.local/share}/openemux-devbox}
BOX_HOME="${DEVBOX_ROOT}/home"

# See devbox/lib.sh for why :77 and why loopback.
DEVBOX_DISPLAY=${DEVBOX_DISPLAY:-:77}
DEVBOX_VNC_PORT=${DEVBOX_VNC_PORT:-5977}
DEVBOX_GEOMETRY=${DEVBOX_GEOMETRY:-1600x1000}
#: A real ROM library to use instead of the synthetic one. Empty by default --
#: see devbox-seed for why a synthetic library is the better default.
DEVBOX_ROMS=${DEVBOX_ROMS:-}

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
	cat <<-EOF
	usage: devbox.sh <command> [args]

	  up                       create if needed, provision, start the session
	  enter                    open a shell inside it
	  exec <cmd...>            run a command inside it

	  app start|stop|restart|status|log     the app on the virtual display
	  seed [--wipe]            (re)build the throwaway config and library
	  shot [--win] [path]      screenshot
	  xdo <xdotool args...>    drive the app's window
	  res [WxH]                resize the virtual screen
	  rec start|stop|status    record it
	  tests [args...]          the unit suite, on a real display
	  verify                   is this container able to run the app?

	  view                     open a VNC viewer on the session
	  status                   container, session and app at a glance
	  x start|stop|restart     the virtual display itself
	  rm [--purge]             delete the container (--purge drops its home)
	EOF
}

container_manager() {
	command -v podman 2>/dev/null || command -v docker 2>/dev/null || true
}

require_distrobox() {
	command -v distrobox >/dev/null 2>&1 || die \
		"distrobox not found. Install it with: make distrobox-install"
	[ -n "$(container_manager)" ] || die \
		"neither podman nor docker found -- distrobox needs one of them"
}

# The listing is captured, then matched. Piping it into `grep -q` works
# only while the output stays short enough for the producer to finish
# before grep exits: past that, SIGPIPE plus pipefail reports "no such
# container" for one that is right there.
container_exists() {
	local names
	names=$(distrobox list --no-color 2>/dev/null \
		| awk -F'|' 'NR>1 {gsub(/ /,"",$2); print $2}')
	grep -qx "${NAME}" <<<"${names}"
}

create_container() {
	case "${REPO_ROOT}${SCRIPT_DIR}" in
		*" "*) die "paths with spaces break distrobox --volume; move the checkout" ;;
	esac
	mkdir -p "${BOX_HOME}"

	# The checkout has to be reachable at its real path. When it lives under
	# the home, distrobox already mounts it there and a second --volume for the
	# same path is refused; when it does not, it has to be asked for.
	local -a extra=()
	case "${REPO_ROOT}/" in
		"${HOME}"/*) ;;
		*) extra+=(--volume "${REPO_ROOT}:${REPO_ROOT}:rw") ;;
	esac
	[ -n "${DEVBOX_ROMS}" ] && extra+=(--volume "${DEVBOX_ROMS}:/openemux/roms:rw")

	info "creating ${NAME} from ${IMAGE}"
	# distrobox on Docker prints "openat dev/ptmx: no such device" and exits
	# non-zero for some images while still creating a working container, so the
	# exit status is not the question -- whether the container exists is.
	distrobox create \
		--name "${NAME}" \
		--image "${IMAGE}" \
		--home "${BOX_HOME}" \
		--volume "${SCRIPT_DIR}:/openemux/devkit:ro" \
		"${extra[@]}" \
		--additional-flags "--env DEVBOX_REPO=${REPO_ROOT} \
			--env DEVBOX_DISPLAY=${DEVBOX_DISPLAY} \
			--env DEVBOX_VNC_PORT=${DEVBOX_VNC_PORT} \
			--env DEVBOX_GEOMETRY=${DEVBOX_GEOMETRY} \
			--env DEVBOX_ROMS=${DEVBOX_ROMS:+/openemux/roms}" \
		--yes || {
		container_exists || die "could not create ${NAME}"
		warn "create reported an error but ${NAME} exists -- continuing"
	}
}

start_and_wait() {
	local cm attempt=0 waited=0
	cm=$(container_manager)
	[ -n "${cm}" ] || return 0

	until "${cm}" start "${NAME}" >/dev/null 2>&1; do
		attempt=$((attempt + 1))
		[ "${attempt}" -lt 5 ] || die "could not start ${NAME}"
		warn "start failed, retrying (${attempt}/4)"
		sleep 2
	done

	# First boot installs the container's own base packages; distrobox-init
	# announces the end of that on stdout. Entering before it finishes fails
	# with "unable to find user", which looks like a broken image.
	local logs
	while [ "${waited}" -lt 900 ]; do
		logs=$("${cm}" logs "${NAME}" 2>&1 || true)
		if grep -q 'container_setup_done' <<<"${logs}"; then
			[ "${waited}" -gt 0 ] && printf '\n'
			return 0
		fi
		[ "${waited}" = 0 ] && printf '\033[1;34m==>\033[0m waiting for the container init (first boot)'
		printf '.'
		sleep 3
		waited=$((waited + 3))
	done
	printf '\n'
	die "${NAME} did not finish initialising -- see: $(container_manager) logs ${NAME}"
}

provisioned() {
	local cm; cm=$(container_manager)
	[ -n "${cm}" ] || return 1
	"${cm}" exec "${NAME}" test -e /var/lib/openemux-devbox/provisioned 2>/dev/null
}

provision() {
	if [ "${FORCE_PROVISION:-0}" != "1" ] && provisioned; then
		return 0
	fi
	info "provisioning ${NAME} (first run: installs the desktop bits it needs)"
	if ! distrobox enter --name "${NAME}" -- bash /openemux/devkit/provision.sh; then
		warn "provisioning failed; restarting ${NAME} and retrying once"
		start_and_wait
		distrobox enter --name "${NAME}" -- bash /openemux/devkit/provision.sh
	fi
}

# Everything that runs inside goes through here. --no-tty keeps the output
# clean enough to pipe: distrobox allocates a terminal otherwise, and the
# escape codes end up in whatever is capturing the result.
inside() {
	distrobox enter --no-tty --name "${NAME}" -- "$@"
}

cmd_up() {
	require_distrobox
	container_exists || create_container
	start_and_wait
	provision
	inside devbox-x start
}

ensure_up() {
	require_distrobox
	container_exists || cmd_up
}

cmd_view() {
	local addr="127.0.0.1:${DEVBOX_VNC_PORT}"
	local viewer
	for viewer in vncviewer xtightvncviewer gvncviewer remmina vinagre; do
		if command -v "${viewer}" >/dev/null 2>&1; then
			info "${viewer} ${addr}"
			case "${viewer}" in
				remmina) exec remmina -c "vnc://${addr}" ;;
				*) exec "${viewer}" "${addr}" ;;
			esac
		fi
	done
	warn "no VNC viewer on this host. The session is waiting at ${addr}:"
	printf '    sudo apt install tigervnc-viewer   # then: vncviewer %s\n' "${addr}" >&2
	printf '    or capture it instead:  make devbox-shot OUT=/tmp/devbox.png\n' >&2
	exit 1
}

cmd_status() {
	printf 'container   %s (%s)\n' "${NAME}" "${IMAGE}"
	printf 'home        %s\n' "${BOX_HOME}"
	printf 'checkout    %s\n' "${REPO_ROOT}"
	printf 'captures    %s/devbox-out\n' "${BOX_HOME}"
	printf 'vnc         127.0.0.1:%s\n\n' "${DEVBOX_VNC_PORT}"
	if ! container_exists; then
		printf 'not created yet -- make devbox-up\n'
		return 0
	fi
	distrobox list | awk -v n="${NAME}" 'NR==1 || index($0, n)'
	printf '\n'
	inside devbox-x status 2>/dev/null || printf 'session     down\n'
	inside devbox-app status 2>/dev/null || true
}

cmd_rm() {
	local purge=0
	[ "${1:-}" = "--purge" ] && purge=1
	require_distrobox
	if container_exists; then
		inside devbox-x stop >/dev/null 2>&1 || true
		info "removing ${NAME}"
		distrobox rm --force "${NAME}" >/dev/null
	else
		warn "${NAME} does not exist"
	fi
	if [ "${purge}" = 1 ]; then
		info "purging ${BOX_HOME}"
		rm -rf "${BOX_HOME:?}"
	fi
}

main() {
	local cmd=${1:-}
	[ $# -gt 0 ] && shift || true
	case "${cmd}" in
		up)      cmd_up ;;
		enter)
			ensure_up
			distrobox enter --name "${NAME}" -- bash -lc \
				'devbox-x start >/dev/null; devbox-verify; exec bash'
			;;
		exec)    ensure_up; inside "$@" ;;

		# The tools, one for one. Each ensures the container is up first, so a
		# single command from a cold start does the right thing.
		app)     ensure_up; inside devbox-app "$@" ;;
		seed)    ensure_up; inside devbox-seed "$@" ;;
		shot)    ensure_up; inside devbox-shot "$@" ;;
		xdo)     ensure_up; inside devbox-xdo "$@" ;;
		res)     ensure_up; inside devbox-res "$@" ;;
		rec)     ensure_up; inside devbox-rec "$@" ;;
		tests)   ensure_up; inside devbox-tests "$@" ;;
		verify)  ensure_up; inside devbox-verify ;;
		x)       ensure_up; inside devbox-x "$@" ;;

		view)    cmd_view ;;
		status)  cmd_status ;;
		rm)      cmd_rm "$@" ;;
		-h|--help|help|"") usage ;;
		*) usage; exit 1 ;;
	esac
}

main "$@"

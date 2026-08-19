#!/usr/bin/env bash
#
# Host-side driver for the OpenEmux distrobox test matrix.
#
# One container per (distro, session) pair. Each one is a throwaway desktop
# where the release artifacts in dist/ get installed and launched the way a
# user would, so a packaging regression shows up here instead of in an issue.
#
#   packaging/testenv/testenv.sh up ubuntu x11
#   packaging/testenv/testenv.sh rm fedora wayland
#   packaging/testenv/testenv.sh list
#
# The Makefile wraps this: `make ubuntu-x11`, `make testenv-list`, ...
#
# Two things are mounted into every container:
#   /openemux/dist      <- DIST_DIR (read-only, so a test can never eat a
#                          release artifact)
#   /openemux/testkit   <- this directory, holding the in-container Makefile
#
# Each container gets its OWN home under TESTENV_ROOT/homes/<name>. That is the
# whole point: ~/.openemux starts empty, so first-boot bootstrap runs for real
# and the developer's actual library and config are never touched. The real
# home is still mounted at its usual path by distrobox, so absolute paths into
# the checkout keep working.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)

# Where the artifacts to test live. Override when driving the matrix from a
# worktree, whose own dist/ is empty:
#   make ubuntu-x11 DIST_DIR=/path/to/main/checkout/dist
DIST_DIR=${DIST_DIR:-${REPO_ROOT}/dist}

# Container homes and the shared Flatpak installation.
TESTENV_ROOT=${TESTENV_ROOT:-${XDG_DATA_HOME:-${HOME}/.local/share}/openemux-testenv}

# Base images. Ubuntu 24.04 and Fedora 40 are the floors the packages target
# (libadwaita >= 1.5); Debian's first release that clears that floor is 13
# (trixie) -- bookworm ships libadwaita 1.2 and cannot install the .deb at all.
# Override to test a newer LTS: `make ubuntu-x11 UBUNTU_IMAGE=ubuntu:26.04`.
UBUNTU_IMAGE=${UBUNTU_IMAGE:-ubuntu:24.04}
DEBIAN_IMAGE=${DEBIAN_IMAGE:-debian:13}
FEDORA_IMAGE=${FEDORA_IMAGE:-fedora:42}

PREFIX=openemux

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m==> %s\033[0m\n' "$*" >&2; }
die()   { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
	cat <<-EOF
	usage: testenv.sh <command> [args]

	  up <distro> <session>       create if needed, provision, then enter
	  create <distro> <session>   create + provision, do not enter
	  enter <distro> <session>    enter an existing container
	  run <distro> <session> <target...>
	                              run in-container make targets and exit
	  rm <distro> <session>       delete the container (keeps its home)
	  rm --purge <distro> <session>
	                              delete the container AND its home
	  rm-all [--purge]            delete every openemux-* test container
	  list                        list the test containers
	  status                      containers + artifacts found in dist/
	  install-distrobox           install distrobox on the host (needs sudo)

	  distro:  ubuntu | debian | fedora
	  session: x11 | wayland
	EOF
}

image_for() {
	case "$1" in
		ubuntu) printf '%s' "${UBUNTU_IMAGE}" ;;
		debian) printf '%s' "${DEBIAN_IMAGE}" ;;
		fedora) printf '%s' "${FEDORA_IMAGE}" ;;
		*) die "unknown distro '$1' (ubuntu|debian|fedora)" ;;
	esac
}

check_session() {
	case "$1" in
		x11|wayland) ;;
		*) die "unknown session '$1' (x11|wayland)" ;;
	esac
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

container_exists() {
	distrobox list --no-color 2>/dev/null | awk -F'|' 'NR>1 {gsub(/ /,"",$2); print $2}' \
		| grep -qx "$1"
}

# The dist/ bind is fixed when the container is created. Point DIST_DIR
# somewhere else later and the container would keep serving the old artifacts,
# silently -- so say so instead.
check_dist_mount() {
	local name=$1 cm current
	cm=$(container_manager)
	[ -n "${cm}" ] || return 0
	current=$("${cm}" inspect "${name}" \
		--format '{{range .Mounts}}{{if eq .Destination "/openemux/dist"}}{{.Source}}{{end}}{{end}}' \
		2>/dev/null || true)
	if [ -n "${current}" ] && [ "${current}" != "${DIST_DIR}" ]; then
		warn "${name} serves artifacts from ${current}, not ${DIST_DIR}."
		warn "Recreate it to switch: testenv.sh rm ${name#${PREFIX}-} && ..."
	fi
}

# distrobox's own `enter` waits for the container init only when it finds the
# container stopped. That is fine on its own, but `create` can leave a
# container created-and-not-started while returning an error (see
# create_container); the next `enter` then finds it running, skips the wait,
# races the init and fails with "unable to find user". Starting and waiting
# explicitly, here, takes the ordering out of distrobox's hands.
start_and_wait() {
	local name=$1 cm attempt=0
	cm=$(container_manager)
	[ -n "${cm}" ] || return 0

	until "${cm}" start "${name}" >/dev/null 2>&1; do
		attempt=$((attempt + 1))
		[ "${attempt}" -lt 5 ] || die "could not start ${name}"
		warn "start failed, retrying (${attempt}/4)"
		sleep 2
	done

	# First boot installs the container's own base packages, which is slow;
	# distrobox-init announces the end of it on stdout.
	local waited=0
	while [ "${waited}" -lt 900 ]; do
		if "${cm}" logs "${name}" 2>&1 | grep -q 'container_setup_done'; then
			[ "${waited}" -gt 0 ] && printf '\n'
			return 0
		fi
		if [ "${waited}" = 0 ]; then
			printf '\033[1;34m==>\033[0m waiting for the container init (first boot)'
		fi
		printf '.'
		sleep 3
		waited=$((waited + 3))
	done
	printf '\n'
	die "${name} did not finish initialising -- see: ${cm} logs ${name}"
}

create_container() {
	local distro=$1 session=$2
	local name="${PREFIX}-${distro}-${session}"
	local image home
	image=$(image_for "${distro}")
	home="${TESTENV_ROOT}/homes/${distro}-${session}"

	case "${DIST_DIR}${SCRIPT_DIR}" in
		*" "*) die "paths with spaces break distrobox --volume; move the checkout" ;;
	esac
	[ -d "${DIST_DIR}" ] || die "no such directory: ${DIST_DIR}
Build the artifacts first (make packages), or pass DIST_DIR=<path>."

	mkdir -p "${home}" "${TESTENV_ROOT}/flatpak"

	info "creating ${name} from ${image}"
	# On Docker, `distrobox create` prints "openat dev/ptmx: no such device"
	# and exits non-zero for some images -- reproducibly for debian:13 -- while
	# still creating a perfectly good container. So the exit status alone is
	# not the question; whether the container exists is.
	distrobox create \
		--name "${name}" \
		--image "${image}" \
		--home "${home}" \
		--volume "${DIST_DIR}:/openemux/dist:ro" \
		--volume "${SCRIPT_DIR}:/openemux/testkit:ro" \
		--additional-flags "--env OPENEMUX_SESSION=${session} --env OPENEMUX_TESTENV=${distro}-${session} --env FLATPAK_USER_DIR=${TESTENV_ROOT}/flatpak" \
		--yes || {
		container_exists "${name}" || die "could not create ${name}"
		warn "create reported an error but ${name} exists -- continuing"
	}
}

# Provisioning is idempotent and cheap on re-runs; the marker only keeps the
# common case (a plain `make ubuntu-x11`) from paying an apt round-trip.
#
# It is read from inside the container on purpose. The container's home
# outlives the container -- `testenv-rm` keeps it, and a later create reuses
# it -- so a marker stored there would report a fresh, empty container as
# provisioned and leave it without so much as make(1).
provisioned() {
	local cm; cm=$(container_manager)
	[ -n "${cm}" ] || return 1
	"${cm}" exec "$1" test -e /var/lib/openemux-testenv/provisioned 2>/dev/null
}

provision_container() {
	local name=$1 session=$2
	if [ "${FORCE_PROVISION:-0}" != "1" ] && provisioned "${name}"; then
		return 0
	fi
	info "provisioning ${name} (first run: installs the desktop bits it needs)"
	# Provisioning is idempotent, so the same first-operation race gets one
	# retry here rather than aborting a run that is one restart from working.
	if ! distrobox enter --name "${name}" -- \
		bash /openemux/testkit/provision.sh "${session}"; then
		warn "provisioning failed; restarting ${name} and retrying once"
		start_and_wait "${name}"
		distrobox enter --name "${name}" -- \
			bash /openemux/testkit/provision.sh "${session}"
	fi
}

cmd_up() {
	local distro=${1:?distro} session=${2:?session} enter=${3:-enter}
	check_session "${session}"
	local name="${PREFIX}-${distro}-${session}"

	require_distrobox
	if container_exists "${name}"; then
		check_dist_mount "${name}"
	else
		create_container "${distro}" "${session}"
	fi
	start_and_wait "${name}"
	provision_container "${name}" "${session}"

	case "${enter}" in
		no-enter) info "${name} is ready -- enter it with: make ${distro}-${session}" ;;
		*)
			info "entering ${name}"
			distrobox enter --name "${name}" -- \
				bash -lc 'cd /openemux/testkit && make --no-print-directory help; exec bash'
			;;
	esac
}

cmd_run() {
	local distro=${1:?distro} session=${2:?session}; shift 2
	[ $# -gt 0 ] || die "run needs at least one make target"
	check_session "${session}"
	cmd_up "${distro}" "${session}" no-enter
	distrobox enter --name "${PREFIX}-${distro}-${session}" -- \
		make --no-print-directory -C /openemux/testkit "$@"
}

cmd_rm() {
	local purge=0
	if [ "${1:-}" = "--purge" ]; then purge=1; shift; fi
	local distro=${1:?distro} session=${2:?session}
	check_session "${session}"
	local name="${PREFIX}-${distro}-${session}"
	require_distrobox
	if container_exists "${name}"; then
		info "removing ${name}"
		distrobox rm --force "${name}" >/dev/null
	else
		warn "${name} does not exist"
	fi
	if [ "${purge}" = "1" ]; then
		info "purging home ${TESTENV_ROOT}/homes/${distro}-${session}"
		rm -rf "${TESTENV_ROOT:?}/homes/${distro}-${session}"
	fi
}

cmd_rm_all() {
	local purge=${1:-}
	require_distrobox
	local name
	for name in $(distrobox list --no-color 2>/dev/null \
		| awk -F'|' 'NR>1 {gsub(/ /,"",$2); print $2}' | grep "^${PREFIX}-" || true); do
		info "removing ${name}"
		distrobox rm --force "${name}" >/dev/null
	done
	if [ "${purge}" = "--purge" ]; then
		info "purging ${TESTENV_ROOT}/homes"
		rm -rf "${TESTENV_ROOT:?}/homes"
	fi
}

cmd_list() {
	require_distrobox
	distrobox list | awk -v p="${PREFIX}-" 'NR==1 || index($0, p)'
}

cmd_status() {
	printf 'dist dir:      %s\n' "${DIST_DIR}"
	printf 'testenv root:  %s\n' "${TESTENV_ROOT}"
	printf 'host session:  %s (DISPLAY=%s WAYLAND_DISPLAY=%s)\n\n' \
		"${XDG_SESSION_TYPE:-?}" "${DISPLAY:-<unset>}" "${WAYLAND_DISPLAY:-<unset>}"

	printf 'artifacts:\n'
	local found=0 f
	for f in "${DIST_DIR}"/*.AppImage "${DIST_DIR}"/*.deb "${DIST_DIR}"/*.rpm "${DIST_DIR}"/*.flatpak; do
		[ -e "${f}" ] || continue
		found=1
		printf '  %-46s %s\n' "$(basename "${f}")" \
			"$(du -h "${f}" | cut -f1)"
	done
	[ "${found}" = "1" ] || printf '  (none -- run `make packages`)\n'

	printf '\ncontainers:\n'
	cmd_list | sed 's/^/  /'
}

cmd_install_distrobox() {
	if command -v distrobox >/dev/null 2>&1; then
		info "distrobox already installed: $(distrobox version 2>/dev/null | head -1)"
		return 0
	fi
	[ -n "$(container_manager)" ] || warn \
		"no podman/docker on this host -- install one, distrobox needs a container manager"
	info "installing distrobox (upstream installer, needs sudo)"
	curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh
}

main() {
	local cmd=${1:-}
	[ $# -gt 0 ] && shift || true
	case "${cmd}" in
		up)                cmd_up "$@" ;;
		create)            cmd_up "${1:?distro}" "${2:?session}" no-enter ;;
		enter)
			check_session "${2:?session}"
			require_distrobox
			container_exists "${PREFIX}-${1:?distro}-${2}" \
				|| die "${PREFIX}-${1}-${2} does not exist -- create it with: make ${1}-${2}"
			distrobox enter --name "${PREFIX}-${1}-${2}" -- \
				bash -lc 'cd /openemux/testkit && make --no-print-directory help; exec bash'
			;;
		run)               cmd_run "$@" ;;
		rm)                cmd_rm "$@" ;;
		rm-all)            cmd_rm_all "$@" ;;
		list)              cmd_list ;;
		status)            cmd_status ;;
		install-distrobox) cmd_install_distrobox ;;
		-h|--help|help|"") usage ;;
		*) usage; exit 1 ;;
	esac
}

main "$@"

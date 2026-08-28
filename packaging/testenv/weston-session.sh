#!/usr/bin/env bash
#
# The Wayland half of the matrix, inside a test container.
#
# A distrobox container has no display server of its own -- it borrows the
# host's. On an X11 host (the common case for a developer machine) there is no
# Wayland session to borrow, so this starts weston *nested*: a compositor in a
# window, serving its own Wayland socket. The app then really does speak
# Wayland to a real compositor, which is what the test is for.
#
#   weston-session.sh start|stop|status
#
# On a Wayland host it nests inside that compositor instead, so the two
# sessions in the matrix stay symmetrical either way.

set -euo pipefail

# /run/user/$UID is shared with the host and with every other test
# container, so the socket is named per container -- otherwise the Fedora
# container would happily render inside Ubuntu's weston.
SOCKET=${OPENEMUX_WL_SOCKET:-openemux-wl-${OPENEMUX_TESTENV:-local}}
WORK=${OPENEMUX_TESTENV_WORK:-${HOME}/openemux-testenv}
PIDFILE="${WORK}/weston.pid"
LOGFILE="${WORK}/weston.log"
WIDTH=${OPENEMUX_WL_WIDTH:-1440}
HEIGHT=${OPENEMUX_WL_HEIGHT:-900}

: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
SOCKET_PATH="${XDG_RUNTIME_DIR}/${SOCKET}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

running() {
	local pid
	[ -S "${SOCKET_PATH}" ] || return 1
	[ -f "${PIDFILE}" ] || return 1
	pid=$(cat "${PIDFILE}")
	kill -0 "${pid}" 2>/dev/null || return 1
	# The socket file outlives the compositor that created it, and a pid can be
	# reused, so neither on its own means the session is alive -- and answering
	# "already up" for a dead compositor makes the app look like it failed.
	grep -qa weston "/proc/${pid}/cmdline" 2>/dev/null
}

start() {
	mkdir -p "${WORK}"
	if running; then
		info "weston already up on ${SOCKET_PATH}"
		return 0
	fi
	rm -f "${SOCKET_PATH}" "${SOCKET_PATH}.lock" "${PIDFILE}"

	command -v weston >/dev/null 2>&1 || die \
		"weston is not installed -- recreate this container (it is only
provisioned into the *-wayland ones)"

	# Nest into whatever the host offers.
	local backends
	if [ -n "${WAYLAND_DISPLAY:-}" ]; then
		backends="wayland wayland-backend.so"
	elif [ -n "${DISPLAY:-}" ]; then
		backends="x11 x11-backend.so"
	else
		# No host display at all (ssh, CI). Headless still exercises the
		# Wayland code paths; nothing is visible.
		backends="headless headless-backend.so"
	fi

	# weston 13 renamed the backend names (dropping the .so) and replaced
	# --use-pixman with --renderer=pixman, so every combination gets a try
	# before giving up. The software renderer is the last resort: a container
	# without working DRI cannot start the GL one.
	local backend renderer rc=1
	for backend in ${backends}; do
		for renderer in "" "--renderer=pixman" "--use-pixman"; do
			info "starting weston (--backend=${backend} ${renderer:-gl})"
			# shellcheck disable=SC2086
			# --debug is what lets weston-screenshooter attach; without
			# it the protocol answers "unauthorized" and the Wayland half
			# of the matrix produces no evidence.
			setsid weston \
				--backend="${backend}" \
				--socket="${SOCKET}" \
				--width="${WIDTH}" --height="${HEIGHT}" \
				--debug \
				${renderer} >>"${LOGFILE}" 2>&1 &
			echo $! >"${PIDFILE}"

			local waited=0
			while [ "${waited}" -lt 120 ]; do
				if [ -S "${SOCKET_PATH}" ]; then rc=0; break; fi
				kill -0 "$(cat "${PIDFILE}")" 2>/dev/null || break
				sleep 0.25
				waited=$((waited + 1))
			done
			[ "${rc}" = 0 ] && break

			kill "$(cat "${PIDFILE}")" 2>/dev/null || true
			rm -f "${PIDFILE}"
		done
		[ "${rc}" = 0 ] && break
	done

	if [ "${rc}" != 0 ]; then
		printf '\n--- %s (tail) ---\n' "${LOGFILE}" >&2
		tail -n 25 "${LOGFILE}" >&2 || true
		die "weston did not come up"
	fi
	info "weston up: WAYLAND_DISPLAY=${SOCKET}"
}

stop() {
	if [ -f "${PIDFILE}" ]; then
		kill "$(cat "${PIDFILE}")" 2>/dev/null || true
		rm -f "${PIDFILE}"
	fi
	rm -f "${SOCKET_PATH}" "${SOCKET_PATH}.lock"
	info "weston stopped"
}

case "${1:-status}" in
	start) start ;;
	stop) stop ;;
	status)
		if running; then
			printf 'weston up (pid %s) on %s\n' "$(cat "${PIDFILE}")" "${SOCKET_PATH}"
		else
			printf 'weston down\n'; exit 1
		fi
		;;
	*) die "usage: weston-session.sh start|stop|status" ;;
esac

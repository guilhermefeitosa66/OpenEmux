#!/usr/bin/env bash
#
# Launches one installed flavour of OpenEmux inside a test container, with the
# session (X11 or Wayland) the container was created for.
#
#   launch.sh --label deb -- openemux
#   launch.sh --label appimage --smoke 25 -- /path/to/OpenEmux.AppImage
#
# --smoke turns it into a pass/fail check: start the app, take a screenshot
# halfway through, and require it to still be alive when the clock runs out.
# An app that dies on its own before then failed.

set -euo pipefail

LABEL=app
SMOKE=0

while [ $# -gt 0 ]; do
	case "$1" in
		--label) LABEL=$2; shift 2 ;;
		--smoke) SMOKE=$2; shift 2 ;;
		--) shift; break ;;
		*) printf 'launch.sh: unexpected argument %s\n' "$1" >&2; exit 2 ;;
	esac
done
[ $# -gt 0 ] || { printf 'launch.sh: nothing to run\n' >&2; exit 2; }

SESSION=${OPENEMUX_SESSION:-x11}
TESTENV=${OPENEMUX_TESTENV:-local}
WORK=${OPENEMUX_TESTENV_WORK:-${HOME}/openemux-testenv}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "${WORK}/logs" "${WORK}/shots"
LOG="${WORK}/logs/${TESTENV}-${LABEL}.log"
SHOT="${WORK}/shots/${TESTENV}-${LABEL}.png"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; }

: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR

# The screenshot always goes through the host's X display -- on the Wayland
# side the nested compositor is itself a window there, so its contents are in
# the frame either way. Captured before the app env drops DISPLAY.
HOST_DISPLAY=${DISPLAY:-}

# A container with its own $HOME has no ~/.Xauthority; the real one is still
# mounted at the host path, so point at it rather than relying on the host
# happening to allow SI:localuser.
if [ -z "${XAUTHORITY:-}" ] && [ -n "${DISTROBOX_HOST_HOME:-}" ] \
	&& [ -r "${DISTROBOX_HOST_HOME}/.Xauthority" ]; then
	export XAUTHORITY="${DISTROBOX_HOST_HOME}/.Xauthority"
fi

case "${SESSION}" in
	x11)
		[ -n "${DISPLAY:-}" ] || { fail "no DISPLAY -- the host has no X server to borrow"; exit 1; }
		unset WAYLAND_DISPLAY
		export GDK_BACKEND=x11
		info "session: X11 (DISPLAY=${DISPLAY})"
		;;
	wayland)
		: "${OPENEMUX_WL_SOCKET:=openemux-wl-${TESTENV}}"
		export OPENEMUX_WL_SOCKET
		"${SCRIPT_DIR}/weston-session.sh" start
		export WAYLAND_DISPLAY=${OPENEMUX_WL_SOCKET}
		export GDK_BACKEND=wayland
		# Dropped on purpose: with DISPLAY set, GTK (and Flatpak's
		# fallback-x11) would quietly go back to X11 and the Wayland run
		# would prove nothing.
		unset DISPLAY
		info "session: Wayland (WAYLAND_DISPLAY=${WAYLAND_DISPLAY}, nested weston)"
		;;
	*) fail "unknown OPENEMUX_SESSION=${SESSION}"; exit 2 ;;
esac

# Escape hatch for a container whose GL stack cannot serve GTK4's renderer:
#   make deb-run GSK_RENDERER=cairo
[ -n "${GSK_RENDERER:-}" ] && export GSK_RENDERER

# Evidence, captured exactly.
#
# The container borrows the developer's real desktop, so a root-window grab
# would put whatever else is on screen into a file that ends up attached to an
# issue. Both paths below target one window and one window only.

# X11: the app's own window -- but the developer may have their own OpenEmux
# open on the same display, so the one that matters is the one that was not
# there before this run started.
x11_window_ids() {
	[ -n "${HOST_DISPLAY}" ] || return 0
	command -v xdotool >/dev/null 2>&1 || return 0
	DISPLAY="${HOST_DISPLAY}" xdotool search --class '[Oo]pen[Ee]mux' 2>/dev/null || true
}

# $1: how long to keep waiting for the window to show up. A cold AppImage
# takes noticeably longer to paint than an installed package, so the capture
# waits for the window rather than guessing a moment and missing it.
shot_x11() {
	local limit=$1 waited=0 shooter="" wid="" id
	if command -v import >/dev/null 2>&1; then
		shooter="import"
	elif command -v magick >/dev/null 2>&1; then
		shooter="magick import"
	else
		return 0
	fi
	[ -n "${HOST_DISPLAY}" ] || return 0
	command -v xdotool >/dev/null 2>&1 || {
		info "no xdotool: skipping the screenshot (a root grab would take the whole desktop)"
		return 0
	}

	export DISPLAY="${HOST_DISPLAY}"
	while [ "${waited}" -lt "${limit}" ]; do
		for id in $(xdotool search --class '[Oo]pen[Ee]mux' 2>/dev/null); do
			case " ${PRE_IDS} " in *" ${id} "*) continue ;; esac
			wid=${id}
		done
		[ -n "${wid}" ] && break
		sleep 1
		waited=$((waited + 1))
	done
	[ -n "${wid}" ] || { info "no new OpenEmux window: no screenshot"; return 0; }

	# Raise, never activate: the matrix runs while somebody is using the
	# machine, and stealing keyboard focus every 25 seconds is not on.
	xdotool windowraise "${wid}" 2>/dev/null || true
	sleep 2
	${shooter} -window "${wid}" "${SHOT}" 2>/dev/null \
		&& info "screenshot: ${SHOT}"
}

# Wayland: the app has no X window at all. Every container's weston lands on
# the host display under the same name and class, so picking one from the
# outside is guesswork -- weston's own screenshooter, aimed at this
# container's socket, cannot pick the wrong compositor.
shot_wayland() {
	command -v weston-screenshooter >/dev/null 2>&1 || {
		info "no weston-screenshooter: no screenshot"
		return 0
	}
	local tmp file
	tmp=$(mktemp -d)
	# It writes wayland-screenshot-<stamp>.png into the working directory.
	( cd "${tmp}" && weston-screenshooter ) >/dev/null 2>&1 || true
	file=$(find "${tmp}" -maxdepth 1 -name '*.png' | head -1)
	if [ -n "${file}" ]; then
		mv "${file}" "${SHOT}"
		info "screenshot: ${SHOT}"
	else
		info "weston-screenshooter produced nothing"
	fi
	rm -rf "${tmp}"
}

take_shot() {
	if [ "${SESSION}" = wayland ]; then
		# Nothing to watch for from outside: the app's window belongs to the
		# nested compositor, so the shot is simply taken partway through.
		sleep $((SMOKE / 2))
		shot_wayland
	else
		shot_x11 $((SMOKE > 5 ? SMOKE - 4 : 1))
	fi
}

if [ "${SMOKE}" = 0 ]; then
	info "running: $*"
	exec "$@"
fi

info "smoke (${SMOKE}s): $*"
info "log: ${LOG}"
PRE_IDS=$(x11_window_ids | tr '\n' ' ')
( take_shot ) &
shot_pid=$!

set +e
timeout --kill-after=5 "${SMOKE}" "$@" >"${LOG}" 2>&1
rc=$?
set -e
wait "${shot_pid}" 2>/dev/null || true

# A nested compositor is a window on somebody's desktop, and a window can be
# closed. When that happens its clients shut down cleanly and the app takes the
# blame for something it did not do, so check before passing judgement.
if [ "${SESSION}" = wayland ] \
	&& ! "${SCRIPT_DIR}/weston-session.sh" status >/dev/null 2>&1; then
	fail "INCONCLUSIVE ${TESTENV}/${LABEL} -- the nested compositor went away mid-run"
	printf -- '    its window was closed, or weston died; nothing was proven about the app\n' >&2
	printf -- '    rerun with: make %s-smoke\n' "${LABEL}" >&2
	exit 1
fi

if [ "${rc}" = 124 ]; then
	printf '\033[1;32m==> PASS\033[0m %s/%s -- still running after %ss\n' \
		"${TESTENV}" "${LABEL}" "${SMOKE}"
	exit 0
fi

# rc=0 is a different animal from a crash: the app shut down cleanly, which
# usually means somebody closed it. These windows sit on the real desktop while
# the matrix runs, and one stray click is all it takes.
if [ "${rc}" = 0 ]; then
	fail "FAIL ${TESTENV}/${LABEL} -- exited cleanly before the ${SMOKE}s deadline (closed by hand?)"
else
	fail "FAIL ${TESTENV}/${LABEL} -- exited on its own (rc=${rc})"
fi
printf -- '--- %s (tail) ---\n' "${LOG}" >&2
tail -n 30 "${LOG}" >&2 || true
exit 1

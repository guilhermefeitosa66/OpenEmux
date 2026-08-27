#!/usr/bin/env bash
#
# Shared settings for the in-container devbox tools. Sourced by every
# devbox-* command by absolute path -- the kit is always mounted at
# /openemux/devkit, so there is nothing to resolve.

# --- The display -----------------------------------------------------------
#
# :77, and never :0. distrobox runs the container with the host's network
# namespace AND bind-mounts the host's /tmp, so both places an X server
# advertises itself -- the abstract socket and /tmp/.X11-unix -- are shared
# with the desktop the developer is using. A display number the host also uses
# would not collide loudly; it would connect, and every screenshot and
# keystroke below would land on their screen. That is the failure this whole
# container exists to prevent, so the number is high, fixed, and asserted
# (see devbox-x: the server has to answer with the VNC extension, which only
# ours has).
DEVBOX_DISPLAY=${DEVBOX_DISPLAY:-:77}

# Loopback only. The network namespace is the host's, so binding the VNC port
# on 0.0.0.0 would put the container's screen on the local network.
DEVBOX_VNC_HOST=127.0.0.1
DEVBOX_VNC_PORT=${DEVBOX_VNC_PORT:-5977}

DEVBOX_GEOMETRY=${DEVBOX_GEOMETRY:-1600x1000}

# --- Paths -----------------------------------------------------------------

DEVBOX_KIT=/openemux/devkit
# The checkout under test, at the same absolute path it has on the host -- the
# container is created with an env var carrying it. Same path on both sides is
# deliberate: an edit saved on the host is live in here with no copying and no
# rebuild, and a traceback from in here names a file the host can open.
DEVBOX_REPO=${DEVBOX_REPO:?the container was created without DEVBOX_REPO}
# Runtime state of the container session. Under the container's own home, which
# is a directory the host can read -- so evidence never needs to be copied out.
DEVBOX_STATE=${DEVBOX_STATE:-${HOME}/.devbox}
DEVBOX_OUT=${DEVBOX_OUT:-${HOME}/devbox-out}

export XAUTHORITY="${DEVBOX_STATE}/Xauthority"
export DISPLAY="${DEVBOX_DISPLAY}"

# --- The interpreter -------------------------------------------------------
#
# /usr/bin/python3, spelled out, every time. distrobox forwards the host's
# PATH and mounts the host's home, so a pyenv shim in there resolves ahead of
# the container's own python -- and that interpreter has no PyGObject, so the
# app dies at `import gi` with an error that looks like a broken container.
DEVBOX_PYTHON=/usr/bin/python3

# The container has a home of its own, and everything in this kit writes into
# it: a throwaway ~/.openemux, a synthetic library, the logs and the captures.
# The developer's real home is *also* mounted, at its real path, so that the
# checkout is live in here -- which means one wrong HOME turns every tool below
# into something that edits their actual config. distrobox names the host home,
# so the mistake is detectable; refuse rather than find out afterwards.
if [ -n "${DISTROBOX_HOST_HOME:-}" ] && [ "${HOME}" = "${DISTROBOX_HOST_HOME}" ]; then
	printf '\033[1;31m==> HOME is the host home (%s)\033[0m\n' "${HOME}" >&2
	printf "    This container was meant to have its own. Recreate it:\n" >&2
	printf "    make devbox-rm && make devbox-up\n" >&2
	exit 1
fi

mkdir -p "${DEVBOX_STATE}" "${DEVBOX_OUT}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

# The session bus started alongside the X server. GApplication wants one for
# its single-instance registration, and without it every launch logs a warning
# that has nothing to do with the change under test.
load_bus() {
	[ -r "${DEVBOX_STATE}/bus" ] || return 0
	DBUS_SESSION_BUS_ADDRESS=$(cat "${DEVBOX_STATE}/bus")
	export DBUS_SESSION_BUS_ADDRESS
}

# True when the X server on DEVBOX_DISPLAY is the one this kit started.
#
# "Something answers on :77" is the weak version of this question and it is not
# the one worth asking -- see the display comment above. Only Xvnc advertises
# this extension; it is not inherited from the X.Org codebase Xvnc is built on
# (that vendor string is identical either way), so the check cannot pass
# against a host display.
#
# Both spellings: TigerVNC called it VNC-EXTENSION up to 1.14 and TIGERVNC from
# 1.15 on. Matching only the old name made a perfectly good server look absent
# and the session time out after 60s of it already running.
# Captured into a variable rather than piped into `grep -q`, and that is not a
# style choice: grep -q exits at the first match, the producer gets SIGPIPE for
# writing into a closed pipe, and under `set -o pipefail` the pipeline then
# reports 141 -- a failure -- for a check that just succeeded. xdpyinfo prints
# enough lines to lose that race every time, which is how a perfectly healthy
# server looked absent until it timed out.
display_is_ours() {
	local out
	out=$(xdpyinfo -display "${DEVBOX_DISPLAY}" 2>/dev/null) || return 1
	grep -qE '^[[:space:]]*(TIGERVNC|VNC-EXTENSION)$' <<<"${out}"
}

require_display() {
	display_is_ours || die "no virtual display on ${DEVBOX_DISPLAY} -- start it with: devbox-x start"
}

# True when a window manager is managing OUR display.
#
# The question is about the display, never about the process table: this
# container shares the host's PID namespace, so `pgrep -x openbox` happily
# matches the developer's own window manager and reports a WM that is not
# managing anything in here. That exact mistake left :77 unmanaged -- GTK then
# ignores resize requests (there is no WM to mediate them) and every capture of
# a narrow layout came out as the wide one, clipped.
wm_running() {
	local out
	out=$(xprop -root -display "${DEVBOX_DISPLAY}" _NET_SUPPORTING_WM_CHECK 2>/dev/null) || return 1
	[ -n "${out}" ] && ! grep -q 'not found' <<<"${out}"
}

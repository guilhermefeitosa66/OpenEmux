#!/usr/bin/env bash
#
# Drive the app through a library session and print what it cost.
#
# Runs INSIDE the devbox (it needs the box's display and the box's HOME):
#
#   ./devbox/devbox.sh exec env DEVBOX_REPO=$PWD tools/perf/library_bench.sh <label> [<out dir>]
#
# Expects the config's roms_path to point at a library (tools/perf/gen_library.py
# makes a big one; `tools/perf/library_bench.sh --use ~/games/big` points the
# devbox config at it first). One JSON object per line on stdout:
#
#   time_to_window_s / startup_settle_s   the window, and the start-up quiet
#   <step>_main_settle_s                  how long the main thread stayed busy
#                                         after a click (what feels frozen)
#   <step>_settle_s                       the same for the whole process, decode
#                                         pool included
#   at=<step> rss_kb / cpu_s / main_cpu_s memory and CPU after each step
#   cards_built                           cards the grids built, from the log
#
# Steps: start on a console page, open "All", type a search, zoom in, zoom out,
# scroll "All", visit ten consoles, come back to "All", quit. COLD=1 empties the
# cartridge composite cache first, so the shelf pays its first render.
# Screenshots of each step land in the out dir.
set -uo pipefail
. /openemux/devkit/lib.sh

if [ "${1:-}" = "--use" ]; then
	/usr/bin/python3 - "$2" "$DEVBOX_REPO/src" <<-'PY'
	import sys
	sys.path.insert(0, sys.argv[2])
	from openemux.core.config import ConfigManager
	config = ConfigManager()
	config.config["roms_path"] = sys.argv[1]
	config.save_config()
	print("roms_path =", config.get_roms_path())
	PY
	exit 0
fi

label=${1:-run}
out=${2:-$DEVBOX_OUT/bench}
mkdir -p "$out"
devbox-x start >/dev/null
require_display
load_bus
cd "$DEVBOX_REPO"
# The session file remembers the last view: start on a console page every time.
rm -f "$HOME/.openemux/session.json"
if [ -n "${COLD:-}" ]; then rm -rf "$HOME/.openemux/cache/cartridges"; fi
export PYTHONPATH=src GDK_BACKEND=x11
log="$out/$label.app.log"
: >"$log"
start=$(date +%s.%N)
/usr/bin/python3 ${PYFLAGS:-} src/openemux/main.py >>"$log" 2>&1 &
pid=$!
wid=""
for _ in $(seq 1 1200); do
	kill -0 "$pid" 2>/dev/null || { echo "{\"label\":\"$label\",\"error\":\"exited\"}"; tail -5 "$log" >&2; exit 1; }
	wid=$(xdotool search --onlyvisible --pid "$pid" 2>/dev/null | head -1)
	[ -n "$wid" ] && break
	sleep 0.05
done
t_win=$(echo "$(date +%s.%N) - $start" | bc)

cpu() { awk '{printf "%.2f", ($14+$15)/100}' /proc/$pid/stat; }
mcpu() { awk '{printf "%.2f", ($14+$15)/100}' "/proc/$pid/task/$pid/stat"; }
rss() { awk '/VmRSS/{print $2}' /proc/$pid/status; }
snap() {
	echo "{\"label\":\"$label\",\"at\":\"$1\",\"rss_kb\":$(rss),\"cpu_s\":$(cpu),\"main_cpu_s\":$(mcpu),\"t\":$(echo "$(date +%s.%N) - $start" | bc)}"
}
# Quiet for 1.0 s of the whole process; printed relative to $1.
settle() {
	local t0=$1 last quiet=0 now
	last=$(awk '{print $14+$15}' /proc/$pid/stat)
	for _ in $(seq 1 600); do
		sleep 0.1
		now=$(awk '{print $14+$15}' /proc/$pid/stat)
		if [ "$now" = "$last" ]; then quiet=$((quiet + 1)); else quiet=0; fi
		last=$now
		[ $quiet -ge 10 ] && break
	done
	echo "$(echo "$(date +%s.%N) - $t0 - 1.0" | bc)"
}
# Quiet for 0.5 s of the main thread alone, polled every 50 ms.
msettle() {
	local t0=$1 last quiet=0 now
	last=$(awk '{print $14+$15}' "/proc/$pid/task/$pid/stat")
	for _ in $(seq 1 1200); do
		sleep 0.05
		now=$(awk '{print $14+$15}' "/proc/$pid/task/$pid/stat")
		if [ "$now" = "$last" ]; then quiet=$((quiet + 1)); else quiet=0; fi
		last=$now
		[ $quiet -ge 10 ] && break
	done
	echo "$(echo "$(date +%s.%N) - $t0 - 0.5" | bc)"
}
step() { # step <name> <xdotool args...>: time the main thread and the process after an action
	local name=$1 m0 t0 ms s
	shift
	m0=$(mcpu)
	t0=$(date +%s.%N)
	xdotool "$@"
	ms=$(msettle "$t0")
	echo "{\"label\":\"$label\",\"${name}_main_settle_s\":$ms,\"${name}_main_cpu_s\":$(echo "$(mcpu) - $m0" | bc)}"
	s=$(settle "$t0")
	echo "{\"label\":\"$label\",\"${name}_settle_s\":$s}"
	snap "$name"
	import -display "$DISPLAY" -window root "$out/$label-$name.png"
}

echo "{\"label\":\"$label\",\"time_to_window_s\":$t_win}"
s=$(settle "$start")
echo "{\"label\":\"$label\",\"startup_settle_s\":$s}"
snap "start"
xdotool windowactivate --sync "$wid" 2>/dev/null
xdotool windowsize "$wid" 1280 800
xdotool windowmove "$wid" 160 100
sleep 1
import -display "$DISPLAY" -window root "$out/$label-console.png"
# The sidebar at 1280x800 placed at (160,100): "All" is the first row.
step all mousemove 240 176 click 1
xdotool key ctrl+f
sleep 0.5
m0=$(mcpu); t0=$(date +%s.%N)
for ch in a l p h a; do xdotool key $ch; sleep 0.4; done
ms=$(msettle "$t0")
echo "{\"label\":\"$label\",\"search_main_settle_s\":$ms,\"search_main_cpu_s\":$(echo "$(mcpu) - $m0" | bc)}"
snap "search"
import -display "$DISPLAY" -window root "$out/$label-search.png"
xdotool key ctrl+a
xdotool key BackSpace
sleep 1.5
xdotool key Escape
sleep 0.5
xdotool mousemove 650 300 click 1
sleep 0.5
step zoom_in key ctrl+plus
step zoom_out key ctrl+minus
xdotool mousemove 650 300 click 1
sleep 0.3
for _ in $(seq 1 15); do xdotool key Page_Down; sleep 0.2; done
sleep 2
snap "scrolled"
import -display "$DISPLAY" -window root "$out/$label-scrolled.png"
for i in 0 1 2 3 4 5 6 7 8 9; do
	xdotool mousemove 240 $((262 + 50 * i)) click 1
	sleep 1.2
done
sleep 3
snap "ten_consoles"
step all_again mousemove 240 176 click 1
echo "{\"label\":\"$label\",\"hwm_kb\":$(awk '/VmHWM/{print $2}' /proc/$pid/status)}"
xdotool key ctrl+q
sleep 2
kill "$pid" 2>/dev/null
sleep 1
kill -9 "$pid" 2>/dev/null
built=$(grep -o "cards built this session=[0-9]*" "$log" | tail -1 | grep -o "[0-9]*$")
echo "{\"label\":\"$label\",\"cards_built\":${built:-null},\"log_problems\":$(grep -ciE "traceback|critical" "$log")}"

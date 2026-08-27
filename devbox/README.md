# The devbox — running OpenEmux without taking the screen

`make run` puts OpenEmux on your desktop and takes the mouse and keyboard with
it. That is fine when you are the one testing. It is not fine when somebody
else is driving — an assistant checking a change has to click, type, resize and
screenshot, and every one of those lands on the display you are working on.

The devbox is one [distrobox] container on the current Ubuntu LTS with an X
server of its own, running the app **from this checkout**. Nothing it does
touches your session: the app opens on a display nobody is looking at, and you
can carry on working. When you *do* want to look, `make devbox-view` opens a
VNC viewer on it.

```bash
make devbox-up                          # create it (first run: a few minutes)
make devbox-app                         # start the app on the virtual display
make devbox-shot OUT=/tmp/grid.png      # capture it
make devbox-xdo CMD='key ctrl+f'        # drive it
make devbox                             # a shell inside, with the tools on PATH
```

## This is not `packaging/testenv/`

They look alike and answer different questions.

|  | `packaging/testenv/` | `devbox/` |
|---|---|---|
| Runs | the release artifacts in `dist/` | the source in `src/` |
| Answers | does the `.deb` install and start on Debian 13? | does the change I just made look right? |
| Display | **yours** — it borrows the host session | its own, headless |
| Distros | six (Ubuntu/Debian/Fedora × X11/Wayland) | one, the current Ubuntu LTS |
| When | before a release | all day, while you work |

Use testenv to answer packaging questions. Use the devbox to look at the app.

## What the container is

- **Ubuntu 26.04 LTS** — deliberately not the 24.04 the packages target. That
  floor is testenv's job; here the point is to meet the newest GTK and
  libadwaita, which is where an API that moved shows up first. On a Mint 22.3
  host the difference is GTK 4.22 / libadwaita 1.9 in here against 4.14 / 1.5
  outside, so `make devbox-tests` is a second run of the suite against a stack
  the host does not have.
- **A `$HOME` of its own**, under `~/.local/share/openemux-devbox/home`. The
  `~/.openemux` in there is throwaway — your real config, library and playlists
  are never opened. Captures and logs land in that home, which is a plain
  directory on the host, so nothing needs copying out.
- **The checkout at its real path.** Save a file on the host and the next
  `make devbox-app ACTION=restart` runs it. Nothing to sync, nothing to rebuild.
- **No venv.** The app's three runtime dependencies come from apt, and the
  interpreter is spelled `/usr/bin/python3` everywhere. See *The traps* below
  for why that matters.

## The tools

Inside the container, on `PATH`; from the host, one `make` target each.

| Inside | From the host | |
|---|---|---|
| `devbox-app start\|stop\|restart\|status\|log` | `make devbox-app ACTION=…` | the app |
| `devbox-shot [--win] [path]` | `make devbox-shot OUT=… WIN=1` | screenshot |
| `devbox-xdo <xdotool args>` | `make devbox-xdo CMD='key ctrl+f'` | drive it |
| `devbox-res [WxH]` | `make devbox-res RES=520x900` | resize the screen |
| `devbox-rec start\|stop` | `make devbox-rec CMD=start` | record it |
| `devbox-seed [--wipe] [--tour]` | `make devbox-seed` | config + library |
| `devbox-tests [args]` | `make devbox-tests` | the unit suite |
| `devbox-verify` | `make devbox-verify` | is any of this working? |
| `devbox-x start\|stop\|status` | — | the virtual display |
| `devbox-win [--list]` | — | which window is the app's |

Housekeeping: `make devbox-status`, `make devbox-view`, `make devbox-rm`
(`PURGE=1` also drops the home, and with it every capture).

Knobs, all overridable on the command line:

```bash
make devbox-up DEVBOX_IMAGE=ubuntu:24.04     # a different base
make devbox-up DEVBOX_DISPLAY=:78            # if :77 is taken
make devbox-up DEVBOX_GEOMETRY=1920x1080     # a different screen
make devbox-up DEVBOX_ROMS=~/games/roms      # your real library instead of the fake one
```

## The library it opens on

A fresh `~/.openemux` sends the app to first boot, which downloads every
libretro core before it will show a window, and an empty library shows empty
states and nothing else. So `devbox-seed` — which `devbox-app start` runs for
you the first time — marks the bootstrap done and writes a **synthetic
library**: 39 zero-byte files with real No-Intro names across eight consoles,
and the rest of the consoles left empty on purpose, because the checklist wants
two populated consoles *and* the empty state and one library can be both.

Every value it writes goes through `ConfigManager`, so it cannot drift from the
schema the app actually reads.

Two things it turns off, both because they would otherwise be in every capture:
the welcome tour (`--tour` keeps it) and the start-up update check. To get the
real first-boot experience, cores and all: `devbox-app start --first-boot`.

## Driving the app

Keyboard first. `Tab`, `Return` and accelerators survive a different window
size and a changed layout; a click at (412, 260) does not, and it also proves
nothing about whether the UI can be driven from the keyboard.

```bash
make devbox-xdo CMD='key ctrl+f'
make devbox-xdo CMD='type sonic'
make devbox-xdo CMD=win                     # what is being targeted right now
```

`make` splits `CMD=` on whitespace, so an argument that contains a space wants
the script directly: `./devbox/devbox.sh xdo type 'Super Mario'`.

Check the state between steps rather than chaining keystrokes blind — one
`CMD=win` or one screenshot costs a second and saves a whole sequence typed
into the wrong window. `devbox-win` decides what "the app's window" means: the
focused window when it is the app's (that is the open dialog, which is where a
keystroke has to land), otherwise the most recent one.

For a capture of the window rather than the screen, `WIN=1` — it trims GTK4's
client-side shadow, which otherwise pads every image with transparent margin. A
full-screen grab is safe here in a way it is not on the host, since this
display holds the app and nothing else.

The Python driver from the `refresh-screenshots` skill
(`.claude/skills/refresh-screenshots/scripts/{ui,app}.py`) works unchanged in
here — `wmctrl`, `xwininfo`, ImageMagick and `python3-xlib` are all installed.
Point `DISPLAY` at `:77` and `app.Session` behaves exactly as it does outside.

## The traps

Every one of these was hit while building this, and each is a case where the
wrong thing *looks* like it works.

**distrobox shares the host's network, PID namespace and `/tmp`.** That is
three separate ways for something in here to reach out and touch the desktop
this is supposed to leave alone:

- The X display number must be one the host will never use (`:77`), because
  both places an X server advertises itself are shared. And "something answers
  on `:77`" is not the same question as "that is *my* server": the check is
  that it advertises the VNC extension, which only Xvnc does. Without that
  assertion a display collision would not fail — it would connect, and every
  keystroke below would land on your screen.
- Nothing is ever killed by name. `pkill openemux` in here would take down the
  copy *you* have open. Only pids this kit wrote down.
- `pgrep -x openbox` matches **your** window manager. Asking the process table
  whether the WM is running reported yes while `:77` had none — and a display
  with no window manager quietly ignores resize requests, so every "narrow
  layout" capture came out as the wide layout with the right-hand side cut off.
  The question has to be asked of the display: `_NET_SUPPORTING_WM_CHECK`.

**The host's `PATH` and home come through.** `python3` in here resolves to the
developer's pyenv shim, which has no PyGObject, so the app dies at `import gi`
with an error that looks like a broken container. Everything spells out
`/usr/bin/python3`. Same reason the app is not started through `make run`: that
would use the host's `.venv`.

**`grep -q` at the end of a pipeline lies under `set -o pipefail`.** It exits at
the first match, the producer dies of SIGPIPE, and the pipeline reports 141 —
a failure — for a check that just succeeded. It only shows up once the producer
is big enough to still be writing, which is why it passed for `distrobox list`
and failed for `xdpyinfo`. Capture into a variable and match with `<<<`.

**Do not regenerate the X cookie before deciding to start a server.** Replacing
it under a running Xvnc locks you out of a display that is working perfectly
well. `devbox-x` reads the pid out of `/tmp/.X77-lock` to tell "mine, and
wedged" from "somebody else's, hands off".

**`wmctrl -i` wants a hex window id**; `xdotool` hands out decimal. The pair
silently does nothing at all — the screen shrinks, the window does not, and the
capture comes out cropped instead of narrow.

## What it does not cover

- **A real GPU.** Rendering is software (llvmpipe). Fine for layout, colour and
  every capture; not the place to judge performance.
- **Running a game.** RetroArch opens fullscreen and grabs input, and no core
  is downloaded here anyway. Validate the built argv with a probe and leave the
  real session to a person.
- **Wayland.** X11 only, on purpose — the automation is X11. The Wayland half
  of the matrix lives in `packaging/testenv/`.
- **The packages.** Nothing here is installed; it runs from `src/`.

[distrobox]: https://distrobox.it

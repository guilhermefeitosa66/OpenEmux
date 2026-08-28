# Test environments

Six throwaway desktops — Ubuntu, Debian and Fedora, each in an X11 and a
Wayland flavour — where the artifacts in `dist/` get installed and launched the
way a user of that distro would. Built on [distrobox]; the containers share the
host's kernel, GPU and display, so this costs seconds per run instead of the
minutes a VM would.

```bash
make distrobox-install     # once, if the host does not have distrobox yet
make packages              # the artifacts under test

make ubuntu-x11            # bring the container up and drop into a shell
make fedora-wayland        # same, on a nested weston session
```

Inside the container:

```bash
make deb-install           # install the .deb, resolving Depends with apt
make deb-run               # launch it in this container's session
make deb-smoke             # launch it, screenshot it, fail if it dies
make smoke-all             # every format this distro can take, end to end
make help                  # the full list, tailored to the container
```

Or skip the shell entirely:

```bash
make ubuntu-x11 RUN="deb-install deb-smoke"
make testenv-matrix                       # all six, every format
make testenv-matrix SMOKE_SECONDS=12      # shorter runs, less screen time
```

## What runs where

| | AppImage | `.deb` | `.rpm` | Flatpak |
| --- | :---: | :---: | :---: | :---: |
| `ubuntu-{x11,wayland}` | ✅ | ✅ | — | ✅ |
| `debian-{x11,wayland}` | ✅ | ✅ | — | ✅ |
| `fedora-{x11,wayland}` | ✅ | — | ✅ | ✅ |

The native packages are only offered where they belong; asking for
`rpm-install` in an Ubuntu container gets you a refusal, not a broken dnf.

Base images are the floors each package targets, and are overridable:

```bash
make ubuntu-x11 UBUNTU_IMAGE=ubuntu:26.04
```

| Variable | Default | Why |
| --- | --- | --- |
| `UBUNTU_IMAGE` | `ubuntu:24.04` | the floor the `.deb` targets (libadwaita ≥ 1.5) |
| `DEBIAN_IMAGE` | `debian:13` | trixie is Debian's first release clearing that floor — bookworm ships libadwaita 1.2 and cannot install the package at all |
| `FEDORA_IMAGE` | `fedora:42` | the `.rpm` is built on the fc40 floor and installed on a current release |

## X11 and Wayland on the same host

A container has no display server of its own — it borrows the host's. On an
X11 host there is no Wayland session to borrow, so the `*-wayland` containers
start **weston nested**: a compositor in a window, serving its own Wayland
socket. The app then really does speak Wayland to a real compositor. On a
Wayland host weston nests inside that instead, so both halves of the matrix
behave the same either way.

The launcher forces the backend rather than trusting a fallback — `GDK_BACKEND`
plus, on the Wayland side, dropping `DISPLAY` so neither GTK nor Flatpak's
`fallback-x11` can quietly go back to X11 and make the run prove nothing.

```bash
make weston-start          # poke at the nested session by hand
make weston-status
make weston-stop
```

## What a smoke test is

`make deb-smoke` starts the app, screenshots it once its window is up, and
requires it to still be alive when the clock runs out (`SMOKE_SECONDS`,
default 25). An app that exits on its own before then failed, and the tail of
its log is printed. A clean exit is called out separately from a crash — these
windows sit on your real desktop while the matrix runs, and one stray click on
one of them is enough to close the app and fail the run. Evidence lands in the
container's home:

```
~/openemux-testenv/logs/<distro>-<session>-<format>.log
~/openemux-testenv/shots/<distro>-<session>-<format>.png
```

Screenshots capture **one window**, never the root window — the container
borrows the real desktop, and a root grab would put whatever else is on screen
into a file that ends up attached to an issue. On X11 that is the window that
was not there before the run started, so your own running copy of OpenEmux is
never mistaken for the one under test; the capture waits for it to appear
rather than guessing a moment. On Wayland the app has no X window at all, so
weston's own screenshooter is aimed at this container's socket — every
container's weston lands on the host display under an identical name and
class, and picking one from outside would be guesswork.

## Isolation

Each container gets its **own home** under
`~/.local/share/openemux-testenv/homes/<distro>-<session>`. That is the point:
`~/.openemux` starts empty, so first-boot bootstrap runs for real, and the
developer's actual library, config and covers are never touched. The real home
is still mounted at its usual path, so absolute paths into the checkout keep
working.

`dist/` is bind-mounted read-only at `/openemux/dist`, so no test can eat a
release artifact. Driving the matrix from a worktree, whose own `dist/` is
empty? Point at the real one:

```bash
make ubuntu-x11 DIST_DIR=/path/to/main/checkout/dist
```

The Flatpak installation at `~/.local/share/openemux-testenv/flatpak` is
**shared by all six containers** — runtimes are self-contained, so one ~1 GB
copy of `org.gnome.Platform` serves the whole matrix instead of six. Nothing
here touches the developer's own `~/.local/share/flatpak`. It also means the
containers must not run Flatpak operations concurrently, which is why
`testenv-matrix` is serial.

## Housekeeping

```bash
make testenv-list                     # what exists
make testenv-status                   # containers + the artifacts they serve
make testenv-rm-fedora-wayland        # drop one (keeps its home)
make testenv-rm-fedora-wayland PURGE=1
make testenv-rm-all PURGE=1
```

A container remembers which `dist/` it was created against; point `DIST_DIR`
somewhere else and `testenv-status` says so rather than serving stale
artifacts behind your back.

## Things that surprised us

**`distrobox create` can report an error and still create the container.**
With Docker it answers the first operation on some images with
`openat dev/ptmx: no such device`. The container is fine — the driver checks
whether it exists and carries on rather than aborting the run.

**The host's `PATH` reaches into the container.** distrobox forwards it, so a
`~/.local/bin/openemux` on the host shadows the package under test and a smoke
run would pass for the wrong binary. The run targets address `/usr/bin/openemux`
absolutely, and `deb-install` warns when it sees a shadow. (This is also why
the packaged launcher refuses to trust `python3` from `PATH` — see
[`packaging/README.md`](../README.md).)

**Flatpak needs a system D-Bus to install anything.** It asks the system bus
about parental controls, and a container image starts no bus at all, so the
install dies with `Could not connect: No such file or directory` — after
downloading the whole GNOME runtime. The `system-bus` target starts one first.

**A container image is not a desktop, and Fedora's is furthest from one.**
Three separate gaps, each of which failed a different format: `mesa-dri-drivers`
does not pull `libGLESv2`, so GTK4's renderer aborted the `.rpm` at window
construction; `fuse` carries the `fusermount` binary the AppImage runtime
actually execs, which no container image has; and nothing creates
`/var/lib/flatpak/repo`, so a plain `flatpak run` refused to start until it was
told `--user`. All three are provisioning, not app bugs — which is the sort of
thing this rig exists to tell apart.

**Screenshots on the Wayland side need `weston --debug`.** Without it the
screenshooter protocol answers `unauthorized` and that half of the matrix
produces no evidence at all.

**A container's home outlives the container.** `testenv-rm` keeps it and a
later `create` reuses it, which is the point — but it means the
"already provisioned" marker cannot live there, or a freshly recreated
container is declared ready while holding nothing, not even make(1). It is
kept inside the container instead.

**The AppImage wants `/dev/fuse`.** It is there in a distrobox container, so
the normal FUSE path is what gets tested. Where it is not, the target falls
back to extract-and-run and says so, because only the first path is what users
actually get.

**No FUSE *library* is installed any more.** `libfuse2`/`fuse-libs` were here
so the vendored RetroArch AppImage could mount itself; the packages ship the
portable tree instead (issue #328), so these containers are now exactly the
host that used to fail — no FUSE 2 anywhere — and a game launching on them is
the evidence that matters.

## What this does not cover

Containers share the host kernel and desktop, so this proves the *packages*
work: dependency resolution, the launcher, the install layout, GTK/libadwaita
version differences, and both display backends. It does not prove anything
about a real GNOME or KDE session, `xdg-desktop-portal`, notifications, the
file picker, tray behaviour, drivers or kernels. Those still want a VM.

Launching a game needs RetroArch, which these containers do not install — the
smoke tests cover the app coming up, not emulation.

[distrobox]: https://distrobox.it

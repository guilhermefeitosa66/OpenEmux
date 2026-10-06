# OpenEmux 1.14.0

A release about getting started and getting help: **the first boot is ready in seconds instead of
nearly two minutes**, **a bug can be reported from inside the app**, and **a running game is no
longer reachable from your network**.

## Report a bug from inside the app

Until now, reporting a bug meant finding `~/.openemux/runtime/openemux_startup.log` on your own,
and nothing told you that the log is what lets a bug get fixed. OpenEmux now carries the whole
path for you ([#461](https://github.com/guilhermefeitosa66/OpenEmux/issues/461)).

- **A "Log" button at the right end of the bottom bar** opens a live view of what OpenEmux is
  doing, with errors in red. While it is closed, a red count on the button says how many errors
  happened since you last looked, so a problem never goes by unnoticed.
- **"Report a Bug…"**, in the main menu, in the log panel and in Settings › System ›
  Troubleshooting, takes two steps:
  1. **Copy.** It shows exactly what will be copied before copying it: your OpenEmux version and
     how it was installed, your distribution, kernel, desktop and session, the GTK, libadwaita
     and Python versions, RetroArch and your language, plus the last 300 lines of the log.
  2. **Open GitHub.** The bug form opens with the version and the distribution already filled in.
     You paste the rest.

  Nothing leaves your computer by itself.
- **Your name stays out of it.** A home directory is named after its user, and nearly every path
  in the log started with one. The log, the file on disk and the copied report now write it as
  `~`: `path=~/.openemux/playlists/VB.list`.
- **Failed launches are logged now.** A launch that failed ("RetroArch was not found") used to be
  shown in a toast and nowhere else. A report about a game that would not start carried no trace
  of the error. It is logged now.

## The first boot is ready in about ten seconds

The first launch downloaded **every** core the libretro buildbot lists, plus both shader packs,
before the window opened: 240 downloads and 747 MiB, measured at **110 seconds** on a fast machine
and connection. OpenEmux only ever uses 35 of those cores
([#442](https://github.com/guilhermefeitosa66/OpenEmux/issues/442)).

- **The first boot now waits only for what makes every console playable:** those 35 cores, and
  the shader pack your video driver actually reads (`.glslp` for Linux's default `gl`). Measured
  against the real buildbot: **9.6 seconds**.
- **Everything else downloads in the background** once the library is open, under the progress
  banner ("Downloading the remaining cores"). You can cancel it. If you close the app halfway, the
  next launch picks it up.
- **Downloads run eight at a time** instead of four.
- **The core pickers show real names.** The core info files are installed for the first time, so
  the pickers show "Snes9x" and "bsnes-mercury Accuracy" instead of names made from filenames.
  Every core whose info declares a console is offered for it: the SNES picker went from two
  entries to twenty.

## A running game is no longer reachable from your network

To pause, save or reset a running game, OpenEmux turned on RetroArch's network command interface,
on the assumption that it only listened on your own machine. It did not. RetroArch bound it to
every address, so while a game ran, **anyone on your local network** could pause it, reset it,
quit it, or overwrite and load its save states, with no password.

On Linux, OpenEmux now talks to RetroArch over a private pipe that only it holds, and turns the
network interface off explicitly for every game it launches. Windows keeps the old channel: the
Windows build of RetroArch has no other one.

## Drop ROMs on the sidebar

After the first console's games are in, the natural place to drop the next console's games is the
sidebar, not the grid of some other console. The sidebar now accepts them
([#456](https://github.com/guilhermefeitosa66/OpenEmux/issues/456)). Every file goes to the console
its extension names: a `.gba` dropped on the SNES row lands in Game Boy Advance. Dropping on the
grid works exactly as before.

## ScreenScraper is on for new installs

A fresh install listed ScreenScraper switched off, because a new config was being built through
the migration meant for configs older than 1.9. It is now on, after libretro thumbnails and before
the OpenEmux mirror ([#455](https://github.com/guilhermefeitosa66/OpenEmux/issues/455)).
ScreenScraper is the only source of cartridge labels, and it finds games by their contents rather
than by their filenames. **An existing install keeps its own setting.** You can turn it on in
Settings › Library › Artwork Providers.

## A cartridge without a label looks like a cartridge

In the cartridge view, a game with box art but no cartridge label had its **box art cropped into
the label area**: a different shape and a different picture, which looked broken
([#457](https://github.com/guilhermefeitosa66/OpenEmux/issues/457)). It now gets a plain, blank
label. Box art still counts as artwork, so the "missing artwork" badge does not appear on it, and
views without cartridges keep showing the box art.

## ARM: the core pickers find your distribution's cores

On aarch64 the core pickers looked for distribution cores in an `x86_64` directory, so a console
whose game launched fine showed an empty picker. They now search the directory for the machine
they run on ([#119](https://github.com/guilhermefeitosa66/OpenEmux/issues/119)).

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states and input
profiles are all kept.

- **The new first boot applies to new installs.** If yours already finished its first boot, it
  already has every core.
- **ScreenScraper stays as you left it** on an existing install.
- **If you also start RetroArch on its own**, outside OpenEmux: OpenEmux 1.9.0 to 1.11.1 wrote
  `network_cmd_enable = "true"` into your own `retroarch.cfg`. OpenEmux now overrides it for the
  games it launches, but RetroArch started by itself still reads it. Set it to `"false"` there, or
  turn off Settings › Network › Network Commands in RetroArch.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

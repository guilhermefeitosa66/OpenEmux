# OpenEmux 1.11.2

Two fixes for the same mistake: OpenEmux configures RetroArch for **one launch**, and that configuration was escaping the launch.

## Your RetroArch configuration was being rewritten

Every game OpenEmux starts is handed a small config file describing that session — the window it should open, the command channel, where its save states go. What was easy to miss is that RetroArch **saves its configuration when it exits**, and by then those values are simply part of the configuration. So each launch quietly wrote them into your own `retroarch.cfg`, permanently.

The visible casualty was the game window. Once a single game had run inside the OpenEmux window, this was left behind in your RetroArch:

```
video_window_show_decorations = "false"
pause_nonactive = "false"
input_toggle_fullscreen = "nul"
savestate_directory = "…/.openemux/states/…"
```

From then on RetroArch was borderless **everywhere** — including games launched with "Play in an OpenEmux window" turned off, and RetroArch sessions you started yourself, with no title bar, no borders and a dead fullscreen hotkey. Turning the setting off did not help, because nothing ever wrote the defaults back.

Now nothing OpenEmux imposes for a launch outlives it, and a launch without the OpenEmux window states the normal window behaviour explicitly — so a configuration an earlier version already changed heals itself the next time you play. Core options, control remaps, battery saves, save states and playlists live in their own files and were never affected.

## Flatpak: games ran several times too fast, in silence

OpenEmux picks the audio driver by checking what the machine actually offers, because a `retroarch.cfg` may name a driver the RetroArch being launched does not have. On a **Flatpak** install it was asking the wrong machine: the emulator runs on the host, while the check looked inside OpenEmux's own sandbox — which is granted no audio socket at all. The answer was always "no audio server here", so no driver was chosen and RetroArch fell back to whatever its config said.

When that fails, RetroArch continues without audio — and emulation is paced off the audio clock. With no clock it falls through to the monitor's refresh rate, so on a 240 Hz display a 60 fps game ran four times too fast. It looks like a speed bug and is really a silence bug; it is the same failure that 1.10.1 fixed for other installs, arriving at the Flatpak by a different road.

The Flatpak install now asks the host directly, so it chooses the same driver every other install does.

## If a previous version already changed your RetroArch config

Playing once with 1.11.2 puts the window behaviour right. If you want your `retroarch.cfg` clean of everything earlier versions left there, these are the keys to look for — in `~/.config/retroarch/retroarch.cfg`, or `~/.var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg` for the RetroArch Flatpak:

```
video_window_show_decorations   video_windowed_fullscreen   video_fullscreen
pause_nonactive                 input_toggle_fullscreen     savestate_directory
network_cmd_enable              audio_driver                video_shader / video_shader_enable
```

Delete the lines you did not set yourself and RetroArch will write its own defaults back. Nothing in OpenEmux depends on them.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to configure. Settings, playlists, artwork, save states and input profiles are all kept.

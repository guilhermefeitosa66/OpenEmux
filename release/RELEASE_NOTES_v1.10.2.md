# OpenEmux 1.10.2

A single fix, for the mirror image of the last one: this time it was the **Flatpak** that could not play games.

## Flatpak: no game would launch

If you installed **both OpenEmux and RetroArch as Flatpaks** — the setup our own install instructions recommend, and the natural one on an immutable distro like Fedora Silverblue — clicking any game failed with *"No RetroArch core found"*, no matter the console, and no matter how many cores you had installed through RetroArch. Reported by Marc Mader in [#179](https://github.com/guilhermefeitosa66/OpenEmux/issues/179).

The cores were there all along. OpenEmux looks for them exactly where the RetroArch Flatpak keeps them, `~/.var/app/org.libretro.RetroArch/config/retroarch/cores` — and our manifest asked for access to your home directory, assuming that covered it. It does not: **Flatpak hides `~/.var/app` from other applications' sandboxes even when they have access to everything else in home**, precisely so one app cannot read another's private data. So OpenEmux looked in the right place and saw an empty world.

## The fix

The manifest now declares a **read-only grant for the RetroArch Flatpak's directory**. OpenEmux can see the cores again — and only read them; it still cannot write into RetroArch's data. Installs that pair OpenEmux with a native (non-Flatpak) RetroArch were never affected.

If you don't want to wait for the update, the same grant works from the outside on any existing install:

```bash
flatpak override --user --filesystem=~/.var/app/org.libretro.RetroArch:ro io.github.guilhermefeitosa66.OpenEmux
```

After updating to 1.10.2 that override is no longer needed and can be dropped:

```bash
flatpak override --user --reset io.github.guilhermefeitosa66.OpenEmux
```

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

`flatpak update` brings the new permission with it — nothing to configure, and Flatpak will list the new filesystem access for you to see. Settings, playlists, artwork, save states and input profiles are all kept. The `.deb`, `.rpm` and AppImage are rebuilt for completeness but carry no behavioural change.

# OpenEmux 1.17.0

Games can now start in fullscreen and get a bezel beside the picture, the artwork manager opens on
the cover you already have, and a handful of bugs that made games, covers and cores go missing are
gone. On Android, **RetroAchievements** arrive.

## Start games in fullscreen

**Settings → Video → Game Window → "Start games in fullscreen"** decides how every game opens: in a
window (the default) or filling the screen. The switch wins over whatever your `retroarch.cfg` says,
and the in-game fullscreen hotkey still toggles as before
([#505](https://github.com/guilhermefeitosa66/OpenEmux/issues/505)).

## Bezels beside 4:3 games

On a wide screen a 4:3 game leaves two black bars. Each 4:3 console now has a **Bezel** choice in
**Settings → Video → Bezels**: **None** (the default), **Simple** (a frame OpenEmux draws) or
**Custom image…** (a PNG of your own). The bezel sits under the in-game bar's buttons and leaves the
console's shader alone. Suggested by **u/felipeonline** on Reddit
([#507](https://github.com/guilhermefeitosa66/OpenEmux/issues/507)).

## The artwork manager starts from the cover you have

Opening a game's artwork used to drop you on a search form. It now opens on a **Current** tab that
shows the cover (and the label, on cartridge consoles) whole, says where it came from (synced,
chosen by you, or a local file) and puts the adjustments right there: pick another match, replace it
from a file, crop/flip/rotate it, or reset it to the synced one. A game with no art offers to sync,
search or import ([#510](https://github.com/guilhermefeitosa66/OpenEmux/issues/510)).

## Fixes

- **Games disappeared on "All".** On the grouped pages ("All", "Favorites", collections), a console
  with many games showed its first block of cards and then empty cells, more of them as the window
  got narrower. Every game now stays on screen while you scroll
  ([#511](https://github.com/guilhermefeitosa66/OpenEmux/issues/511)).
- **Cores lost after an upgrade.** Replacing the app folder (most visibly on Windows, where the cores
  live inside it) dropped every core while OpenEmux still believed they were downloaded. On every
  start OpenEmux now checks that the cores are there and quietly downloads the missing ones, and
  **Settings → System → Initial Setup → "Verify cores"** runs the same check on demand
  ([#512](https://github.com/guilhermefeitosa66/OpenEmux/issues/512)).
- **Cartridge labels never synced for zipped Game Boy / Game Boy Color ROMs.** ScreenScraper was
  asked about the `.zip` instead of the ROM inside it. It now gets the ROM's own name and checksums,
  and a refusal from the service is reported instead of passing as "nothing found"
  ([#506](https://github.com/guilhermefeitosa66/OpenEmux/issues/506)).
- **Covers cropped at the top or bottom.** A cover whose shape differs from the console's usual box
  (a portrait Japanese box on a landscape card, a square scan) was zoomed to fill the card and lost
  its edges. It is now shown whole
  ([#508](https://github.com/guilhermefeitosa66/OpenEmux/issues/508)).
- **Windows: Python's icon on the taskbar.** OpenEmux now shows its own icon, gets its own taskbar
  group, and "Pin to taskbar" pins something that actually starts the app
  ([#509](https://github.com/guilhermefeitosa66/OpenEmux/issues/509)).
- **Windows build** moved from MSYS2's MINGW64 to UCRT64, after MINGW64 dropped GTK 4 and
  libadwaita. The bundle now ships GTK 4.24 and libadwaita 1.10
  ([#527](https://github.com/guilhermefeitosa66/OpenEmux/issues/527)).

The About dialog, the README and the website also say plainly how OpenEmux relates to OpenEmu:
inspired by it, not a fork, no shared code, not affiliated
([#504](https://github.com/guilhermefeitosa66/OpenEmux/issues/504)).

## Android: RetroAchievements

`OpenEmux-mobile-1.17.0.apk` adds **Settings → Achievements → RetroAchievements**. Sign in once with
your username and password. The password is exchanged for a token and never stored. After that,
achievements are tracked in every game, with an optional **Hardcore mode** that turns off loading
states and fast forward the way RetroAchievements requires
([#515](https://github.com/guilhermefeitosa66/OpenEmux/issues/515)).

The APK installs over 1.16.0 and keeps your library. `OpenEmux-mobile.apk` is the same file under a
name that does not change between releases.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states and input
profiles are all kept. Fullscreen and bezels are off until you turn them on.

- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.
- **Windows users**: if a previous upgrade left you without cores, this version finds that out on
  its first start and downloads them again.

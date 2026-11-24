# OpenEmux 1.25.0

The themes release. OpenEmux now looks the way **you** want: build your own theme in an editor with
a live preview, or pick one of five ready-made ones, on the desktop, in Big Picture and on Android.
It started with a small idea from mtesseracttech, any colour for a cartridge, and grew from there.
mtesseracttech also reported the two mouse bugs fixed here and asked for proper Arch packages. Thank
you!

`OpenEmux-mobile-1.25.0.apk` installs over 1.24.0, or over any beta, and keeps your library.

## Themes

System, Light and Dark are still there, unchanged. Next to them, in Preferences › Interface:

- **Five ready-made themes**: **Pastel**, **Dracula**, **Kitty** (a cosy one with a cat), **Neon**
  and **Tokyo Night**. Each one combines a colour scheme with its own background artwork, drawn for
  OpenEmux. Ready-made themes stay as they are; **Duplicate** gives you a copy to change.
- **Your own themes**, made in a theme editor with a live preview of the real app. Start from Light
  or Dark and change:
  - the background of each part of the window (sidebar, header, game list, cards, dialogs, details),
    the text, the accent of the selected item, borders, corners and shadows;
  - icon size and colour, the font size, spacing, card size and density;
  - a **background image** for the game list and for the sidebar, with fit, dim and blur.

  Every control resets to the base value, and a contrast warning tells you when text gets hard to
  read.
- **Every colour field takes a colour from a palette**: Basic, Dracula, Pastel, Nord, Gruvbox, Neon,
  Earth and Green screen, the same ones the Android skin editor has, or from your own palettes and
  saved colours. **Start from a palette** seeds a whole theme in one click.
- **Share a theme**: export it as a single `.openemux-theme` file and import it on another computer,
  or on your phone. A theme file holds settings and images only, never code, and is checked before
  anything is written.
- **Big Picture follows the theme**: its colours, background image, font and sizes, and the colour
  behind the console list. Focus always stays visible from the couch.
- **Android has the same themes**: the same five ready-made ones, its own editor built for touch and
  for a controller, palettes on every colour, a themable console list, and the same theme files as
  the desktop.

Requested in [issue 1010](https://github.com/guilhermefeitosa66/OpenEmux/issues/1010).

## Any colour for a cartridge

"Cartridge colour" has a **Pick a Color…** entry, in a game's right-click menu and on its details
row. It opens a dialog with a live preview of that game's cartridge, a colour plane, a hue slider and
a hex field. The colour is kept like a named one: it survives restarts and renames, and travels with
Share. Colours you pick are **saved**, so you can give the next cartridge the same one from the menu,
and you can choose from the same palettes as the themes or make your own. Suggested by
mtesseracttech ([issue 983](https://github.com/guilhermefeitosa66/OpenEmux/issues/983)).

## Fixes

- **Mouse clicks stopped registering.** After a while of use, the window could stop taking clicks
  while still reacting to the pointer. Right-click submenus closed in the wrong order and left the
  menu's hold on the pointer behind. They now close innermost first. Reported by mtesseracttech
  ([issue 984](https://github.com/guilhermefeitosa66/OpenEmux/issues/984)).
- **Right-click menus flickered.** Hovering "Load State" or "Core" made the submenu open and close
  in a loop. Reported by mtesseracttech
  ([issue 985](https://github.com/guilhermefeitosa66/OpenEmux/issues/985)).
- **The Flatpak did not see gamepads** that the AppImage did: the sandbox had no access to
  `/dev/input`. It does now ([issue 1001](https://github.com/guilhermefeitosa66/OpenEmux/issues/1001)).
- **Recently played lines up.** Cartridges of different consoles have different shapes, and mixing
  them broke the layout. Every game now takes the same slot, still in the order you played them
  ([issue 996](https://github.com/guilhermefeitosa66/OpenEmux/issues/996)).
- **Big Picture**: the selected item is no longer clipped at the edges of a row or at the bottom of
  a list, scrollbars are hidden, and the game grid fills the whole width with large cards instead of
  leaving an empty strip ([issue 999](https://github.com/guilhermefeitosa66/OpenEmux/issues/999),
  [issue 1000](https://github.com/guilhermefeitosa66/OpenEmux/issues/1000)).

## Arch Linux

The repository has AUR recipes for **`openemux-git`** (the latest commit) and for the releases:
**`openemux`** (built from the release source), **`openemux-bin`** (the prebuilt package) and
**`openemux-appimage`** (the AppImage). A workflow updates the release ones on every release. They
are not on the AUR yet, because AUR registration is closed for now; until then, build them from
`packaging/aur/`. Asked for by mtesseracttech
([issue 986](https://github.com/guilhermefeitosa66/OpenEmux/issues/986)).

## Android

- **Themes**, as above.
- **Export a game's file and save, and import a save**, from the game's page: back up a ROM, take a
  save to another device, or bring one from another emulator
  ([issue 1005](https://github.com/guilhermefeitosa66/OpenEmux/issues/1005)).
- **Recent shows only the 12 latest games**, like the desktop
  ([issue 997](https://github.com/guilhermefeitosa66/OpenEmux/issues/997)).
- **With a controller in portrait**, LB and RB switch one console at a time, like in landscape,
  instead of walking along a row that did not scroll
  ([issue 998](https://github.com/guilhermefeitosa66/OpenEmux/issues/998)).

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files,
skins and input profiles are all kept, and the theme you had (System, Light or Dark) stays selected.

- **Android**: install `OpenEmux-mobile-1.25.0.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included.
- **Desktop**: install the new package over the old one.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

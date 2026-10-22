# OpenEmux 1.16.0

Two things in this release: **every console that had cartridges now draws its own**, and
**OpenEmux comes to Android**, with its first release as an APK next to the desktop builds.

## A cartridge for every cartridge console

The Cartridge Grid used to draw cartridges for nine consoles and show covers for the rest. Now
**Atari 2600, 5200 and 7800, ColecoVision, Game Gear, Intellivision, Lynx, Neo Geo Pocket,
Odyssey², PC Engine, 32X, SG-1000, Virtual Boy, Vectrex and WonderSwan** games sit in their own
console's cartridge too, with the label inside the sticker window, in all twelve shell colors
("Cartridge color" in a game's menu). Only the disc consoles and the Famicom Disk System still show
their covers ([#500](https://github.com/guilhermefeitosa66/OpenEmux/pull/500)).

## OpenEmux for Android (first release)

`OpenEmux-mobile-1.16.0.apk` is the first release of OpenEmux for Android phones. It brings the
same idea to the phone: the games you own, as cartridges on a shelf per console, played on RetroArch
underneath.

- **A controller skin for every console.** Each of the 31 consoles has its own on-screen
  controller, laid out like the original pad, in portrait and in landscape. A strip under the
  picture saves and loads a state, turns on turbo and fast-forwards. The Nintendo DS shows both
  screens, stacked or side by side, and a button cycles its screen layouts.
- **Cartridges, covers or a list**, with cartridge labels from ScreenScraper and box art from the
  OpenEmux artwork mirror. The shelves can be put in any order.
- **Gamepad support**: with a controller connected the on-screen skin steps aside and the game
  takes the whole screen; the app's menus follow the D-pad too.
- **Light and dark themes**, and the same eight languages as the desktop app.
- **Cores are downloaded on first run.** The APK does not carry them: the first time it opens, the
  app downloads every console's core from the RetroArch buildbot, with the system files PSP and
  GameCube need. Allow a few minutes on the first launch.

### Installing the APK

The app is not on the Play Store yet. Download `OpenEmux-mobile-1.16.0.apk` (or
`OpenEmux-mobile.apk`, the same file under a name that does not change between releases), open it on
the phone and allow your browser or file manager to install apps when Android asks. Android 8 or
newer, 64-bit ARM. Put your ROMs in through **Import**, or in
`Android/data/com.openemux.mobile/files/roms/<console>` on the phone.

The Android app is a fork of RetroArch, so unlike the desktop app (MIT) it is licensed under the
**GPLv3**. Its source is at
[guilhermefeitosa66/open-emux-mobile](https://github.com/guilhermefeitosa66/open-emux-mobile).

## The website

The [website](https://guilhermefeitosa66.github.io/OpenEmux/) presents the Android app, with
screenshots, what it does and how to install it, in every language it speaks. The promo video in the
hero now shows the desktop and the Android app.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate on the desktop. Settings, playlists, artwork, save states
and input profiles are all kept, and the new cartridges appear on their own.

- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

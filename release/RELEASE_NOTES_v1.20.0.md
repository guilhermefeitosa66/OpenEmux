# OpenEmux 1.20.0

The cartridges finally look like cartridges. Every frame that used to look flat has been re-rendered
with real relief, on the desktop and on Android, and the desktop cartridge view lost the boxes it drew
around them. On Android you can now fix a wrong or missing cover or label yourself, pick a Dark or an
official-color controller skin, and lay out the Nintendo DS screens the way you like.

## Cartridges with real relief

Most cartridge frames were low-resolution drawings whose ridges, grooves and logos barely read. They
have been rebuilt from a 3D height map, lit from one direction and shaded with cast shadows and
ambient occlusion, so grips, notches, screws and embossed lettering now stand out. That covers the
NES, Game Boy, Game Boy Color, Virtual Boy, Master System, Game Gear, SG-1000, 32X, PC Engine, the
Atari consoles, ColecoVision, Intellivision, Lynx, Neo Geo Pocket, Odyssey², Vectrex, WonderSwan,
Nintendo 64, Game Boy Advance, Mega Drive and the Nintendo DS card. The Super Nintendo frame was
already good and stays as it was.

Both apps use the same frames, in the neutral shell and in all twelve cartridge colors, and labels sit
exactly where they did. On the desktop the cached cartridge images are rebuilt on the first start, so
you see the new frames without clearing anything.

## Desktop: a cleaner cartridge view

The shadow meant to lift each cartridge off the shelf was drawn as a rectangle around the widget, so
every cartridge sat on a visible box, most obvious around the N64's rounded top and the NES's notched
corners. The shadow now follows the cartridge's own outline. Hovering a cartridge no longer lays a
dark block over it either: you see the play button, the favorite star and the menu, nothing more.
The cover and list views are unchanged.

## Android

### Fix a game's cover or label yourself

A wrong cover or a missing label used to stay that way: art only came from the automatic sync. Each
game now has an **Artwork** entry on its detail screen, between Shader and Controller skin, that opens
an artwork manager:

- **Current** shows the cover and, on cartridge consoles, the label, with where each came from
  (synced automatically, chosen by you, a local file, or missing). From there you can search, adjust
  or remove each one.
- **Search** looks for covers and labels by name or by the ROM's hash, in libretro thumbnails,
  ScreenScraper and the OpenEmux artwork mirror, and offers similar names when nothing matches.
- **Edit** crops, rotates and flips the current image, with Save and Cancel.
- **Import** takes an image from your phone.

Art you choose is never overwritten by a later sync. Settings gain an **Artwork providers** page to
reorder or turn providers off and to add your own ScreenScraper account for a bigger quota.

### Controller skins

- **Dark skins** for every bundled console, for playing with the lights off: the bright shells
  around the game no longer pull your eye away from the picture.
- **Official color variants** for the consoles that were sold in several colors, such as the Game Boy
  Advance, Game Boy Color, Nintendo 64, Super Nintendo and Nintendo DS.

### Nintendo DS

Every screen layout is now available in both orientations, a **Screens** button in the quick actions
bar switches layouts during play, and the skins have variants that let the DS screens fill the
display instead of floating in black space.

### Smaller fixes

- **A shader picked in-game is remembered for that game.** It used to last only for the session.
- **A, B and Y do what the hint bar says.** In the game list and the game detail the focus no longer
  starts on the back arrow, so A opens the game or plays it instead of going back, and the "Y:
  Options" hint that did nothing is gone.

## Website

The site shows the new cartridges everywhere: the screenshots, the cartridge wall and the promo
video, which is now calmer and shorter. The "From one device to another" section plays an animation
of a real transfer on its own, in a loop: select games, Share, Receive, accept, the progress bar
filling up, and the game arriving in the library.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files and
input profiles are all kept.

- **Android**: install `OpenEmux-mobile-1.20.0.apk` over the app you have, including over a beta.
  Do not uninstall first: uninstalling an Android app deletes its data, games included.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

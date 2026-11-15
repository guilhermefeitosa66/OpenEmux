# OpenEmux 1.24.0

The couch release. **Big Picture** turns the desktop app into a full-screen layout for a TV and a
controller, laid out one to one like the Android app: a shelf of consoles, a big game grid, a page
for each game and a pause menu, all reachable with the pad. Around it, the desktop and Android apps
now share the same game icons, console art stays sharp at any size, and two problems reported by
mozertdev are fixed.

`OpenEmux-mobile-1.24.0.apk` installs over 1.23.5, or over any beta, and keeps your library.

## Big Picture: the couch layout

Press **F11** (or start with `openemux --big-picture`) and OpenEmux fills the screen with a layout
built for a sofa, a TV and a controller. **Guide**, **F11** or **Back to desktop** at the bottom of
the left rail takes you back to the normal window.

- **The shelf.** Every console as a coloured tile with its icon and its full name, plus All games,
  Favorites and your playlists. Search across every console from the top of the page.
- **The game grid.** A console's games fill the whole width, at the size the normal library uses at
  200% zoom. LB and RB switch consoles; the console chips above the grid show each console's icon.
  Filters for favorites, games with a save state, missing artwork and never played.
- **A page for each game.** Selecting a game opens it on its own page: large artwork, the core, the
  shader, the cartridge colour, playlists and save states. Back returns to the grid on the same game.
- **A pause menu.** Guide during a game pauses it and opens a full-screen menu in the style of the
  Android app: continue, restart, save and load with the slot, every saved state, fast forward and
  slow motion, screenshot, audio, RetroArch's own menu and quit. The pause gesture can be changed in
  Settings › Controllers.
- **A QWERTY on-screen keyboard** for search and names, instead of an alphabetical grid. X deletes,
  Y types a space.
- **Import from the pad**, with a file browser you can drive with the controller.
- **Settings in two panes**, and the clock in the bottom hint bar, which also shows what each button
  does on the current page.

## Sharp pixel-art console icons

The console icons are pixel art. Scaled up, they used to blur. They now scale only by whole
multiples, pixel for pixel, with a soft grid between the pixels when they are large, on the desktop
and on Android.

## Desktop

- **The window opens maximised.** Un-maximise it and it goes back to a normal size.
- **The in-game bar uses an eye to hide itself**, like Android: the old down arrow was easy to
  misread. Reported by mozertdev on Diolinux Plus ([issue 938](https://github.com/guilhermefeitosa66/OpenEmux/issues/938)).
- **The volume you set during a game is remembered**, and the next game no longer starts too loud.
  Reported by mozertdev on Diolinux Plus ([issue 939](https://github.com/guilhermefeitosa66/OpenEmux/issues/939)).
- **The in-game bar uses the same action icons as Android** for pause, fast forward, slow motion,
  mute and the rest.
- **Recently played** follows the library's view mode, cartridges included, and keeps only the 12
  latest games.

## Android

- **Save and load use the desktop's floppy icons**, redrawn for phone sizes, in the pause menu and in
  the on-screen quick buttons (copied skins included).
- **Controller focus changes the item's background** instead of drawing a glowing ring around it.
- **The console chips show each console's icon** next to its short name.
- Enlarged console icons get the same soft pixel grid as the desktop.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files,
skins and input profiles are all kept.

- **Android**: install `OpenEmux-mobile-1.24.0.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included.
- **Desktop**: install the new package over the old one.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

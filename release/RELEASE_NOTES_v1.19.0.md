# OpenEmux 1.19.0

BIOS files stop being the part you have to sort out by hand. You can import them per console from a
file picker, on the desktop and on Android, and Share nearby now sends them along with the game. On
top of that, both apps call each console by one name, the desktop header bar is tidier, and the
Android app makes better use of a phone held sideways.

## BIOS files travel with the game

Share nearby used to send the game, its saves, its save states and its artwork, but not the BIOS the
console needs. A PlayStation or Sega CD game would arrive on the other device and refuse to start,
even though the sending device had the BIOS all along.

Now the console's BIOS files go with the game, in every direction: desktop to Android, Android to
desktop, and between two of either. The receiving side puts them where it looks for BIOS, whatever
layout the other side uses. Only the BIOS files OpenEmux knows for that console are sent, never
anything else from the folder. A BIOS the receiver already has is skipped, and a different file under
the same name is never overwritten silently. The offer and the transfer report list the BIOS files
next to the other items, so you can see they came along.

Both devices need 1.19.0 for this. An older OpenEmux on the other side still receives the game, just
without the BIOS.

## Import BIOS files per console

**Desktop.** Getting a BIOS in used to mean opening the console's folder in the file manager, copying
the file there under exactly the right name, and then finding the small reload button so the app
would notice it. Now each console in Settings → BIOS has an **Import** button. Pick one or more
files: the ones whose name matches what that console expects are copied in, and the status updates
straight away. Anything that was not accepted is listed with the reason, so a file in the wrong
console or under a slightly different name no longer fails in silence.

**Android.** The single "Import from device" button, which asked for a whole folder and only reported
a count, is replaced by the same per-console **Import**. You pick the files, and a summary tells you
what was imported, what was not and why, and which names that console expects.

## One name per console

Consoles used to carry every regional name at once, "Nintendo (NES) / Famicom" or "Sega Genesis /
Mega Drive", which crowded the sidebar and the shelf. Each console now has one name, the most widely
known one: Nintendo (NES), Super Nintendo, Mega Drive, Mega CD, PC Engine, PC Engine CD and
Odyssey². Both apps use the same names, so a game shared between them reads the same on both ends.
Only the label changed: your folders, playlists, covers and cores are untouched.

## Desktop

- **A tidier header bar.** The three-button Cover / Cartridge / List switcher is gone. It repeated
  what the **View mode** button already offers, which stays as the one place to change the view.
- **A sun that looks like a sun.** The light/dark toggle showed a sun that, at that size, read as a
  plain circle. It now has clearly separated rays and matches the moon next to it, whatever icon
  theme your desktop uses.

## Android

- **"All" next to "Favorites" on the shelf.** The whole library is one tap away from the first
  screen, in a card beside Favorites.
- **Game Boy Color has its own icon,** in the colours of the Pikachu edition, so it no longer looks
  like the Game Boy card.
- **Landscape game list in one row.** Back, the console filter, search, sort and view now share a
  single row at the top. The console filter is a pager you step through with the arrows, or with
  the shoulder buttons when a controller is connected. The space saved goes to the covers.
- **Landscape console labels above the row.** In "All", Favorites and search, the console label no
  longer takes a game's slot in the row. A small label above the row names the console you are
  scrolling through, with its icon.
- **Landscape game detail without scrolling.** On a phone held sideways, the cartridge sits on the
  left and the actions on the right, so Continue, Restart and the cartridge colour are on screen
  without scrolling.

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

- **Android**: install `OpenEmux-mobile-1.19.0.apk` over the app you have, including over a beta.
  Do not uninstall first: uninstalling an Android app deletes its data, games included.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

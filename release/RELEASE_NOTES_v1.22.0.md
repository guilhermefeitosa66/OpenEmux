# OpenEmux 1.22.0

An Android release about what happens while you are playing. The pause menu can now change and edit
the skin without leaving the game, save states show their whole picture and can be deleted, a game
being received no longer holds you on the transfer screen, and "Restart game" restarts the game. The
desktop app has no changes in this release: it moves to 1.22.0 only to keep both apps on the same
version number.

`OpenEmux-mobile-1.22.0.apk` installs over the app you have and keeps your library.

## Android: change and edit the skin without leaving the game

([#827](https://github.com/guilhermefeitosa66/OpenEmux/issues/827))

Trying a skin used to mean saving a state, quitting the game, going to the skin screen, changing it,
launching again and loading the state. Whether a layout is comfortable can only be judged while
playing, so every small adjustment cost that whole trip.

The pause menu has two new rows:

- **"Change skin"** shows the same cards and miniatures as the console's skin screen. Tap one and it
  is on the running game.
- **"Edit skin"** opens the editor on the skin in use, with the game paused behind it. Save, and you
  are back where you stopped, with the new layout on screen.

No state is saved or loaded, and the game is never closed. A bundled skin is copied the first time
you edit it, and cancelling leaves the skin as it was.

## Android: save states show the whole picture, and can be deleted

([#828](https://github.com/guilhermefeitosa66/OpenEmux/issues/828))

- **The thumbnails were cropped.** They now show the whole screen of the game, everywhere states are
  listed.
- **A state can be deleted.** Press and hold it, or use its three-dots button. It asks first, and the
  other states keep their slot numbers.
- **The in-game menu has a slot selector.** Arrows around "Save state" pick the slot, from 0 to 99,
  and it always says which one and whether it is already in use.

## Android: keep playing while a game arrives

([#829](https://github.com/guilhermefeitosa66/OpenEmux/issues/829))

Accepting a transfer in Share nearby kept you on the progress view: the transfer itself carried on
in the background, but Back only offered to cancel it. Now Back, or "Continue in Background", leaves
the view and the transfer goes on. A chip above the tabs shows how far it is and reopens the view, as
does the notification, and the result is there when it ends. Sending works the same way once the
files are moving.

## Android: "Restart game" restarts the game

([#831](https://github.com/guilhermefeitosa66/OpenEmux/issues/831))

The row in the in-game menu did nothing visible on its first press, because it was treated like the
reset hotkey, which asks you to press it twice. It now asks once, in a dialog, and restarts the game
on that confirmation. The skin's Restart key and the gamepad hotkey keep their press-twice guard,
since those sit under your fingers.

## Android: the D-pad and sticks are easier to catch

([#826](https://github.com/guilhermefeitosa66/OpenEmux/issues/826))

A thumb that landed just beside the on-screen D-pad or an analog stick did nothing. A touch that
starts up to about a thumb's width outside the control now grabs it, and the zone stops short of the
neighbouring buttons and the game picture. Nothing drawn on the skin changes, and the wider zone only
counts when a touch starts.

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

- **Android**: install `OpenEmux-mobile-1.22.0.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included.
- **Desktop**: no changes from 1.21.1; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

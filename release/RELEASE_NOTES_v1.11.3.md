# OpenEmux 1.11.3

One fix, for a failure that took a working game and made it unplayable.

## The game window vanished and left the game trapped

Reported by **u/CoverUnited** on Reddit, playing on a Wayland desktop:

> everytime I open a game, it opens in a window where you can control volume, controller etc, perfect, but if I move that window, it disapears given place to a square in the center of the monitor without any chance of moving it or anything else, but gaming still going.

That is exactly what happened, and it took two things at once.

When a game plays inside the OpenEmux window, RetroArch is told to drop its own title bar, borders and fullscreen hotkey — correct, because the OpenEmux window is the one holding it. Adopting RetroArch's window is an X11 operation, so on a Wayland desktop both programs have to land on XWayland for it to work. When RetroArch came up on Wayland instead, there was no window to adopt.

The OpenEmux window then waited **twenty seconds without saying anything**, closed itself, and deliberately left the game running — but running with no title bar to drag, no borders to resize, and its fullscreen hotkey unbound on purpose. An undecorated square in the middle of the screen that could not be moved, resized or escaped, with the game still playing inside it. Nothing explained any of it, which is why moving the window looked like the cause: the twenty seconds simply ran out around the same moment.

Four changes, from prevention to rescue:

- **RetroArch is kept on X11 while the game window is on.** Its Wayland connection is denied rather than merely discouraged, and a saved RetroArch setting can no longer override that. Most of the time the adoption now just works where it used to fail.
- **The wait is visible and short.** The window shows a spinner and the game's name while the game starts, instead of a black rectangle. And RetroArch announces which display system it chose as soon as it has video, so OpenEmux reads that and knows within seconds — not twenty — whether adoption can ever happen.
- **The game is handed back, never stranded.** If adoption fails, OpenEmux says so and reopens the game in RetroArch's own **normal window**: title bar, movable, resizable, fullscreen hotkey working, pausing when it loses focus. Every later game that session opens that way from the start, so one failure is never repeated.
- **A gamepad can no longer break it.** The fullscreen hotkey was unbound on the keyboard but not on the pad, so pressing that button made RetroArch rebuild its window and the game fell out of the OpenEmux one. Both are unbound now, and the keyboard fullscreen key still works — the OpenEmux window handles it.

Same for a session that can never embed at all: OpenEmux now says the game is opening in RetroArch's own window instead of failing silently, and RetroArch keeps its decorations.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to configure. Settings, playlists, artwork, save states and input profiles are all kept.

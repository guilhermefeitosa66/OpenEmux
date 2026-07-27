# OpenEmux 1.9.1

A patch release on top of 1.9.0, built around one crash and the artwork work it exposed.

## The crash

Picking an entry in a game's context menu could take the whole app down — the report that started this was *Sync label…* on a SNES game, which closed OpenEmux with a segmentation fault and no message.

The action ran from inside the click, while the menu was still coming down: it opened a window, the grid dropped the popover in the same pass, and GTK crashed laying the main window out, still holding a pointer focus that pointed into a menu whose surface had just been destroyed.

Menu entries now close the menu first and run the action once that teardown is over. This was never specific to artwork — every context-menu entry took the same path — so the fix covers all of them.

Crashes below Python cannot be caught, only recorded. OpenEmux now writes the native stack into its log on the way down, and logs unhandled exceptions from background threads, so the next one arrives as a report instead of a blank terminal.

## Sync and manage are two different things

*Sync cover…* and *Sync label…* opened the artwork manager, which is not what they say. They are the quick action now: click one and that game's artwork is fetched in the background, through the same provider chain the library-wide sync uses. Because asking for one game by hand usually means what it has is wrong, the fetch replaces artwork already on disk rather than skipping it.

The manager gets entries of its own — **Manage cover…** and **Manage label…** — for when you want to look through what the providers have, or import your own.

## The artwork manager

- **Results are laid out on the library's own grid**, at its largest zoom, with the console's cover proportions. Judging a cover from a 160px thumbnail was never going to work.
- **The picked image is marked** with a check stamped on the artwork itself, so what *Save* will apply is not left to a thin outline.
- **A running search can be cancelled.** The provider chain can take a while, and closing the window was previously the only way out.
- **An imported image gets the whole area.** The drop zone steps aside once there is an image, with a trash button in the corner to clear it and pick another.
- **The edit controls are one row** — crop, flip, rotate, reset and the save destination — instead of two competing toolbars.

## Upgrading

Nothing to do. Settings, playlists, artwork and input profiles are all kept.

## Verify what you downloaded

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

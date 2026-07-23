# OpenEmux 1.6.0

Your library, arranged the way you want it: three layouts, six sort orders and a zoom control, all one click from the toolbar instead of buried in a settings dialog. OpenEmux also speaks your language on first launch now, and the controller finally reaches every part of the interface — including the button that was, until this release, impossible to bind.

## Choose how the library looks

A **View Mode** button sits in the header, next to search:

- **Cover Grid** — box art on a grid
- **Cartridge Grid** — the shelf look, still the default
- **Compact List** — one game per row: thumbnail, title and platform

The cartridge frame used to be a switch inside Preferences, which is the wrong place for something you change while looking at your games. The Preferences row is still there and still works — it just mirrors the toolbar now.

## Zoom the artwork

The same menu holds a `−  100%  +` stepper, or use `Ctrl+plus`, `Ctrl+minus` and `Ctrl+0`. Six steps from **50% to 200%**, remembered between sessions.

Zoom does not just scale the covers: the gaps between cards move with them, so zooming out gives you more games *and* a tighter grid, not the same sparse layout with smaller pictures. At 200% three columns of large art; at 50%, eight.

## Sort the library

Six orders, behind **Sort by** in the same menu:

| | |
| --- | --- |
| Name (A-Z) / (Z-A) | case-insensitive, so lowercase titles are not exiled after the Z's |
| Recently played | see below |
| Recently added | when *your* copy of the file appeared, not when the ROM was made |
| File size | largest first |
| Platform | grouped by console, alphabetical inside each |

The choice applies to every page — each console, Favorites and All — and is remembered.

**Recently played** needed something OpenEmux never recorded: it now stamps each launch in `~/.openemux/play_history.json`. Nothing is uploaded anywhere, renaming a game carries its history with it, and deleting one forgets it. The order starts out flat, of course, and fills in as you play.

## It starts in your language

OpenEmux opened in English no matter what your desktop was set to. It now reads your session's locale on first launch and picks the closest translation it ships: `pt_BR` and `pt_PT` both get Portuguese, `es_MX` gets Spanish, `fr_CA` gets French, `zh_TW` gets 简体中文, and anything unsupported still gets English.

Your own pick always wins: choose a language in Preferences and it stays chosen. If you never picked one — which includes every existing install still sitting on the English default — OpenEmux now follows your desktop.

## Remapping a controller works

Assigning **B** on an Xbox pad used to close the configuration dialog instead of storing the binding, because the interface was still reading that button as "go back". Any button whose meaning overlaps with UI navigation had the same problem, which made the pad essentially unconfigurable from within OpenEmux.

The remapping dialog now takes the controller for itself while it waits. Navigation goes quiet — held directions stop repeating too — and comes back the moment the mapping is stored or cancelled.

## The controller reaches the rest of the interface

**Select** opens the main menu, so Preferences, Keyboard Shortcuts and About are finally reachable without a mouse. Press it again to close it.

**The right analog stick** steers as well as the left one. The triggers deliberately do not: a resting trigger reads as a held direction on most pads.

**Focus comes back where you left it.** Closing a dialog or a menu could leave the window with nothing focused at all, which on a controller is a dead end — every direction resolves against nowhere. Close Preferences with B now and you are back on the same game you opened it from.

**You can see where you are.** GTK only draws focus rings once it decides you are using a keyboard, and focus moved by a gamepad did not always qualify. While you are on a pad or the keyboard, the rings stay visible.

## Also in this release

- List rows share one thumbnail column, so titles line up down the page whatever shape each console's box art is.
- All and Favorites no longer force their own name ordering over the one you chose.

## Upgrading

Nothing to do. Your existing settings carry over: the cartridge switch becomes the matching view mode, and the language behaviour is described above.

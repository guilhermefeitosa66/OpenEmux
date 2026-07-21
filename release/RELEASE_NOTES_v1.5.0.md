# OpenEmux 1.5.0

You can put the mouse down. This release makes the whole library navigable with a gamepad or the keyboard, the way a console interface should be — and fixes the packaged builds, which were in worse shape than they looked.

## Drive the library with a gamepad

Plug in a controller and the interface answers to it. The D-pad and the left stick move through your games, **A** launches, **B** steps back, **X** opens the game's menu, **Y** favorites, and **L1/R1** flip between consoles. Start launches too. Held directions repeat, so crossing a long shelf is one press.

It follows the RetroArch convention on purpose: the buttons mean the same thing here as they do in the emulator you are about to launch.

Any connected controller works, and plugging one in mid-session is enough — no restart, no configuration. While a game is running the pad belongs to RetroArch, so OpenEmux stops listening until you come back. Preferences → Interface turns the whole thing off if you would rather it did nothing.

## The keyboard reaches everything

Arrows move through the games, Enter plays, Esc steps back. `Right` goes from the console list into the games, and `Tab`, `Esc`, `Backspace` or `F6` bring you back — deliberately *not* into the toolbar buttons on the way.

Actions have keys now too:

| | |
| --- | --- |
| `Enter` | Play the focused game |
| `Menu` | The game's context menu |
| `Ctrl+D` | Toggle favorite |
| `F2` | Rename |
| `Delete` | Delete |
| `F5` | Rescan the current console |
| `Ctrl+O` | Import ROMs |
| `Ctrl+Shift+S` | Sync cover art |
| `Ctrl+Escape` | Stop the running game |

The full list lives in Menu → Keyboard Shortcuts, now split into General, Library and Games.

## The bottom bar tells you what the buttons do

The right side of the status bar shows what each control does right now — Ⓐ Play, Ⓑ Back, Ⓧ Options — switching between gamepad glyphs and key names depending on what you last touched, and staying out of the way when you are using the mouse.

## The game grid lays out properly

Cards used to drift apart as the window widened, because the underlying widget shares the leftover width *between* them. They now pack left to right with fixed gaps and wrap to the next line, the way a file manager lays out icons, with the rows packed to the top.

Card sizes are fixed per console and follow that console's box-art proportions — a tall NES slab is not the same shape as a wide SNES cover — while All and Favorites use one uniform size, since they mix consoles. Selecting a game no longer draws an oversized border across empty space.

## The packaged builds actually work now

Three things that made 1.4.0 worse than running from source:

**The AppImage showed no cover art and no cartridges.** Two bundling faults: the image-loader cache shipped with the *build machine's* paths baked into it, so nothing could be decoded on your machine, and the bundle never pointed at its own vector library, so cartridge frames failed silently and fell back to plain covers. Both are fixed, and the build now refuses to produce a bundle missing either.

**The `.deb` installed but would not start.** The launcher used whatever `python3` your `PATH` offered. If you use pyenv, conda or asdf, that is a shim without the GTK bindings, so a correctly installed OpenEmux died with `No module named 'gi'`. It now picks an interpreter that actually has them.

**The app was hiding its own menu entry.** Running from a source checkout wrote a desktop entry into your home directory, and that entry takes precedence over the one a package installs — so after installing the `.deb`, the menu still pointed at the developer tree. A packaged install no longer writes one, and clears a stale one it finds.

## Flatpak support is gone

The Flatpak manifest is removed and OpenEmux is distributed as **AppImage, `.deb` and `.rpm`** only. The sandbox needed permissions that made the RetroArch hand-off fragile, and maintaining a fourth format was not paying for itself. If you installed the Flatpak, switch to one of the three above; your library and settings in `~/.openemux` are untouched.

## Also in this release

- Cards show their play overlay and buttons when reached by keyboard or gamepad, not only on hover.
- Packaging was reorganised: one entry point per format, each building in its own container, each install-testing its own artifact.

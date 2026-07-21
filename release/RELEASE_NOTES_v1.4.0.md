# OpenEmux 1.4.0

Two things in this release: your games are shown inside the cartridge they shipped on, and the library finally lets you manage the ROMs in it — rename, delete, and act on several at once.

## Games sit inside their cartridge

A grid of box art tells you what you own. A shelf of cartridges tells you what console each game belongs to at a glance — the grey Game Boy shell, the black Mega Drive one, the tall NES slab.

The cartridge look existed before this release, but it was marked beta and off by default, and for good reason: each frame was a PNG with the cover positioned behind it by hand-measured coordinates, redone for every card on every redraw. Three consoles had one, and adding a fourth meant measuring pixels.

It now works the other way around. A frame is an **SVG** holding the cartridge art plus one object marking where the label goes. The renderer reads that object's position *and its exact shape* straight from the artwork, drops the cover into it, and stamps the cartridge on top — once, cached to disk as a single flat image. Adding a console is one SVG file and no code, and because the source is vector the result is sharp at any size.

**Nine consoles** ship with a cartridge: NES/Famicom, Game Boy, Game Boy Color, Game Boy Advance, Nintendo 64, Nintendo DS, Mega Drive/Genesis, Master System and Super Nintendo. The look is **on by default** now; Preferences → Appearance turns it off.

A game with no cover art gets a blank cartridge rather than a generic icon, so the shelf still reads as a shelf.

## Favoriting is one click

The star on a cover was a badge — it told you a game was a favorite but did nothing when clicked. It is a button now, in the same place, matching the "…" button on the opposite corner: lit on a favorite, and appearing on hover otherwise.

## Rename a ROM

New in the context menu. Type the new name and the **file on disk is renamed too**, keeping its extension. Everything keyed to the name follows: the cover art, the cartridge image, the console playlist and your favorites.

For a zipped ROM, the entry *inside* the archive is renamed as well. The library shows the name of the ROM inside the zip rather than the zip's own name, so renaming just the container would have left the card showing the old title.

The dialog opens with the name focused and selected, so renaming never needs the mouse.

## Delete a ROM

Also new in the context menu, behind a confirmation. The file is **moved to your system trash**, not erased — if you delete the wrong game, it is where you would look for it. If the drive has no trash, the delete fails and says so rather than quietly turning permanent.

## Select several ROMs at once

Drag across the empty area of the library and a selection band sweeps up every cartridge it touches. Ctrl-click builds a selection one game at a time.

A bar appears at the bottom with what you can do to the lot:

- **Delete** — the same confirmation, for the whole selection.
- **Sync covers** — fetches artwork for *only* those games, instead of walking the entire console.

Clicking an empty spot, or leaving the page, drops the selection.

## Under the hood

- Rendering nine consoles at once surfaced a crash that a single console never could: librsvg handles are not thread-safe, and the grid fills its cards from several threads. Sharing one handle aborted the whole application with a Rust panic. Handle use is serialised now, and a test drives 24 renders across 8 threads to keep it that way.
- Cartridge images are cached under `~/.openemux/cache/cartridges/`, keyed so that replacing a cover regenerates the image on its own. The folder is safe to delete at any time.
- SVG rendering needs the librsvg introspection typelib. The `.deb` and AppImage now depend on it; Fedora already provided it, and the Flatpak runtime ships it.

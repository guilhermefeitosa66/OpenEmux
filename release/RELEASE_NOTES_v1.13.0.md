# OpenEmux 1.13.0

A focused release about one thing: the library becomes **yours**. It remembers where you left it,
it stops mixing every console into one alphabetical pile, and the consoles finally sit in the order
you put them in — not the order they happen to be declared in.

Five issues ([#382](https://github.com/guilhermefeitosa66/OpenEmux/issues/382)–[#386](https://github.com/guilhermefeitosa66/OpenEmux/issues/386)),
all of them about navigating and presenting what you already own.

## The library opens where you left it

Close OpenEmux on SNES, open it again on SNES.

Nothing was remembered before. The landing page was computed from what was on screen *right now*,
and at startup there is nothing on screen — so every launch fell through to the same default,
"Favorites", whether you had any favorites or not.

The view you were on is now written as it changes and again when the window closes, so it survives
a crash, a `pkill` or a logout, not just a clean exit. It lives in a **small session file of its
own** rather than in `config.yaml`: your ROM path, credentials, per-console cores and input
profiles have no business being rewritten every time you click a sidebar row.

If the remembered view is gone by the next launch — the console lost its ROMs, the collection was
deleted — the library lands on Favorites when you have some, and on All when you do not.

## "Favorites" appears with the first star

The sidebar used to offer "Favorites" on every library, including one where nothing had ever been
starred. Selecting it landed on *"No favorites yet: right-click a game and choose Add to
favorites"* — a row that could only ever disappoint, sitting above every console that actually had
games in it.

It now appears the moment you star your first game and goes when you unstar the last one. Every
path that changes favorites reaches the sidebar: the star badge, the context menu, `Ctrl+D`, the
gamepad's Ⓨ, deleting a ROM, and the pruning that runs when a drive is missing.

Unstarring the last game *while standing on the Favorites page* keeps the row, so the empty state
can explain what just happened; it goes on your next navigation away. Collections are deliberately
not treated this way — you created those, and they would otherwise have nowhere to drop games.

**A crash came out of this work.** The star badge, `Ctrl+D` and the gamepad's Ⓨ were all dying with
a `RecursionError` before touching your favorites — a function that called itself, left behind by a
refactor in 1.12.0. Only the context-menu entry still worked. It is fixed, with a test.

## "All", "Favorites" and collections group by console

Those three pages were one flat grid sorted A-Z, so a Mega Drive game sat between two SNES ones and
the eye had nothing to hold on to.

They are grouped by console now — each group under a header with the console's icon, its name and
its game count — and the groups follow the order the consoles have in the sidebar. Each group is
bound to a single console, so it draws that console's box-art proportions and drops the console
caption the flat page had to print on every card; the header above already says it.

Everything that treated the page as one grid still does: search filters within the groups and hides
the ones it empties, headers and counts included; `Ctrl+A` and the list view's master checkbox
cross every group; the selection bar reports the whole page; and arrowing off the bottom of one
group enters the next. "Platform" is no longer offered as a sort order on these pages — every game
already sits under its console's header, so it would change nothing.

**One trade-off, stated plainly:** a grouped page builds a card per ROM instead of a screenful. The
virtualization from 1.12.0 still holds on the console pages, which is where a single console's
thousands of ROMs live, but "All" on a very large library now pays for what it shows. Grouping and
virtualizing across sections at the same time needs a layout GTK's grid view does not have; that is
separate work.

## The cartridge shelf reaches those pages

The cartridge shelf is the look OpenEmux ships with — and it was exactly the look you could not get
on "All", on "Favorites" or in a collection. Those pages drew plain covers whatever the view mode
said. Nothing blocked the *action*, either: you could pick "Cartridge" there and simply see no
change, which reads as a bug.

With the games grouped by console, each group is drawn in **its own console's cartridge**. NES
cartridges, then Game Boy, then Game Boy Advance, each with its own proportions. Zoom scales the
frames as it does on a console page, the mode is remembered per page, and the per-ROM cartridge
colour submenu works there too.

A console nobody has drawn a cartridge for renders covers in its group while the rest of the page
keeps its shelf — the same fallback a console page has always had, applied per group. List view is
unchanged: rows show box art, never a frame.

## Consoles go where you put them

The consoles were in the declaration order of an internal list — an order nobody chose and nobody
could change.

You arrange them now:

- **Drag a console row** up or down the sidebar, with a line showing where it will land.
- **`Ctrl+Up` / `Ctrl+Down`** on the focused row, because drag-and-drop is unusable with a keyboard
  or a gamepad and both of them drive this sidebar. "Move up" / "Move down" are in the row's
  context menu too.
- **Preferences → Library → "Console Order"**, with per-row arrows and "Restore default order".

It is one order: the sidebar, the console groups on "All", "Favorites" and the collections, and the
console cycling all follow it. Only consoles take part — "All", "Favorites" and the collections
cannot be displaced or dropped onto, and a dragged row can never be swallowed by the ROM file-drop
target.

A console with **no games right now keeps its slot**, so when you import for it again it comes back
where you put it. A console added in a later release lands at the end rather than at a position
nobody chose.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with — don't run it.

## Upgrading

Nothing to configure. Settings, playlists, artwork, save states and input profiles are all kept.

- The **remembered view** starts empty, so your first launch after upgrading lands on Favorites if
  you have any and on All if you do not; from then on it follows you.
- The **console order** starts at the default, which is the order you have today. Nothing moves
  until you move it.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

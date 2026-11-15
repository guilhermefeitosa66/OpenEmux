# Big Picture: the couch layout

Big Picture is OpenEmux drawn for a TV and a controller: one page at a time,
read from three metres away, driven with a pad from a sofa. It replaced the
"TV mode" of 1.23.x (issue 914), which only put the desktop layout in
fullscreen and zoomed it: the sidebar became a full-screen console list, and
walking it with a D-pad was the part that did not work. Big Picture is not
the desktop enlarged. It is a layout of its own, built the way the Android
app looks when a controller is connected, so a player who uses both sees one
product.

Since issue 957 the layout follows the Android app's gamepad layout element
by element: the analysis comment on that issue lists every Android element
with its decision (port, adapt, drop) and the maintainer's four decisions
(keep the clock, drop the quick menu, a pad-driven file browser for Import,
Guide opens the pause menu). This document records how the code carries
them.

## In and out

| Way in | Way out |
|---|---|
| F11 | F11 |
| The pad's Guide/Home/PS button | The same button |
| The header-bar button (a screen icon, next to Search) | "Back to desktop", last on the rail |
| Main menu › Big Picture | |
| `openemux --big-picture` | |
| Settings › System › "Start in Big Picture" | |

F11 is handled in the window's capture-phase key controller, not as an
application accelerator. In the 1.23.5 AppImage on Cinnamon the accelerator
never fired while the same key worked from the Flatpak; the capture handler
does not depend on the accelerator path reaching the window, and the header
button and the menu entry are two more ways in that need no key at all. With
both the handler and the accelerator registered, one press toggled twice, so
the accelerator is gone; the shortcuts window still lists F11.

The desktop layout is never torn down. The window holds both layouts in a
stack; entering the mode moves the window's page stack (the grids, the
grouped pages, the empty states, the search's "no match" page) under the
games page's chips and gives it back on the way out, so leaving lands on exactly
the desktop that was there, on the same page. Settings changed in either
layout are the same config.

## The navigation model

The pad means the same thing on every page:

| Button | Everywhere | On the games |
|---|---|---|
| D-pad, left stick | Move the focus | Move between cards; Up/Down cross console groups on All |
| A | Open / confirm / change | Show the game in the detail pane; hold for selection mode |
| B | Back one level; on a tab's first page, back to the Library; never leaves the mode | Back to the Shelf (from the pane, back to the grid) |
| X | The page's secondary action | Favorite |
| Y | The page's other action (Order on the Shelf, Share in the pane) | The game's options |
| LB / RB | The tabs, from a tab's first page; the games beside one on an expanded game | The console chips |
| LT / RT | Shift on the text keyboard; range in selection mode | Range selection |
| View (Select / Share / −) | Search: the on-screen keyboard | |
| Menu (Start / Options / +) | Search (Done on the keyboard) | Multi-select |
| Guide / Home / PS | Leave Big Picture; during a game, the pause menu | |

With a keyboard: arrows, Enter, Escape as B, Tab and Shift+Tab as the
shoulders, Ctrl+D as X, Alt+Enter as Y, Ctrl+F as View, Menu as Menu, F11
as Guide. Escape, like B, never leaves the mode. The hint bar, centered as
on Android, always shows what the buttons do, with the letters of the pad
in hand (Xbox, PlayStation, Nintendo or generic, or the keys when a
keyboard is driving); the confirm key is drawn filled in the accent.

The contexts the navigator tells apart (`ui/navigation.py`): the Shelf,
the games page, the detail pane, the tab rail, a page of rows, the
on-screen keyboard, the grid and its multi-select, the file browser and the
pause menu, plus the desktop's own dialog and popover contexts. Dialogs
that remain dialogs (share nearby, the welcome tour, the import's "which
console" question, every confirmation) are the desktop's, drawn bigger by
the theme.

## The pages

- **The rail**: the app's logo, then Library, Recent, Import and Settings,
  the tab on screen on an accent pill; last, "Back to desktop", drawn like a
  tab but an action: A leaves the mode, LB and RB skip it (issue 978).
- **Shelf** (the Library tab's first page): "Shelf", "N consoles · M
  games", a "Search all consoles" field and "Import ROMs"; the task banners
  (a running task with its progress, a newer release); then the cards three
  to a row: All games, Favorites, the playlists, and one card per console
  in the console's own color (`core/big_picture_shelf.py`, copied from
  Android's `Console.kt`) with its art, short code, name and count.
- **The games** of a scope, list-detail: on the left the back link, the
  eyebrow, title and count, the console chips (LB/RB), the filter chips
  with counts (`core/library_facets.py`), the view's name with the
  Cartridges / Covers / List switch (Big Picture's own view, the desktop's
  untouched), and the window's own page for the scope, borrowed; on the
  right the detail pane.
- **The detail pane** (`ui/bigpicture/details.py`): expand, favorite and
  share; the art with "Search artwork…"; the title with its pencil; "Console
  · Core · played"; Play (Continue with an automatic state); the save states;
  Core, Shader (with a DEFAULT tag for the console's value), cartridge color
  and playlists. Expanded, it is a page and LB/RB walk the games.
- **Recent**: the last 12 games played, with their last state's screenshot.
- **Import**: Choose files, Choose a whole folder (both open the pad file
  browser: folders first, A enters or marks, X marks, Y imports, B goes up),
  Receive games, and every console's accepted formats.
- **Settings**: Android's list on the left (the BIOS card; Appearance,
  Achievements, Artwork, one entry per console, Share nearby, General), the
  chosen entry on the right. Every row calls what the
  desktop dialog calls; Big Picture asks before the irreversible actions.
- **The launch splash**: the game's art and "Starting <core>" until the
  game's window takes the screen; a launch that fails says why there.
- **The pause menu** (`ui/bigpicture/pause_menu.py`): the gesture is
  watched by the pad reader during a game (`core/pause_trigger.py`; Guide by
  default, or hold Start, Start + Select, L3 + R3, off); the game is paused
  over the command channel and a full-screen window shows Continue, Restart,
  Save and Load with the slot slider, See all, Fast forward, Slow motion,
  Screenshot, Audio, RetroArch's menu and Quit (`core/pause_session.py`).
  If the window cannot come to the front in two seconds, RetroArch's own
  menu opens instead.

## Scale and theme

Every size comes from one number: the window's height over 1080 times the
"Text size" setting (80–150%). GTK's CSS cannot multiply, so
`ui/bigpicture/theme.py` generates the stylesheet and the shell reloads it
when the window changes size or the setting moves.

The palette is the Android app's dark one, always, whatever the desktop's
theme (the style manager is forced dark while the mode is on and given back
after). The controller focus is issue 951's: the focused item's background
takes a deeper purple, nothing is drawn around it; art items (a card, a
cartridge) sit on a plate of that tone.

## What stayed out, and why

- Skins, the skin editor and the touch controls: phone things.
- The pause menu's Shader and Screens tiles: the command channel has no
  verb to set a shader by path, and the desktop has no DS layout choice.
- A live frame of the game behind the pause menu: grabbing one needs a
  screenshot round trip through RetroArch.

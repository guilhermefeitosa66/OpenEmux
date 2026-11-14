# Big Picture: the couch layout

Big Picture is OpenEmux drawn for a TV and a controller: one page at a time,
read from three metres away, driven with a pad from a sofa. It replaced the
"TV mode" of 1.23.x (issue 914), which only put the desktop layout in
fullscreen and zoomed it: the sidebar became a full-screen console list, and
walking it with a D-pad was the part that did not work. Big Picture is not
the desktop enlarged. It is a layout of its own, built the way the Android
app looks when a controller is connected, so a player who uses both sees one
product.

Design canvas: the Claude Design project "Big Picture mode — OpenEmux
desktop" (18 artboards: library, details, search, quick menu, settings in
every section, capture, text entry, confirmations, import, covers, share,
first start, welcome, light theme at 720p). This document records the
decisions the canvas was drawn from and how the code carries them.

## In and out

| Way in | Way out |
|---|---|
| F11 | F11 |
| The pad's Guide/Home/PS button | The same button |
| The header-bar button (a screen icon, next to Search) | "Back to desktop" on the home page or in the quick menu |
| Main menu › Big Picture | The quick menu's "Back to desktop" |
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
console rail and gives it back on the way out, so leaving lands on exactly
the desktop that was there, on the same page. Settings changed in either
layout are the same config.

## The navigation model

The pad means the same thing on every page:

| Button | Everywhere | On the games |
|---|---|---|
| D-pad, left stick | Move the focus | Move between cards; Up/Down cross console groups on All |
| A | Open / confirm / change | Play; hold for selection mode (issue #78) |
| B | Back one level; never leaves the mode | Back to the rail / pop the page |
| X | The page's secondary action | Game details |
| Y | The page's other action | Favorite |
| LB / RB | Previous / next console on the rail; sections in Settings; neighbouring game in details | Console groups on All |
| LT / RT | Shift on the text keyboard; range in selection mode | Range selection |
| Start (Menu / Options / +) | Search: the on-screen keyboard | |
| View (Select / Share / −) | The quick menu | |
| Guide / Home / PS | Leave Big Picture | |

With a keyboard: arrows, Enter, Escape as B, Tab and Shift+Tab as the
shoulders, Alt+Enter as X, Ctrl+D as Y, Ctrl+F as Start, Menu as View, F11
as Guide. Escape, like B, never leaves the mode: one Escape too many on the
home page would otherwise drop a keyboard user back on the desktop. The hint bar always shows what the buttons do, with the letters of
the pad in hand (Xbox, PlayStation, Nintendo or generic, or the keys when a
keyboard is driving); the confirm key is drawn filled in the accent.

The contexts the navigator tells apart (`ui/navigation.py`): the home rows,
the console rail, the games under the rail, a page of rows, the on-screen
keyboard, plus the desktop's own dialog, popover and selection-mode
contexts, which keep their behaviour. Dialogs that remain dialogs (share
nearby, the incoming offer, the welcome tour, the import's "which console"
question, every confirmation) are the desktop's, drawn bigger by the theme;
in all of them A confirms, B closes, and a destructive answer is never the
default.

## The pages

- **Home**: "Continue playing" (the last games launched, as wide cards),
  "Consoles" (every scope the sidebar lists: All, Recently played,
  Favorites, the playlists, the consoles with games) and "System" (search,
  import, covers, share nearby, Settings, back to desktop). Up and Down move
  between the rows, Left and Right within one.
- **Library**: the console rail over the games. The rail is the sidebar on
  its side, the current scope marked and centred; LB/RB step it from
  anywhere on the page. Under it, the same page the desktop shows for that
  scope, at a zoom floor of 150% with a 4 px focus ring and a slight lift on
  the focused card. The search keyboard slides up over the games and filters
  them as the letters go in; Done lands on the first match.
- **Game details**: a page, not a dialog. The cover and the save states on
  the left; the title, the play caption and a column of rows on the right:
  Continue/Play, Start fresh, Load a state, Favorite, Core, Shader,
  Cartridge color, Playlists, Artwork, Rename, Share nearby, Remove.
  LB/RB go to the neighbouring game.
- **Settings**: two columns, the sections on the left (Library, BIOS, Input,
  Video, Cores, System), the rows on the right. Every setting the desktop
  dialog has, with the same effect: a switch flips in place, a choice opens
  a full-page list and pops when picked, a text value opens the on-screen
  keyboard, a number steps with Left/Right, and the console order and the
  artwork providers are reordered with Left/Right on their rows. Big
  Picture asks before the irreversible actions the desktop does not
  (restore defaults, reset the mapping, import saves, sign out), because Y
  and A are easy to press on a pad. The controller mapping keeps the
  desktop's capture flow with three differences: every pad button is an
  answer during a capture, so none can cancel it, and an 8-second
  countdown, Escape or the Guide button do; cancelling never clears the
  binding (A on a bound action offers Remap, Clear or Keep); and leaving
  with unsaved bindings asks first.
- **Import ROMs** and **Sync covers**: the options on the left, the live
  progress on the right, so a pad user never meets the header-bar banner.
  The quick menu offers to stop the running task.
- **Quick menu** (View): search, import, covers, share, receive, rescan,
  Settings, back to desktop, quit.
- **First start** and the **welcome tour** keep their flows; in the mode the
  first-boot window is fullscreen and scaled.

## Scale and theme

Every size comes from one number: the window's height over 1080 (the canvas
was drawn at 1080p) times the "Text size" setting (80–150%). GTK's CSS
cannot multiply, so `ui/bigpicture/theme.py` generates the stylesheet and
the shell reloads it when the window changes size, the setting moves or the
theme flips. At 1080p: titles 40 px, rows 24/18 px, body and hints 22 px, a
64 px hint bar, a title-safe inset of 96 px on the sides and 54 px above.

The palette is the Android app's: its purple accent for the focus ring, the
primary row and the confirm key; surfaces from libadwaita's named colours,
so light and dark follow the app's theme setting. The focus ring is a 4 px
ring with a soft halo and a 4% lift, the same as on the phone.

## What stayed out, and why

- A per-family icon set for the hints: the letters in keycaps are what the
  Android app draws, and a font-independent glyph set is a separate piece
  of artwork.
- A file browser of its own for the import and the BIOS pickers: the GTK
  file dialog is keyboard-navigable and the pad's directions are keys to
  it; a second browser would be a second thing to maintain.
- Remembering a Big Picture page across sessions: the mode opens on home,
  and the library opens on the page the desktop had.

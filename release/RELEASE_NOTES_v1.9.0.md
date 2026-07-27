# OpenEmux 1.9.0

The biggest release so far, and it pulls in three directions at once: making the shelf *yours*, letting you act on many games instead of one, and putting the running game under your control without leaving the emulator window. It also ships OpenEmux as a Flatpak for the first time.

## Colour your collection

Cartridge view draws every game inside its console's shell — and now that shell has a colour. **Right-click a game → Cartridge color** and pick from a palette of twelve, on top of the original art.

Real shelves were never one colour: special editions, regional runs and Pokémon-style carts came in red, yellow, gold and clear plastic. Use it for that, or as your own filing system — one colour for "finished", one for favourites, one for hacks. The choice is remembered per game, follows a rename, and is dropped when the game is deleted.

The palette covers the full hue circle at even spacing, so any two picks are told apart at thumbnail size, and every tone is desaturated enough to read as moulded plastic rather than a UI accent. Adding a colour is a pure art change: drop a new SVG next to the console's frame and it appears in the menu.

## Select many, act once

Building a selection now works the way it does everywhere else on your desktop:

- **Mouse** — Ctrl+click toggles a game, Shift+click takes the range, Ctrl+Shift+click adds a range to what you already have, and dragging across empty space rubber-bands over whatever it sweeps.
- **Keyboard** — Shift+arrows extend the range from wherever you are standing, Ctrl+arrows move without selecting, Ctrl+Space toggles, Ctrl+A takes everything the search is currently showing and Ctrl+Shift+A clears.
- **Gamepad** — hold Ⓐ on a game to enter selection mode: Ⓐ toggles, a trigger held with the D-pad extends a range, Ⓨ selects all or none, Ⓧ opens the actions, Ⓑ leaves. On-screen hints explain it as you go, so nothing has to be memorised.
- **List view** — a checkbox on every row, and a header checkbox that selects everything shown, with an indeterminate state when only some are.

Select-all always respects the active search, and changing console clears the selection, as before.

## Artwork, under your control

**Per-ROM artwork manager** — *Sync cover…* (or *Sync label…* in cartridge view) opens a window that searches every enabled provider **by name or by ROM hash** and shows you what each one actually has, each result labelled with where it came from. Pick the one you like. An **Import** tab takes an image from your computer by drag-and-drop or file chooser, with crop, flip, rotate and reset — your original file is never modified.

**Providers are now a list you order.** Preferences → Library shows each source with move-up/down and an on/off switch: the topmost enabled one is tried first, the rest are fallbacks. Your existing cover-source setting carries over untouched.

**A new source: the OpenEmux mirror.** The project now hosts its own box-art set, so there is a fallback fully under OpenEmux's control rather than only third-party servers. Fresh installs try it first, then libretro, then ScreenScraper — the one that needs credentials and has a daily quota comes last.

Cover sync also got two fixes worth naming: syncing labels no longer skips games that merely have box art, and downloads keep their real file format instead of being renamed to `.png`.

## Command the running game

Enabling RetroArch's control channel means OpenEmux can finally talk to a game in progress:

- **Volume** — a slider and a mute button in the header while a game runs, remembered for the next launch. Prefer the keyboard? Volume up, volume down and mute are now bindable hotkeys.
- **Save states** — OpenEmux keeps them in its own per-console folder, and the ROM's context menu has a **Load state** list showing every slot with the date and time it was saved (empty ones are shown as empty). Pick one and the game starts from there. Which slot the save/load hotkeys act on is a setting, and stepping between slots is bindable too.

Saving and loading stay on RetroArch's hotkeys, where they belong — reaching for the mouse mid-game was never going to be an improvement.

## Controls that fit your hands

- **The analog stick can drive the D-pad**, so both work at once with no re-mapping. On per console, and off by default for the consoles whose pads use the stick natively (N64, PlayStation, PSP, GameCube, Saturn) so a game never loses its analog.
- **Turbo / autofire** — bind a Turbo modifier and hold it with any button to auto-fire, with adjustable period, duty cycle and mode per console. It stays unbound until you want it.
- The input mapping is now split into **Game Controls** and **System Hotkeys**, so the buttons a game reads are no longer mixed in with the frontend's own actions.

## Around the library

- The **view mode switcher moved into the header** as three buttons — cover grid, cartridge grid, compact list — one visible click each, collapsing back into the menu on narrow windows.
- Newly imported games fetch their artwork automatically, labels only for the consoles that have a cartridge to put them on.

## OpenEmux as a Flatpak

The Flatpak is back and is now a first-class release format. Two ways in:

```bash
# The repository — updates arrive with `flatpak update`
flatpak install -y flathub org.libretro.RetroArch
flatpak remote-add --if-not-exists --no-gpg-verify openemux \
  https://guilhermefeitosa66.github.io/openemux-flatpak/repo
flatpak install -y openemux io.github.guilhermefeitosa66.OpenEmux
```

Or grab the single-file `OpenEmux-1.9.0.flatpak` below and `flatpak install -y ./OpenEmux-1.9.0.flatpak`. Games are played through the RetroArch Flatpak, which manages its own cores.

## Verify what you downloaded

Every release from now on ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to do. Settings, playlists, artwork and input profiles are all kept. Your cover-source choice is carried into the new provider list, existing input profiles leave the new hotkeys unbound until you bind them, and save states you already had are found in place.

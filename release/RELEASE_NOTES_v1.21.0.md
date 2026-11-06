# OpenEmux 1.21.0

The input page now shows the console's controller, drawn, and you remap by clicking the button you
mean. Along the way it turned out that a number of buttons had been doing nothing in game, and they
are back. On Android, controller skins are now a format of OpenEmux's own, every console has one,
and you can edit them in the app or share them.

## Remap on a drawing of the controller

Suggested by mozertdev on Diolinux Plus
([#760](https://github.com/guilhermefeitosa66/OpenEmux/issues/760), delivered as
[#814](https://github.com/guilhermefeitosa66/OpenEmux/issues/814),
[#815](https://github.com/guilhermefeitosa66/OpenEmux/issues/815) and
[#816](https://github.com/guilhermefeitosa66/OpenEmux/issues/816)).

"Settings" → "Input" used to be a list of action names, and matching "L1" or "Y" to the pad in your
hands took a moment of thought on every row. The page now draws the selected console's controller,
in its own body colour, right above the list: the Super Nintendo pad, the N64 controller, the Game
Boy, all thirty-one consoles, using the same art the Android app's skins are made of.

- **Click a button on the drawing to remap it.** It lights up while it waits for the key or pad
  button, and the row in the list follows.
- **Hold a key, see the button.** With nothing being remapped, holding a mapped key (with the
  keyboard as the device) or a pad button, stick or D-pad direction (with a gamepad) lights the
  button it is bound to, for as long as it is held. Several light together. A hotkey lights only when
  it would fire: Select + Start lights the menu button, Start alone only Start.
- Hovering a button names it and its binding under the drawing, and Tab walks the buttons in order,
  so the drawing works from the keyboard and with a screen reader too.
- The pad is read for the drawing only while the input page is in front of you, and never while a
  capture is running; nothing changes a binding by being pressed.

## Buttons that did nothing in game are back

Drawing every control of every console showed which ones had no action behind them, and for most of
them that was worse than "not remappable": OpenEmux writes every RetroPad button a console does not
list as unbound at launch, so those buttons were dead in game, on a keyboard and on a gamepad alike.

- **Mega Drive, 32X and Mega-CD**: the six-button pad's A and Y.
- **Nintendo 64**: the Z trigger, and the four C buttons, which a keyboard could not press at all.
- **PlayStation**: L2 and R2. **PSP**: triangle and square. **Saturn** and **GameCube**: the L and R
  triggers.
- **Virtual Boy**: L, R and the right D-pad. **Vectrex**: buttons 3 and 4. **Famicom Disk System**:
  the disk side. **Atari 7800**: pause. **Intellivision**: the third side button.

Each of them now has its row in "Game Controls" and its target on the drawing, and a profile saved by
an earlier version gains the new buttons the first time it is loaded, keyboard and pads alike, with
nothing you bound changed. The right stick's four directions are new actions on the N64, PlayStation
and GameCube, bindable to keys like the left stick's; they start unbound.

The only control left not remappable is the "Keypad" switch of the Atari 5200, ColecoVision,
Intellivision and Odyssey² skins, which opens the on-screen keypad on Android and has nothing behind
it on the desktop.

## OpenEmux owns the whole input configuration

Suggested by mozertdev on Diolinux Plus
([#759](https://github.com/guilhermefeitosa66/OpenEmux/issues/759)), who found remapping "mixing
what was registered in OpenEmux with what was RetroArch's default".

Every game now starts from RetroArch's stock input defaults with your OpenEmux bindings laid on top,
for all sixteen players, so a hotkey or bind changed in your own `retroarch.cfg`, or a core remap
saved from RetroArch's quick menu, no longer sneaks into an OpenEmux launch or doubles up with a
button you remapped. Your `retroarch.cfg` itself is never touched; the launch log says which of its
keys were overridden.

## Windows: a portable mode that is actually portable

Reported by maxpelle72 ([#757](https://github.com/guilhermefeitosa66/OpenEmux/issues/757), delivered
as [#766](https://github.com/guilhermefeitosa66/OpenEmux/issues/766),
[#767](https://github.com/guilhermefeitosa66/OpenEmux/issues/767) and
[#768](https://github.com/guilhermefeitosa66/OpenEmux/issues/768)).

The Windows zip made the program portable but not its data: settings, library, saves and BIOS files
still landed in the user profile, and every stored path was absolute, so a USB stick that came up
under another drive letter lost its library.

- **Everything stays inside the unzipped folder**: settings, library index, playlists, input
  profiles, saves, states, BIOS files, covers and caches.
- **Paths are stored relative to that folder**, so it can move between drives and machines. ROMs on
  another disk keep their absolute path.
- **An existing installation can be brought along**: on the first start of an empty portable folder,
  and from Preferences afterwards, OpenEmux offers to copy the data of an installed OpenEmux into it.
  It copies, never moves, and a copy that fails never replaces a working portable folder.

## Game Boy Color has its own icon

The Game Boy and the Game Boy Color shared one icon, so two rows of the sidebar looked alike. The
Game Boy Color now has the yellow one the Android app shows.

## Android

### Controller skins in OpenEmux's own format

Skins used to be Delta and Manic packages, whose art was one flat image per layout. OpenEmux has a
format of its own now: `skin.json`, six layouts (phone and tablet, upright and sideways, and the
foldable's screens), and one image per control, so a button can be moved, resized, painted or
replaced on its own. Every bundled skin has been remade in it, for all thirty-one consoles,
including the keypad consoles (Atari 5200, ColecoVision, Intellivision, Odyssey²) and the Nintendo DS
with its screen-layout pages. Delta and Manic skins you imported still work, and can be copied into
the new format with "Edit".

### A skin editor in the app

"Edit" on any skin, bundled or yours, opens an editor with a live preview: move and resize controls
on a magnetic grid, paint buttons, the D-pad, the body and the frame, pick textures and palettes,
rename a label or move it, try the skin on a game before saving, and keep drafts. Each console has a
skin library where your skins and the bundled ones are listed, renamed, duplicated and deleted.

### Skins travel

A skin can be downloaded as a template zip, edited on a computer and imported back, and it can be
sent to another phone with Share nearby.

### Smaller changes

- **Rename a game** from its detail screen; its saves, artwork and settings follow it. Asked for on
  Reddit by u/JuamPiX84.
- **Import ROMs with "Open with" and "Share"** from the file manager, without going through Settings.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files and
input profiles are all kept.

- **Input profiles** gain the buttons listed above on their first load. Nothing you bound is changed;
  the right stick's directions start unbound until you bind them.
- **Android**: install `OpenEmux-mobile-1.21.0.apk` over the app you have, including over a beta.
  Do not uninstall first: uninstalling an Android app deletes its data, games included. A skin you
  copied from a bundled one before this release keeps the old flat art; make it again with "Edit"
  to get the editable one.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

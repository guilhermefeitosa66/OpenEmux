# OpenEmux 1.23.0

An Android release about the on-screen controls, the pause menu and the library. Games that need
two buttons at once can now be played on glass, the pause menu was rebuilt around tiles, a phone
that reports a gamepad it does not have no longer hides the touch controls for good, and the library
zooms with a pinch. The desktop app has no changes in this release: it moves to 1.23.0 only to keep
both apps on the same version number.

`OpenEmux-mobile-1.23.0.apk` installs over the app you have, including over a beta, and keeps your
library.

## Android: anchor mode for the on-screen controls

([#841](https://github.com/guilhermefeitosa66/OpenEmux/issues/841))

Some games want one button held while another is pressed: hold Y to run and press B to jump in Super
Mario World, keep shooting charged while jumping in Mega Man X. On glass that meant covering two
buttons with one thumb, which rarely worked.

The quick-actions strip under the game has a new **anchor** key, after fast forward. While it is lit,
the first button a finger presses stays held until that finger leaves the screen, and any other
button counts while the finger is over it. Hold Y, slide onto B and back: Mario keeps running and
jumps each time. The D-pad, the sticks and the quick actions never anchor. A short card at the bottom
of the screen explains the mode when you turn it on and closes by itself. The mode is remembered per
console.

## Android: combo buttons you make yourself

([#842](https://github.com/guilhermefeitosa66/OpenEmux/issues/842))

The skin editor can add a button that presses up to three buttons together: Y+B, L+R, L+R+A. Tap
**Combo**, hold the buttons for a second (or pick them one by one), and the new button appears in
every layout of the skin, placed over nothing and ready to drag. It can be moved, resized, recoloured,
recorded again and deleted, and its shape can be a circle, a pill or a triangle that tucks into the
corner between two round buttons. No bundled skin ships one. A skin with combos keeps them when it is
exported or sent with Share nearby, and an older app still opens it, just without the combos.

## Android: skins are part of the backup

([#843](https://github.com/guilhermefeitosa66/OpenEmux/issues/843))

A backup restored on a new phone brought back the library and the saves but not the skins you had
imported or edited. Your own skins now go into the backup and come back with the restore, still
picked for their consoles. Bundled skins are not copied into the archive, and older backups restore
as before.

## Android: the pause menu, rebuilt

([#849](https://github.com/guilhermefeitosa66/OpenEmux/issues/849),
[#855](https://github.com/guilhermefeitosa66/OpenEmux/issues/855),
[#857](https://github.com/guilhermefeitosa66/OpenEmux/issues/857),
[#858](https://github.com/guilhermefeitosa66/OpenEmux/issues/858),
[#861](https://github.com/guilhermefeitosa66/OpenEmux/issues/861),
[#862](https://github.com/guilhermefeitosa66/OpenEmux/issues/862),
[#867](https://github.com/guilhermefeitosa66/OpenEmux/issues/867),
[#875](https://github.com/guilhermefeitosa66/OpenEmux/issues/875),
[#881](https://github.com/guilhermefeitosa66/OpenEmux/issues/881))

- **Continue, Restart, Save and Load** sit at the top as an even two-by-two grid, upright and in
  landscape, with Save and Load using the same icons as the keys on the game screen. The sheet never
  covers the game picture.
- **Everything else is a tile** in a fixed grid (four columns upright, five elsewhere): fast forward,
  slow motion, screenshot, shader, screens, audio, touch controls, change skin, edit skin and
  RetroArch. **Quit** is always the last tile, in red.
- **The Audio tile shows its state.** It used to look the same after muting; now it turns red with a
  crossed speaker while muted, and its label says what a tap will do (Mute or Unmute).
- **A slot slider** under Save and Load picks the save slot in fixed steps, with the slot number on
  the thumb, filled when that slot is in use and outlined when it is empty. "See all" opens the full
  list of states.
- **The slot is remembered per game.** The menu used to forget it; now each ROM keeps its current
  slot.

## Android: touch controls over a gamepad the phone only thinks it has

([#865](https://github.com/guilhermefeitosa66/OpenEmux/issues/865))

Some phones report a built-in gamepad that is not there (the Poco F4 does), so the app hid the touch
controls and left nothing to play with. The pause menu now always has a **Touch controls** toggle:
turning it off shows the controller layout even with no controller, and the controller layout has a
key that brings the touch controls back. Plugging or unplugging a real controller mid-game still
switches by itself; your manual choice holds until the next time that happens.

## Android: a Controllers screen in Settings

([#873](https://github.com/guilhermefeitosa66/OpenEmux/issues/873),
[#884](https://github.com/guilhermefeitosa66/OpenEmux/issues/884))

Controller settings are grouped in one **Controllers** screen. **Interface mode** chooses how the app
is driven: Automatic, Touch screen or Controller. Under Touch screen, pressing a controller button
switches to controller navigation at once, and touching the screen goes back to touch. **Button
labels** picks the names shown in the on-screen hints: Nintendo, Xbox or standard. On a phone held
upright, the controller hint bar now sits right on top of the tab bar instead of floating above it
with the list showing through.

## Android: the library

([#868](https://github.com/guilhermefeitosa66/OpenEmux/issues/868),
[#869](https://github.com/guilhermefeitosa66/OpenEmux/issues/869),
[#874](https://github.com/guilhermefeitosa66/OpenEmux/issues/874),
[#882](https://github.com/guilhermefeitosa66/OpenEmux/issues/882))

- **Pinch to zoom** on a phone held upright: the cartridge and cover views go from one to five
  columns, the list from small to large artwork. Each view keeps its own zoom.
- **Long names scroll** as a marquee instead of being cut with an ellipsis.
- **The list view has a very subtle zebra striping**, so the eye can follow a row.
- **The cover view lines up.** Covers of the same console had different shapes (GBA and SNES boxes
  most of all), and the grid came out ragged. Each console now has one cover shape, and covers are
  cropped from the centre to fit it.

## Android: full screen again

([#850](https://github.com/guilhermefeitosa66/OpenEmux/issues/850))

The whole app runs full screen again, without the flash at launch that an earlier fix had traded it
for.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files,
skins and input profiles are all kept.

- **Android**: install `OpenEmux-mobile-1.23.0.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included.
- **Desktop**: no changes from 1.22.0; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

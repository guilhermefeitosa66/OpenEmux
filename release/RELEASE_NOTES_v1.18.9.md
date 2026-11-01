# OpenEmux 1.18.9

An Android update for people who play with a controller. Navigating the app with a gamepad was
unreliable: presses that did nothing, focus that vanished after a touch, sheets and dialogs the pad
could not reach. That is fixed, and with a controller connected the app now switches to a layout
made for it, while touch keeps working alongside. The desktop app has no changes in this release:
it moves to 1.18.9 only to keep both apps on the same version number.

`OpenEmux-mobile-1.18.9.apk` installs over 1.18.5 and over any 1.18.x beta, and keeps your library.

## Android: every gamepad press works, touch or no touch

With a pad in hand, the app was hard to drive without reaching for the screen
([#641](https://github.com/guilhermefeitosa66/OpenEmux/issues/641)):

- **The first press after a touch did nothing.** A touch dropped the focus, and the next D-pad or A
  press was spent bringing it back. Now that press brings the highlight back on the item you were
  on, and every press after it moves or acts. A press that finds nothing focused lands on the
  visible item nearest to where you were, instead of vanishing.
- **Sheets, dialogs and menus answer the pad.** The options sheets, the confirmation dialogs and the
  "…" menu on a game's page ignored the controller. They now take A, B and the other buttons like
  the screens do, open with focus on their first item, and give focus back to where you were when
  they close. Sheets open fully expanded, so no row hides below the screen.
- **No more traps.** Text fields no longer hold on to up and down, B with the keyboard up only
  hides the keyboard, Settings remembers the row you came back to, and a license text scrolls with
  the D-pad.

## Android: a layout for when a controller is connected

The focus ring and the button hints used to appear on a pad press and disappear on the next touch,
so the screen flickered between two looks
([#642](https://github.com/guilhermefeitosa66/OpenEmux/issues/642)). Now they follow whether a
controller is **connected**:

- Plug in a pad and the app shows a visible focus and the hint bar at all times, with larger targets
  where the touch ones were small, and L1/R1 to switch consoles in the library. Unplug it and the
  touch layout comes back, live, without restarting.
- Touch still works in this layout: tapping an item moves the focus to it, and the next pad press
  carries on from there.
- **Settings → General → Controller layout** (`Automatic`, `Always`, `Never`) is there for handhelds
  with built-in controls, where a controller always counts as connected.

## Android: button hints that match your controller

The hint bar always showed Xbox letters, so on a Nintendo pad it told you to press the wrong button
([#643](https://github.com/guilhermefeitosa66/OpenEmux/issues/643)). It now shows the labels printed
on the connected controller: A, B, X and Y on Xbox-style pads, Nintendo's letters on Nintendo pads,
and the cross, circle, square and triangle on PlayStation pads, along with each family's names for
the shoulder, start and select buttons. What each button does stays on its position: the bottom
button confirms and the right one goes back. **Settings → General → Button labels** picks a family by
hand when the automatic choice gets your pad wrong.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states and input
profiles are all kept.

- **Android**: install `OpenEmux-mobile-1.18.9.apk` over the app you have, release or beta.
- **Desktop**: no changes from 1.18.5; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

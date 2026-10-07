# OpenEmux 1.15.0

A release about playing: **the game's controls move inside RetroArch**, as a bar on the bottom
edge of the game's own window, on every console. The window that used to capture RetroArch's to
carry those controls is gone.

## The controls are a bar inside the game's window

The pause, save and volume buttons lived in an OpenEmux window that **captured RetroArch's own
window** to wrap it ([#469](https://github.com/guilhermefeitosa66/OpenEmux/issues/469)). That
worked on some setups and not on others.

- It only worked on X11. On a Wayland session it put the whole library on XWayland just to be
  able to.
- It could break with the window manager, with fullscreen, or with focus moving between the two
  windows. When it failed, it could leave the game in a window with no borders.
- Every click took a detour: the button sent a command to RetroArch, which acted on it at its
  next poll.
- The volume slider showed its own level while RetroArch showed another.

The controls are now **drawn by RetroArch itself**, so a click on them is RetroArch's own input:

- **Close the game · RetroArch menu**
- **Pause · Reset · Slow motion · Fast-forward · Turbo**
- **Save state · Load state**
- **Mute · Volume − · Volume +**
- **Fullscreen · Hide the bar**

Details that matter:

- **The bar does not cover the game.** It sits across the full width of the bottom edge, at any
  window size and in fullscreen, and the game image ends where the bar begins.
- **Toggles show their state.** Pause turns into a blue play button while the game is paused.
  Slow motion, fast-forward and turbo turn blue while they are on, and mute turns red.
- **Hiding the bar gives its space back to the game.** Only a small, faded button stays in the
  bottom-right corner to bring it back, and the bar returns in the state you left it.
- **Your console's shader keeps its quality** with the bar shown or hidden. CRT scanlines and LCD
  dot grids stay sharp.
- **The window is titled with the game**: "Chrono Trigger — Snes9x · RetroArch" instead of
  "RetroArch Snes9x 1.63 fae2fea".
- **Turbo** is one click: the turbo button (B) starts firing by itself, and a second click stops
  it.

Gone with the old window: the "Play in an OpenEmux window" setting, the CRT TV frame, and the
XWayland requirement. The library now runs on whatever your desktop gives it.

## PlayStation and PSP: no touch gamepad over the game

PlayStation and PSP games could open with RetroArch's **touch-screen gamepad** drawn over them
(L1, L2, R1, R2, a d-pad, the four shapes), and no OpenEmux bar
([#471](https://github.com/guilhermefeitosa66/OpenEmux/issues/471)). RetroArch swaps in a
"preferred" overlay for some systems when a game loads, and it ships one for those two. OpenEmux
now turns that off for the games it launches.

## Nintendo 64 has video again

N64 games could open to a **black screen**, on both cores
([#471](https://github.com/guilhermefeitosa66/OpenEmux/issues/471)). Those cores ask RetroArch to
switch to another video driver as the game starts, and that driver could not read the shader
OpenEmux had handed it. OpenEmux now starts RetroArch on the driver the core is going to ask for,
and remembers which one each core asked for.

## The selection rectangle reaches the pointer

On a console with only a few games, dragging a selection rectangle across the empty page drew it
**cut off at the edge of the cards**, short of where the pointer was
([#473](https://github.com/guilhermefeitosa66/OpenEmux/issues/473)). It is now drawn all the way
to the pointer, the way a file manager does it.

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

- **The "Play in an OpenEmux window" setting is gone**, and so is the volume level it stored. The
  volume is RetroArch's own now, changed from the bar.
- **While the bar is up, turbo works as a one-click toggle** whatever turbo mode is set for the
  console.
- **On N64**, a shader you picked for the console only applies if RetroArch's *slang* shader pack
  is installed, because that is the format these cores' video driver reads. If it is not,
  OpenEmux tells you so when the game starts.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

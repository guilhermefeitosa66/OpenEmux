# OpenEmux 1.18.5

An Android update. With a gamepad connected, the in-game controls no longer vanish, and they get a
layout made for playing with a pad. Android also gains slow motion and a way into RetroArch's own
menu. The desktop app has no changes in this release: it moves to 1.18.5 only to keep both apps on
the same version number.

`OpenEmux-mobile-1.18.5.apk` installs over 1.18.0 and over any 1.18.x beta, and keeps your library.

## Android: a gamepad no longer hides the in-game controls

Connecting a gamepad made every on-screen control disappear during a game, not only the virtual
D-pad and buttons but also the menu key, save, load, turbo and fast forward. With a pad plugged in
there was no way to open the pause menu or quit the game short of disconnecting the controller
([#637](https://github.com/guilhermefeitosa66/OpenEmux/issues/637)).

- **The app's controls stay on screen** with a gamepad connected, and they switch to a layout of
  their own the moment the pad connects, without restarting the game. The virtual game buttons go
  away and the picture takes the space they used.
- **Built for a phone in a controller grip.** In landscape the keys sit on two black rails beside
  the picture, stacked from the top so nothing hides under the grip: menu, save and load on the
  left; hide, turbo, slow motion and fast forward on the right. In portrait they form one strip
  under the picture. The keys are faint on purpose, so they stay out of the game's way.
- **Hide them when you don't need them.** The eye key collapses every app control and leaves only a
  faint eye in the same spot to bring them back. It works with a pad and with touch, and the choice
  survives rotating the phone and the pad coming and going.

## Android: slow motion

The desktop has had a slow-motion toggle next to fast forward; Android now has it too
([#638](https://github.com/guilhermefeitosa66/OpenEmux/issues/638)). It sits on screen right before
fast forward on every skin, the bundled controller skins included, in the gamepad layout, and in the
pause menu. Slow motion and fast forward never run together: turning one on turns the other off,
and the screen and the pause menu always show the same state. Like fast forward, it is off in
RetroAchievements hardcore.

## Android: RetroArch's own menu

For settings OpenEmux does not expose, the pause menu has a new **RetroArch menu** row that opens
RetroArch's own menu over the running game
([#639](https://github.com/guilhermefeitosa66/OpenEmux/issues/639)). Leaving it gives the game back
where it was. What you change there lasts for that session only: the next launch starts from
OpenEmux's own settings, so an experiment in there cannot leave a game broken.

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

- **Android**: install `OpenEmux-mobile-1.18.5.apk` over the app you have, release or beta.
- **Desktop**: no changes from 1.18.0; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

# OpenEmux 1.18.0

**Share nearby** arrives: send games from one device to another over your own Wi-Fi, with their
saves, states and covers, between the desktop and Android. On Android, the app now fits tablets and
foldables properly, gets controller skins for twelve consoles, and a long list of fixes.

## Share nearby

Moving a game between your PC and your phone used to mean a cable or a cloud drive, and then putting
the ROM, the battery save, the save states and the cover each in the right folder by hand. Now you
select one or more games and choose **Share**. Devices running OpenEmux on the same network show up
by name, and the one you pick gets an offer it can accept or decline
([#586](https://github.com/guilhermefeitosa66/OpenEmux/issues/586)).

- **Games, not files.** Each game goes over with its battery save, its cover and cartridge label,
  and its save states. A state only loads in the same core, so the receiver checks that before the
  transfer, and incompatible states are skipped with a note instead of copied to fail later. Every
  file lands where that device keeps it.
- **Private by design.** A device is visible only while the share screen is open. Each session is
  encrypted, and both screens show the same short code so you can tell you are talking to the right
  device. Nothing goes through the internet, and there is no account.
- **Works when discovery doesn't.** Devices are found two ways at once (mDNS and a multicast beacon),
  because each fails on some networks. When none shows up, the screen says why and offers a manual
  address.
- **Nothing is lost silently.** If a game cannot be delivered (no room, an unsupported console, a
  conflict you chose to skip), both the sender and the receiver list it with the reason
  ([#610](https://github.com/guilhermefeitosa66/OpenEmux/issues/610)).

On the desktop, **Share** is in the selection bar, in the console menu and in a game's context menu.
**Receive Games…** is under the **Import** button
([#589](https://github.com/guilhermefeitosa66/OpenEmux/issues/589),
[#611](https://github.com/guilhermefeitosa66/OpenEmux/issues/611)). On Android, **Receive games** is
in the **Import** tab ([#612](https://github.com/guilhermefeitosa66/OpenEmux/issues/612)).

## Android: tablets and foldables

`OpenEmux-mobile-1.18.0.apk` lays itself out for the screen it is on
([#535](https://github.com/guilhermefeitosa66/OpenEmux/issues/535)):

- **Tablets** get a navigation rail, a shelf and grids that use the width, Settings and the game
  list as list + detail, and a gameplay skin with the pause menu as a side panel
  ([#536](https://github.com/guilhermefeitosa66/OpenEmux/issues/536)).
- **Foldables**: the app splits on the hinge instead of drawing across it. In tabletop posture the
  game sits on the top half and the controls and pause menu on the bottom (Nintendo DS gets one
  screen per half). The skin is redrawn when you fold, unfold or enter multi-window, and closing a
  Flip pauses the game and writes the auto-save state
  ([#537](https://github.com/guilhermefeitosa66/OpenEmux/issues/537)).
- **Phones in landscape** show two shelf cards per row, and the shelf card was redesigned around a
  larger console icon ([#539](https://github.com/guilhermefeitosa66/OpenEmux/issues/539),
  [#609](https://github.com/guilhermefeitosa66/OpenEmux/issues/609)).

## Android: controls

- **Controller skins** in the Delta/Manic package format, with skins bundled for twelve consoles
  ([#596](https://github.com/guilhermefeitosa66/OpenEmux/issues/596)).
- The on-screen **analog stick** follows the thumb and has a bigger touch area, and the **D-pad**
  keeps working when the thumb slides off it
  ([#546](https://github.com/guilhermefeitosa66/OpenEmux/issues/546),
  [#555](https://github.com/guilhermefeitosa66/OpenEmux/issues/555)).
- **Turbo** and **fast forward** show whether they are on
  ([#554](https://github.com/guilhermefeitosa66/OpenEmux/issues/554)).
- Several on-screen layouts had **buttons in swapped positions**; they now match the real
  controllers ([#540](https://github.com/guilhermefeitosa66/OpenEmux/issues/540)).
- With a **gamepad**, the focused item is no longer clipped and the focus stops at the edges
  ([#538](https://github.com/guilhermefeitosa66/OpenEmux/issues/538)).

## Android: more

- **Select several games and remove them** in one go
  ([#585](https://github.com/guilhermefeitosa66/OpenEmux/issues/585)).
- **Settings, covers and saves survive an uninstall and reinstall**
  ([#545](https://github.com/guilhermefeitosa66/OpenEmux/issues/545)).
- The app **tells you when a new version is out**, and the check can be turned off in Settings
  ([#541](https://github.com/guilhermefeitosa66/OpenEmux/issues/541)).
- Opening the app no longer flashes an **empty library** before your consoles appear
  ([#574](https://github.com/guilhermefeitosa66/OpenEmux/issues/574),
  [#608](https://github.com/guilhermefeitosa66/OpenEmux/issues/608)), and the **system bars** stay
  in the library: only the running game goes full screen
  ([#607](https://github.com/guilhermefeitosa66/OpenEmux/issues/607)).

The APK installs over 1.17.0 and keeps your library. `OpenEmux-mobile.apk` is the same file under a
name that does not change between releases.

## Desktop fixes

- **A game's context menu stayed open** when you clicked outside it while a card had focus. It now
  closes, and that click does nothing else
  ([#601](https://github.com/guilhermefeitosa66/OpenEmux/issues/601)).
- **Icons invisible in the dark theme.** On GTK 4.14 the icons OpenEmux bundles were drawn in a fixed
  dark grey instead of the theme's color, which made the new Share icon disappear on a dark
  background ([#626](https://github.com/guilhermefeitosa66/OpenEmux/issues/626)).

The website's screenshots and the demo library now use a fictional parody catalogue drawn in each
era's style, instead of real games
([#549](https://github.com/guilhermefeitosa66/OpenEmux/issues/549)).

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

- **Share nearby** needs OpenEmux 1.18.0 on both devices, desktop or Android.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

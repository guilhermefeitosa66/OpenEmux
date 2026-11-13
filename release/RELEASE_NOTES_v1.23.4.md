# OpenEmux 1.23.4

A release about speed and about the moments where the app used to leave you guessing. A big library
opens faster and holds far less memory, the app shows your games before it has downloaded a single
emulator, and launching a game now tells you what it is doing. On Android, the release build is
smaller and starts in about half the time, and a controller can finally open the pause menu.

Every change here came out of a review of the whole app, desktop and Android, run against a
synthetic library of 3000 games.

`OpenEmux-mobile-1.23.4.apk` installs over 1.23.3, or over a beta, and keeps your library.

## Desktop: a big library stays fast

([#899](https://github.com/guilhermefeitosa66/OpenEmux/issues/899),
[#900](https://github.com/guilhermefeitosa66/OpenEmux/issues/900),
[#901](https://github.com/guilhermefeitosa66/OpenEmux/issues/901),
[#902](https://github.com/guilhermefeitosa66/OpenEmux/issues/902),
[#903](https://github.com/guilhermefeitosa66/OpenEmux/issues/903),
[#905](https://github.com/guilhermefeitosa66/OpenEmux/issues/905),
[#907](https://github.com/guilhermefeitosa66/OpenEmux/issues/907),
[#908](https://github.com/guilhermefeitosa66/OpenEmux/issues/908))

"All" with 3000 games used to build every card of every console at once, freeze the window for
seconds and keep all of it in memory for as long as the app was open. Now only what is near the
screen is built, a page you leave gives its memory back, and the cartridge pictures are drawn once,
at your display's scale, and kept on disk. On that library, opening "All" went from about 3 s to under
1 s, and memory from 437 MB to 234 MB.

Around that:

- Start-up no longer rescans and rewrites every playlist: only folders that changed are read again.
- Zooming, sorting, switching the theme or clicking the sidebar no longer write the settings to disk
  on every step.
- The first-run download fetches the emulators the pickers offer, not the 200 nobody can choose.
- The AppImage uses the GPU renderer when your system can, with a safe fallback.

## Desktop: the library before the downloads

([#909](https://github.com/guilhermefeitosa66/OpenEmux/issues/909))

The first start no longer makes you wait for every emulator to download. You pick your ROM folder
first, the library opens, and a console's emulator is fetched the first time you play one of its
games. Without a connection, the app still opens and says what it could not download.

## Desktop: launching a game, and coming back

([#904](https://github.com/guilhermefeitosa66/OpenEmux/issues/904),
[#910](https://github.com/guilhermefeitosa66/OpenEmux/issues/910),
[#911](https://github.com/guilhermefeitosa66/OpenEmux/issues/911))

- A card shows "Starting…" while RetroArch comes up, and a banner with Stop stays while you play.
  When the game ends, you read "Played … for 12 min" instead of a technical message.
- **Recently played**: a new page, where the app opens when you have history, with how long ago and
  how long you played each game. "Resume where I left off" starts from the automatic save state.
- A console that needs a BIOS you do not have says so on its sidebar row and on its page, with an
  "Import BIOS…" button, before the first launch fails.

## Desktop: search, game details and TV mode

([#906](https://github.com/guilhermefeitosa66/OpenEmux/issues/906),
[#912](https://github.com/guilhermefeitosa66/OpenEmux/issues/912),
[#913](https://github.com/guilhermefeitosa66/OpenEmux/issues/913),
[#914](https://github.com/guilhermefeitosa66/OpenEmux/issues/914),
[#915](https://github.com/guilhermefeitosa66/OpenEmux/issues/915))

- Search filters as you type, finds words in any order, says what it is searching, offers "Search
  everywhere" and shows a clear message when nothing matches.
- Consoles are called by their names everywhere ("Super Nintendo", not "SFC").
- A **game details** dialog gathers the per-game core, shader and colour, save states, play time and
  artwork in one place. Open it from the card's menu, with Alt+Enter, or with the pad.
- **TV mode** (F11 or the Guide button): fullscreen, no sidebar, bigger cards and text, the pad's own
  button labels, an on-screen keyboard for search and shoulder buttons to jump between consoles.
- Cards and icon buttons have names a screen reader can read, and animations follow the system's
  setting.

## Android: smaller and faster

([#916](https://github.com/guilhermefeitosa66/OpenEmux/issues/916),
[#917](https://github.com/guilhermefeitosa66/OpenEmux/issues/917),
[#918](https://github.com/guilhermefeitosa66/OpenEmux/issues/918),
[#919](https://github.com/guilhermefeitosa66/OpenEmux/issues/919),
[#920](https://github.com/guilhermefeitosa66/OpenEmux/issues/920),
[#921](https://github.com/guilhermefeitosa66/OpenEmux/issues/921))

The APK is optimised and shrunk, and ships with a startup profile: it is 164 MB instead of 186 MB and
cold start took about half the time in our measurements. The release APK now carries only the arm64
engine, which is what phones and TV boxes run. Scrolling "All" and "Favorites" is smoother, a second
launch of the same console reuses the controller skin and cartridge drawn the first time, and Share
nearby no longer re-reads every file each time it offers them.

## Android: first run, launching and the pause menu

([#922](https://github.com/guilhermefeitosa66/OpenEmux/issues/922),
[#923](https://github.com/guilhermefeitosa66/OpenEmux/issues/923),
[#924](https://github.com/guilhermefeitosa66/OpenEmux/issues/924))

- The first run opens on the shelf: you can browse and import while nothing is downloaded, and a
  console's emulator comes down on its first launch. "Download all emulators" in Settings fetches
  them all at once.
- A launch shows its steps, with Cancel. A missing BIOS is caught before the game starts, and a game
  that dies on start says so, instead of dropping you back on the shelf in silence.
- **Pause with the controller**: hold Start (or pick Start + Select, L3 + R3) to open the pause menu
  without touching the screen. Settings › Controllers.

## Android: the shelf, sorting and TV

([#925](https://github.com/guilhermefeitosa66/OpenEmux/issues/925),
[#926](https://github.com/guilhermefeitosa66/OpenEmux/issues/926),
[#927](https://github.com/guilhermefeitosa66/OpenEmux/issues/927),
[#928](https://github.com/guilhermefeitosa66/OpenEmux/issues/928))

- A **Continue playing** row on the phone's shelf.
- A sort menu (A–Z, recently played, recently added, most played, unplayed first) and filter chips.
- OpenEmux appears in the Android TV launcher, with its own banner.
- The header buttons are at least 48 dp, easier to hit.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files,
skins and input profiles are all kept. The first start after the update reads the library once more
to build its new index; later starts only look at folders that changed.

- **Android**: install `OpenEmux-mobile-1.23.4.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included. The APK is arm64
  only; an x86_64 Android device needs to stay on 1.23.3.
- **Desktop**: install the new package over the old one.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

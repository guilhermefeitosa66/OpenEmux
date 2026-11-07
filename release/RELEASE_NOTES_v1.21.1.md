# OpenEmux 1.21.1

An Android fix. On a phone, picking a language in Settings closed the app, whichever language you
picked. That is fixed. The desktop app has no changes in this release: it moves to 1.21.1 only to
keep both apps on the same version number.

`OpenEmux-mobile-1.21.1.apk` installs over 1.21.0 and keeps your library.

## Android: changing the language closed the app

On a phone, "Settings" → "Language" opens the list of languages in a sheet. Tapping any of them
closed the app instead of switching to it. On a tablet, where the list opens in the pane next to
Settings, it worked, which is how it got past testing.

The translations were never the problem: every language has every string, on Android and on the
desktop. The language list asked its sheet for the app's screen to restart it in the new language,
and a sheet is a window of its own, not the app's screen. It now finds the screen behind the sheet.
The game launch had the same flaw and gets the same fix.

Two tests keep it from coming back. One fails the build if any code makes that assumption again.
The other opens the sheet on a phone-sized device and picks a language from it, the way you would.

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

- **Android**: install `OpenEmux-mobile-1.21.1.apk` over the app you have. Do not uninstall first:
  uninstalling an Android app deletes its data, games included.
- **Desktop**: no changes from 1.21.0; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

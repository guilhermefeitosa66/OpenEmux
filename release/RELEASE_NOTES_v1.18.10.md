# OpenEmux 1.18.10

An urgent Android fix. **If you installed the Android app 1.18.5 or 1.18.9 and it closes as soon as
it opens, install this one over it.** Your library, saves and settings are all still there.

The desktop app has no changes in this release: it moves to 1.18.10 only to keep both apps on the
same version number.

## Android: the app closed as soon as it opened

The 1.18.5 and 1.18.9 Android APKs were built without some of the files the app carries inside it:
the cover name lists, the open-source licenses and the shaders. On a phone that already had games,
the app went looking for covers the moment it opened, did not find those files, and closed. A fresh
install got as far as the first-run screen, which is why it slipped through.

This APK carries every file again, and the release build now refuses to finish if any of them is
missing. Nothing changed in the app itself: 1.18.10 is 1.18.9 (gamepad navigation, the controller
layout and the button hints) with its files back.

The 1.18.5 and 1.18.9 downloads were replaced with fixed builds a few hours after they came out, but
a copy downloaded before that is still broken, and the version number does not tell them apart.
That is what 1.18.10 is for.

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

- **Android**: install `OpenEmux-mobile-1.18.10.apk` over the app you have. Do not uninstall first:
  uninstalling an Android app deletes its data, games included.
- **Desktop**: no changes from 1.18.9; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

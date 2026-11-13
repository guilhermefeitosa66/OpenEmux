# OpenEmux 1.23.5

A small release about where OpenEmux lives on the web. The website moved to its own address,
**https://openemux.libre-apps.org/**, part of [Libre Apps](https://libre-apps.org/), the home of our
free apps. The old `guilhermefeitosa66.github.io/OpenEmux` pages now show a notice with a link to
the new address. Both apps point to the new address directly.

`OpenEmux-mobile-1.23.5.apk` installs over 1.23.4, or over a beta, and keeps your library.

## Desktop: the About window

- The website link opens https://openemux.libre-apps.org/.
- Two links follow it: **Source code** (the GitHub repository) and the **Libre Apps foundation**
  (https://libre-apps.org/), in every language the app speaks.
- The software centers (AppStream), the `.deb`, `.rpm` and Arch packages and the Windows
  uninstaller entry name the new site as the homepage.

## Android: the About screen

- The OpenEmux website row opens the new site.
- A new row right below it opens the Libre Apps foundation.

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

- **Android**: install `OpenEmux-mobile-1.23.5.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included. The APK is arm64
  only.
- **Desktop**: install the new package over the old one.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

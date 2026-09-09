# OpenEmux 1.13.1

A patch release about one thing: **OpenEmux works on distributions that are not Debian-derived.**

The AppImage could not start on Arch, and on Arch, Fedora and openSUSE it could not make a single
HTTPS request — so first-time setup never finished. Both bugs, and two more of the same shape, were
found, measured and fixed by **[@Adhnan23](https://github.com/Adhnan23)** against the released
1.13.0 bundle. See [#394](https://github.com/guilhermefeitosa66/OpenEmux/issues/394) and
[#395](https://github.com/guilhermefeitosa66/OpenEmux/pull/395).

The shape of all four: **the AppImage handed its own Ubuntu environment to a process that is not
part of the bundle.**

## The AppImage starts on Arch

The bundle's entry point is a `#!/bin/sh` script, so the kernel loads the *host's* shell under the
bundle's library path. On any distribution whose `/bin/sh` is newer than Ubuntu 24.04's libraries,
the shell resolved the wrong ones and the launch died before a single line of the script ran:

```
/bin/sh: symbol lookup error: /bin/sh: undefined symbol: rl_print_keybinding
```

The launcher now parks that path and leaves the shell only what it needs, and the entry point puts
it back one step before the interpreter that actually uses it.

## HTTPS works everywhere, not just on Debian

The bundled OpenSSL is Ubuntu's, which looks for CA certificates under a path only Debian and its
derivatives have. Everywhere else the trust store loaded **zero** certificates, and every HTTPS
request in the app failed with `CERTIFICATE_VERIFY_FAILED`.

First boot stopped at *"Initial setup incomplete (step: retroarch_download_all_cores)"*, and cover
sync, ScreenScraper and the update check were dead with it.

The bundle now uses **your machine's own certificate store**, not one frozen into a release — a
frozen set keeps trusting roots that were later withdrawn and never learns about new ones. If you
have set `SSL_CERT_FILE` or `SSL_CERT_DIR` yourself, your value wins.

## Three host programs that quietly did nothing

The same environment leak broke three more things outside Debian:

- **"Open folder"** ran `xdg-open` and the child died instantly. The button did nothing at all, not
  even an error toast.
- **The RetroArch Flatpak probe** exited non-zero, so OpenEmux reported *"RetroArch was not found"*
  on machines that had it installed.
- **The PulseAudio probe** failed the same way.

A structural test now walks the source and fails the build if any new call starts a host process
with the bundle's environment.

## Every packaged icon is the size its folder claims

The `.deb` and `.rpm` installed the source logo unresized into the 512×512 folder and rendered the
rest preserving aspect ratio, so the six installed icons measured 30×32, 45×48, 61×64, 121×128,
242×256 and 735×776. Not one was the size it was filed under.

They are square and exact now, and the ladder runs from 16 to 512 — the small sizes a Plasma menu
and a GNOME list row ask for did not exist at all before.

## A native Arch Linux package

```bash
sudo pacman -U ./openemux-1.13.1-x86_64.pkg.tar.zst
```

`pacman` resolves the GTK4 and libadwaita dependencies for you, the vendored RetroArch keeps
finding its own libraries, and `pacman -Rns openemux` leaves nothing behind. On Arch Linux ARM,
build from the recipe in `packaging/arch/` — the emulator is bundled only for x86_64.

## தமிழ் — Tamil

OpenEmux speaks Tamil, contributed by [@Adhnan23](https://github.com/Adhnan23): complete against
the English reference, and offered under its own name in the language list. A desktop already set
to `ta_IN.UTF-8` gets it on first launch.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with — don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states and input
profiles are all kept.

- **If first-time setup never finished** on Arch, Fedora or openSUSE, run OpenEmux again after
  upgrading: it picks up where it stopped and downloads the cores.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

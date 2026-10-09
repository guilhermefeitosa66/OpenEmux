# OpenEmux 1.15.1

A small release on top of 1.15.0: **the in-game control bar shows in the Flatpak again**, it can be
made **semi-transparent**, and the **manual** on the website now speaks every language the app does.

## The control bar was missing in the Flatpak

In the Flatpak build, games opened with **no control bar at all**
([#482](https://github.com/guilhermefeitosa66/OpenEmux/issues/482)). The bar's images and layout
ship inside the OpenEmux package, and OpenEmux handed RetroArch their location in it. But the
Flatpak runs RetroArch from **its own Flatpak** (`org.libretro.RetroArch`), which cannot see inside
OpenEmux's, so the files did not exist as far as RetroArch could tell, and it drew nothing.

OpenEmux now copies the bar's files to `~/.openemux/runtime/overlay` before each game, next to the
settings it already hands RetroArch there, and points RetroArch at that copy. Every RetroArch can
read it, Flatpak or not. The same fix covers a native or AppImage OpenEmux that falls back to the
RetroArch Flatpak.

## A semi-transparent control bar

**Settings → Video → In-Game Bar → "Semi-transparent control bar"** draws the bar see-through,
**over** the game instead of in a strip of its own below it
([#477](https://github.com/guilhermefeitosa66/OpenEmux/issues/477)). The game keeps the whole window,
and hiding or showing the bar no longer resizes it. The faded button that brings a hidden bar back
looks exactly as it does on the opaque bar, so it stays easy to find. The setting applies from the
next game you open, on every console, and your console's shader keeps working.

Suggested by **@mozertdev** from the Diolinux Plus community, after testing the new bar. Thank you!

## The manual, in every language

The website's [manual](https://guilhermefeitosa66.github.io/OpenEmux/manual/), which covers
installing, importing, cover art, views, playlists, cores, shaders and every settings page, is now
available in Português (Brasil), Español, Français, Deutsch, 日本語, 简体中文 and தமிழ் as well
as English ([#480](https://github.com/guilhermefeitosa66/OpenEmux/issues/480)). Buttons and
settings are named exactly as the app names them in your language, so you can find what the manual
points at. The screenshots are still in English.

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

- **The semi-transparent bar is off by default**: the bar looks as it did in 1.15.0 until you turn
  it on.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

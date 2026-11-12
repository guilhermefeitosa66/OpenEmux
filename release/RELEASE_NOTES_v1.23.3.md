# OpenEmux 1.23.3

An Android release about the on-screen buttons. You can now give each button the shape you want,
the triangles lost their sharp corners, and a button shows when it is pressed. The desktop app has
no changes in this release. It moves to 1.23.3 only to keep both apps on the same version number.
The number skips 1.23.1 and 1.23.2 because those went to Android beta builds, and the release has to
install over them.

`OpenEmux-mobile-1.23.3.apk` installs over 1.23.0, or over a beta, and keeps your library.

## Android: pick the shape of each on-screen button

([#891](https://github.com/guilhermefeitosa66/OpenEmux/issues/891))

Anchor mode made it easy to move buttons around, but each one kept the skin's outline wherever it
went. Put L and R next to A and B on a Game Boy Advance, the way an SNES pad has X and Y, and you got
two long pills where two round buttons belonged.

In the skin editor, select a button (or its group) and "Shape" is the first tool in the actions
bar. Every button except the D-pad and the sticks can take:

- **Original**: the skin's own outline, the default. You can always go back to it.
- **Circle**
- **Pill**
- **Rounded square**, which is new
- **Triangle**, pointing to any corner

The shape belongs to the button, the way its colour does. You set it once and it holds in portrait,
in landscape and on every other layout the skin has. Combo buttons get the rounded square too.

## Android: rounded triangles

Triangles, on buttons and on combos, are drawn with properly rounded corners, as round as the
rounded square's, instead of sharp points.

## Android: you can see what is being pressed

Nothing used to show that A, B, Start or the shoulder buttons were held down, only the dot on the
D-pad and the sticks moved. Now every button of an OpenEmux skin changes colour while it is held: it
gets darker on a light face and lighter on a dark one. Each D-pad direction lights up on its own. The
engine draws it, so it shows up in screen recordings, which is handy when you want to show someone
what you are pressing.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with. Don't run it.

## Upgrading

Nothing to configure, nothing to migrate. Settings, playlists, artwork, save states, BIOS files,
skins and input profiles are all kept. If a skin from the 1.23.1 beta has different shapes in
portrait and landscape, it opens with the shape you picked, on every layout.

- **Android**: install `OpenEmux-mobile-1.23.3.apk` over the app you have, including over a beta. Do
  not uninstall first: uninstalling an Android app deletes its data, games included.
- **Desktop**: no changes from 1.23.0; updating is optional.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

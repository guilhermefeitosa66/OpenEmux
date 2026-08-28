# OpenEmux 1.12.0

The largest release so far: **71 issues**, a new operating system, a new CPU architecture, and a
library that no longer makes you wait.

Much of what follows started as a hands-on QA report by **[@mozertdev](https://github.com/mozertdev)**
([#273](https://github.com/guilhermefeitosa66/OpenEmux/issues/273)) — a full pass over v1.11.2 on
Linux Mint with an Xbox pad, five defects and five suggestions, every one of them reproduced,
diagnosed and fixed here.

## OpenEmux runs on Windows

There is now a Windows build: an **installer** (`OpenEmux-1.12.0-setup.exe`) and a **portable ZIP**,
both carrying the GTK 4 stack, the Python runtime and RetroArch, so nothing has to be installed
alongside them.

Getting there meant more than a build script. Gamepads on Windows are read through **SDL2** rather
than the Linux event device, and the platform-specific parts of the app — paths, process launching,
the window embed — were moved behind a seam so both systems run the same code. Windows is built and
tested in CI on every push, like Linux.

Three Windows-only problems were found and fixed before this shipped:

- **The install was slow** because the bundle carried 21.909 files, thousands of which nothing ever
  reads. NSIS extracts one file at a time, so that was the install. The bundle is now pruned to what
  the app actually loads.
- **No shader was ever applied.** The video driver on Windows is Direct3D 11 and the shader
  catalogue offered GLSL presets, which d3d11 cannot load — so every selection silently did nothing.
  OpenEmux now picks the preset format the active video driver can actually load.
- **RetroArch's own menu bar showed up on every game** launched from OpenEmux, on top of the game.

## Linux on ARM

Every Linux format — AppImage, `.deb`, `.rpm` and Flatpak — is now built for **aarch64** as well as
x86_64. Single-board machines and ARM laptops install the same way x86_64 ones do. The one thing
ARM does not get is the vendored RetroArch AppImage, which upstream only publishes for x86_64; on
ARM, OpenEmux uses the RetroArch your distribution provides.

## Large libraries stopped freezing

The report was blunt about it: a big console would hang the window long enough for the desktop to
offer to force-quit the app, and switching playlists quickly made it worse.

Several separate pieces of waste were behind it, and all of them are gone:

- **The grid builds a screenful, not a library.** A 500-ROM console used to build roughly ten
  thousand widgets in a single main-loop turn before drawing anything. Cards are now built for what
  is on screen and recycled as you scroll.
- **Every ROM was fully read and CRC32-hashed on every playlist load**, on the main thread, to fill a
  field nothing ever read. It is not computed any more.
- **Each card re-read and re-hashed the entire favorites list** just to draw its own star. Favorites
  are read once, as paths.
- **Clicking the sidebar rebuilt a page that was already identical**, and the library was built twice
  at startup. Both are gone.
- **Every rebuild leaked the grid before it**, because the viewport signal handler was never
  disconnected. It is now.
- **Cover work for a page you had already left kept landing on the main thread.** Leaving a page
  cancels its in-flight cover work instead of letting it resolve against destroyed cards.
- Cartridge artwork was parsed twice per card, the translation table was rebuilt on every string
  lookup, and ROMs were hashed three times per sync. Once each, now.

Cover sync got faster too: cores download in parallel and stream to disk instead of being buffered
whole in RAM, and ScreenScraper is only asked about the ROMs the local files could not resolve.

## Your data is not lost any more

Four ways OpenEmux could destroy something you cared about, all closed:

- **Nothing is written half-way.** Config, playlists and collections were written in place — a crash,
  a full disk or a power cut in the middle left a truncated file behind. Every persisted file is now
  written whole or not at all.
- **A corrupt file is kept, not overwritten.** A state file that failed to parse was silently
  replaced with defaults, taking your settings with it. It is kept aside now, and reported.
- **Favorites survive an unplugged drive.** If the drive holding those ROMs was not mounted, the
  favorites pointing at them were permanently deleted on the next load.
- **First boot works offline.** With no internet, first boot failed instead of falling back to the
  bundled cores — and reported success when the core listing came back empty.

## New this release

- **RetroAchievements.** Sign in once in Settings and RetroArch tracks achievements on every launch.
- **Export and import saves and save states** from one place, instead of hunting for two separate
  directories in the RetroArch tree.
- **Advanced core settings for PlayStation and PSP**: internal resolution, graphics API and texture
  filtering.
- **Import ROMs as links instead of copies**, for a collection shared with other applications.

## Fixes from the QA report

- **A context menu could be left stuck open.** Nothing owned "one menu at a time", so a keyboard or
  gamepad menu could open on top of a pointer-opened one; clicking outside dismissed only one, and
  the `(...)` button stayed pinned behind the leak.
- **Remapping a control kept the old binding alive.** Clearing a colliding action was silently undone
  by the normalisation step, so the button ended up bound to both commands at once. A cleared binding
  is now a distinct state from an unset one.
- **The volume slider told the truth only by accident** — an abandoned walk, a 7.8-second ramp and no
  read-back from the running game.
- **The mouse cursor stayed hidden** over an embedded game after a screen lock.
- **Arrow keys flipped the Welcome slides** while the language dropdown was open.
- **Every ROM grid failed to build** on a regression — a teardown was connected to a GTK signal that
  does not exist (`unroot`).

## Games start, and stop, correctly

- **A launch failure says why.** Pre-launch I/O errors escaped the click handler, and an AppImage
  that could not start simply reported "finished".
- **Quitting with a game embedded cleans up.** RetroArch could abort on an X error or be left
  orphaned behind the closed window.
- **Each launch gets its own RetroArch command port**, so a second game cannot talk to the first.
- **Game exit no longer kills the gamepad navigation thread.**
- **The embedded window's fullscreen hotkey works for non-letter bindings**, its focus reclaim is no
  longer fragile, and a double-click no longer raises an error toast.
- **RetroArch is vendored as a portable directory**, not an AppImage: no FUSE, no unpacking at
  startup, one less hard dependency.

## Scanning and importing

- **A ROM whose filename is not valid UTF-8** used to kill the scan thread and disable scanning for
  the rest of the session.
- **ROMs behind symlinked directories are visible**, and can be favourited.
- **Archive import keeps every disc** of a multi-disc set instead of losing colliding entries, and
  never leaves half a ROM behind on a truncated file.
- **A rescan keeps the collection you were in** instead of bouncing to Favorites, and no longer drops
  a rescan queued while another was running.
- **Cover sync stopped saving HTTP error pages** and empty responses as cover files, which then
  blocked every later sync for that game.
- **The empty-library onboarding page is reachable again** — fresh installs were landing on the
  Favorites empty state instead.
- **The first-boot window can no longer freeze** with no error and no way out.

## Security and packaging

- **Shader packs can no longer write outside the shader directory.** The extraction guard missed
  embedded `../` segments and absolute member names.
- **The Flatpak build no longer writes a credential into a tracked file**, restored only by an exit
  trap.
- **The AppImage needs no libfuse2** — which neither Ubuntu 24.04 nor Fedora 40 installs, so it
  could not start on either.
- **Every package ships the AppStream metainfo** software centres read; the app was invisible in
  them before.
- **Native packages depend on the WebP pixbuf loader**, so synced covers no longer render blank.
- **The RPM builds from a source tarball** rather than the project's bind mount, closing three
  Fedora-review blockers.
- **Release builds are reproducible**: pinned images, authenticated apt sources, a checked AppImage
  version and unprivileged containers.
- **Packages carry the sources, not the maintainer's build state** — gitignored build artifacts and a
  stale egg-info from an old project name were being staged.
- **Desktop integration gaps closed**: `TryExec` no longer hides the AppImage entry, MIME types are
  declared, and the `.deb` ships its md5sums and changelog.
- 18 MB of unreferenced icon artwork no longer ships, and the OpenEmu-derived assets carry their
  license terms.
- **The Flatpak sandbox is documented and narrowed**, and the Wayland trade-off of the game window is
  written down.

## Under the hood

Nothing here changes what you see, but it is what the rest of the list was built on:
`OpenEmuxWindow` was one class with 14 responsibilities and three copies of the navigation state —
it is now a shell and six collaborators. `grid.py` and `preferences.py` were split, and the
170-line runtime-override writer broken up. CI builds every package format on every push instead of
first discovering a broken one on release day, tests run on every supported Python version, the app
is started headlessly in CI, coverage has a floor, and lint and dependency audits gate the merge.
The test suite no longer writes to the developer's real home directory, and twelve previously
untested modules are covered.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been
tampered with — don't run it.

## Upgrading

Nothing to configure. Settings, playlists, artwork, save states and input profiles are all kept.

Two notes for existing installs:

- **AppImage users**: this build no longer needs `libfuse2`. If you installed it only for OpenEmux,
  you can remove it.
- **Flatpak users**: `flatpak update` picks this up once the release is published to the OpenEmux
  Flatpak repository.

# Contributors

OpenEmux is shaped as much by the people who report bugs, test releases and ask
for the right feature as by the people who write the code. This file records
that — including contributions that predate the practice of crediting them.

## Maintainer

- **Guilherme Feitoza** ([@guilhermefeitosa66](https://github.com/guilhermefeitosa66)) — author and maintainer.

## Community contributions

Listed by the work each person set in motion.

### Xefir ([@Xefir](https://github.com/Xefir))

Asked for Flatpak distribution in [#67](https://github.com/guilhermefeitosa66/OpenEmux/issues/67), which
became the whole Flatpak delivery path: the `.flatpak` bundle shipped with every
release, the `make flatpak` target, and the
[openemux-flatpak](https://github.com/guilhermefeitosa66/openemux-flatpak)
repository that makes `flatpak update` work.

### mozertdev ([@mozertdev](https://github.com/mozertdev))

From the [Diolinux Plus](https://plus.diolinux.com.br/) community. Ran a
detailed hands-on test of **v1.9.2** end to end — install, import, artwork,
layout, collections, controller remapping, autofire, save states and a full
play session — and wrote it up step by step. That report produced eight issues
covering gamepad hotkeys, the master volume control, analog stick defaults,
artwork gaps, cover-rendering performance, live input remapping, a restart
action, and one-click access to Preferences.

Came back for **v1.11.2** with a second end-to-end report,
[#273](https://github.com/guilhermefeitosa66/OpenEmux/issues/273): five defects
— library loading blocking the interface, a context menu that could be left
stuck open, control remapping that mixed the old binding with the new one, the
volume slider drifting away from RetroArch, and the mouse cursor staying hidden
over the game after a screen lock — plus five feature suggestions, from save
backup and export to a visual controller map. The plan that came out of it is
[#274](https://github.com/guilhermefeitosa66/OpenEmux/issues/274). Also
contributed the game-name database in
[#188](https://github.com/guilhermefeitosa66/OpenEmux/pull/188).

After trying the in-game control bar, suggested an option to make it
semi-transparent for people who keep it on screen, which became
[#477](https://github.com/guilhermefeitosa66/OpenEmux/issues/477).

### Marc Mader ([@marcmaderhome](https://github.com/marcmaderhome))

Reported in [#179](https://github.com/guilhermefeitosa66/OpenEmux/issues/179) that no
game would launch on a fully-Flatpak setup (OpenEmux + RetroArch, Fedora
Silverblue): the OpenEmux sandbox could not see the RetroArch Flatpak's cores
directory. The report exposed a missing `--filesystem` grant in the manifest
that broke every Flatpak-on-Flatpak install, fixed in v1.10.2.

### CoverUnited (Reddit)

Reported on Reddit that a game would open inside the OpenEmux window and then
lose it mid-play, leaving RetroArch as *"a square in the center of the monitor
without any chance of moving it or anything else, but gaming still going"* —
the first user-facing sighting of a failure the project had only described
from the code side. That report became
[#267](https://github.com/guilhermefeitosa66/OpenEmux/issues/267): the game
window now says what it is doing while it waits, gives up in seconds instead
of twenty, and hands the game back a normal decorated window instead of
stranding it.

### Sheik Adhnan ([@Adhnan23](https://github.com/Adhnan23))

Reported in [#394](https://github.com/guilhermefeitosa66/OpenEmux/issues/394) that the AppImage
could not start on Arch at all, and that on every distribution that is not Debian-derived not one
HTTPS request succeeded — so first-time setup stopped before it could download a single core. Then
chased it down and sent the fix,
[#395](https://github.com/guilhermefeitosa66/OpenEmux/pull/395): four instances of the same shape,
the bundle handing its own Ubuntu environment to a process that is not part of it, each measured
against the released 1.13.0 AppImage rather than reasoned about. The structural test that came with
it — every `subprocess` call in the app must pass an explicit environment — is what stops it
happening a fifth time.

The same work brought the native **Arch Linux package**, the packaged icons finally being the size
the folder they sit in claims, and **தமிழ் (Tamil)**, the project's first locale contributed by
someone other than the maintainer.

### felipeonline (Reddit)

Asked, in the Reddit feedback thread on **v1.16.0** while playing on the
Windows build, for a way to start games in fullscreen instead of toggling it on
every launch. That request became
[#505](https://github.com/guilhermefeitosa66/OpenEmux/issues/505): a "Start
games in fullscreen" switch in Settings → Video that every launch now follows.

In the same thread, also reported that cartridge labels never synced for Game
Boy and Game Boy Color even with a ScreenScraper account set. That report became
[#506](https://github.com/guilhermefeitosa66/OpenEmux/issues/506): a zipped ROM
is now looked up by the game inside the archive rather than by the archive
itself, a Game Boy game filed under Game Boy Color is found on one more try, and
a sync that ScreenScraper refused or never answered says so instead of counting
every game as a plain miss.

In the same thread, also reported that some covers showed up cropped at the
top or the bottom of the library grid. That report became
[#508](https://github.com/guilhermefeitosa66/OpenEmux/issues/508): a card has
its console's typical box shape, and a cover of another shape (a portrait
Japanese box on a landscape Super Nintendo card) was filled into it and lost up
to 60% of its art. Now only a cover close to the card's shape fills it, and any
other is shown whole on the card's backdrop.

In the same thread, also asked for the cover manager to open on the cover the
game already has, with ways to adjust it from there. That became
[#510](https://github.com/guilhermefeitosa66/OpenEmux/issues/510): the artwork
manager now opens on a "Current" tab that shows the cover and label as they
are, says whether the sync wrote them, you chose them or they were simply found
in the folder, and offers picking another match, replacing, adjusting and
resetting to the synced art right there.

## How contributions are credited

- **Reporting an issue counts.** If your report or suggestion leads to a change,
  the commit that implements it carries you as `Co-authored-by:`, and the issue
  is referenced in the commit message.
- **Feedback from outside GitHub counts too** — Reddit, Diolinux Plus, or
  anywhere else. Tell us the name or handle you would like to be credited under.
- If you would rather **not** be listed here, or want your entry changed, open an
  issue and it will be removed or edited.

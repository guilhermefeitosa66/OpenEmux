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

## How contributions are credited

- **Reporting an issue counts.** If your report or suggestion leads to a change,
  the commit that implements it carries you as `Co-authored-by:`, and the issue
  is referenced in the commit message.
- **Feedback from outside GitHub counts too** — Reddit, Diolinux Plus, or
  anywhere else. Tell us the name or handle you would like to be credited under.
- If you would rather **not** be listed here, or want your entry changed, open an
  issue and it will be removed or edited.

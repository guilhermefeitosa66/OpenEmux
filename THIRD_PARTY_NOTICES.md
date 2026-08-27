# Third-Party Notices

OpenEmux itself is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).
It is a *front-end*: it does not include, copy, or link any RetroArch source
code. It launches RetroArch as a separate external program (its own binary /
AppImage) via the command line. Under both the GPL and general copyright law,
running another program at arm's length does not make the calling program a
derivative work, so OpenEmux's own code can be — and is — MIT-licensed.

When OpenEmux **redistributes** third-party software (for example, the vendored
RetroArch AppImage bundled inside the OpenEmux AppImage, or libretro cores it
downloads), those components remain under **their own licenses**. This is a
"mere aggregation" of independently-licensed works. The notices below cover the
components OpenEmux ships or fetches.

---

## RetroArch

- **License:** GNU General Public License v3.0 (GPLv3)
- **Copyright:** The RetroArch / libretro team and contributors
- **Source:** https://github.com/libretro/RetroArch
- **How OpenEmux uses it:** invoked as a separate process. The official,
  unmodified RetroArch AppImage may be vendored (`vendors/`) and bundled into
  the OpenEmux AppImage for convenience.
- **Obligation when redistributing:** the GPLv3 terms apply to the RetroArch
  binary. Because it is redistributed **unmodified**, pointing to the upstream
  corresponding source above satisfies the source-availability requirement.
  The GPLv3 license text ships with RetroArch itself.

## libretro API

- **License:** MIT
- **Source:** https://github.com/libretro/libretro-common /
  https://www.libretro.com/
- **How OpenEmux uses it:** OpenEmux does not link the libretro API directly;
  RetroArch does. Listed for completeness.

## libretro cores

- **License:** varies per core (GPLv2, GPLv3, and others; a few carry
  non-commercial or other terms).
- **Source:** https://docs.libretro.com/development/licenses/
- **How OpenEmux uses it:** cores are **downloaded at runtime** from the official
  RetroArch Buildbot (https://buildbot.libretro.com/) into the user's own
  configuration directory. OpenEmux does not redistribute cores in this
  repository. Each core is governed by its individual license.

---

## The Windows bundle

The Linux packages depend on the distribution's GTK stack and install nothing of
it. The Windows installer and portable zip have nowhere to depend on, so they
**redistribute** a Windows build of that whole stack, taken unmodified from the
MSYS2 MINGW64 repository (https://repo.msys2.org/mingw/mingw64/). The exact
package set and versions are pinned in
[`packaging/windows/packages.lock`](packaging/windows/packages.lock), which is
the authoritative list of what any given build shipped.

The components are redistributed as unmodified dynamic libraries, and OpenEmux
links none of them statically.

### GTK 4, libadwaita, GLib, Pango, gdk-pixbuf, librsvg

- **License:** GNU Lesser General Public License, v2.1 or later (LGPL-2.1+)
- **Source:** https://gitlab.gnome.org/GNOME/ — and, for the exact Windows
  builds shipped, the MSYS2 packages named in `packages.lock`, whose own
  sources are at https://github.com/msys2/MINGW-packages
- **Obligation when redistributing:** the LGPL requires that a user be able to
  replace these libraries with their own versions. The bundle satisfies this by
  shipping them as ordinary, separate `.dll` files in `bin\`, which the user can
  substitute; nothing is statically linked and no relinking is required.

### GStreamer (core and base libraries)

- **License:** GNU Lesser General Public License, v2.1 or later (LGPL-2.1+)
- **Source:** https://gitlab.freedesktop.org/gstreamer/gstreamer
- **How OpenEmux uses it:** it does not. GTK 4 declares it as a dependency for
  its optional media-playback backend, so it arrives with the GTK packages and
  is shipped rather than second-guessed. Only the core and base *libraries* are
  included — none of the plugin sets whose licences vary.

### Python

- **License:** Python Software Foundation License 2.0
- **Source:** https://www.python.org/
- **How OpenEmux uses it:** the bundled interpreter runs the application.

### PyGObject and pycairo

- **License:** LGPL-2.1+ (PyGObject), LGPL-2.1 / MPL-1.1 (pycairo)
- **Source:** https://gitlab.gnome.org/GNOME/pygobject ,
  https://github.com/pygobject/pycairo

### SDL2

- **License:** zlib License
- **Source:** https://www.libsdl.org/
- **How OpenEmux uses it:** the gamepad backend on Windows, where Linux's
  evdev interface does not exist.

### Adwaita icon theme, Cantarell, Source Code Pro

- **License:** CC-BY-SA-3.0 (icon theme), SIL Open Font License 1.1 (fonts)
- **Source:** https://gitlab.gnome.org/GNOME/adwaita-icon-theme ,
  https://gitlab.gnome.org/GNOME/cantarell-fonts ,
  https://github.com/adobe-fonts/source-code-pro

### RetroArch (bundled, Windows only)

The Windows artifacts ship the official, unmodified RetroArch Windows x86_64
build so that OpenEmux works without a separate install. This is a
redistribution of a GPLv3 binary and carries the obligations in the RetroArch
section above: the version is pinned in
[`vendors/manifest.json`](vendors/manifest.json), RetroArch's own licence text
ships beside the executable inside the bundle, and the corresponding source is
the upstream tag at https://github.com/libretro/RetroArch.

**libretro cores are not included.** They are downloaded from the buildbot on
first launch, exactly as on Linux, which keeps their many different licences out
of the installer entirely.

---

> This file is informational and is **not legal advice**. If you plan to
> redistribute OpenEmux together with RetroArch and/or cores commercially or at
> scale, review each component's license (and any trademark terms) for your
> specific case.

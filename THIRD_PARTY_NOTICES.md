# Third-Party Notices

Opemux itself is licensed under the **MIT License** (see [`LICENSE`](LICENSE)).
It is a *front-end*: it does not include, copy, or link any RetroArch source
code. It launches RetroArch as a separate external program (its own binary /
AppImage) via the command line. Under both the GPL and general copyright law,
running another program at arm's length does not make the calling program a
derivative work, so Opemux's own code can be — and is — MIT-licensed.

When Opemux **redistributes** third-party software (for example, the vendored
RetroArch AppImage bundled inside the Opemux AppImage, or libretro cores it
downloads), those components remain under **their own licenses**. This is a
"mere aggregation" of independently-licensed works. The notices below cover the
components Opemux ships or fetches.

---

## RetroArch

- **License:** GNU General Public License v3.0 (GPLv3)
- **Copyright:** The RetroArch / libretro team and contributors
- **Source:** https://github.com/libretro/RetroArch
- **How Opemux uses it:** invoked as a separate process. The official,
  unmodified RetroArch AppImage may be vendored (`vendors/`) and bundled into
  the Opemux AppImage for convenience.
- **Obligation when redistributing:** the GPLv3 terms apply to the RetroArch
  binary. Because it is redistributed **unmodified**, pointing to the upstream
  corresponding source above satisfies the source-availability requirement.
  The GPLv3 license text ships with RetroArch itself.

## libretro API

- **License:** MIT
- **Source:** https://github.com/libretro/libretro-common /
  https://www.libretro.com/
- **How Opemux uses it:** Opemux does not link the libretro API directly;
  RetroArch does. Listed for completeness.

## libretro cores

- **License:** varies per core (GPLv2, GPLv3, and others; a few carry
  non-commercial or other terms).
- **Source:** https://docs.libretro.com/development/licenses/
- **How Opemux uses it:** cores are **downloaded at runtime** from the official
  RetroArch Buildbot (https://buildbot.libretro.com/) into the user's own
  configuration directory. Opemux does not redistribute cores in this
  repository. Each core is governed by its individual license.

---

> This file is informational and is **not legal advice**. If you plan to
> redistribute Opemux together with RetroArch and/or cores commercially or at
> scale, review each component's license (and any trademark terms) for your
> specific case.

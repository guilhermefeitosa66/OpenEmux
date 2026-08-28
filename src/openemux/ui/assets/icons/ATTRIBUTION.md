# Third-party artwork in this directory

Two sets of icons here are not OpenEmux's own work and are **not covered by
OpenEmux's MIT license**. Their terms are recorded below and travel with them in
every package, which is also what those terms require.

## `systems/` — console icons, from OpenEmu

Source: <https://github.com/OpenEmu/OpenEmu>, commit
`1d205104640d8410659d321809889cbfd06b99a9`.

Imported from `OpenEmu/SystemPlugins/*/Images.xcassets/*_library.imageset/*.png`,
renamed to `<system_plugin_slug>__<original_filename>.png` — for example
`systems/genesis__megadrive_library@2x.png`. Only the icons OpenEmux actually
displays are kept: one file (plus its `@2x` variant) per console in
`CONSOLE_ICON_FILES` (`ui/window.py`). Artwork for consoles OpenEmux does not
support, regional variants it does not use, and OpenEmu's own
`Other Assets/Unused console icons/` were removed in issue #233 — about 18 MB
that shipped in every package without ever being displayed. Re-import from the
commit above if a console is ever added.

### License

The OpenEmu repository ships no separate license file; every source file in it
carries the notice below, and this artwork is redistributed from that
repository under the same terms. Condition 2 is the reason this file exists:
a package is a binary distribution, and the notice has to travel with it.

```
Copyright (c) 2009-2023, OpenEmu Team

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the OpenEmu Team nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY OpenEmu Team ''AS IS'' AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL OpenEmu Team BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

OpenEmu credits the individual artists behind its *controller* illustrations in
[`ILLUSTRATIONS.md`](https://github.com/OpenEmu/OpenEmu/blob/master/ILLUSTRATIONS.md).
OpenEmux no longer ships any of those files.

## `symbolic/` — Adwaita symbolic icons, from GNOME

See [`symbolic/LICENSE`](symbolic/LICENSE): LGPL-3 or CC-BY-SA-3.0 US, at your
option. Bundled so the UI renders its symbolic icons on hosts whose icon theme
does not provide these names.

## Everything else under `ui/assets/`

OpenEmux's own work, under the project's MIT license (`LICENSE` at the
repository root).

---

`packaging/common/copyright`, installed as
`/usr/share/doc/openemux/copyright`, says the same thing in the machine-readable
DEP-5 format, and `tests/test_icon_assets.py` fails when a directory here has no
entry above.

# Packaging

Three distributable formats, one entry point. Every build runs inside its own
container, so the host only needs Docker and nothing leaks in from the
developer's machine.

```bash
make appimage        # or: ./packaging/build.sh appimage   (x86_64 hosts only)
make deb             # or: ./packaging/build.sh deb
make rpm             # or: ./packaging/build.sh rpm
make packages        # all three
make packages-clean  # wipe dist/ artifacts
```

Artifacts land in `dist/`.

## Layout

| Path | Responsibility |
| --- | --- |
| `build.sh` | Host-side entry point: builds the image, runs the target's build script in it |
| `docker/<target>.Dockerfile` | The build toolchain for one target |
| `<target>/build.sh` | What runs **inside** the container: build + install-test |
| `common/` | The install layout, the launcher, the desktop entry and the AppStream metainfo — shared by every format |
| `appimage/AppImageBuilder.yml` | The bundle recipe |
| `appimage/openemux-launcher.sh` | The bundle's entry point (sets its runtime env) |
| `rpm/openemux.spec` | RPM metadata; unpacks a source tarball and installs via `common/stage_tree.sh` |
| `testenv/` | The distrobox matrix the built artifacts get install-tested in |

Building a package is only half of it. `testenv/` installs and launches the
finished artifacts on Ubuntu, Debian and Fedora, under X11 and Wayland --
`make ubuntu-x11`, `make testenv-matrix`. See
[`testenv/README.md`](testenv/README.md).

`common/` holds `stage_tree.sh` (the `/opt/openemux` install layout),
`copy_tree.sh` and `assert_sources_only.sh` (staging sources without the
working tree's build state, and proving it),
`openemux-launcher.sh` (the `/usr/bin/openemux` launcher), `openemux.desktop`
(the single desktop entry every format installs) and
`io.github.guilhermefeitosa66.OpenEmux.metainfo.xml` (the AppStream data every
format installs to `/usr/share/metainfo/`).

## Things that are easy to get wrong

**Interpreter selection (native packages).** The launcher must not use `python3`
from `PATH`. A version manager (pyenv, conda, asdf) puts a shim first, and those
interpreters have no PyGObject — a correctly installed app then dies with
`ModuleNotFoundError: No module named 'gi'`. The launcher walks candidates and
takes the first that can `import gi`. Both `deb/build.sh` and `rpm/build.sh`
regression-test this with a fake `python3` earlier in `PATH`.

**gdk-pixbuf loaders (AppImage).** The cache written while bundling records the
*builder's* absolute loader directory. Shipped as-is, every loader in it is
unreachable on the user's machine — no SVG, no WebP. `appimage/build.sh`
regenerates the cache from the bundled loaders and strips the build-time path so
entries are bare filenames, which `GDK_PIXBUF_MODULEDIR` resolves at runtime.
The build fails if the SVG loader is missing from the result.

**Runtime environment (AppImage).** appimage-builder generates its own `AppRun`
and overwrites anything shipped at `AppDir/AppRun`, so the bundle's environment
is set by `appimage/openemux-launcher.sh` (the recipe's `app_info.exec`) with
the recipe's `runtime.env` as a second layer. `GI_TYPELIB_PATH` matters most:
without it the `Rsvg` import fails and the cartridge frames silently degrade to
plain covers.

**Versions.** `src/openemux/__init__.py` is the single source of truth; the
AppImage recipe carries its own copy that must be bumped with it.

**Staging is sources only.** Every format copies through
`common/copy_tree.sh` and checks the result with `common/assert_sources_only.sh`.
A plain `cp -r src` shipped whatever the maintainer's tree happened to hold:
the released `.deb` and `.rpm` both carried `opt/openemux/src/opemux.egg-info/`,
a directory named after a project name that no longer exists — its
`top_level.txt` registers a phantom distribution on
`PYTHONPATH=/opt/openemux/src`, and its `SOURCES.txt` publishes the development
tree's file inventory. The same list also keeps the 193 MiB Windows RetroArch
out of a Linux package built after `make vendor-retroarch`.

**AppStream metainfo.** Every format installs
`common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml` to
`/usr/share/metainfo/`; without it GNOME Software and KDE Discover know the app
only as a bare desktop entry — no summary, no screenshots, no release notes and
no update notification — and both rpmlint and lintian flag it. The `.deb`,
`.rpm` and Flatpak builds run `appstreamcli validate --no-net` over the file
they install, and `tests/test_appstream_metainfo.py` covers what a validator
cannot: that every shipped version is in the release history, and that the
screenshot URLs are pinned to a commit rather than to `main`. They are
re-indexed by the software centre long after the install, so a screenshot
refresh that renames a file under `docs/assets/` would blank them for everyone.

**The RPM must stand on its own.** `rpm/build.sh` packs a source tarball,
resolves `Version:` into the copy of the spec it hands to `rpmbuild`, and builds
with `-ba` — so the `.src.rpm` is self-contained and `rpmbuild --rebuild`,
`mock` and COPR need no OpenEmux checkout. The build proves it on every run by
rebuilding its own SRPM in a different `_topdir`, and runs rpmlint over both
artifacts, failing on the findings that block Fedora review. The spec was
previously driven with `--define "repo_root /work"` and had no `Source0`, so it
could only ever be built from this project's own Docker bind mount.

**The ScreenScraper credential.** `embed_screenscraper_credentials.py` rewrites
`_EMBEDDED_BLOB` in `core/embedded_credentials.py`, and every target must run it
against **its own staging copy** — `$DESTDIR` for the `.deb`/`.rpm`, `AppDir`
for the AppImage, the staged bundle for Windows, a `mktemp -d` tree for the
Flatpak. Never the working tree: the tracked file restored by a trap is one
`docker kill` away from leaving the project's credential in a committable file.
`build.sh` refuses to start when the tracked file already carries a blob, and
`tests/test_packaging_credentials.py` checks that no injection site targets it.

The Flatpak needs the extra staging step because its source is `type: dir`,
`path: ../..` — the *whole* directory beside the manifest, `.env` and `dist/`
included. `flatpak/build.sh` copies the build inputs into a staging tree and
builds the manifest from there; the manifest's own `skip:` list covers the two
paths that build the working tree directly (a developer running
`org.flatpak.Builder` by hand, and the `openemux-flatpak` publish workflow).

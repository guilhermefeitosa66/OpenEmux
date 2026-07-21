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
| `common/` | Everything the `.deb` and `.rpm` share |
| `appimage/AppImageBuilder.yml` | The bundle recipe |
| `appimage/openemux-launcher.sh` | The bundle's entry point (sets its runtime env) |
| `rpm/openemux.spec` | RPM metadata; installs via `common/stage_tree.sh` |

`common/` holds `stage_tree.sh` (the `/opt/openemux` install layout),
`openemux-launcher.sh` (the `/usr/bin/openemux` launcher) and
`openemux.desktop` (the single desktop entry all three formats install).

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

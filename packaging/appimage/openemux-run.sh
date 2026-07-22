#!/bin/sh
# Environment setup for the AppImage, then hand over to Python.
#
# Reached from openemux-launcher (a static ELF), because appimage-builder
# requires app_info.exec to be a real binary and overwrites AppDir/AppRun with
# its own -- so neither of those can carry this setup.
set -eu

APPDIR="${APPDIR:-$(cd -- "$(dirname -- "$0")/../.." && pwd)}"
export APPDIR
LIBDIR="$APPDIR/usr/lib/x86_64-linux-gnu"

# GObject-introspection typelibs. Rsvg lives here, and the cartridge frames are
# SVGs composited through it at runtime: without this the import fails and the
# grid silently falls back to plain covers.
export GI_TYPELIB_PATH="$LIBDIR/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"

# Icon themes (Adwaita symbolic icons) and mime data.
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

# gdk-pixbuf loaders: the cache ships with bare module filenames, so the module
# dir has to be pointed at the bundled loaders for any of them (SVG above all)
# to be found. Without it every cover and symbolic icon fails to decode.
PIXBUF_VERSION_DIR="$LIBDIR/gdk-pixbuf-2.0/2.10.0"
if [ -d "$PIXBUF_VERSION_DIR/loaders" ]; then
    export GDK_PIXBUF_MODULEDIR="$PIXBUF_VERSION_DIR/loaders"
    if [ -s "$PIXBUF_VERSION_DIR/loaders.cache" ]; then
        export GDK_PIXBUF_MODULE_FILE="$PIXBUF_VERSION_DIR/loaders.cache"
    fi
fi

# GSettings schemas (GTK reads its own settings through them).
if [ -f "$APPDIR/usr/share/glib-2.0/schemas/gschemas.compiled" ]; then
    export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas"
fi

export OPENEMUX_PROJECT_ROOT="$APPDIR/usr/lib/openemux"
export PYTHONPATH="$OPENEMUX_PROJECT_ROOT/src:$APPDIR/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
# PYTHONHOME is deliberately left alone: AppRun.env points it at $APPDIR/usr so
# the bundled interpreter finds its own stdlib. Clearing it (which the native
# launcher does, to shake off a pyenv environment) breaks the bundle instead.

# The bundled interpreter's ELF interpreter path is *relative*
# ("lib64/ld-linux-x86-64.so.2"), so it resolves against the working directory.
# The recipe makes both candidate directories -- $APPDIR and runtime/compat,
# where appimage-builder's exec hooks chdir -- carry a lib64 pointing at the
# loader. This cd covers the case where the hooks are not loaded at all.
cd "$APPDIR" || exit 1

# OPENEMUX_SELFTEST=1 runs the bundle self-check through this very entry point,
# so it sees exactly the environment the app sees. Set only by the build.
if [ -n "${OPENEMUX_SELFTEST:-}" ]; then
    exec "$APPDIR/usr/bin/python3" "$APPDIR/usr/lib/openemux/selftest.py" "$@"
fi

exec "$APPDIR/usr/bin/python3" "$OPENEMUX_PROJECT_ROOT/src/openemux/main.py" "$@"

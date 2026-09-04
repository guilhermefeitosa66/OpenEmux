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

# TLS trust. The bundled OpenSSL is Ubuntu's, compiled with
# OPENSSLDIR=/usr/lib/ssl, so it looks for CA certificates at
# /usr/lib/ssl/cert.pem and /usr/lib/ssl/certs -- paths that exist only on
# Debian and its derivatives. On Arch, Fedora and openSUSE the store loaded
# zero certificates and *every* HTTPS request the app makes failed with
# "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate": the
# core and shader downloads (which fail first boot outright, with
# "Initial setup incomplete (step: retroarch_download_all_cores)"), cover
# sync, ScreenScraper and the update check.
#
# The host's own store is used rather than one bundled here: a CA set frozen
# into a release keeps trusting roots that were later withdrawn, and stops
# trusting ones added since. A value the user already set wins.
if [ -z "${SSL_CERT_FILE:-}" ] && [ -z "${SSL_CERT_DIR:-}" ]; then
    for ca_bundle in \
        /etc/ssl/certs/ca-certificates.crt \
        /etc/pki/tls/certs/ca-bundle.crt \
        /etc/ssl/ca-bundle.pem \
        /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
        /etc/ssl/cert.pem
    do
        if [ -r "$ca_bundle" ]; then
            export SSL_CERT_FILE="$ca_bundle"
            break
        fi
    done
    # A hashed directory covers the distributions that ship no single file.
    if [ -z "${SSL_CERT_FILE:-}" ] && [ -d /etc/ssl/certs ]; then
        export SSL_CERT_DIR=/etc/ssl/certs
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

# openemux-launcher parked this before exec'ing this script, because the
# kernel runs it with the *host's* /bin/sh and that shell would otherwise be
# loaded against the bundle's libraries. On Arch that meant an Ubuntu-noble
# libreadline.so.8 resolved for a bash built against readline 8.3, and every
# launch died with "undefined symbol: rl_print_keybinding" before reaching a
# single line of this file. Only the bundled interpreter needs it, so it goes
# back on now -- on the far side of the shell, one exec before python3.
# (LD_PRELOAD is not parked: it carries libapprun_hooks.so, which has to be
# loaded *in this shell* to fix up the environment of the exec below.)
if [ -n "${APPDIR_SHELL_LD_LIBRARY_PATH+x}" ]; then
    export LD_LIBRARY_PATH="$APPDIR_SHELL_LD_LIBRARY_PATH"
fi
unset APPDIR_SHELL_LD_LIBRARY_PATH

# OPENEMUX_SELFTEST=1 runs the bundle self-check through this very entry point,
# so it sees exactly the environment the app sees. Set only by the build.
if [ -n "${OPENEMUX_SELFTEST:-}" ]; then
    exec "$APPDIR/usr/bin/python3" "$APPDIR/usr/lib/openemux/selftest.py" "$@"
fi

exec "$APPDIR/usr/bin/python3" "$OPENEMUX_PROJECT_ROOT/src/openemux/main.py" "$@"

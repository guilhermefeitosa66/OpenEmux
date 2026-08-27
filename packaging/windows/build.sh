#!/usr/bin/env bash
# Builds the OpenEmux Windows artifacts: a portable .zip and an installer .exe.
# Runs *inside* the container defined by packaging/docker/windows.Dockerfile --
# launch it through `packaging/build.sh windows` (or `make windows`), not
# directly on the host.
#
# Nothing here runs on Windows. The GTK/Python runtime is downloaded already
# compiled from MSYS2, the launcher is cross-compiled with mingw-w64, and the
# installer is produced by NSIS's native Linux build.
set -euo pipefail

# Hand the artifacts back even when a later step fails, so a failed run does not
# leave root-owned files in dist/ and build/.
trap 'chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist build 2>/dev/null || true' EXIT

VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
echo "==> building OpenEmux ${VERSION} for Windows x86_64"

BUILD_DIR="build/win"
EXTRACTED="$BUILD_DIR/extracted"
BUNDLE="$BUILD_DIR/OpenEmux"
CACHE="$BUILD_DIR/msys2-cache"

# The download cache survives; everything derived from it is rebuilt, so a
# half-finished previous run cannot leak files into this bundle.
rm -rf "$EXTRACTED" "$BUNDLE"
mkdir -p "$BUILD_DIR" dist

echo "==> phase 1: fetch the MINGW64 runtime from MSYS2"
python3 packaging/windows/msys2_packages.py --prefix "$EXTRACTED" --cache "$CACHE"

echo "==> phase 2: stage the bundle tree"
python3 packaging/windows/stage.py --extracted "$EXTRACTED" --bundle "$BUNDLE"

echo "==> phase 3: application icon"
# Windows picks the size it wants out of a multi-resolution .ico; 16 and 32 are
# the ones the taskbar and Explorer actually use, and leaving them out gets a
# blurry downscale of the 256 instead.
convert src/openemux/ui/assets/images/logo.png \
  -background none \
  \( -clone 0 -resize 16x16 \) \
  \( -clone 0 -resize 32x32 \) \
  \( -clone 0 -resize 48x48 \) \
  \( -clone 0 -resize 64x64 \) \
  \( -clone 0 -resize 128x128 \) \
  \( -clone 0 -resize 256x256 \) \
  -delete 0 "$BUNDLE/openemux.ico"
cp "$BUNDLE/openemux.ico" packaging/windows/openemux.ico

echo "==> phase 4: cross-compile the launcher"
# The resource compiler resolves "openemux.ico" relative to the .rc file, which
# is why the icon was copied next to it above.
# The quotes are escaped twice on purpose. windres does not hand -D straight to
# the preprocessor: it builds a command line and runs it through a shell, which
# eats one level. With a single level the macro expands to a bare 1.11.3 and
# `VALUE "FileVersion", 1.11.3` is a syntax error -- which is where the Windows
# build stopped before it ever produced an .exe (issue #118).
x86_64-w64-mingw32-windres \
  -DOPENEMUX_VERSION="\\\"${VERSION}\\\"" \
  -DOPENEMUX_VERSION_COMMA="$(echo "$VERSION" | tr '.' ','),0" \
  -I packaging/windows \
  packaging/windows/openemux-launcher.rc \
  -O coff -o "$BUILD_DIR/openemux-launcher.res"

# -mwindows marks the binary as GUI subsystem, so double-clicking it opens no
# console; -municode selects the wide entry point. Together they make the C
# runtime start at wWinMainCRTStartup, which is why the launcher defines
# wWinMain and not main.
x86_64-w64-mingw32-gcc \
  -O2 -s -municode -mwindows \
  packaging/windows/openemux-launcher.c \
  "$BUILD_DIR/openemux-launcher.res" \
  -o "$BUNDLE/OpenEmux.exe"

rm -f packaging/windows/openemux.ico "$BUILD_DIR/openemux-launcher.res"

echo "==> phase 5: verify the bundle"
# Cheap checks for the failures that are invisible until a user double-clicks:
# a missing typelib, uncompiled schemas, or a RetroArch that did not come along.
test -f "$BUNDLE/OpenEmux.exe"
test -f "$BUNDLE/bin/pythonw.exe"
test -f "$BUNDLE/lib/girepository-1.0/Adw-1.typelib"
test -f "$BUNDLE/lib/girepository-1.0/Gtk-4.0.typelib"
test -f "$BUNDLE/lib/girepository-1.0/Rsvg-2.0.typelib"
test -f "$BUNDLE/share/glib-2.0/schemas/gschemas.compiled"
# Not loaders.cache: that file holds absolute paths to the loader modules, so
# one written here would name a directory that does not exist on a user's
# machine -- and the tool that writes it has to dlopen Windows DLLs, which this
# Linux host cannot do. What the build can guarantee is that the loaders and
# the tool are both present; the cache is written on first launch by
# core/pixbuf_loaders.py (issue #118).
test -f "$BUNDLE/bin/gdk-pixbuf-query-loaders.exe"
test -n "$(ls -A "$BUNDLE/lib/gdk-pixbuf-2.0/2.10.0/loaders")"
# The two formats that are loader-only and that OpenEmux actually needs: SVG
# for its own artwork, WebP for the covers libretro serves.
ls "$BUNDLE/lib/gdk-pixbuf-2.0/2.10.0/loaders/"*svg* >/dev/null
ls "$BUNDLE/lib/gdk-pixbuf-2.0/2.10.0/loaders/"*webp* >/dev/null
test -f "$BUNDLE/etc/ssl/certs/ca-bundle.crt"
test -f "$BUNDLE/src/openemux/main.py"
test -f "$BUNDLE/vendors/RetroArch-Win64/retroarch.exe"
test -d "$BUNDLE/vendors/RetroArch-Win64/cores"
test -f "$BUNDLE/LICENSE"
test -f "$BUNDLE/THIRD_PARTY_NOTICES.md"
# RetroArch is GPLv3 and redistributed unmodified; its licence must ship beside
# the binary. stage.py fails earlier if it is absent -- this is the last gate.
ls "$BUNDLE/vendors/RetroArch-Win64/"COPYING* \
   "$BUNDLE/vendors/RetroArch-Win64/LICENSE"* >/dev/null 2>&1

# Nothing in the bundle may point at the machine that built it. An absolute
# MSYS2 path baked into a config or cache means a file that resolves on a
# developer's box and nowhere else -- exactly how the OpenSSL CA bundle broke.
# Collected first, then tested. `| grep -q .` exits on the first line and
# SIGPIPEs the grep still walking the bundle; with `set -o pipefail` the
# pipeline then reports failure, the `if` takes the else branch, and a bundle
# that *does* carry the build machine's paths passes the check.
LEAKED_PATHS="$(grep -rIl --exclude-dir=vendors -e 'C:/msys64' -e 'C:\\msys64' "$BUNDLE" 2>/dev/null || true)"
if [ -n "$LEAKED_PATHS" ]; then
  echo "!! files in the bundle reference the build machine's MSYS2 prefix:" >&2
  head -n 20 <<< "$LEAKED_PATHS" >&2
  exit 1
fi

echo "==> phase 6: portable zip"
ZIP="OpenEmux-${VERSION}-windows-x86_64.zip"
rm -f "dist/$ZIP"
# -r from inside build/win so the archive contains a single OpenEmux/ directory
# instead of spilling several hundred files into whatever the user unzips into.
( cd "$BUILD_DIR" && zip -q -r -9 "../../dist/$ZIP" "OpenEmux" )
echo "==> built: dist/$ZIP"

echo "==> phase 7: installer"
SETUP="OpenEmux-${VERSION}-setup.exe"
rm -f "dist/$SETUP"
makensis -V2 \
  "-DVERSION=${VERSION}" \
  "-DBUNDLE_DIR=$PWD/$BUNDLE" \
  "-DOUTPUT_FILE=$PWD/dist/$SETUP" \
  packaging/windows/openemux.nsi
test -f "dist/$SETUP"
echo "==> built: dist/$SETUP"

echo ""
echo "==> Windows artifacts:"
ls -lh "dist/$ZIP" "dist/$SETUP"

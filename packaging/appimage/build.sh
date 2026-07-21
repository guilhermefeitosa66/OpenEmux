#!/usr/bin/env bash
# Builds the OpenEmux AppImage. Runs *inside* the container defined by
# packaging/docker/appimage.Dockerfile -- launch it through
# `packaging/build.sh appimage` (or `make appimage`), not directly on the host.
set -euo pipefail

# Hand the artifacts back even when a check fails, so a failed run does not
# leave root-owned files in dist/.
trap 'chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist AppDir appimage-build appimage-builder-cache 2>/dev/null || true' EXIT

RECIPE=packaging/appimage/AppImageBuilder.yml
APPDIR_LIB="$PWD/AppDir/usr/lib/x86_64-linux-gnu"

echo "==> phase 1: assemble the AppDir (no packaging yet)"
appimage-builder --recipe "$RECIPE" --skip-tests --skip-appimage

# Regenerate the gdk-pixbuf loaders cache from the *bundled* loaders. The cache
# written during bundling omits libpixbufloader-svg.so, and without it every
# symbolic icon in the UI and every SVG asset fails to render.
# LD_LIBRARY_PATH points at the bundled libs so the SVG and WebP loaders (which
# need librsvg/cairo/libxml2/libwebp) can be dlopen-ed while querying.
GPB_DIR="$APPDIR_LIB/gdk-pixbuf-2.0"
QUERY_BIN=/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders
if [ ! -d "$GPB_DIR/2.10.0/loaders" ] || [ ! -x "$QUERY_BIN" ]; then
  echo "ERROR: gdk-pixbuf query tool or bundled loaders dir not found." >&2
  exit 1
fi

echo "==> regenerating gdk-pixbuf loaders.cache from the bundled loaders"
tmp_cache="$(mktemp)"
LD_LIBRARY_PATH="$APPDIR_LIB:$PWD/AppDir/lib/x86_64-linux-gnu" \
GDK_PIXBUF_MODULEDIR="$GPB_DIR/2.10.0/loaders" \
  "$QUERY_BIN" > "$tmp_cache"
# Strip the build-time absolute loader dir so entries become bare filenames; at
# runtime GDK_PIXBUF_MODULEDIR ($APPDIR/...) resolves them. Leaving the build
# path in makes every loader unreachable on the user's machine.
sed -i "s|$GPB_DIR/2.10.0/loaders/||g" "$tmp_cache"
for required in svg; do
  if ! grep -q "$required" "$tmp_cache"; then
    echo "ERROR: regenerated loaders.cache is missing the $required loader." >&2
    rm -f "$tmp_cache"
    exit 1
  fi
done
mv "$tmp_cache" "$GPB_DIR/2.10.0/loaders.cache"
echo "loaders.cache: $(grep -c '\.so' "$GPB_DIR/2.10.0/loaders.cache") loaders registered"

# The cartridge frames are rendered through the Rsvg typelib; if it did not get
# bundled the grid silently falls back to plain covers, so fail loudly here.
test -f "$APPDIR_LIB/girepository-1.0/Rsvg-2.0.typelib" \
  || { echo "ERROR: Rsvg-2.0.typelib missing from the bundle." >&2; exit 1; }

echo "==> phase 2: package the AppImage from the fixed AppDir"
appimage-builder --recipe "$RECIPE" --skip-script --skip-build --skip-tests

mkdir -p dist
shopt -s nullglob
for artifact in *.AppImage *.zsync; do
  mv "$artifact" dist/
done

# Actually start the thing. Everything above only inspects the AppDir, and a
# bundle can assemble perfectly and still fail to exec its own interpreter --
# which is exactly how a release shipped that died with
# "usr/bin/python3: not found" on every machine.
BUNDLE="$(ls -1 dist/*.AppImage | head -1)"
echo "==> launch test: $BUNDLE"
LAUNCH_LOG="$(mktemp)"
# No FUSE in the build container, so run from an extraction; xvfb gives GTK a
# display to open the window on.
APPIMAGE_EXTRACT_AND_RUN=1 timeout 60 xvfb-run -a "$BUNDLE" > "$LAUNCH_LOG" 2>&1 || true

if grep -qE "not found|No module named|ModuleNotFoundError|Traceback" "$LAUNCH_LOG"; then
  echo "ERROR: the bundle failed to start." >&2
  sed -n '1,40p' "$LAUNCH_LOG" >&2
  exit 1
fi
# The app logs this once GTK is up and the window is being built; reaching it
# proves the interpreter, the typelibs and the UI import chain all resolved.
if ! grep -q "startup context" "$LAUNCH_LOG"; then
  echo "ERROR: the bundle started but never reached the UI." >&2
  sed -n '1,40p' "$LAUNCH_LOG" >&2
  exit 1
fi
echo "launch test OK: $(grep -m1 'startup context' "$LAUNCH_LOG")"

echo "==> ALL APPIMAGE CHECKS PASSED"

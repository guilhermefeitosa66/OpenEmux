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
# The static-FUSE3 AppImage runtime baked into the build image (see phase 2).
RUNTIME_SRC=/opt/appimage-runtime-x86_64

# The recipe is the only place the version is duplicated -- the .deb, .rpm and
# Flatpak all derive it from src/openemux/__init__.py. A forgotten bump
# produced OpenEmux-<old>-x86_64.AppImage beside correctly versioned siblings,
# and it went into dist/, into SHA256SUMS and into the GitHub release with
# every check passing (issue #255).
VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
if ! grep -q "^    version: \"${VERSION}\"$" "$RECIPE"; then
  echo "FAIL: $RECIPE does not carry version \"${VERSION}\"." >&2
  echo "src/openemux/__init__.py says ${VERSION}; the recipe says:" >&2
  grep -n '^    version:' "$RECIPE" >&2
  exit 1
fi
echo "==> building openemux ${VERSION} AppImage"

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
# webp as well as svg: the cache is regenerated from the bundled loaders,
# and a webp loader that failed to be queried is a blank card for every
# synced cover (issue #251).
for required in svg webp; do
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

# AppStream metainfo: what an AppImage integrator (appimaged, AppImageLauncher,
# GearLever) hands to the software centre when it installs the bundle. Missing
# from every format but the Flatpak until issue #253; validated by the .deb,
# .rpm and Flatpak builds, which have appstreamcli.
test -f AppDir/usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml \
  || { echo "ERROR: AppStream metainfo missing from the bundle." >&2; exit 1; }

# TryExec is resolved against the user's PATH, and no `openemux` binary lives
# there for an AppImage. An integrator (appimaged, AppImageLauncher,
# GearLever) rewrites Exec to the bundle path and leaves TryExec alone, so an
# entry carrying one is silently hidden from the menu after integration
# (issue #256). The shared desktop file has none; only stage_tree.sh adds one,
# for the native packages that do install /usr/bin/openemux.
if grep -q '^TryExec=' AppDir/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop; then
  echo "ERROR: the bundled desktop entry carries TryExec; integrators would hide it." >&2
  exit 1
fi

echo "==> phase 2: package the AppImage from the fixed AppDir"
#
# Assembled here instead of by `appimage-builder --skip-build`, because the
# two halves of a type-2 AppImage have to agree on a compressor and those two
# do not. The runtime this bundle ships is type2-runtime's: static-pie with
# squashfuse and FUSE 3 linked in, so the image needs no libfuse.so.2 on the
# user's machine -- which is the whole of issue #248, since neither Ubuntu
# 24.04 nor Fedora 40 installs one. That runtime reads zlib and zstd only,
# and appimage-builder hardcodes `mksquashfs -comp xz`; pairing them gives a
# bundle that assembles perfectly and then refuses to open itself with
# "Squashfs image uses xz compression, this version supports only zlib,
# zstd". zstd is also the faster read of the two, which a mounted AppImage
# pays for on every block it faults in.
#
# What follows is all of AppImagePrimer.prime() that is not dead code for
# this recipe (it has no update-information and no signing key): squash the
# AppDir, append it to the runtime, mark it executable.
if [ ! -f "$RUNTIME_SRC" ]; then
  echo "ERROR: $RUNTIME_SRC missing. Rebuild the image (packaging/docker/appimage.Dockerfile)." >&2
  exit 1
fi
# The same name appimage-builder gave the file, from the same field, so the
# release artifact keeps its name.
VERSION="$(sed -n 's/^ *version: *"\(.*\)"/\1/p' "$RECIPE" | head -1)"
test -n "$VERSION" || { echo "ERROR: no version: field in $RECIPE." >&2; exit 1; }
BUNDLE_NAME="OpenEmux-${VERSION}-x86_64.AppImage"
PAYLOAD="$PWD/AppDir.squashfs"
rm -f "$PAYLOAD" "$BUNDLE_NAME"
mksquashfs AppDir "$PAYLOAD" -root-owned -noappend -reproducible \
  -comp zstd -Xcompression-level 19
cat "$RUNTIME_SRC" "$PAYLOAD" > "$BUNDLE_NAME"
rm -f "$PAYLOAD"
chmod +x "$BUNDLE_NAME"
echo "packaged $BUNDLE_NAME ($(stat -c %s "$BUNDLE_NAME") bytes)"

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

# The bug this guards against is invisible in the build container -- every
# check below runs the bundle extracted, so a runtime that cannot mount
# itself passes them all and only fails on the user's desktop (issue #248).
# So inspect the runtime itself: it is the first N bytes of the AppImage,
# where N is the size of the runtime the payload was appended to.
echo "==> runtime check: $BUNDLE"
RUNTIME_HEAD="$(mktemp)"
head -c "$(stat -c %s "$RUNTIME_SRC")" "$BUNDLE" > "$RUNTIME_HEAD"
if strings -a "$RUNTIME_HEAD" | grep -q 'libfuse\.so\.2'; then
  echo "ERROR: the AppImage runtime still wants libfuse.so.2." >&2
  rm -f "$RUNTIME_HEAD"
  exit 1
fi
if readelf -d "$RUNTIME_HEAD" 2>/dev/null | grep -q "(NEEDED)"; then
  echo "ERROR: the AppImage runtime is dynamically linked:" >&2
  readelf -d "$RUNTIME_HEAD" | grep "(NEEDED)" >&2
  rm -f "$RUNTIME_HEAD"
  exit 1
fi
rm -f "$RUNTIME_HEAD"
echo "runtime OK: statically linked, no libfuse.so.2"

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

# Starting is not the same as working: the loaders, the Rsvg bindings and the
# GI<->cairo bridge are separate packages, and a missing one only shows up as
# blank cards. The self-check exercises each for real, inside the bundle.
echo "==> bundle self-check"
SELFTEST_LOG="$(mktemp)"
APPIMAGE_EXTRACT_AND_RUN=1 OPENEMUX_SELFTEST=1 \
  timeout 60 xvfb-run -a "$BUNDLE" > "$SELFTEST_LOG" 2>&1 || true

if ! grep -q "all bundle self-checks passed" "$SELFTEST_LOG"; then
  echo "ERROR: the bundle self-check did not pass." >&2
  sed -n '1,40p' "$SELFTEST_LOG" >&2
  exit 1
fi
sed -n '/self-check inside/,$p' "$SELFTEST_LOG"

echo "==> ALL APPIMAGE CHECKS PASSED"

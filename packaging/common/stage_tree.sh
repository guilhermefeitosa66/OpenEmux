#!/bin/sh
# Populate a staging root with the OpenEmux install layout shared by the .deb
# and .rpm packages. The app runs from /opt/openemux (its "project root", which
# holds src/ and the vendored RetroArch AppImage); /usr/bin/openemux launches it
# and the desktop file + icons register it with the desktop environment.
#
# Usage: DESTDIR=<stage> ROOT_DIR=<repo> stage_tree.sh
set -eu
: "${DESTDIR:?DESTDIR is required}"
: "${ROOT_DIR:?ROOT_DIR is required}"

APP_ID="io.github.guilhermefeitosa66.OpenEmux"
LOGO="$ROOT_DIR/src/openemux/ui/assets/images/logo.png"

install -d "$DESTDIR/opt/openemux"
cp -r "$ROOT_DIR/src" "$DESTDIR/opt/openemux/"
cp -r "$ROOT_DIR/vendors" "$DESTDIR/opt/openemux/"
install -Dm644 "$ROOT_DIR/requirements.lock" "$DESTDIR/opt/openemux/requirements.lock"
install -Dm644 "$ROOT_DIR/README.md" "$DESTDIR/opt/openemux/README.md"
install -Dm644 "$ROOT_DIR/LICENSE" "$DESTDIR/opt/openemux/LICENSE"

# Ship only sources, no build/test caches.
find "$DESTDIR/opt/openemux/src" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

install -Dm755 "$ROOT_DIR/packaging/common/openemux-launcher.sh" "$DESTDIR/usr/bin/openemux"
install -Dm644 "$ROOT_DIR/packaging/common/openemux.desktop" \
  "$DESTDIR/usr/share/applications/$APP_ID.desktop"

# Icons: the themed hicolor entry is what a modern menu uses. Several sizes are
# installed because menus that do not scale pick the nearest exact match, and
# /usr/share/pixmaps is the fallback older Cinnamon/MATE/XFCE menus still read.
install -Dm644 "$LOGO" "$DESTDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
if command -v convert >/dev/null 2>&1; then
  for size in 32 48 64 128 256; do
    install -d "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps"
    convert "$LOGO" -resize "${size}x${size}" \
      "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
  done
fi
install -Dm644 "$LOGO" "$DESTDIR/usr/share/pixmaps/$APP_ID.png"

install -Dm644 "$ROOT_DIR/LICENSE" \
  "$DESTDIR/usr/share/doc/openemux/copyright"

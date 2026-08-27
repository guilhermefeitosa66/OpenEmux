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
# Sources only: copy_tree.sh leaves the working tree's build state behind. A
# plain `cp -r` shipped every gitignored artifact the maintainer happened to
# have -- egg-info directories (one of them from a project name that no longer
# exists) and __pycache__ (issue #254).
sh "$ROOT_DIR/packaging/common/copy_tree.sh" "$ROOT_DIR/src" "$DESTDIR/opt/openemux"
sh "$ROOT_DIR/packaging/common/copy_tree.sh" "$ROOT_DIR/vendors" "$DESTDIR/opt/openemux"
install -Dm644 "$ROOT_DIR/requirements.lock" "$DESTDIR/opt/openemux/requirements.lock"
install -Dm644 "$ROOT_DIR/README.md" "$DESTDIR/opt/openemux/README.md"
install -Dm644 "$ROOT_DIR/LICENSE" "$DESTDIR/opt/openemux/LICENSE"

# Bake the ScreenScraper developer credential into the staged copy (never the
# host source). No-op unless SCREENSCRAPER_DEVID/DEVPASSWORD are set.
python3 "$ROOT_DIR/packaging/embed_screenscraper_credentials.py" \
  "$DESTDIR/opt/openemux/src/openemux/core/embedded_credentials.py"

install -Dm755 "$ROOT_DIR/packaging/common/openemux-launcher.sh" "$DESTDIR/usr/bin/openemux"
install -Dm644 "$ROOT_DIR/packaging/common/openemux.desktop" \
  "$DESTDIR/usr/share/applications/$APP_ID.desktop"

# AppStream metainfo. Without it GNOME Software and KDE Discover know the app
# only as a bare desktop entry -- no summary, no screenshots, no release notes
# and no update notification -- and both rpmlint and lintian flag a desktop
# application that ships none (issue #253). It used to be installed by the
# Flatpak module alone, which is why it lived under packaging/flatpak/.
install -Dm644 "$ROOT_DIR/packaging/common/$APP_ID.metainfo.xml" \
  "$DESTDIR/usr/share/metainfo/$APP_ID.metainfo.xml"

# Absolute Exec/TryExec for the system packages. A PATH-relative "openemux"
# makes the menu entry run whatever shadows /usr/bin in the user's PATH --
# an AppImage manager dropping a symlink at ~/.local/bin/openemux is exactly
# how a freshly installed .deb kept opening a stale AppImage instead of
# itself. Rewritten here rather than in the source file because the AppImage
# build installs that same file and needs the relative name (its desktop
# entry is resolved inside the AppDir).
sed -i \
  -e 's|^Exec=.*|Exec=/usr/bin/openemux|' \
  -e 's|^TryExec=.*|TryExec=/usr/bin/openemux|' \
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

# Check the result rather than trust the exclude list.
sh "$ROOT_DIR/packaging/common/assert_sources_only.sh" "$DESTDIR/opt/openemux"

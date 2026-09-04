#!/bin/sh
# Populate a staging root with the OpenEmux install layout shared by the .deb
# and .rpm packages. The app runs from /opt/openemux (its "project root", which
# holds src/ and the vendored RetroArch); /usr/bin/openemux launches it and the
# desktop file + icons register it with the desktop environment.
#
# Usage: DESTDIR=<stage> ROOT_DIR=<repo> stage_tree.sh
set -eu
: "${DESTDIR:?DESTDIR is required}"
: "${ROOT_DIR:?ROOT_DIR is required}"

APP_ID="io.github.guilhermefeitosa66.OpenEmux"
LOGO="$ROOT_DIR/src/openemux/ui/assets/images/logo.png"

# The vendored RetroArch is per-architecture, and a package must carry only its
# own: an x86_64 binary on an ARM machine is not a RetroArch that failed to
# start, it is a file the kernel refuses to execute (issue #119). libretro
# publishes no ARM build, so on aarch64 there is usually nothing to carry at
# all and the launcher falls back to a distro or Flatpak RetroArch.
#
# A directory name since issue #328: what is vendored is the portable tree the
# AppImage used to wrap, so the package needs no FUSE to run it.
BUILD_ARCH="$(uname -m)"
case "$BUILD_ARCH" in
  aarch64|arm64) FOREIGN_RETROARCH="RetroArch-Linux-x86_64" ;;
  *)             FOREIGN_RETROARCH="RetroArch-Linux-aarch64" ;;
esac

install -d "$DESTDIR/opt/openemux"
# Sources only: copy_tree.sh leaves the working tree's build state behind. A
# plain `cp -r` shipped every gitignored artifact the maintainer happened to
# have -- egg-info directories (one of them from a project name that no longer
# exists) and __pycache__ (issue #254).
sh "$ROOT_DIR/packaging/common/copy_tree.sh" "$ROOT_DIR/src" "$DESTDIR/opt/openemux"
sh "$ROOT_DIR/packaging/common/copy_tree.sh" "$ROOT_DIR/vendors" \
  "$DESTDIR/opt/openemux" "$FOREIGN_RETROARCH"
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
#
# TryExec is *added* here rather than rewritten: only the native packages
# install /usr/bin/openemux, so only they can promise it resolves. The shared
# file carries none, because TryExec is resolved against the user's PATH and
# an AppImage integrator (appimaged, AppImageLauncher, GearLever) rewrites
# Exec to the bundle path and leaves TryExec alone -- so the integrated entry
# named a binary that does not exist and was silently hidden from the menu
# (issue #256).
sed -i 's|^Exec=.*|Exec=/usr/bin/openemux|' \
  "$DESTDIR/usr/share/applications/$APP_ID.desktop"
grep -q '^TryExec=' "$DESTDIR/usr/share/applications/$APP_ID.desktop" ||
  sed -i '/^Exec=/a TryExec=/usr/bin/openemux' \
    "$DESTDIR/usr/share/applications/$APP_ID.desktop"

# Icons, at every size the desktop asks for. Its own script because the sizes
# have to be *measured* to be trusted -- see stage_icons.sh for the six that
# were each filed under a size they were not.
DESTDIR="$DESTDIR" APP_ID="$APP_ID" LOGO="$LOGO" \
  sh "$ROOT_DIR/packaging/common/stage_icons.sh"

# The packaged copyright file. Not a copy of LICENSE: about a third of what
# ships is third-party (the OpenEmu console icons, the Adwaita symbolic icons,
# the vendored RetroArch), and installing the bare MIT text here implicitly
# claimed MIT over all of it (issue #233). DEP-5, so the per-file terms are
# machine-readable and each one names where its notice lives.
install -Dm644 "$ROOT_DIR/packaging/common/copyright" \
  "$DESTDIR/usr/share/doc/openemux/copyright"

# Check the result rather than trust the exclude list.
sh "$ROOT_DIR/packaging/common/assert_sources_only.sh" "$DESTDIR/opt/openemux"

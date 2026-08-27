#!/usr/bin/env bash
# Builds the OpenEmux .deb and smoke-tests it. Runs *inside* the container
# defined by packaging/docker/deb.Dockerfile -- launch it through
# `packaging/build.sh deb` (or `make deb`), not directly on the host.
set -euo pipefail

VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
echo "==> building openemux ${VERSION} .deb"

STAGE="$(mktemp -d)"
DESTDIR="$STAGE" ROOT_DIR="$PWD" sh packaging/common/stage_tree.sh

# libfuse2t64 | libfuse2 is a hard dependency, not a Recommends: the vendored
# RetroArch AppImage is the only emulator this package ships and its runtime
# needs libfuse.so.2 to mount itself. `apt install ./x.deb` does pull
# recommends, but `dpkg -i` and offline installs do not -- and the app then
# installed cleanly and could not launch a single game (issue #248). The
# alternative covers both spellings: noble renamed the package to libfuse2t64.
#
# webp-pixbuf-loader is there for the same reason in a different place: cover
# art synced from libretro is WebP and gdk-pixbuf has no built-in decoder for
# it. Nothing else this package depends on pulls the loader -- measured
# against the released 1.11.3 artifact, `apt install ./openemux_*.deb` on a
# stock ubuntu:24.04 left gdk-pixbuf with no webp loader at all, so every
# synced cover decoded to nothing and the card rendered blank (issue #251).
install -d "$STAGE/DEBIAN"
INSTALLED_KB="$(du -ks "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: openemux
Version: ${VERSION}
Architecture: amd64
Maintainer: Guilherme Feitoza <guilhermefeitosa66@gmail.com>
Installed-Size: ${INSTALLED_KB}
Section: games
Priority: optional
Homepage: https://github.com/guilhermefeitosa66/OpenEmux
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0 (>= 4.6), gir1.2-adw-1 (>= 1.5), python3-yaml, python3-xlib, librsvg2-common, gir1.2-rsvg-2.0, webp-pixbuf-loader, adwaita-icon-theme, shared-mime-info, libfuse2t64 | libfuse2
Description: Linux-native emulator frontend for RetroArch
 OpenEmux is a GTK4/Adwaita frontend that manages a ROM library and launches
 games through RetroArch, inspired by OpenEmu. It bundles a RetroArch AppImage
 and downloads libretro cores on first launch.
EOF

# Refresh the icon and desktop caches so the entry shows up in the menu without
# a re-login.
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
EOF
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

desktop-file-validate "$STAGE/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop"
# The file GNOME Software and KDE Discover read. Without it the app is invisible
# in both -- no name, no summary, no screenshots, no update notification
# (issue #253). --no-net keeps the build offline.
appstreamcli validate --no-net \
  "$STAGE/usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml"
# The packaged entry must point at /usr/bin explicitly: a PATH-relative Exec
# resolves through ~/.local/bin, where AppImage managers drop shadowing
# symlinks, and the menu icon then opens a different (often stale) install.
grep -q '^Exec=/usr/bin/openemux$' \
  "$STAGE/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop"

mkdir -p dist
DEB="dist/openemux_${VERSION}_amd64.deb"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB"
echo "==> built: $DEB"
dpkg-deb --info "$DEB"

echo "==> install test (resolves Depends via apt)"
apt-get update -qq
apt-get install -y "./$DEB"

echo "==> verify installed files"
test -x /usr/bin/openemux
test -f /opt/openemux/vendors/RetroArch-Linux-x86_64.AppImage
test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
test -f /usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png
test -f /usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png

echo "==> verify the vendored symbolic icons all shipped"
SRC_ICONS="$(find src/openemux/ui/assets/icons/symbolic -name '*.svg' | wc -l)"
PKG_ICONS="$(find /opt/openemux/src/openemux/ui/assets/icons/symbolic -name '*.svg' | wc -l)"
if [ "$SRC_ICONS" -eq 0 ] || [ "$SRC_ICONS" -ne "$PKG_ICONS" ]; then
  echo "FAIL: expected $SRC_ICONS symbolic icons in the package, found $PKG_ICONS" >&2
  exit 1
fi
test -f /opt/openemux/src/openemux/ui/assets/icons/symbolic/LICENSE
echo "all $PKG_ICONS symbolic icons present"

echo "==> import smoke test against installed deps"
OPENEMUX_PROJECT_ROOT=/opt/openemux PYTHONPATH=/opt/openemux/src python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
import openemux
from openemux.ui import window  # exercises the full UI import chain
from openemux.core import update_checker
print("import OK, version", openemux.__version__)
PY

echo "==> the installed package must be able to decode every cover format"
# Not an import: the loaders are separate packages, and a missing one shows
# up only as a blank card and a "cover decode failed" line in the log. WebP
# is the format the libretro thumbnail sync downloads (issue #251); png/jpeg
# carry local art and svg is every symbolic icon in the UI.
OPENEMUX_PROJECT_ROOT=/opt/openemux PYTHONPATH=/opt/openemux/src python3 - <<'LOADERS'
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
from openemux.core.scraper import SUPPORTED_COVER_EXTS

names = {f.get_name() for f in GdkPixbuf.Pixbuf.get_formats()}
# scraper spells JPEG both "jpg" and "jpeg"; gdk-pixbuf calls the loader "jpeg".
required = {{"jpg": "jpeg"}.get(ext, ext) for ext in SUPPORTED_COVER_EXTS} | {"svg"}
missing = sorted(required - names)
if missing:
    raise SystemExit(f"FAIL: no pixbuf loader for {missing}; declare the dependency")
print("pixbuf loaders OK:", sorted(required))
LOADERS

echo "==> launcher must ignore a shadowing python3 without PyGObject"
# Reproduces the pyenv/conda case: a python3 earlier in PATH that cannot import
# gi used to make the installed app die with ModuleNotFoundError.
mkdir -p /tmp/fakebin
cat > /tmp/fakebin/python3 <<'FAKE'
#!/bin/sh
echo "fake python3 (no gi) was used" >&2
exit 99
FAKE
chmod +x /tmp/fakebin/python3
if PATH=/tmp/fakebin:$PATH timeout 20 openemux --help >/tmp/launch.log 2>&1; then
  :
fi
if grep -q "fake python3" /tmp/launch.log; then
  echo "FAIL: launcher used the shadowing python3" >&2
  cat /tmp/launch.log >&2
  exit 1
fi
if grep -q "No module named 'gi'" /tmp/launch.log; then
  echo "FAIL: launcher could not find a PyGObject interpreter" >&2
  cat /tmp/launch.log >&2
  exit 1
fi
echo "launcher resolved a working interpreter"

echo "==> ALL DEB CHECKS PASSED"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist 2>/dev/null || true

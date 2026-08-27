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
#
# shared-mime-info is deliberately absent. It was declared so that the
# `update-desktop-database` in the scriptlets below had something to index --
# but the desktop entry carries no MimeType, so it indexed nothing (issue
# #256). GTK needs the shared MIME database at runtime and `libgtk-4-1`
# already depends on it, so nothing changes for the user. Declare it again the
# day OpenEmux can open a ROM handed to it by a file manager, together with a
# MimeType= line and a %%U on Exec.
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
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0 (>= 4.6), gir1.2-adw-1 (>= 1.5), python3-yaml, python3-xlib, librsvg2-common, gir1.2-rsvg-2.0, webp-pixbuf-loader, adwaita-icon-theme, libfuse2t64 | libfuse2
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
# Only the native packages install /usr/bin/openemux, so only they may promise
# TryExec resolves; the shared entry the AppImage installs carries none.
grep -q '^TryExec=/usr/bin/openemux$' \
  "$STAGE/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop"
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

# The release history, rendered from the spec's %changelog so a release
# documents itself in one place. The .deb shipped none at all before --
# lintian's debian-changelog-file-missing (issue #256).
python3 packaging/deb/changelog_from_spec.py > "$STAGE/changelog.Debian"
gzip -9n "$STAGE/changelog.Debian"
install -Dm644 "$STAGE/changelog.Debian.gz" \
  "$STAGE/usr/share/doc/openemux/changelog.Debian.gz"
rm -f "$STAGE/changelog.Debian.gz"

# md5sums, so `debsums openemux` can verify the 600+ installed files of a
# package that ships an executable AppImage. dpkg-deb --build generates none;
# nothing here did either, which is lintian's no-md5sums-control-file.
( cd "$STAGE" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' \
  | sort -z | xargs -0 md5sum > DEBIAN/md5sums )
chmod 0644 "$STAGE/DEBIAN/md5sums"
echo "md5sums: $(wc -l < "$STAGE/DEBIAN/md5sums") files"

mkdir -p dist
DEB="dist/openemux_${VERSION}_amd64.deb"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB"
echo "==> built: $DEB"
dpkg-deb --info "$DEB"

echo "==> install test (resolves Depends via apt)"
apt-get update -qq
apt-get install -y "./$DEB"

echo "==> the control members lintian and debsums look for"
# Listed once into a variable, not piped straight into `grep -q` five times.
# `grep -q` exits on its first match and SIGPIPEs whatever is still writing;
# under `set -o pipefail` that pipeline is a failure (141), and whether it
# happens at all depends on how much of the listing is still buffered -- so the
# build passed on the maintainer's machine and died in CI on the same commit.
CTRL_MEMBERS="$(dpkg-deb --ctrl-tarfile "$DEB" | tar -t)"
FSYS_MEMBERS="$(dpkg-deb --fsys-tarfile "$DEB" | tar -t)"
FSYS_LONG="$(dpkg-deb --fsys-tarfile "$DEB" | tar -tv)"
sort <<< "$CTRL_MEMBERS"

# Matched against the listing already in memory, with a here-string rather than
# a pipe. `grep -q` exits on its first match and SIGPIPEs whatever is still
# writing into it, which under `set -o pipefail` fails the pipeline (141) --
# and whether it happens depends on how much of the listing was still buffered,
# so the same commit passed on the maintainer's machine and died in CI.
require_member() {
  grep -Fxq "$1" <<< "$2" || { echo "FAIL: $DEB does not carry $1" >&2; exit 1; }
}
require_member './md5sums' "$CTRL_MEMBERS"
# Present is not the same as complete: a file missing from md5sums is a file
# debsums silently does not verify.
PACKAGED_FILES="$(grep -c '^-' <<< "$FSYS_LONG")"
MD5SUM_LINES="$(dpkg-deb --ctrl-tarfile "$DEB" | tar -xO ./md5sums | wc -l)"
if [ "$PACKAGED_FILES" -ne "$MD5SUM_LINES" ]; then
  echo "FAIL: $PACKAGED_FILES files packaged, $MD5SUM_LINES in md5sums" >&2
  exit 1
fi
echo "md5sums covers all $PACKAGED_FILES packaged files"
require_member './usr/share/doc/openemux/changelog.Debian.gz' "$FSYS_MEMBERS"
require_member './usr/share/doc/openemux/copyright' "$FSYS_MEMBERS"

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

echo "==> debsums must be able to verify every installed file"
apt-get install -y -qq debsums >/dev/null
debsums -s openemux
echo "debsums verified $(dpkg-query -W -f='${Installed-Size}' openemux) KB of installed files"

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

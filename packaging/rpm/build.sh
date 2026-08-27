#!/usr/bin/env bash
# Builds the OpenEmux .rpm and smoke-tests it. Runs *inside* the container
# defined by packaging/docker/rpm.Dockerfile -- launch it through
# `packaging/build.sh rpm` (or `make rpm`), not directly on the host.
set -euo pipefail

VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
echo "==> building openemux ${VERSION} .rpm"

desktop-file-validate packaging/common/openemux.desktop

rpmbuild -bb packaging/rpm/openemux.spec \
  --define "version ${VERSION}" \
  --define "repo_root /work" \
  --define "_topdir /tmp/rpmbuild"

mkdir -p dist
RPM_PATH="$(find /tmp/rpmbuild/RPMS -name "openemux-${VERSION}-*.rpm" | head -1)"
cp "$RPM_PATH" dist/
RPM_NAME="$(basename "$RPM_PATH")"
echo "==> built: dist/${RPM_NAME}"
rpm -qip "dist/${RPM_NAME}"

echo "==> install test (resolves Requires via dnf)"
dnf install -y "./dist/${RPM_NAME}" >/dev/null

echo "==> verify installed files"
test -x /usr/bin/openemux
test -f /opt/openemux/vendors/RetroArch-Linux-x86_64.AppImage
test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
# PATH-relative Exec would let a ~/.local/bin shadow (AppImage-manager
# symlink) hijack the menu icon; the packaged entry must be explicit.
grep -q '^Exec=/usr/bin/openemux$' /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
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
mkdir -p /tmp/fakebin
cat > /tmp/fakebin/python3 <<'FAKE'
#!/bin/sh
echo "fake python3 (no gi) was used" >&2
exit 99
FAKE
chmod +x /tmp/fakebin/python3
PATH=/tmp/fakebin:$PATH timeout 20 openemux --help >/tmp/launch.log 2>&1 || true
if grep -q "fake python3" /tmp/launch.log; then
  echo "FAIL: launcher used the shadowing python3" >&2
  cat /tmp/launch.log >&2
  exit 1
fi
echo "launcher resolved a working interpreter"

echo "==> ALL RPM CHECKS PASSED"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist 2>/dev/null || true

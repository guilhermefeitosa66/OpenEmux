#!/usr/bin/env bash
# Build the OpenEmux .deb inside an Ubuntu 24.04 container and smoke-test that it
# installs and imports against distro system packages (GTK4/Adwaita/PyGObject).
# Targets Ubuntu 24.04 LTS and newer (libadwaita >= 1.5, required by the UI).
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install Docker to build the .deb." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST_UID="${HOST_UID:-$(stat -c '%u' "${ROOT_DIR}")}"
HOST_GID="${HOST_GID:-$(stat -c '%g' "${ROOT_DIR}")}"
IMAGE="${DEB_BUILD_IMAGE:-ubuntu:24.04}"

docker run --rm -t \
  -v "${ROOT_DIR}:/work" \
  -e HOST_UID="${HOST_UID}" \
  -e HOST_GID="${HOST_GID}" \
  -w /work \
  "${IMAGE}" \
  bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends dpkg-dev desktop-file-utils

    VERSION="$(sed -n "s/.*\"\(.*\)\".*/\1/p" src/openemux/__init__.py)"
    echo "Building openemux ${VERSION} .deb"

    STAGE="$(mktemp -d)"
    DESTDIR="$STAGE" ROOT_DIR=/work sh packaging/common/stage_tree.sh

    # Debian control metadata.
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
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0 (>= 4.6), gir1.2-adw-1 (>= 1.5), python3-yaml, librsvg2-common, adwaita-icon-theme, shared-mime-info
Recommends: libfuse2t64 | libfuse2
Description: Linux-native emulator frontend for RetroArch
 OpenEmux is a GTK4/Adwaita frontend that manages a ROM library and launches
 games through RetroArch, inspired by OpenEmu. It bundles a RetroArch AppImage
 and downloads libretro cores on first launch.
EOF

    # dpkg maintainer scripts: refresh icon/desktop caches.
    cat > "$STAGE/DEBIAN/postinst" <<EOF
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

    mkdir -p dist
    DEB="dist/openemux_${VERSION}_amd64.deb"
    dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB"
    echo "=== built: $DEB ==="
    dpkg-deb --info "$DEB"
    dpkg-deb --contents "$DEB" | sed -n "1,40p"

    echo "=== install test (resolves deps via apt) ==="
    apt-get install -y "./$DEB"

    echo "=== verify installed files ==="
    test -x /usr/bin/openemux
    test -f /opt/openemux/vendors/RetroArch-Linux-x86_64.AppImage
    test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
    test -f /usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png

    echo "=== import smoke test against installed deps ==="
    OPENEMUX_PROJECT_ROOT=/opt/openemux PYTHONPATH=/opt/openemux/src python3 - <<PY
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
import openemux
from openemux.ui import window  # exercises the full UI import chain
from openemux.core import update_checker
print("import OK, version", openemux.__version__)
PY

    echo "=== ALL DEB CHECKS PASSED ==="
    chown -R "${HOST_UID}:${HOST_GID}" dist 2>/dev/null || true
  '

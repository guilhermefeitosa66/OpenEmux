#!/usr/bin/env bash
# Build the OpenEmux .rpm inside a Fedora container and smoke-test that it
# installs and imports against distro system packages (GTK4/Adwaita/PyGObject).
# Targets Fedora 40 and newer (libadwaita >= 1.5, required by the UI).
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install Docker to build the .rpm." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST_UID="${HOST_UID:-$(stat -c '%u' "${ROOT_DIR}")}"
HOST_GID="${HOST_GID:-$(stat -c '%g' "${ROOT_DIR}")}"
IMAGE="${RPM_BUILD_IMAGE:-fedora:41}"

docker run --rm -t \
  -v "${ROOT_DIR}:/work" \
  -e HOST_UID="${HOST_UID}" \
  -e HOST_GID="${HOST_GID}" \
  -w /work \
  "${IMAGE}" \
  bash -lc '
    set -euo pipefail
    dnf install -y rpm-build desktop-file-utils coreutils >/dev/null

    VERSION="$(sed -n "s/.*\"\(.*\)\".*/\1/p" src/openemux/__init__.py)"
    echo "Building openemux ${VERSION} .rpm"

    desktop-file-validate packaging/appimage/io.github.guilhermefeitosa66.OpenEmux.desktop

    rpmbuild -bb packaging/rpm/openemux.spec \
      --define "version ${VERSION}" \
      --define "repo_root /work" \
      --define "_topdir /tmp/rpmbuild"

    mkdir -p dist
    RPM_PATH="$(find /tmp/rpmbuild/RPMS -name "openemux-${VERSION}-*.rpm" | head -1)"
    cp "$RPM_PATH" dist/
    RPM_NAME="$(basename "$RPM_PATH")"
    echo "=== built: dist/${RPM_NAME} ==="
    rpm -qip "dist/${RPM_NAME}"
    echo "=== contents (head) ==="
    rpm -qlp "dist/${RPM_NAME}" | sed -n "1,25p"

    echo "=== install test (resolves deps via dnf) ==="
    dnf install -y "./dist/${RPM_NAME}" >/dev/null

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

    echo "=== ALL RPM CHECKS PASSED ==="
    chown -R "${HOST_UID}:${HOST_GID}" dist 2>/dev/null || true
  '

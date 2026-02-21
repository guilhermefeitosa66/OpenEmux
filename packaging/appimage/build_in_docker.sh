#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST_UID="${HOST_UID:-$(stat -c '%u' "${ROOT_DIR}")}"
HOST_GID="${HOST_GID:-$(stat -c '%g' "${ROOT_DIR}")}"

docker run --rm -t \
  -v "${ROOT_DIR}:/work" \
  -e HOST_UID="${HOST_UID}" \
  -e HOST_GID="${HOST_GID}" \
  -w /work \
  ubuntu:24.04 \
  bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y \
      python3 python3-pip python3-setuptools python3-wheel \
      file desktop-file-utils squashfs-tools patchelf fakeroot strace xz-utils zsync wget \
      libgdk-pixbuf2.0-bin libglib2.0-bin gtk-update-icon-cache
    python3 -m pip install --break-system-packages "packaging<22" "appimage-builder==1.1.0"
    appimage-builder --recipe packaging/appimage/AppImageBuilder.yml --skip-test
    mkdir -p dist
    shopt -s nullglob
    for appimage in *.AppImage; do
      mv "$appimage" dist/
    done
    for zsync in *.zsync; do
      mv "$zsync" dist/
    done
    chown -R "${HOST_UID}:${HOST_GID}" dist AppDir appimage-build appimage-builder-cache 2>/dev/null || true
  '

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
      libgdk-pixbuf2.0-bin libglib2.0-bin gtk-update-icon-cache \
      librsvg2-common
    python3 -m pip install --break-system-packages "packaging<22" "appimage-builder==1.1.0"

    RECIPE=packaging/appimage/AppImageBuilder.yml

    # Phase 1: assemble the AppDir (apt bundle + app), but do not package yet.
    appimage-builder --recipe "$RECIPE" --skip-tests --skip-appimage

    # Regenerate the gdk-pixbuf loaders cache from the *bundled* loaders so the
    # SVG loader (librsvg2-common) is registered. Without this the cache written
    # during bundling omits libpixbufloader-svg.so, and every symbolic icon in
    # the GTK/Adwaita UI (header bar, menus, rows, status pages) fails to render.
    # LD_LIBRARY_PATH points at the bundled libs so the SVG loader (needs
    # librsvg/cairo/libxml2) can be dlopen-ed while querying.
    GPB_DIR="$(pwd)/AppDir/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0"
    QUERY_BIN=/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders
    if [ ! -d "$GPB_DIR/2.10.0/loaders" ] || [ ! -x "$QUERY_BIN" ]; then
      echo "ERROR: gdk-pixbuf query tool or bundled loaders dir not found." >&2
      exit 1
    fi
    tmp_cache="$(mktemp)"
    LD_LIBRARY_PATH="$(pwd)/AppDir/usr/lib/x86_64-linux-gnu:$(pwd)/AppDir/lib/x86_64-linux-gnu" \
    GDK_PIXBUF_MODULEDIR="$GPB_DIR/2.10.0/loaders" \
      "$QUERY_BIN" > "$tmp_cache"
    # Strip the build-time absolute loader dir so entries become bare filenames;
    # at runtime GDK_PIXBUF_MODULEDIR ($APPDIR/...) is prepended to resolve them.
    sed -i "s|$GPB_DIR/2.10.0/loaders/||g" "$tmp_cache"
    if ! grep -q "svg" "$tmp_cache"; then
      echo "ERROR: regenerated loaders.cache is missing the SVG loader; aborting." >&2
      rm -f "$tmp_cache"
      exit 1
    fi
    mv "$tmp_cache" "$GPB_DIR/2.10.0/loaders.cache"
    echo "gdk-pixbuf loaders.cache regenerated with SVG loader ($(grep -c '\.so' "$GPB_DIR/2.10.0/loaders.cache") loaders)."

    # Phase 2: package the AppImage from the fixed AppDir (do not rebuild it).
    appimage-builder --recipe "$RECIPE" --skip-script --skip-build --skip-tests

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

#!/usr/bin/env bash
# Builds the OpenEmux Flatpak bundle. Runs *inside* the container defined by
# packaging/docker/flatpak.Dockerfile -- launch it through
# `packaging/build.sh flatpak` (or `make flatpak`), not directly on the host.
#
# Output: dist/OpenEmux-<version>.flatpak (single-file bundle; users install it
# with `flatpak install ./OpenEmux-<version>.flatpak`, the GNOME runtime is
# pulled from their configured remote), plus the ostree repo under
# flatpak-repo/ for publication to the openemux-flatpak repository.
set -euo pipefail

APP_ID="io.github.guilhermefeitosa66.OpenEmux"
MANIFEST="packaging/flatpak/${APP_ID}.yaml"
RUNTIME_VERSION="$(sed -n "s/^runtime-version: '\(.*\)'/\1/p" "$MANIFEST")"
VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
echo "==> building openemux ${VERSION} flatpak (GNOME ${RUNTIME_VERSION})"

# The manifest builds the working tree (type: dir), so the embedded credential
# is injected in place and restored afterwards, exactly like the other builds.
CRED_FILE="src/openemux/core/embedded_credentials.py"
cp "$CRED_FILE" "${CRED_FILE}.orig"
trap 'mv "${CRED_FILE}.orig" "$CRED_FILE"' EXIT
python3 packaging/embed_screenscraper_credentials.py "$CRED_FILE"

flatpak remote-add --user --if-not-exists flathub \
  https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y --user --noninteractive flathub \
  "org.gnome.Platform//${RUNTIME_VERSION}" "org.gnome.Sdk//${RUNTIME_VERSION}"

flatpak-builder --user --force-clean --disable-rofiles-fuse \
  --repo=flatpak-repo .flatpak-build-dir "$MANIFEST"

mkdir -p dist
BUNDLE="dist/OpenEmux-${VERSION}.flatpak"
flatpak build-bundle flatpak-repo "$BUNDLE" "$APP_ID"
echo "==> built: $BUNDLE"

echo "==> verify the vendored symbolic icons made it into the build"
# pip installs them as package data; a pattern regression in pyproject would
# drop them from the Flatpak only, so count them against the source tree.
ICONS_DIR="$(find .flatpak-build-dir/files -type d -path '*openemux/ui/assets/icons/symbolic' | head -1)"
if [ -z "$ICONS_DIR" ]; then
  echo "FAIL: openemux/ui/assets/icons/symbolic missing from the flatpak build" >&2
  exit 1
fi
SRC_ICONS="$(find src/openemux/ui/assets/icons/symbolic -name '*.svg' | wc -l)"
PKG_ICONS="$(find "$ICONS_DIR" -name '*.svg' | wc -l)"
if [ "$SRC_ICONS" -eq 0 ] || [ "$SRC_ICONS" -ne "$PKG_ICONS" ]; then
  echo "FAIL: expected $SRC_ICONS symbolic icons in the flatpak, found $PKG_ICONS" >&2
  exit 1
fi
test -f "$ICONS_DIR/LICENSE"
echo "all $PKG_ICONS symbolic icons present"

echo "==> verify the bundle installs"
flatpak install -y --user --noninteractive "./$BUNDLE"
flatpak info --user "$APP_ID"

echo "==> ALL FLATPAK CHECKS PASSED"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist flatpak-repo 2>/dev/null || true

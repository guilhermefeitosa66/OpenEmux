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

# Build from a staging copy, never from the working tree (issue #250).
#
# The manifest's source is `type: dir`, `path: ../..` -- the repository root
# relative to the manifest. Copying the manifest into a staging tree makes that
# same relative path resolve to the staging tree instead, so nothing here has
# to be duplicated in the manifest and the openemux-flatpak workflow, which
# builds a throwaway CI checkout directly, keeps working unchanged.
#
# Two things this buys:
#
#   * the ScreenScraper credential is injected into the copy. It used to be
#     written into the *tracked* src/openemux/core/embedded_credentials.py and
#     restored by an EXIT trap, so any SIGKILL (docker kill, OOM, reboot) left
#     the obfuscated developer credential in a tracked file, one `git commit -a`
#     away from being published.
#   * the copy is an explicit list of inputs, so `.env` (which holds
#     SCREENSCRAPER_DEVID/DEVPASSWORD), `.git`, `dist/`, `.venv/` and every
#     other gitignored artifact in the working tree cannot reach the
#     root-owned .flatpak-build-dir the way `path: ../..` on the real tree did.
#
# The staging tree lives outside the bind mount, so an interrupted build leaves
# nothing behind on the host at all.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Everything the manifest reads: `pip3 install .` needs the project metadata
# and src/, the install steps need packaging/flatpak/ and LICENSE. A file added
# to the manifest and forgotten here fails the build loudly rather than
# silently widening what gets copied.
for item in pyproject.toml README.md LICENSE requirements.lock src \
            packaging/common packaging/flatpak \
            packaging/embed_screenscraper_credentials.py; do
  install -d "$STAGE/$(dirname "$item")"
  cp -a "$item" "$STAGE/$item"
done
python3 "$STAGE/packaging/embed_screenscraper_credentials.py" \
  "$STAGE/src/openemux/core/embedded_credentials.py"

# After the injection, which imports the staged package and writes bytecode of
# its own. setuptools reuses egg-info when it finds one, and __pycache__ of a
# pre-injection module is exactly the sort of build state a package should not
# be carrying.
find "$STAGE/src" \( -name '__pycache__' -o -name '*.egg-info' \) -type d -prune \
  -exec rm -rf {} + 2>/dev/null || true

# The tracked file must have come out of this untouched.
grep -q '^_EMBEDDED_BLOB = ""$' src/openemux/core/embedded_credentials.py

echo "==> validate the two files Flathub reads before publishing"
# Neither was checked here: deb/build.sh and rpm/build.sh both run
# desktop-file-validate, the Flatpak ran nothing at all -- on the app that is
# heading for Flathub, whose linter reads exactly these two (issue #253).
# --no-net keeps the build offline; the screenshot URLs are checked by
# tests/test_appstream_metainfo.py.
appstreamcli validate --no-net \
  "$STAGE/packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml"
desktop-file-validate "$STAGE/packaging/common/openemux.desktop"

flatpak remote-add --user --if-not-exists flathub \
  https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y --user --noninteractive flathub \
  "org.gnome.Platform//${RUNTIME_VERSION}" "org.gnome.Sdk//${RUNTIME_VERSION}"

flatpak-builder --user --force-clean --disable-rofiles-fuse \
  --repo=flatpak-repo .flatpak-build-dir "$STAGE/$MANIFEST"

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

echo "==> verify the exported desktop entry is not hidden by TryExec"
# Flatpak exports the entry to the host, where TryExec is resolved against the
# host PATH -- and no `openemux` binary lives there.
DESKTOP="$(find .flatpak-build-dir/files/share/applications -name '*.desktop' | head -1)"
if grep -q '^TryExec=' "$DESKTOP"; then
  echo "FAIL: the exported desktop entry still carries TryExec" >&2
  exit 1
fi
grep -q '^Exec=openemux$' "$DESKTOP"
test -f .flatpak-build-dir/files/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
echo "desktop entry and metainfo in place"

echo "==> verify the build carried no working-tree leftovers"
# The staging list is the whole defence against `path: ../..` scooping up the
# working tree; check the result rather than trusting the list.
for unwanted in .env .git dist .venv AppDir flatpak-repo; do
  if [ -e "$STAGE/$unwanted" ]; then
    echo "FAIL: $unwanted reached the flatpak staging tree" >&2
    exit 1
  fi
done
echo "staging tree is clean"

echo "==> verify the bundle installs"
flatpak install -y --user --noninteractive "./$BUNDLE"
flatpak info --user "$APP_ID"

echo "==> ALL FLATPAK CHECKS PASSED"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist flatpak-repo 2>/dev/null || true

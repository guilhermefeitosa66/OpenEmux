#!/usr/bin/env bash
# Writes, checks and (optionally) publishes the three release AUR recipes --
# openemux, openemux-bin and openemux-appimage -- for one release tag
# (issue #991). Runs *inside* the Arch build image; launch it through
# `packaging/build.sh aur-release` (`make aur-release` / `make aur-publish`),
# not directly.
#
#   AUR_TAG     the release tag, e.g. v1.24.0 (required)
#   AUR_MODE    check    -- generate, build, namcap, install and swap-test
#               dry-run  -- check, then print the diff against the AUR
#               publish  -- check, then commit and push to the AUR
#   AUR_PKGREL  1 for a new release (the default); more for a recipe fix
#   AUR_SSH_PRIVATE_KEY  the AUR account's key; publish refuses without it
#
# The recipes download the release from GitHub, as a user's makepkg would: the
# code under test is the published release, not this checkout. What this
# checkout contributes is the recipes themselves.
set -euo pipefail

trap 'sh packaging/common/hand_back.sh || true' EXIT

TAG="${AUR_TAG:-}"
MODE="${AUR_MODE:-check}"
PKGREL="${AUR_PKGREL:-1}"
PACKAGES=(openemux openemux-bin openemux-appimage)
OUT=build/aur/release
BUILDDIR=/tmp/aurrelease
APP_ID=io.github.guilhermefeitosa66.OpenEmux
# The AUR's published host key (https://aur.archlinux.org, "SSH fingerprints":
# SHA256:RFzBCUItH9LZS0cKB5UE6ceAYhBD5C8GeOBip8Z11+4). Pinned, so a push never
# trusts whatever answers on the first connection.
AUR_HOST_KEY='aur.archlinux.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEuBKrPzbawxA/k2g6NcyV5jmqwJ2s+zpgZGZ7tpLIcN'

test -n "$TAG" || { echo "FAIL: AUR_TAG is not set (e.g. AUR_TAG=v1.24.0)" >&2; exit 2; }
case "$MODE" in
  check|dry-run|publish) ;;
  *) echo "FAIL: AUR_MODE must be check, dry-run or publish (got '$MODE')" >&2; exit 2 ;;
esac
# Before anything is downloaded: a publish that cannot push should say so in
# its first line, not after ten minutes of building.
if [ "$MODE" = publish ] && [ -z "${AUR_SSH_PRIVATE_KEY:-}" ]; then
  echo "FAIL: AUR_SSH_PRIVATE_KEY is not set, so nothing can be pushed to the AUR." >&2
  echo "Add the AUR account's SSH key as the repository secret AUR_SSH_PRIVATE_KEY," >&2
  echo "or run with AUR_MODE=dry-run (make aur-publish DRY_RUN=1) to see the diff." >&2
  exit 1
fi

echo "==> generating the recipes for ${TAG} (pkgrel ${PKGREL})"
rm -rf "$OUT"
python3 packaging/aur/release.py "$TAG" --out "$OUT" --pkgrel "$PKGREL"
VERSION="${TAG#v}"

chown -R builder:builder "$OUT"
for pkg in "${PACKAGES[@]}"; do
  runuser -u builder -- bash -lc "cd '$PWD/$OUT/$pkg' && makepkg --printsrcinfo > .SRCINFO"
  SRCINFO="$(cat "$OUT/$pkg/.SRCINFO")"
  for line in "pkgbase = $pkg" "pkgver = $VERSION" "pkgrel = $PKGREL"; do
    grep -qxF "	$line" <<< "$SRCINFO" || grep -qxF "$line" <<< "$SRCINFO" || {
      echo "FAIL: $pkg/.SRCINFO lacks '$line'" >&2; exit 1; }
  done
  # Every recipe pins a real checksum; SKIP would mean the template leaked.
  if grep -q 'sha256sums = SKIP' <<< "$SRCINFO"; then
    echo "FAIL: $pkg/.SRCINFO still skips its checksum" >&2
    exit 1
  fi
  if [ "$pkg" != openemux ]; then
    grep -qF 'provides = openemux' <<< "$SRCINFO" || {
      echo "FAIL: $pkg does not provide openemux" >&2; exit 1; }
    grep -qF 'conflicts = openemux' <<< "$SRCINFO" || {
      echo "FAIL: $pkg does not conflict with openemux" >&2; exit 1; }
  fi
done

echo "==> building each recipe the way makepkg on a user's machine would"
rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR"
cp -a "$OUT/." "$BUILDDIR/"
chown -R builder:builder "$BUILDDIR"
declare -A PKG_PATH
for pkg in "${PACKAGES[@]}"; do
  # --nodeps: the image carries the runtime dependencies; the install test
  # below resolves the rest (retroarch, fuse2) through pacman.
  runuser -u builder -- bash -lc "cd '$BUILDDIR/$pkg' && makepkg -f --nodeps --noconfirm"
  PKG_PATH[$pkg]="$(find "$BUILDDIR/$pkg" -maxdepth 1 -name "${pkg}-${VERSION}-${PKGREL}-*.pkg.tar.*" -print -quit)"
  test -n "${PKG_PATH[$pkg]}" || { echo "FAIL: makepkg produced no $pkg package" >&2; exit 1; }
  pacman -Qip "${PKG_PATH[$pkg]}"

  echo "==> namcap $pkg: the findings that would break an install"
  NAMCAP="$(namcap "${PKG_PATH[$pkg]}" || true)"
  echo "$NAMCAP"
  for finding in 'Missing custom license directory' 'Package contains reference to \$srcdir' \
                 'Invalid syntax' 'No ELF files and not an "any" package' \
                 'Directory (usr/share/doc) is empty'; do
    if grep -qi "$finding" <<< "$NAMCAP"; then
      echo "FAIL: namcap reports for $pkg: $finding" >&2
      exit 1
    fi
  done
done

# What every one of them must leave on the system, whichever it is.
verify_installed() {
  local pkg="$1" desktop="/usr/share/applications/${APP_ID}.desktop" info
  info="$(pacman -Qi "$pkg")"
  echo "$info"
  if [ "$pkg" != openemux ]; then
    grep -Eq '^Provides +: openemux$' <<< "$info" || {
      echo "FAIL: $pkg does not provide openemux" >&2; exit 1; }
    grep -Eq '^Conflicts With +: openemux$' <<< "$info" || {
      echo "FAIL: $pkg does not conflict with openemux" >&2; exit 1; }
  fi
  test -x /usr/bin/openemux
  test -f "$desktop"
  grep -q '^Exec=/usr/bin/openemux$' "$desktop"
  desktop-file-validate "$desktop"
  test -f "/usr/share/icons/hicolor/512x512/apps/${APP_ID}.png"
  appstreamcli validate --no-net "/usr/share/metainfo/${APP_ID}.metainfo.xml"
  test -f "/usr/share/licenses/$pkg/LICENSE"
  test -f "/usr/share/licenses/$pkg/copyright"
  test ! -e /usr/share/doc/openemux
}

# The two native layouts run the app from /opt/openemux.
import_smoke() {
  OPENEMUX_PROJECT_ROOT=/opt/openemux PYTHONPATH=/opt/openemux/src python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: F401
import openemux
from openemux.ui import window  # noqa: F401  (the full UI import chain)

print("import OK, version", openemux.__version__)
PY
}

echo "==> install test: openemux (resolves retroarch through pacman)"
# -Syu, not -Sy: retroarch and fuse2 come from today's repositories, and
# installing them over the pinned image's older libraries is a partial upgrade.
pacman -Syu --noconfirm >/dev/null
pacman -U --noconfirm "${PKG_PATH[openemux]}"
verify_installed openemux
command -v retroarch
retroarch --version
test ! -e /opt/openemux/vendors/RetroArch-Linux-x86_64
import_smoke

# Swapping is what the conflicts are for. --ask=4 answers "remove the
# conflicting package?" with yes, which --noconfirm alone answers with no.
swap_to() {
  local pkg="$1" previous="$2"
  echo "==> swap: $previous -> $pkg"
  pacman -U --noconfirm --ask=4 "${PKG_PATH[$pkg]}"
  # By exact name: `pacman -Q openemux` also answers for whatever provides it.
  local installed
  installed="$(pacman -Qq)"
  if grep -qx "$previous" <<< "$installed"; then
    echo "FAIL: $previous is still installed next to $pkg" >&2
    exit 1
  fi
  verify_installed "$pkg"
}

swap_to openemux-bin openemux
# The release package's own RetroArch, runnable where it was put.
/opt/openemux/vendors/RetroArch-Linux-x86_64/usr/bin/retroarch --version
import_smoke

swap_to openemux-appimage openemux-bin
test -x /opt/openemux-appimage/OpenEmux.AppImage
test "$(readlink /usr/bin/openemux)" = /opt/openemux-appimage/OpenEmux.AppImage
# The bundle is the AppImage alone: nothing of the native layout is left.
test ! -e /opt/openemux/src/openemux/main.py
# Its runtime starts: reading its own offset needs no FUSE in the container.
/opt/openemux-appimage/OpenEmux.AppImage --appimage-offset

swap_to openemux openemux-appimage
test ! -e /opt/openemux-appimage

echo "==> the removal must leave nothing of ours behind"
pacman -Rns --noconfirm openemux >/dev/null
for path in /usr/bin/openemux /opt/openemux/src/openemux/main.py /opt/openemux-appimage \
            /usr/share/applications/${APP_ID}.desktop \
            /usr/share/metainfo/${APP_ID}.metainfo.xml \
            /usr/share/licenses/openemux /usr/share/licenses/openemux-bin \
            /usr/share/licenses/openemux-appimage; do
  if [ -e "$path" ]; then
    echo "FAIL: $path survived the removal" >&2
    exit 1
  fi
done

echo "==> the files for the AUR: ${OUT}/<package>/{PKGBUILD,.SRCINFO}"
for pkg in "${PACKAGES[@]}"; do
  ls -l "$OUT/$pkg/PKGBUILD" "$OUT/$pkg/.SRCINFO"
done

if [ "$MODE" = check ]; then
  echo "==> ALL AUR RELEASE CHECKS PASSED"
  exit 0
fi

REPOS=/tmp/aurrepos
rm -rf "$REPOS"
mkdir -p "$REPOS"
if [ "$MODE" = publish ]; then
  pacman -S --noconfirm --needed openssh >/dev/null
  install -d -m 700 /root/.ssh
  printf '%s\n' "$AUR_SSH_PRIVATE_KEY" > /root/.ssh/aur
  chmod 600 /root/.ssh/aur
  printf '%s\n' "$AUR_HOST_KEY" > /root/.ssh/known_hosts
  export GIT_SSH_COMMAND="ssh -i /root/.ssh/aur -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
fi

PUSHED=0
for pkg in "${PACKAGES[@]}"; do
  echo "==> ${pkg}: the AUR repository against ${TAG}"
  if [ "$MODE" = publish ]; then
    git clone -q "ssh://aur@aur.archlinux.org/${pkg}.git" "$REPOS/$pkg"
  else
    # Read-only and anonymous: a dry run needs no account. A package the AUR
    # does not have yet clones as an empty repository.
    git clone -q "https://aur.archlinux.org/${pkg}.git" "$REPOS/$pkg"
  fi
  cp "$OUT/$pkg/PKGBUILD" "$OUT/$pkg/.SRCINFO" "$REPOS/$pkg/"
  git -C "$REPOS/$pkg" add PKGBUILD .SRCINFO
  if git -C "$REPOS/$pkg" diff --cached --quiet; then
    echo "$pkg: the AUR already has these files; nothing to change"
    continue
  fi
  git -C "$REPOS/$pkg" --no-pager diff --cached --stat
  git -C "$REPOS/$pkg" --no-pager diff --cached
  if [ "$MODE" = publish ]; then
    git -C "$REPOS/$pkg" -c user.name="Guilherme Feitoza" \
      -c user.email="guilhermefeitosa66@users.noreply.github.com" \
      commit -q -m "Update to ${VERSION}-${PKGREL}"
    git -C "$REPOS/$pkg" push -q origin HEAD:master
    echo "$pkg: pushed ${VERSION}-${PKGREL} to the AUR"
    PUSHED=$((PUSHED + 1))
  fi
done

if [ "$MODE" = dry-run ]; then
  echo "==> DRY RUN: nothing was pushed to the AUR"
else
  echo "==> PUBLISHED: ${PUSHED} package(s) pushed to the AUR"
fi

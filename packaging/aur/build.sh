#!/usr/bin/env bash
# Builds packaging/aur/openemux-git/PKGBUILD the way the AUR would, installs it,
# checks it and removes it again -- then writes the PKGBUILD and .SRCINFO to
# push to the AUR (issue #986). Runs *inside* the Arch build image; launch it
# through `packaging/build.sh aur` (or `make aur-git`), not directly.
#
# The recipe clones GitHub's `develop`, which is not the code under test. The
# host side (packaging/build.sh) mounts a bare clone of the checkout's HEAD at
# /src/openemux.git, and the copy makepkg sees here points at that commit
# instead. Only the `source` line differs: the copy written for the AUR is the
# tracked recipe, untouched but for the version.
set -euo pipefail

trap 'sh packaging/common/hand_back.sh || true' EXIT

RECIPE=packaging/aur/openemux-git/PKGBUILD
SRC_REPO=/src/openemux.git
OUT=build/aur/openemux-git
BUILDDIR=/tmp/aurbuild

test -d "$SRC_REPO" || {
  echo "FAIL: no bare clone at $SRC_REPO; run this through packaging/build.sh aur" >&2
  exit 1
}

COMMIT="$(git --git-dir="$SRC_REPO" rev-parse HEAD)"
echo "==> building openemux-git from commit ${COMMIT}"

rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR"
# A copy, so the bind mount stays read-only and the clone is builder's: git
# refuses to read a repository owned by somebody else.
cp -a "$SRC_REPO" "$BUILDDIR/openemux.git"

GITHUB_SOURCE='git+https://github.com/guilhermefeitosa66/OpenEmux.git#branch=$_branch'
grep -qF "$GITHUB_SOURCE" "$RECIPE" || {
  echo "FAIL: $RECIPE no longer clones $GITHUB_SOURCE" >&2
  exit 1
}
sed "s|${GITHUB_SOURCE}|git+file://${BUILDDIR}/openemux.git#commit=${COMMIT}|" \
  "$RECIPE" > "$BUILDDIR/PKGBUILD"
grep -qF "#commit=${COMMIT}" "$BUILDDIR/PKGBUILD"

chown -R builder:builder "$BUILDDIR"
# --nodeps: the image already carries every runtime dependency but retroarch,
# which the install test below resolves through pacman. -f so a rebuild in a
# warm container overwrites.
runuser -u builder -- bash -lc "cd '$BUILDDIR' && makepkg -f --nodeps --noconfirm"

PKG_PATH="$(find "$BUILDDIR" -maxdepth 1 -name 'openemux-git-*.pkg.tar.*' -print -quit)"
test -n "$PKG_PATH" || { echo "FAIL: makepkg produced no package" >&2; exit 1; }
PKGINFO="$(pacman -Qip "$PKG_PATH")"
echo "$PKGINFO"

# The version pkgver() computed: <__version__>.r<commit count>.g<short sha>.
APP_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/openemux/__init__.py)"
PKGVER="$(sed -n 's/^pkgver=//p' "$BUILDDIR/PKGBUILD")"
case "$PKGVER" in
  "${APP_VERSION}.r"*".g${COMMIT:0:7}") echo "pkgver: $PKGVER" ;;
  *) echo "FAIL: pkgver() gave '$PKGVER'" >&2; exit 1 ;;
esac

echo "==> namcap: the findings that would break an install"
NAMCAP="$(namcap "$PKG_PATH" || true)"
echo "$NAMCAP"
for finding in 'Missing custom license directory' 'Package contains reference to \$srcdir' \
               'Invalid syntax'; do
  if grep -qi "$finding" <<< "$NAMCAP"; then
    echo "FAIL: namcap reports: $finding" >&2
    exit 1
  fi
done

echo "==> install test (resolves retroarch through pacman)"
pacman -Sy --noconfirm >/dev/null
pacman -U --noconfirm "$PKG_PATH"

echo "==> verify the installed package"
INSTALLED="$(pacman -Qi openemux-git)"
grep -Eq '^Provides +: openemux$' <<< "$INSTALLED" || {
  echo "FAIL: openemux-git does not provide openemux" >&2; exit 1; }
grep -Eq '^Conflicts With +: openemux$' <<< "$INSTALLED" || {
  echo "FAIL: openemux-git does not conflict with openemux" >&2; exit 1; }
test -x /usr/bin/openemux
# The emulator is the distribution's, found on PATH; nothing is vendored.
command -v retroarch
test ! -e /opt/openemux/vendors/RetroArch-Linux-x86_64
test ! -e /opt/openemux/vendors/RetroArch-Linux-aarch64
test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
grep -q '^Exec=/usr/bin/openemux$' \
  /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png
appstreamcli validate --no-net \
  /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
test -f /usr/share/licenses/openemux-git/LICENSE
test -f /usr/share/licenses/openemux-git/copyright
test ! -e /usr/share/doc/openemux

echo "==> import smoke test, and the launcher finds the system RetroArch"
OPENEMUX_PROJECT_ROOT=/opt/openemux PYTHONPATH=/opt/openemux/src python3 - <<'PY'
import shutil

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: F401
import openemux
from openemux.ui import window  # noqa: F401  (the full UI import chain)

print("import OK, version", openemux.__version__)
retroarch = shutil.which("retroarch")
if not retroarch:
    raise SystemExit("FAIL: no retroarch on PATH")
print("retroarch:", retroarch)
PY

echo "==> the removal must leave nothing of ours behind"
pacman -Rns --noconfirm openemux-git >/dev/null
for path in /usr/share/licenses/openemux-git /usr/bin/openemux \
            /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop \
            /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml \
            /opt/openemux/src/openemux/main.py; do
  if [ -e "$path" ]; then
    echo "FAIL: $path survived the removal" >&2
    exit 1
  fi
done

echo "==> the files to push to the AUR: ${OUT}/"
# The tracked recipe, GitHub source and all, with the version just built so
# the AUR page shows something real. Never the local copy above.
rm -rf "$OUT"
mkdir -p "$OUT"
sed "s/^pkgver=.*/pkgver=${PKGVER}/" "$RECIPE" > "$OUT/PKGBUILD"
chown -R builder:builder "$OUT"
runuser -u builder -- bash -lc "cd '$PWD/$OUT' && makepkg --printsrcinfo > .SRCINFO"
SRCINFO="$(cat "$OUT/.SRCINFO")"
for line in 'pkgbase = openemux-git' "pkgver = ${PKGVER}" 'provides = openemux' \
            'conflicts = openemux' 'depends = retroarch' \
            'source = openemux::git+https://github.com/guilhermefeitosa66/OpenEmux.git#branch=develop'; do
  grep -qF "$line" <<< "$SRCINFO" || { echo "FAIL: .SRCINFO lacks '$line'" >&2; exit 1; }
done
if grep -q 'file://' <<< "$SRCINFO"; then
  echo "FAIL: .SRCINFO points at the local clone" >&2
  exit 1
fi
cat "$OUT/.SRCINFO"

echo "==> ALL AUR CHECKS PASSED"

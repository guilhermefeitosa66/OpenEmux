#!/usr/bin/env bash
# Builds the OpenEmux Arch package and smoke-tests it. Runs *inside* the
# container defined by packaging/docker/arch.Dockerfile -- launch it through
# `packaging/build.sh arch` (or `make arch`), not directly on the host.
#
# makepkg refuses to run as root, so the actual build runs as the unprivileged
# `builder` user the image creates; the install test needs root and runs back
# out here.
set -euo pipefail

# Hand the tree back even when a check fails: this runs as root on a bind mount
# of the developer's checkout, so anything it writes is theirs to keep.
trap 'sh packaging/common/hand_back.sh || true' EXIT

VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
# Derived, not declared -- the same rule the .deb takes from dpkg and the .rpm
# from rpmbuild. The vendored RetroArch is per-architecture and the package
# must carry only its own (issue #119).
CARCH="$(uname -m)"
case "$CARCH" in
  x86_64|aarch64) ;;
  *) echo "unsupported architecture: $CARCH" >&2; exit 1 ;;
esac
echo "==> building openemux ${VERSION} Arch package for ${CARCH}"

desktop-file-validate packaging/common/openemux.desktop

BUILDDIR=/tmp/archbuild
rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR"

# The build inputs, and only those: an explicit list cannot pick up a `.env`,
# a `dist/` or a stray build artifact the way a wholesale copy of the tree can.
echo "==> packing ${BUILDDIR}/openemux-${VERSION}.tar.gz"
tar --create --gzip --file "$BUILDDIR/openemux-${VERSION}.tar.gz" \
    --transform "s,^,openemux-${VERSION}/," \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
    LICENSE README.md pyproject.toml requirements.lock packaging src vendors

# `pkgver` is a placeholder in the tracked PKGBUILD so the version lives only
# in src/openemux/__init__.py. Resolving it into the copy makepkg sees is what
# keeps the recipe self-contained: the result is a PKGBUILD that builds on a
# real Arch box, or in the AUR, with no OpenEmux checkout in sight.
sed "s/^pkgver=.*/pkgver=${VERSION}/" packaging/arch/PKGBUILD \
  > "$BUILDDIR/PKGBUILD"
grep -q "^pkgver=${VERSION}$" "$BUILDDIR/PKGBUILD"

chown -R builder:builder "$BUILDDIR"
# --nodeps: the container installs the runtime dependencies itself for the
# install test below, and makepkg's own check would otherwise pull the entire
# GTK stack a second time. -f so a rebuild in a warm container overwrites.
runuser -u builder -- bash -lc "cd '$BUILDDIR' && makepkg -f --nodeps --noconfirm"

mkdir -p dist
PKG_PATH="$(find "$BUILDDIR" -maxdepth 1 -name "openemux-${VERSION}-*.pkg.tar.*" -print -quit)"
test -n "$PKG_PATH" || { echo "FAIL: makepkg produced no package" >&2; exit 1; }
cp "$PKG_PATH" dist/
PKG_NAME="$(basename "$PKG_PATH")"
echo "==> built: dist/${PKG_NAME}"
pacman -Qip "dist/${PKG_NAME}"

echo "==> namcap: the packaging findings that matter here"
# Collected, then matched. Three findings are this package's design:
#
#   elffile-in-questionable-dir / file-in-non-standard-dir
#       /opt is where a self-contained app that runs from its own project root
#       belongs, and where the .deb and .rpm already put it.
#   elffile-with-* / insecure-rpath
#       RUNPATH=$ORIGIN is what makes the vendored RetroArch relocatable -- it
#       is how the binary finds the 56 libraries beside it (issue #328).
#   depends-by-namcap-sight
#       namcap reads dependencies off ELF linkage, and this package's only
#       ELFs are somebody else's emulator; the real dependency list is Python
#       imports, which it cannot see.
NAMCAP="$(namcap "dist/${PKG_NAME}" || true)"
BY_DESIGN='questionable-dir|non-standard-dir|insecure-rpath|rpath|depends-by-namcap-sight|dependency detected and not included|elffile'
echo "by design, suppressed: $(grep -Eic "$BY_DESIGN" <<< "$NAMCAP" || true) lines"
REST="$(grep -Eiv "$BY_DESIGN" <<< "$NAMCAP" || true)"
echo "$REST"
# A missing or malformed .PKGINFO field is what actually breaks an install.
for finding in 'Missing custom license directory' 'Package contains reference to \$srcdir' \
               'Invalid syntax'; do
  if grep -qi "$finding" <<< "$NAMCAP"; then
    echo "FAIL: namcap reports: $finding" >&2
    grep -i "$finding" <<< "$NAMCAP" >&2
    exit 1
  fi
done

echo "==> install test (resolves depends via pacman)"
pacman -Sy --noconfirm >/dev/null
pacman -U --noconfirm "./dist/${PKG_NAME}"

echo "==> verify installed files"
test -x /usr/bin/openemux
# x86_64 bundles RetroArch; aarch64 has none to bundle and depends on the
# distribution's retroarch instead, which pacman has just resolved (issue #119).
if [ "$CARCH" = "x86_64" ]; then
  RETROARCH_DIR=/opt/openemux/vendors/RetroArch-Linux-x86_64
  test -x "$RETROARCH_DIR/usr/bin/retroarch"
  # The tree is only portable because the binary finds its own 56 libraries
  # through RUNPATH=$ORIGIN/../lib, and that has to survive being packaged and
  # installed somewhere else (issue #328). Checked with ldd rather than by
  # running it: RetroArch also needs libGL, libjack and the host's audio stack,
  # which a build container has no reason to install.
  #
  # This is also what `options=('!strip')` in the PKGBUILD protects: makepkg
  # strips and rewrites every ELF it finds by default, which would rewrite this
  # RUNPATH the same way appimage-builder once did.
  LDD="$(ldd "$RETROARCH_DIR/usr/bin/retroarch" || true)"
  case "$LDD" in
    # What the loader prints is the RUNPATH as written -- $ORIGIN is the
    # directory holding the binary, so the resolved path keeps the `bin/..`.
    *"$RETROARCH_DIR/usr/bin/../lib/"*) ;;
    *)
      echo "FAIL: the installed RetroArch does not resolve its bundled libraries" >&2
      echo "$LDD" >&2
      exit 1
      ;;
  esac
  echo "the vendored RetroArch resolves its own libraries from $RETROARCH_DIR"
else
  test ! -e /opt/openemux/vendors/RetroArch-Linux-x86_64
  PKG_DEPENDS="$(pacman -Qi openemux)"
  case "$PKG_DEPENDS" in
    *retroarch*) ;;
    *) echo "FAIL: the aarch64 package does not depend on retroarch" >&2; exit 1 ;;
  esac
fi
test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
appstreamcli validate --no-net \
  /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
# PATH-relative Exec would let a ~/.local/bin shadow (AppImage-manager symlink)
# hijack the menu icon; the packaged entry must be explicit (issue #256).
grep -q '^Exec=/usr/bin/openemux$' \
  /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
grep -q '^TryExec=/usr/bin/openemux$' \
  /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png
test -f /usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png

echo "==> the licence must be where Arch keeps it"
test -f /usr/share/licenses/openemux/LICENSE
test -f /usr/share/licenses/openemux/copyright
test ! -e /usr/share/doc/openemux

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
# Not an import: the loaders are separate packages, and a missing one shows up
# only as a blank card and a "cover decode failed" line in the log. WebP is
# what the libretro thumbnail sync downloads (issue #251); png/jpeg carry
# local art and svg is every symbolic icon in the UI.
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
PATH=/tmp/fakebin:$PATH timeout 20 openemux --help >/tmp/launch.log 2>&1 || true
if grep -q "fake python3" /tmp/launch.log; then
  echo "FAIL: launcher used the shadowing python3" >&2
  cat /tmp/launch.log >&2
  exit 1
fi
echo "launcher resolved a working interpreter"

echo "==> the removal must leave nothing of ours behind"
pacman -Rns --noconfirm openemux >/dev/null
for path in /usr/share/licenses/openemux /usr/bin/openemux \
            /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop \
            /usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png \
            /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml \
            /opt/openemux/vendors /opt/openemux/src/openemux/main.py; do
  if [ -e "$path" ]; then
    echo "FAIL: $path survived the removal" >&2
    exit 1
  fi
done
# /opt/openemux itself may survive: this container ran the app as root, which
# writes __pycache__ next to the sources, and pacman does not remove files it
# does not own. Every path the package installed is gone.
echo "removal is clean"

echo "==> ALL ARCH CHECKS PASSED"

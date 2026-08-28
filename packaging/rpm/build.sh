#!/usr/bin/env bash
# Builds the OpenEmux .rpm and smoke-tests it. Runs *inside* the container
# defined by packaging/docker/rpm.Dockerfile -- launch it through
# `packaging/build.sh rpm` (or `make rpm`), not directly on the host.
#
# The spec is built from a source tarball, like any other RPM: `%prep` unpacks
# it and `%install` runs the staging script from there. It used to be driven
# with `--define "repo_root /work"` and no Source0/%prep at all, which meant no
# SRPM could be produced and the package could not be rebuilt outside this
# exact Docker bind mount -- so `mock`, COPR, Fedora review and a maintainer on
# a real Fedora box all had nowhere to start (issue #252).
set -euo pipefail

VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
echo "==> building openemux ${VERSION} .rpm"

desktop-file-validate packaging/common/openemux.desktop

TOPDIR=/tmp/rpmbuild
rm -rf "$TOPDIR"
mkdir -p "$TOPDIR"/{SOURCES,SPECS}

# The build inputs, and only those: an explicit list cannot pick up a `.env`,
# a `dist/` or a stray build artifact the way a wholesale copy of the tree can.
echo "==> packing ${TOPDIR}/SOURCES/openemux-${VERSION}.tar.gz"
tar --create --gzip --file "$TOPDIR/SOURCES/openemux-${VERSION}.tar.gz" \
    --transform "s,^,openemux-${VERSION}/," \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
    LICENSE README.md pyproject.toml requirements.lock packaging src vendors

# `Version:` is templated in the tracked spec so the version lives only in
# src/openemux/__init__.py. Resolving it into the copy rpmbuild sees is what
# makes the resulting SRPM self-contained -- a `--define` would not survive
# into it, and `rpmbuild --rebuild` would then hit an undefined macro.
sed "s/^Version:.*/Version:        ${VERSION}/" \
  packaging/rpm/openemux.spec > "$TOPDIR/SPECS/openemux.spec"
grep -q "^Version:        ${VERSION}$" "$TOPDIR/SPECS/openemux.spec"

rpmbuild -ba "$TOPDIR/SPECS/openemux.spec" --define "_topdir $TOPDIR"

mkdir -p dist
RPM_PATH="$(find "$TOPDIR/RPMS" -name "openemux-${VERSION}-*.rpm" -print -quit)"
cp "$RPM_PATH" dist/
RPM_NAME="$(basename "$RPM_PATH")"
echo "==> built: dist/${RPM_NAME}"
rpm -qip "dist/${RPM_NAME}"

echo "==> the SRPM must rebuild with no OpenEmux checkout in sight"
# The point of Source0/%prep: this is `mock`, COPR and Fedora review in
# miniature. A different _topdir and a different working directory, so nothing
# can reach /work by accident.
SRPM_PATH="$(find "$TOPDIR/SRPMS" -name "openemux-${VERSION}-*.src.rpm" -print -quit)"
if [ -z "$SRPM_PATH" ]; then
  echo "FAIL: rpmbuild -ba produced no SRPM" >&2
  exit 1
fi
echo "==> rebuilding $(basename "$SRPM_PATH")"
( cd /tmp && rpmbuild --rebuild --define "_topdir /tmp/rpmbuild-verify" "$SRPM_PATH" )
# -quit rather than `| head -1`: head exits on the first line and SIGPIPEs
# find, and that shape kills a build outright the moment it is used outside a
# command substitution (issue #119).
test -n "$(find /tmp/rpmbuild-verify/RPMS -name "openemux-${VERSION}-*.rpm" -print -quit)"
echo "the SRPM rebuilds standalone"

echo "==> rpmlint: the Fedora-review blockers must be gone"
# The whole report is noisy and not all of it is actionable here; these are the
# findings issue #252 identified, each of which is an error for Fedora review.
rpmlint "dist/${RPM_NAME}" "$SRPM_PATH" > /tmp/rpmlint.txt 2>&1 || true
# Three findings are this package's design rather than defects, and each of
# them repeats per file, so together they bury everything worth reading:
#
#   dir-or-file-in-opt          /opt is where a self-contained app that runs
#                               from its own project root belongs -- hundreds
#                               of lines, one per packaged path.
#   binary-or-shlib-defines-rpath  RUNPATH=$ORIGIN is what makes the vendored
#                               RetroArch relocatable -- it is how the binary
#                               finds the 56 libraries beside it (issue #328).
#   unstripped-binary-or-object the __brp_strip overrides at the top of the
#                               spec are deliberate: the emulator is
#                               redistributed unmodified, byte for byte.
#   shared-library-not-executable  the same reason, from the other end: 0644 is
#                               the mode libretro shipped those 56 libraries
#                               with, and dlopen does not care. chmod-ing them
#                               would mean the tree is no longer what upstream
#                               published, which the manifest's tree_sha256
#                               exists to state.
#
# Counted first, then listed, so a new *kind* of finding is visible even when
# it is one line among a thousand. This package ships no libraries of its own,
# so the last two can only ever be about the vendored emulator.
BY_DESIGN='dir-or-file-in-opt|binary-or-shlib-defines-rpath|unstripped-binary-or-object'
BY_DESIGN="$BY_DESIGN|shared-library-not-executable"
REST="$(grep -Ev "$BY_DESIGN" /tmp/rpmlint.txt || true)"
echo "by design, suppressed: $(grep -Ec "$BY_DESIGN" /tmp/rpmlint.txt || true) lines"
sed -n 's/.*: [EW]: \([a-z0-9-]*\).*/\1/p' <<< "$REST" | sort | uniq -c | sort -rn
tail -30 <<< "$REST"
for finding in incoherent-changelog-date no-blank-line-in-changelog \
               dir-or-file-in-usr-share-doc buildarch-instead-of-exclusivearch-tag; do
  if grep -q "$finding" /tmp/rpmlint.txt; then
    echo "FAIL: rpmlint still reports $finding" >&2
    grep "$finding" /tmp/rpmlint.txt >&2
    exit 1
  fi
done
echo "no changelog or /usr/share/doc findings"

echo "==> install test (resolves Requires via dnf)"
dnf install -y "./dist/${RPM_NAME}" >/dev/null

echo "==> verify installed files"
test -x /usr/bin/openemux
# x86_64 bundles RetroArch; aarch64 has none to bundle and depends on the
# distribution's retroarch instead, which dnf has just resolved (issue #119).
if [ "$(uname -m)" = "x86_64" ]; then
  RETROARCH_DIR=/opt/openemux/vendors/RetroArch-Linux-x86_64
  test -x "$RETROARCH_DIR/usr/bin/retroarch"
  # The tree is only portable because the binary finds its own 56 libraries
  # through RUNPATH=$ORIGIN/../lib, and that has to survive being packaged and
  # installed somewhere else (issue #328). Checked with ldd rather than by
  # running it: RetroArch also needs libGL, libjack and the host's audio stack,
  # which a build container has no reason to install.
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
  # Not `command -v retroarch`: the dependency is a Recommends, because
  # RetroArch lives in RPM Fusion rather than in Fedora, and this container has
  # only Fedora. What must hold is that the package *asks* for it.
  # Collected first, then matched. `rpm -q ... | grep -q` exits on the first
  # line and SIGPIPEs rpm, which under `set -o pipefail` makes the pipeline
  # report failure -- so the check would fail on a package that does declare it.
  RECOMMENDS="$(rpm -q --recommends openemux)"
  case "$RECOMMENDS" in
    *retroarch*) ;;
    *) echo "the aarch64 package does not recommend retroarch" >&2; exit 1 ;;
  esac
fi
test -f /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml
# PATH-relative Exec would let a ~/.local/bin shadow (AppImage-manager
# symlink) hijack the menu icon; the packaged entry must be explicit.
grep -q '^Exec=/usr/bin/openemux$' /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
test -f /usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png
test -f /usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png

echo "==> the licence must be installed, and its directory owned"
# `%license /usr/share/doc/openemux/copyright` listed a file in a directory the
# package did not own: `rpm -qf` found no owner, `dnf remove` left it behind
# and rpmlint raised dir-or-file-in-usr-share-doc (issue #252).
test -f /usr/share/licenses/openemux/LICENSE
rpm -qf /usr/share/licenses/openemux >/dev/null
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

echo "==> the erase must leave no directory of ours orphaned"
dnf remove -y openemux >/dev/null
for path in /usr/share/doc/openemux /usr/share/licenses/openemux /usr/bin/openemux \
            /usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop \
            /usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png \
            /usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml \
            /opt/openemux/vendors /opt/openemux/src/openemux/main.py; do
  if [ -e "$path" ]; then
    echo "FAIL: $path survived the erase" >&2
    exit 1
  fi
done
# /opt/openemux itself may survive: this container ran the app as root, which
# writes __pycache__ next to the sources, and rpm does not remove files it does
# not own. Every path the package installed is gone.
echo "erase is clean"

echo "==> ALL RPM CHECKS PASSED"
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" dist 2>/dev/null || true

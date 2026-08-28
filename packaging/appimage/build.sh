#!/usr/bin/env bash
# Builds the OpenEmux AppImage. Runs *inside* the container defined by
# packaging/docker/appimage.Dockerfile -- launch it through
# `packaging/build.sh appimage` (or `make appimage`), not directly on the host.
set -euo pipefail

# Hand the tree back even when a check fails, so a failed run does not leave
# root-owned files behind. Not a list of paths: see packaging/common/hand_back.sh
# for what naming them by hand kept missing.
trap 'sh packaging/common/hand_back.sh || true' EXIT

# Everything that varies with the architecture, derived from the host. The
# AppDir is assembled out of foreign-arch debs and the result only runs on the
# machine type it was built for, so host == target here; packaging/build.sh
# refuses a mismatch before getting this far (issue #119).
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  TRIPLET=x86_64-linux-gnu ;;
  aarch64) TRIPLET=aarch64-linux-gnu ;;
  *) echo "unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

SOURCE_RECIPE=packaging/appimage/AppImageBuilder.yml
# One recipe, rendered per architecture: four values differ and ninety lines of
# package list do not, and two copies of that list is a package added to one of
# them. On x86_64 the render is byte-identical to the file in git.
RECIPE="$PWD/build/appimage/AppImageBuilder.${ARCH}.yml"
python3 packaging/appimage/arch_recipe.py "$SOURCE_RECIPE" --arch "$ARCH" --output "$RECIPE"

APPDIR_LIB="$PWD/AppDir/usr/lib/$TRIPLET"
# The static-FUSE3 AppImage runtime baked into the build image (see phase 2).
RUNTIME_SRC="/opt/appimage-runtime-$ARCH"

# The recipe is the only place the version is duplicated -- the .deb, .rpm and
# Flatpak all derive it from src/openemux/__init__.py. A forgotten bump
# produced OpenEmux-<old>-x86_64.AppImage beside correctly versioned siblings,
# and it went into dist/, into SHA256SUMS and into the GitHub release with
# every check passing (issue #255).
VERSION="$(sed -n 's/.*"\(.*\)".*/\1/p' src/openemux/__init__.py)"
if ! grep -q "^    version: \"${VERSION}\"$" "$SOURCE_RECIPE"; then
  echo "FAIL: $SOURCE_RECIPE does not carry version \"${VERSION}\"." >&2
  echo "src/openemux/__init__.py says ${VERSION}; the recipe says:" >&2
  grep -n '^    version:' "$SOURCE_RECIPE" >&2
  exit 1
fi
echo "==> building openemux ${VERSION} AppImage for ${ARCH}"

echo "==> phase 1: assemble the AppDir (no packaging yet)"
appimage-builder --recipe "$RECIPE" --skip-tests --skip-appimage

# appimage-builder rewrites every PT_INTERP to a *relative* path, so the ELF
# loader is looked up from the working directory -- $APPDIR, or runtime/compat
# where its exec hooks chdir. It then links the loader into both runtimes
# itself... on x86_64. On aarch64 it does not: its glibc file list matches
# `ld-linux-x86-64.so*` and `ld-linux.so.2` and nothing that matches
# `ld-linux-aarch64.so.1`, so the loader stays under usr/lib, the relative
# `lib/ld-linux-aarch64.so.1` resolves to nothing, and the bundle dies with
# "usr/bin/python3: not found" -- a file that is right there (issue #119).
#
# Derived rather than hardcoded: read the interpreter the bundled python
# actually asks for and make that exact relative path resolve from both
# directories. On x86_64 the recipe's own lib64 links already satisfy it and
# this finds nothing to do.
echo "==> ensuring the bundled interpreter's loader resolves"
PYTHON_BIN="$(readlink -f AppDir/usr/bin/python3)"
test -f "$PYTHON_BIN" || { echo "ERROR: no bundled python3 in the AppDir." >&2; exit 1; }
INTERP="$(readelf -l "$PYTHON_BIN" | sed -n 's/.*program interpreter: \(.*\)]/\1/p')"
test -n "$INTERP" || { echo "ERROR: $PYTHON_BIN declares no ELF interpreter." >&2; exit 1; }
echo "    interpreter: $INTERP"
case "$INTERP" in
  /*)
    # Absolute: the host's own loader, nothing for us to place.
    echo "    absolute; nothing to link"
    ;;
  *)
    # -quit, not `| head -1`: head exits on the first line and SIGPIPEs find,
    # which under `set -o pipefail` fails the pipeline and, under `set -e`,
    # kills the build -- exit 141, with the diagnostics never printed. The
    # suite has a guard against this shape for `grep -q`; it covers `head` too
    # now, because this is where it bit.
    LOADER="$(find AppDir/usr/lib AppDir/lib AppDir/usr/lib64 AppDir/lib64 \
                   AppDir/runtime -name "$(basename "$INTERP")" \
                   \( -type f -o -type l \) -print -quit 2>/dev/null || true)"
    test -n "$LOADER" || {
      echo "ERROR: $(basename "$INTERP") is nowhere in the AppDir." >&2
      exit 1
    }
    echo "    loader:      $LOADER"
    for base in AppDir AppDir/runtime/compat; do
      target="$base/$INTERP"
      if [ -e "$target" ]; then
        echo "    ok:          $target"
        continue
      fi
      mkdir -p "$(dirname "$target")"
      ln -sfn "$(realpath --relative-to="$(dirname "$target")" "$LOADER")" "$target"
      echo "    linked:      $target -> $(readlink "$target")"
    done
    ;;
esac
# Both, because openemux-run.sh cds to $APPDIR while the exec hooks cd to
# runtime/compat, and the bundle has to start either way.
for base in AppDir AppDir/runtime/compat; do
  case "$INTERP" in /*) continue ;; esac
  test -e "$base/$INTERP" || {
    echo "ERROR: $base/$INTERP still does not resolve." >&2
    exit 1
  }
done

# Regenerate the gdk-pixbuf loaders cache from the *bundled* loaders. The cache
# written during bundling omits libpixbufloader-svg.so, and without it every
# symbolic icon in the UI and every SVG asset fails to render.
# LD_LIBRARY_PATH points at the bundled libs so the SVG and WebP loaders (which
# need librsvg/cairo/libxml2/libwebp) can be dlopen-ed while querying.
GPB_DIR="$APPDIR_LIB/gdk-pixbuf-2.0"
QUERY_BIN="/usr/lib/$TRIPLET/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders"
if [ ! -d "$GPB_DIR/2.10.0/loaders" ] || [ ! -x "$QUERY_BIN" ]; then
  echo "ERROR: gdk-pixbuf query tool or bundled loaders dir not found." >&2
  exit 1
fi

echo "==> regenerating gdk-pixbuf loaders.cache from the bundled loaders"
tmp_cache="$(mktemp)"
LD_LIBRARY_PATH="$APPDIR_LIB:$PWD/AppDir/lib/$TRIPLET" \
GDK_PIXBUF_MODULEDIR="$GPB_DIR/2.10.0/loaders" \
  "$QUERY_BIN" > "$tmp_cache"
# Strip the build-time absolute loader dir so entries become bare filenames; at
# runtime GDK_PIXBUF_MODULEDIR ($APPDIR/...) resolves them. Leaving the build
# path in makes every loader unreachable on the user's machine.
sed -i "s|$GPB_DIR/2.10.0/loaders/||g" "$tmp_cache"
# webp as well as svg: the cache is regenerated from the bundled loaders,
# and a webp loader that failed to be queried is a blank card for every
# synced cover (issue #251).
for required in svg webp; do
  if ! grep -q "$required" "$tmp_cache"; then
    echo "ERROR: regenerated loaders.cache is missing the $required loader." >&2
    rm -f "$tmp_cache"
    exit 1
  fi
done
mv "$tmp_cache" "$GPB_DIR/2.10.0/loaders.cache"
echo "loaders.cache: $(grep -c '\.so' "$GPB_DIR/2.10.0/loaders.cache") loaders registered"

# The cartridge frames are rendered through the Rsvg typelib; if it did not get
# bundled the grid silently falls back to plain covers, so fail loudly here.
test -f "$APPDIR_LIB/girepository-1.0/Rsvg-2.0.typelib" \
  || { echo "ERROR: Rsvg-2.0.typelib missing from the bundle." >&2; exit 1; }

# AppStream metainfo: what an AppImage integrator (appimaged, AppImageLauncher,
# GearLever) hands to the software centre when it installs the bundle. Missing
# from every format but the Flatpak until issue #253; validated by the .deb,
# .rpm and Flatpak builds, which have appstreamcli.
test -f AppDir/usr/share/metainfo/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml \
  || { echo "ERROR: AppStream metainfo missing from the bundle." >&2; exit 1; }

# The vendored RetroArch, staged now that appimage-builder has finished with
# the AppDir -- and deliberately not by the recipe, which runs before it.
#
# appimage-builder patches every ELF it finds: PT_INTERP to a relative loader
# and RUNPATH to the bundle's own library paths. That was harmless while the
# vendored RetroArch was one opaque image, and is not now that it is 115 loose
# files (issue #328): it rewrote the binary's RUNPATH from $ORIGIN/../lib to
# "librt.so.1" -- after "Patch value (25275 bytes @0x678) exceeds segment
# bounds" -- and the bundled RetroArch could no longer find one of the 56
# libraries shipped beside it. Copied here, nothing ever touches it.
#
# Only this architecture's: an x86_64 tree inside an ARM bundle is dead weight
# the kernel refuses to execute (issue #119), and libretro publishes no ARM
# build, so on aarch64 there is usually nothing to carry at all.
echo "==> staging the vendored RetroArch"
case "$ARCH" in
  aarch64) FOREIGN_RETROARCH="RetroArch-Linux-x86_64" ;;
  *)       FOREIGN_RETROARCH="RetroArch-Linux-aarch64" ;;
esac
sh packaging/common/copy_tree.sh vendors AppDir/usr/lib/openemux "$FOREIGN_RETROARCH"
sh packaging/common/assert_sources_only.sh AppDir/usr/lib/openemux/vendors

VENDORED_RETROARCH="AppDir/usr/lib/openemux/vendors/RetroArch-Linux-${ARCH}/usr/bin/retroarch"
if [ "$ARCH" = "x86_64" ]; then
  test -x "$VENDORED_RETROARCH" || {
    echo "ERROR: the vendored RetroArch is not in the bundle." >&2
    exit 1
  }
  # Collected first, then matched: `readelf | grep -q` SIGPIPEs readelf, and
  # under `set -o pipefail` that fails the pipeline on a bundle that is fine.
  VENDORED_DYNAMIC="$(readelf -d "$VENDORED_RETROARCH")"
  case "$VENDORED_DYNAMIC" in
    *'$ORIGIN/../lib'*) ;;
    *)
      echo "ERROR: the vendored RetroArch's RUNPATH was rewritten:" >&2
      grep -E 'RUNPATH|RPATH' <<< "$VENDORED_DYNAMIC" >&2 || true
      exit 1
      ;;
  esac
  # PT_INTERP too: a relative loader path resolves against the cwd of whoever
  # execs it, and the launcher execs RetroArch from the user's own directory.
  VENDORED_INTERP="$(readelf -l "$VENDORED_RETROARCH")"
  case "$VENDORED_INTERP" in
    *"[Requesting program interpreter: /"*) ;;
    *)
      echo "ERROR: the vendored RetroArch's ELF interpreter was rewritten:" >&2
      grep -F 'program interpreter' <<< "$VENDORED_INTERP" >&2 || true
      exit 1
      ;;
  esac
  LIB_COUNT="$(find "$(dirname "$VENDORED_RETROARCH")/../lib" -name '*.so*' | wc -l)"
  test "$LIB_COUNT" -ge 50 || {
    echo "ERROR: only $LIB_COUNT bundled RetroArch libraries reached the AppDir." >&2
    exit 1
  }
  echo "vendored RetroArch OK: $LIB_COUNT libraries, RUNPATH and interpreter intact"
fi

# TryExec is resolved against the user's PATH, and no `openemux` binary lives
# there for an AppImage. An integrator (appimaged, AppImageLauncher,
# GearLever) rewrites Exec to the bundle path and leaves TryExec alone, so an
# entry carrying one is silently hidden from the menu after integration
# (issue #256). The shared desktop file has none; only stage_tree.sh adds one,
# for the native packages that do install /usr/bin/openemux.
if grep -q '^TryExec=' AppDir/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop; then
  echo "ERROR: the bundled desktop entry carries TryExec; integrators would hide it." >&2
  exit 1
fi

echo "==> phase 2: package the AppImage from the fixed AppDir"
#
# Assembled here instead of by `appimage-builder --skip-build`, because the
# two halves of a type-2 AppImage have to agree on a compressor and those two
# do not. The runtime this bundle ships is type2-runtime's: static-pie with
# squashfuse and FUSE 3 linked in, so the image needs no libfuse.so.2 on the
# user's machine -- which is the whole of issue #248, since neither Ubuntu
# 24.04 nor Fedora 40 installs one. That runtime reads zlib and zstd only,
# and appimage-builder hardcodes `mksquashfs -comp xz`; pairing them gives a
# bundle that assembles perfectly and then refuses to open itself with
# "Squashfs image uses xz compression, this version supports only zlib,
# zstd". zstd is also the faster read of the two, which a mounted AppImage
# pays for on every block it faults in.
#
# What follows is all of AppImagePrimer.prime() that is not dead code for
# this recipe (it has no update-information and no signing key): squash the
# AppDir, append it to the runtime, mark it executable.
if [ ! -f "$RUNTIME_SRC" ]; then
  echo "ERROR: $RUNTIME_SRC missing. Rebuild the image (packaging/docker/appimage.Dockerfile)." >&2
  exit 1
fi
# The same name appimage-builder gave the file, from the same field, so the
# release artifact keeps its name.
# No `| head -1`: that shape SIGPIPEs its producer, and while sed over a small
# file survives it, the harmful and the harmless read identically at a glance
# -- so the suite bans the shape and the first line is taken here instead.
VERSION="$(sed -n 's/^ *version: *"\(.*\)"/\1/p' "$RECIPE")"
VERSION="${VERSION%%$'\n'*}"
test -n "$VERSION" || { echo "ERROR: no version: field in $RECIPE." >&2; exit 1; }
BUNDLE_NAME="OpenEmux-${VERSION}-${ARCH}.AppImage"
PAYLOAD="$PWD/AppDir.squashfs"
rm -f "$PAYLOAD" "$BUNDLE_NAME"
mksquashfs AppDir "$PAYLOAD" -root-owned -noappend -reproducible \
  -comp zstd -Xcompression-level 19
cat "$RUNTIME_SRC" "$PAYLOAD" > "$BUNDLE_NAME"
rm -f "$PAYLOAD"
chmod +x "$BUNDLE_NAME"
echo "packaged $BUNDLE_NAME ($(stat -c %s "$BUNDLE_NAME") bytes)"

mkdir -p dist
shopt -s nullglob
for artifact in *.AppImage *.zsync; do
  mv "$artifact" dist/
done

# Actually start the thing. Everything above only inspects the AppDir, and a
# bundle can assemble perfectly and still fail to exec its own interpreter --
# which is exactly how a release shipped that died with
# "usr/bin/python3: not found" on every machine.
# Without a pipe into head, for the reason the suite states: the shape is
# banned because the harmful and the harmless instances look the same.
set -- dist/*.AppImage
BUNDLE="$1"
test -f "$BUNDLE" || { echo "ERROR: no AppImage in dist/." >&2; exit 1; }

# The bug this guards against is invisible in the build container -- every
# check below runs the bundle extracted, so a runtime that cannot mount
# itself passes them all and only fails on the user's desktop (issue #248).
# So inspect the runtime itself: it is the first N bytes of the AppImage,
# where N is the size of the runtime the payload was appended to.
echo "==> runtime check: $BUNDLE"
RUNTIME_HEAD="$(mktemp)"
head -c "$(stat -c %s "$RUNTIME_SRC")" "$BUNDLE" > "$RUNTIME_HEAD"
# Read into variables first. `producer | grep -q` SIGPIPEs the producer on the
# first match, and `set -o pipefail` then reports the pipeline as failed -- so
# a runtime that *does* want libfuse.so.2 takes the else branch and the check
# passes exactly when it should not.
RUNTIME_STRINGS="$(strings -a "$RUNTIME_HEAD")"
RUNTIME_DYNAMIC="$(readelf -d "$RUNTIME_HEAD" 2>/dev/null || true)"
if grep -q 'libfuse\.so\.2' <<< "$RUNTIME_STRINGS"; then
  echo "ERROR: the AppImage runtime still wants libfuse.so.2." >&2
  rm -f "$RUNTIME_HEAD"
  exit 1
fi
if grep -q "(NEEDED)" <<< "$RUNTIME_DYNAMIC"; then
  echo "ERROR: the AppImage runtime is dynamically linked:" >&2
  grep "(NEEDED)" <<< "$RUNTIME_DYNAMIC" >&2
  rm -f "$RUNTIME_HEAD"
  exit 1
fi
rm -f "$RUNTIME_HEAD"
echo "runtime OK: statically linked, no libfuse.so.2"

echo "==> launch test: $BUNDLE"
LAUNCH_LOG="$(mktemp)"
# No FUSE in the build container, so run from an extraction; xvfb gives GTK a
# display to open the window on.
APPIMAGE_EXTRACT_AND_RUN=1 timeout 60 xvfb-run -a "$BUNDLE" > "$LAUNCH_LOG" 2>&1 || true

if grep -qE "not found|No module named|ModuleNotFoundError|Traceback" "$LAUNCH_LOG"; then
  echo "ERROR: the bundle failed to start." >&2
  sed -n '1,40p' "$LAUNCH_LOG" >&2
  # "exec: .../python3: not found" from a shell means one of two things, and
  # they need different fixes: the file is missing, or its ELF interpreter is.
  # appimage-builder rewrites every PT_INTERP to a *relative* path, so the
  # second is the likely one and the answer is which loader the interpreter
  # wants and whether the AppDir has it at that relative path -- a question the
  # log used to leave entirely unanswered (issue #119).
  echo "--- interpreter diagnostics ---" >&2
  PY_BIN="AppDir/usr/bin/python3"
  ls -l "$PY_BIN" >&2 || echo "$PY_BIN is missing" >&2
  if [ -e "$PY_BIN" ]; then
    WANTED="$(readelf -l "$(readlink -f "$PY_BIN")" 2>/dev/null \
              | sed -n 's/.*program interpreter: \(.*\)]/\1/p')"
    echo "PT_INTERP: ${WANTED:-<none>}" >&2
    for base in AppDir AppDir/runtime/compat; do
      echo "  $base/$WANTED: $(ls -l "$base/$WANTED" 2>&1)" >&2
    done
  fi
  echo "AppDir/lib*:" >&2
  ls -ld AppDir/lib AppDir/lib64 AppDir/runtime/compat/lib \
         AppDir/runtime/compat/lib64 2>&1 >&2 || true
  exit 1
fi
# The app logs this once GTK is up and the window is being built; reaching it
# proves the interpreter, the typelibs and the UI import chain all resolved.
if ! grep -q "startup context" "$LAUNCH_LOG"; then
  echo "ERROR: the bundle started but never reached the UI." >&2
  sed -n '1,40p' "$LAUNCH_LOG" >&2
  exit 1
fi
echo "launch test OK: $(grep -m1 'startup context' "$LAUNCH_LOG")"

# Starting is not the same as working: the loaders, the Rsvg bindings and the
# GI<->cairo bridge are separate packages, and a missing one only shows up as
# blank cards. The self-check exercises each for real, inside the bundle.
echo "==> bundle self-check"
SELFTEST_LOG="$(mktemp)"
APPIMAGE_EXTRACT_AND_RUN=1 OPENEMUX_SELFTEST=1 \
  timeout 60 xvfb-run -a "$BUNDLE" > "$SELFTEST_LOG" 2>&1 || true

if ! grep -q "all bundle self-checks passed" "$SELFTEST_LOG"; then
  echo "ERROR: the bundle self-check did not pass." >&2
  sed -n '1,40p' "$SELFTEST_LOG" >&2
  exit 1
fi
sed -n '/self-check inside/,$p' "$SELFTEST_LOG"

echo "==> ALL APPIMAGE CHECKS PASSED"

#!/bin/sh
# Copy one directory of the project into a staging tree, leaving the local
# build state behind.
#
# Usage: copy_tree.sh <source-dir> <destination-parent> [extra-exclude ...]
#
# Equivalent to `cp -r <source-dir> <destination-parent>/`, minus everything a
# build, a test run or an editor drops beside the sources. Plain `cp -r` is how
# the .deb and .rpm came to ship `src/opemux.egg-info/` -- a stale directory
# from a typo'd project name that no longer exists in the repository at all --
# along with `src/openemux.egg-info/` and whatever `__pycache__` the maintainer
# happened to have (issue #254). Neither is tracked; both were in the packages.
#
# Why it matters beyond tidiness: `top_level.txt` in a stray egg-info registers
# a second, phantom distribution on `PYTHONPATH=/opt/openemux/src`, which
# `importlib.metadata` reports as installed, and `SOURCES.txt` publishes the
# development tree's whole file inventory. A package that carries the
# maintainer's local state is also not reproducible from a clean clone.
#
# The vendors/ entries below are the same class of problem with a bigger
# number on it: the Windows RetroArch is 556 MiB unpacked, gitignored, and
# fetched on demand for the Windows build alone -- a Linux package built after
# `make vendor-retroarch-win64` would carry all of it. `.cache` and `*.7z` are
# the downloads both of them come out of, which are bigger still.
#
# tar rather than `git archive`: this has to work from an unpacked source
# tarball too (the RPM's %install runs in %{_builddir}, where there is no git
# repository), and rsync is not installed in any of the build images.
set -eu

SRC="${1:?usage: copy_tree.sh <source-dir> <destination-parent>}"
DEST_PARENT="${2:?usage: copy_tree.sh <source-dir> <destination-parent>}"
shift 2

# Anything else on the command line is another tar --exclude pattern. The one
# caller that needs it is the vendored RetroArch: a package built for one
# architecture must not carry the tree for the other, which is dead weight the
# kernel would refuse to execute anyway (issue #119).
EXTRA=""
for pattern in "$@"; do
  EXTRA="$EXTRA --exclude=$pattern"
done

[ -d "$SRC" ] || { echo "copy_tree: no such directory: $SRC" >&2; exit 1; }

install -d "$DEST_PARENT"
tar --create --file - \
    --exclude='__pycache__' \
    --exclude='*.py[cod]' \
    --exclude='*.egg-info' \
    --exclude='*.egg-link' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='.coverage' \
    --exclude='htmlcov' \
    --exclude='RetroArch-Win64' \
    --exclude='.cache' \
    --exclude='*.7z' \
    $EXTRA \
    --directory "$(dirname "$SRC")" "$(basename "$SRC")" \
  | tar --extract --file - --directory "$DEST_PARENT"

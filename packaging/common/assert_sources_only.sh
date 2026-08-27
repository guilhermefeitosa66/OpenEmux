#!/bin/sh
# Fail the build if a staged tree carries local build state.
#
# Usage: assert_sources_only.sh <dir> [<dir>...]
#
# copy_tree.sh is what keeps these out; this is what proves it. A staged tree
# is the package, so an artifact that slips through the exclude list is an
# artifact the next release ships -- which is exactly how `src/opemux.egg-info/`
# rode along in every .deb and .rpm for months (issue #254).
set -eu

[ "$#" -gt 0 ] || { echo "usage: assert_sources_only.sh <dir> [<dir>...]" >&2; exit 2; }

leftovers="$(find "$@" \
  \( -name '__pycache__' \
     -o -name '*.egg-info' \
     -o -name '*.egg-link' \
     -o -name '*.py[cod]' \
     -o -name '.pytest_cache' \
     -o -name '.mypy_cache' \
     -o -name '.ruff_cache' \
     -o -name 'RetroArch-Win64' \) \
  -print 2>/dev/null)"

if [ -n "$leftovers" ]; then
  echo "assert_sources_only: build artifacts reached the staged tree:" >&2
  echo "$leftovers" >&2
  exit 1
fi

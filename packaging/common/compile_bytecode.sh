#!/bin/sh
# Compile a staged tree's bytecode, so the shipped app does not recompile
# itself on every launch.
#
# Usage: compile_bytecode.sh <dir> [<dir>...]
#
# An installed OpenEmux lands somewhere the user cannot write, so CPython's
# attempt to put __pycache__ beside the sources fails and it silently falls
# back to compiling in memory -- all ~36k lines of it, on every single launch
# (issue #364).
#
# Only for the formats that *pin* the interpreter they run: the AppImage
# bundles its own python3, the Flatpak gets one from org.gnome.Platform, and
# in both the build and the runtime interpreter are the same one. The .deb and
# .rpm cannot do this. One .deb serves Ubuntu 24.04 through 26.04 and one .rpm
# serves Fedora 40 onwards, whose interpreters do not agree on the bytecode
# magic number -- bytecode built here would be ignored on most of them. They
# redirect the cache at runtime instead, in main.py's _redirect_bytecode_cache.
#
# Run this *after* assert_sources_only.sh, never before: that check exists to
# prove the maintainer's own __pycache__ did not ride into the package
# (issue #254), and it cannot tell one kind of bytecode from another. Compiling
# afterwards keeps the check exactly as strict as it was.
set -eu

[ "$#" -gt 0 ] || { echo "usage: compile_bytecode.sh <dir> [<dir>...]" >&2; exit 2; }

# --invalidation-mode unchecked-hash, and it is load-bearing. A default .pyc
# records the source's mtime and revalidates against it on every import -- and
# both appimage-builder and flatpak-builder rewrite mtimes on the way into the
# image, which would invalidate every file and buy exactly nothing. An
# unchecked-hash .pyc (PEP 552) is accepted without reading the .py at all,
# which is the right contract for a tree that is read-only for good, and it
# keeps the build reproducible: no timestamp from the build machine gets baked
# into the artifact.
for target in "$@"; do
    [ -d "$target" ] || { echo "compile_bytecode: $target is not a directory" >&2; exit 1; }
    python3 -m compileall -q -j0 --invalidation-mode unchecked-hash "$target"
done

# Prove it landed. A compileall that quietly wrote nothing -- the wrong path, a
# tree that moved -- would leave the package shipping no bytecode and nothing
# to say so until somebody measured a launch.
for target in "$@"; do
    sources="$(find "$target" -name '*.py' | wc -l)"
    compiled="$(find "$target" -name '*.pyc' | wc -l)"
    if [ "$sources" -gt 0 ] && [ "$compiled" -lt "$sources" ]; then
        echo "compile_bytecode: $target has $sources sources but only $compiled .pyc" >&2
        exit 1
    fi
    echo "compile_bytecode: $target -- $compiled files"
done

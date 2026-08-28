#!/bin/sh
# Hand the working tree back to the user who started the build.
#
# Every packaging build runs as root inside a container that bind-mounts the
# repository at /work, so everything it writes there lands as root:root. The
# developer is then locked out of parts of their own checkout, and `chown`
# needs root -- so the host cannot undo it afterwards. It has to happen here,
# before the container exits.
#
# Usage: HOST_UID=<uid> HOST_GID=<gid> sh packaging/common/hand_back.sh
#
# Nothing is listed by hand, and that is the point. Each build script used to
# name the paths it knew it had created -- `dist`, `build`, `AppDir`,
# `flatpak-repo` -- and each list forgot something different:
#
#   * the Flatpak build left 2154 root-owned files in .flatpak-builder/ and
#     .flatpak-build-dir/, which the developer could not read *or delete*;
#   * every format that embeds the ScreenScraper credential left
#     src/openemux/core/embedded_credentials.py -- a file that is *tracked* --
#     owned by root, so the next edit to it failed;
#   * containers that run python from /work leave root-owned __pycache__.
#
# So the rule is the state rather than a list: anything under the tree that is
# not the user's is handed back, whatever created it.
set -eu

if [ -z "${HOST_UID:-}" ] || [ -z "${HOST_GID:-}" ]; then
  # Not in the container, or launched without them. Chowning to a guessed
  # `0:0` would be the very bug this script exists to prevent.
  echo "hand_back: HOST_UID/HOST_GID unset; leaving ownership alone." >&2
  exit 0
fi

# -uid, not -user: the value is numeric and the container has no passwd entry
# for the developer's uid. -h so a symlink is chowned rather than its target,
# which may live outside the tree.
leftovers="$(find . ! -uid "$HOST_UID" -print 2>/dev/null || true)"
if [ -n "$leftovers" ]; then
  find . ! -uid "$HOST_UID" -exec chown -h "$HOST_UID:$HOST_GID" {} + 2>/dev/null || true
  echo "hand_back: $(printf '%s\n' "$leftovers" | wc -l) path(s) returned to ${HOST_UID}:${HOST_GID}"
fi

# The artifacts themselves get 755: the AppImage has to be executable to be
# worth anything, and the rest are files the developer hands to other people.
# Only dist/ -- a blanket chmod over the tree would mark every source file
# executable, which is a different bug.
if [ -d dist ]; then
  chmod 755 dist 2>/dev/null || true
  find dist -maxdepth 1 -type f -exec chmod 755 {} + 2>/dev/null || true
fi

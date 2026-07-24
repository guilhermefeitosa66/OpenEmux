#!/usr/bin/env bash
# Shared entry point for the packaging builds: `packaging/build.sh <target>`,
# where <target> is appimage, deb or rpm. Every build runs in the container
# defined by packaging/docker/<target>.Dockerfile, so the host only needs
# Docker, and artifacts land in dist/.
#
# The per-target logic lives in packaging/<target>/build.sh, which this script
# runs *inside* the container.
set -euo pipefail

TARGET="${1:-}"
case "$TARGET" in
  appimage|deb|rpm) ;;
  *)
    echo "usage: $0 {appimage|deb|rpm}" >&2
    exit 2
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load the local, gitignored .env so `make packages` can bake in the
# ScreenScraper developer credential without it living in the shell profile.
# Absent/empty .env -> the injection later is a no-op and no credential ships.
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install Docker to build packages." >&2
  exit 1
fi

if [ "$TARGET" = "appimage" ]; then
  # appimage-builder bundles amd64 debs and the result only runs on x86_64.
  ARCH="$(uname -m)"
  if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    echo "AppImage builds require an x86_64 host (found: $ARCH)." >&2
    exit 1
  fi
fi

IMAGE="openemux-build-$TARGET"
echo "==> building image $IMAGE"
docker build -q -t "$IMAGE" -f "packaging/docker/$TARGET.Dockerfile" packaging/docker

# Artifacts are written as root inside the container; hand them back afterwards.
HOST_UID="${HOST_UID:-$(id -u)}"
HOST_GID="${HOST_GID:-$(id -g)}"

DOCKER_ARGS=(--rm -t -v "$ROOT_DIR:/work" -w /work
             -e HOST_UID="$HOST_UID" -e HOST_GID="$HOST_GID")
# Pass the ScreenScraper developer credential through to the build (from the
# local .env sourced above, or the shell environment). Unset/empty means no
# embedded credential -- the injection step is then a no-op and ScreenScraper
# stays opt-in, so a build without a .env needs nothing here.
DOCKER_ARGS+=(-e SCREENSCRAPER_DEVID="${SCREENSCRAPER_DEVID:-}"
              -e SCREENSCRAPER_DEVPASSWORD="${SCREENSCRAPER_DEVPASSWORD:-}")
# appimage-builder needs to mount squashfs/use FUSE-ish tooling while bundling.
if [ "$TARGET" = "appimage" ]; then
  DOCKER_ARGS+=(--privileged)
fi

echo "==> running packaging/$TARGET/build.sh in $IMAGE"
docker run "${DOCKER_ARGS[@]}" "$IMAGE" bash "packaging/$TARGET/build.sh"

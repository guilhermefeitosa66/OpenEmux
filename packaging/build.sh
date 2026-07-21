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
# appimage-builder needs to mount squashfs/use FUSE-ish tooling while bundling.
if [ "$TARGET" = "appimage" ]; then
  DOCKER_ARGS+=(--privileged)
fi

echo "==> running packaging/$TARGET/build.sh in $IMAGE"
docker run "${DOCKER_ARGS[@]}" "$IMAGE" bash "packaging/$TARGET/build.sh"

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
  appimage|deb|rpm|flatpak|windows) ;;
  *)
    echo "usage: $0 {appimage|deb|rpm|flatpak|windows}" >&2
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

# Never build from a tree that already carries a baked credential (issue #250).
# Every target injects the credential into its own staging copy and leaves the
# tracked source alone; a non-empty blob in the working tree therefore means an
# interrupted build restored nothing, and building on would bake a credential
# that the next `git commit -a` would publish.
CRED_FILE="src/openemux/core/embedded_credentials.py"
if ! grep -q '^_EMBEDDED_BLOB = ""$' "$ROOT_DIR/$CRED_FILE"; then
  echo "$CRED_FILE carries an embedded credential." >&2
  echo "A previous build was interrupted before it could restore the file." >&2
  echo "Restore it with: git checkout -- $CRED_FILE" >&2
  exit 1
fi
if [ -e "$ROOT_DIR/${CRED_FILE}.orig" ]; then
  echo "${CRED_FILE}.orig is left over from an interrupted build." >&2
  echo "Check it against the tracked file and delete it before building." >&2
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

if [ "$TARGET" = "windows" ]; then
  # The bundled RetroArch for Windows is gitignored and fetched on demand (193
  # MiB), so unlike the Linux AppImage it may simply not be there yet. Said
  # here rather than 20 minutes later, after the whole GTK stack has downloaded.
  if [ ! -f vendors/RetroArch-Win64/retroarch.exe ]; then
    echo "vendors/RetroArch-Win64/retroarch.exe is missing." >&2
    echo "Run 'make vendor-retroarch-win64' first, or just 'make windows'," >&2
    echo "which fetches it. 'make vendor-retroarch' on a Linux host takes the" >&2
    echo "artifact for *this* platform, which is the committed AppImage." >&2
    exit 1
  fi
fi

IMAGE="openemux-build-$TARGET"
echo "==> building image $IMAGE"
# --pull: without it a stale local image is reused silently, possibly one
# cached before a security update. The Dockerfiles pin their base by digest, so
# this only ever re-fetches the same bytes (issue #255).
docker build --pull -q -t "$IMAGE" -f "packaging/docker/$TARGET.Dockerfile" packaging/docker

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
# Two builds have to mount a filesystem, and --privileged is how they used to
# get to: full host root, every capability and every device, in a container
# that also bind-mounts the repository and carries SCREENSCRAPER_DEVPASSWORD --
# so any compromised dependency pulled during those builds ran as root on the
# host machine (issue #255). The real requirement is narrower, and different
# for each of them; both sets below were established by probing the actual
# failure, not by guessing.
if [ "$TARGET" = "appimage" ]; then
  # appimage-builder mounts squashfs while bundling: SYS_ADMIN for mount(2),
  # /dev/fuse for the filesystem itself, and an AppArmor exception because the
  # host's docker-default profile denies mount unconditionally.
  DOCKER_ARGS+=(--cap-add SYS_ADMIN --device /dev/fuse
                --security-opt apparmor:unconfined)
elif [ "$TARGET" = "flatpak" ]; then
  # flatpak-builder builds every module inside bubblewrap, which needs two
  # more things: NET_ADMIN to bring up loopback in the network namespace it
  # unshares (without it: "bwrap: loopback: Failed RTM_NEWADDR"), and seccomp
  # unconfined because Docker's default profile blocks pivot_root (without it:
  # "bwrap: pivot_root: Operation not permitted"). SYS_CHROOT is not needed.
  DOCKER_ARGS+=(--cap-add SYS_ADMIN --cap-add NET_ADMIN --device /dev/fuse
                --security-opt apparmor:unconfined
                --security-opt seccomp=unconfined)
fi

echo "==> running packaging/$TARGET/build.sh in $IMAGE"
docker run "${DOCKER_ARGS[@]}" "$IMAGE" bash "packaging/$TARGET/build.sh"

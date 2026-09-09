#!/usr/bin/env bash
# Shared entry point for the packaging builds: `packaging/build.sh <target>`,
# where <target> is appimage, deb, rpm or arch. Every build runs in the container
# defined by packaging/docker/<target>.Dockerfile, so the host only needs
# Docker, and artifacts land in dist/.
#
# The per-target logic lives in packaging/<target>/build.sh, which this script
# runs *inside* the container.
set -euo pipefail

TARGET="${1:-}"
case "$TARGET" in
  appimage|deb|rpm|arch|flatpak|windows) ;;
  *)
    echo "usage: $0 {appimage|deb|rpm|arch|flatpak|windows}" >&2
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

# Every Linux format is built for the architecture of the machine building it.
# That is not a limitation to work around: an AppDir is assembled out of debs
# for one architecture and only runs there, the .deb takes its Architecture
# from dpkg, and the .rpm from rpmbuild. Cross-building any of them would mean
# a second, untested path -- build ARM on ARM (issue #119).
#
# The check is which architectures are *supported*, then, rather than which one
# the host is.
case "$TARGET" in
  appimage|deb|rpm|arch)
    # The container's architecture, which PLATFORM overrides.
    ARCH="$(uname -m)"
    case "${PLATFORM:-}" in
      */arm64|*/aarch64) ARCH=aarch64 ;;
      */amd64|*/x86_64)  ARCH=x86_64 ;;
    esac
    case "$ARCH" in
      x86_64|amd64|aarch64|arm64) ;;
      *)
        echo "$TARGET builds are supported on x86_64 and aarch64 (found: $ARCH)." >&2
        exit 1
        ;;
    esac
    # ...except the Arch one on ARM. The recipe itself is architecture-neutral
    # and `makepkg` builds it fine on Arch Linux ARM -- what does not exist is
    # a container to build it in: the official `archlinux` image publishes
    # amd64 only (Arch Linux ARM is a separate distribution with its own
    # images). Said here rather than as a confusing `docker build` failure.
    if [ "$TARGET" = "arch" ]; then
      case "$ARCH" in
        aarch64|arm64)
          echo "The Arch build image (archlinux:base-devel) is amd64-only." >&2
          echo "On an ARM machine, build packaging/arch/PKGBUILD with makepkg" >&2
          echo "directly -- the recipe supports aarch64, the container does not." >&2
          exit 1
          ;;
      esac
    fi
    ;;
esac

# Both vendored RetroArch builds are gitignored and fetched on demand, so
# either may simply not be there yet. Said here rather than 20 minutes later,
# after the whole GTK stack has downloaded into a container.
if [ "$TARGET" = "windows" ]; then
  if [ ! -f vendors/RetroArch-Win64/retroarch.exe ]; then
    echo "vendors/RetroArch-Win64/retroarch.exe is missing." >&2
    echo "Run 'make vendor-retroarch-win64' first, or just 'make windows'," >&2
    echo "which fetches it. 'make vendor-retroarch' on a Linux host takes the" >&2
    echo "artifact for *this* platform, which is the Linux one." >&2
    exit 1
  fi
fi

# The Linux formats that bundle an emulator. The Flatpak does not -- it
# launches the host's org.libretro.RetroArch -- and on aarch64 there is nothing
# to bundle, since libretro publishes no ARM build (issue #119).
# ARCH is set by the architecture gate above, which only runs for these four
# targets; ${ARCH:-} keeps `set -u` out of it for the other two.
case "$TARGET:${ARCH:-}" in
  appimage:x86_64|appimage:amd64|deb:x86_64|deb:amd64|rpm:x86_64|rpm:amd64|arch:x86_64|arch:amd64)
    if [ ! -x vendors/RetroArch-Linux-x86_64/usr/bin/retroarch ]; then
      echo "vendors/RetroArch-Linux-x86_64/usr/bin/retroarch is missing." >&2
      echo "Run 'make vendor-retroarch' first, or 'make $TARGET', which" >&2
      echo "fetches it. It is a 171 MiB download, unwrapped into the portable" >&2
      echo "tree the packages ship (issue #328)." >&2
      exit 1
    fi
    ;;
esac

# Cross-building under QEMU: `PLATFORM=linux/arm64 packaging/build.sh deb` on
# an x86_64 desktop, with binfmt registered
# (`docker run --privileged tonistiigi/binfmt --install arm64`). Slow -- an
# emulated apt install is minutes, not seconds -- and it exists so an ARM
# packaging change can be tried without ARM hardware. The release builds ARM on
# ARM in CI; see docs/DEVELOPMENT.md (issue #119).
PLATFORM_ARGS=()
if [ -n "${PLATFORM:-}" ]; then
  echo "==> emulating $PLATFORM (slow)"
  PLATFORM_ARGS=(--platform "$PLATFORM")
fi

IMAGE="openemux-build-$TARGET${PLATFORM:+-$(echo "$PLATFORM" | tr '/' '-')}"
echo "==> building image $IMAGE"
# --pull: without it a stale local image is reused silently, possibly one
# cached before a security update. The Dockerfiles pin their base by digest, so
# this only ever re-fetches the same bytes (issue #255).
docker build "${PLATFORM_ARGS[@]}" --pull -q -t "$IMAGE" \
  -f "packaging/docker/$TARGET.Dockerfile" packaging/docker

# Artifacts are written as root inside the container; hand them back afterwards.
HOST_UID="${HOST_UID:-$(id -u)}"
HOST_GID="${HOST_GID:-$(id -g)}"

DOCKER_ARGS=("${PLATFORM_ARGS[@]}" --rm -t -v "$ROOT_DIR:/work" -w /work
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

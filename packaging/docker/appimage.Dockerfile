# Build image for the OpenEmux AppImage.
#
# Ubuntu 24.04 (noble) matches the apt sources the recipe bundles from, so the
# libraries pulled into the AppDir are the ones this image can query and test.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# binutils supplies readelf, which appimage-builder shells out to while walking
# the bundled ELFs; gcc + libc6-dev build the static entry-point binary. Neither
# is pulled in by the rest, and --no-install-recommends means nothing arrives by
# accident.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-setuptools python3-wheel \
      ca-certificates gnupg wget file desktop-file-utils \
      squashfs-tools patchelf fakeroot strace xz-utils zsync \
      libgdk-pixbuf2.0-bin libglib2.0-bin gtk-update-icon-cache \
      librsvg2-common \
      binutils gcc libc6-dev \
      # The build launches the finished bundle as a smoke test; GTK needs a
      # display and the app needs its runtime deps present to get that far.
      xvfb \
      libgtk-4-1 libadwaita-1-0 gir1.2-gtk-4.0 gir1.2-adw-1 \
 && rm -rf /var/lib/apt/lists/*

# Pinned: appimage-builder 1.1.0 needs packaging<22 to import.
RUN python3 -m pip install --break-system-packages --no-cache-dir \
      "packaging<22" "appimage-builder==1.1.0"

# The runtime that carries the finished bundle.
#
# Left to itself appimage-builder downloads AppImageKit's "continuous"
# runtime, which is dynamically linked and dlopens libfuse.so.2 at startup.
# Ubuntu 24.04 ships FUSE 3 and does not install libfuse2t64; Fedora 40 does
# not install fuse-libs either -- so on both distributions the project targets
# as its floor, double-clicking the primary download died with
# "dlopen(): error loading libfuse.so.2" before a line of OpenEmux ran
# (issue #248).
#
# type2-runtime's runtime is static-pie with squashfuse and FUSE 3 linked in,
# so it asks the host for no library at all. Pinned to a tagged build (not
# "continuous") and checksummed, because this binary is the first thing every
# user of the AppImage executes. packaging/appimage/build.sh appends the
# squashed AppDir to it by hand: this runtime reads zlib and zstd only, and
# appimage-builder's own packaging step hardcodes xz, so its phase 2 is not
# used at all.
ARG APPIMAGE_RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
ARG APPIMAGE_RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
RUN wget -q -O /opt/appimage-runtime-x86_64 "$APPIMAGE_RUNTIME_URL" \
 && echo "$APPIMAGE_RUNTIME_SHA256  /opt/appimage-runtime-x86_64" | sha256sum -c - \
 && chmod 0644 /opt/appimage-runtime-x86_64

WORKDIR /work

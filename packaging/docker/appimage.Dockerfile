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

WORKDIR /work

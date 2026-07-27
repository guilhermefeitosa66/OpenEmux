# Build image for the OpenEmux Flatpak bundle.
#
# flatpak-builder drives the build; the GNOME runtime/SDK are installed at
# build time (they are too large to bake into the image and follow their own
# release cadence). The container must run --privileged: flatpak-builder's
# bubblewrap sandbox needs it inside Docker.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      flatpak \
      flatpak-builder \
      ca-certificates \
      python3 \
      # eu-strip: flatpak-builder splits debug symbols out of every compiled
      # module (PyYAML's C extension here) and fails hard without it.
      elfutils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# Build image for the OpenEmux Flatpak bundle.
#
# flatpak-builder drives the build; the GNOME runtime/SDK are installed at
# build time (they are too large to bake into the image and follow their own
# release cadence). The container must run --privileged: flatpak-builder's
# bubblewrap sandbox needs it inside Docker.
#
# Pinned by digest, not by tag: `ubuntu:24.04` is a moving target, so two builds
# of the same commit months apart produced different artifacts and a regression
# from a base-image update was indistinguishable from a code regression
# (issue #255). Re-pin deliberately -- `docker manifest inspect ubuntu:24.04` prints
# the current digest -- so a base-image change is a commit somebody reviewed.
FROM ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517

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
      # The two files Flathub's linter reads are validated before the build:
      # appstreamcli for the metainfo, desktop-file-validate for the entry.
      appstream \
      desktop-file-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

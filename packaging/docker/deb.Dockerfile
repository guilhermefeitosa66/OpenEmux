# Build image for the OpenEmux .deb.
#
# Ubuntu 24.04 is the floor the package targets: the Adwaita UI needs
# libadwaita >= 1.5, which is what noble ships. Building on it also keeps the
# install test honest -- the same container resolves the package's Depends.
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
      dpkg-dev \
      desktop-file-utils \
      # appstreamcli, for validating the metainfo the software centre reads.
      appstream \
      imagemagick \
      fakeroot \
      xz-utils \
      python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

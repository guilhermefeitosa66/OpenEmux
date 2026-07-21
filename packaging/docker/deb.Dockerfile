# Build image for the OpenEmux .deb.
#
# Ubuntu 24.04 is the floor the package targets: the Adwaita UI needs
# libadwaita >= 1.5, which is what noble ships. Building on it also keeps the
# install test honest -- the same container resolves the package's Depends.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      dpkg-dev \
      desktop-file-utils \
      imagemagick \
      fakeroot \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

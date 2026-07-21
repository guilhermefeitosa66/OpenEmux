# Build image for the OpenEmux .rpm.
#
# Fedora 40 is the floor the package targets (libadwaita >= 1.5). The install
# test in the same container resolves the spec's Requires.
FROM fedora:40

RUN dnf install -y \
      rpm-build \
      rpmdevtools \
      desktop-file-utils \
      ImageMagick \
 && dnf clean all

WORKDIR /work

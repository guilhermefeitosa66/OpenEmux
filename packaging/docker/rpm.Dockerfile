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
      python3 \
      # appstreamcli: the spec's %check validates the metainfo it installs,
      # and rpmbuild -ba refuses to start with an unmet BuildRequires.
      appstream \
      # The build rebuilds its own SRPM (the check that the spec needs no
      # bind mount) and runs rpmlint over both artifacts, so the Fedora-review
      # findings are caught here rather than by a reviewer.
      rpmlint \
 && dnf clean all

WORKDIR /work

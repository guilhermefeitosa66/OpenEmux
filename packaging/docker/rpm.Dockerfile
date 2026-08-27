# Build image for the OpenEmux .rpm.
#
# Fedora 40 is the floor the package targets (libadwaita >= 1.5). The install
# test in the same container resolves the spec's Requires.
#
# Pinned by digest, not by tag: `ubuntu:24.04` is a moving target, so two builds
# of the same commit months apart produced different artifacts and a regression
# from a base-image update was indistinguishable from a code regression
# (issue #255). Re-pin deliberately -- `docker manifest inspect fedora:40` prints
# the current digest -- so a base-image change is a commit somebody reviewed.
FROM fedora:40@sha256:3c86d25fef9d2001712bc3d9b091fc40cf04be4767e48f1aa3b785bf58d300ed

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

# Build image for the OpenEmux Arch package.
#
# Arch is a rolling distribution with no release to pin to, so unlike the
# Ubuntu and Fedora images this one is pinned to a dated `base-devel` digest
# and its package database is refreshed at build time. Re-pin deliberately --
# `docker manifest inspect archlinux:base-devel` prints the current digest --
# so a base-image change is a commit somebody reviewed (issue #255).
FROM archlinux:base-devel@sha256:84cd9ef000b3cff245ec028e87965b84724f4bf1cc63fc2741ba927b88515ed6

# -Syu, not just -Sy: a partial upgrade on a rolling distribution installs
# packages built against libraries the image does not have, and the failure
# lands somewhere unrelated hours later.
RUN pacman -Syu --noconfirm \
      git \
      # namcap lints the built package the way rpmlint does the .rpm.
      namcap \
      desktop-file-utils \
      imagemagick \
      # appstreamcli, to validate the metainfo software centres read.
      appstream \
      # The runtime dependencies the install test resolves. Listed so the
      # image carries them rather than downloading the GTK stack on every run.
      python \
      python-gobject \
      python-cairo \
      gtk4 \
      libadwaita \
      python-yaml \
      python-xlib \
      librsvg \
      webp-pixbuf-loader \
      adwaita-icon-theme \
      hicolor-icon-theme \
 && pacman -Scc --noconfirm

# makepkg refuses to run as root, and rightly: it unpacks and executes a
# recipe. packaging/arch/build.sh runs the makepkg half as this user and keeps
# the pacman half (which needs root) outside it.
RUN useradd -m builder \
 && echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder

WORKDIR /work

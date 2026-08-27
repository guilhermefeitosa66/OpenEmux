# Build image for the OpenEmux Windows bundle and installer.
#
# Everything OpenEmux ships is built on Linux in Docker, and Windows is no
# exception -- there is no Windows machine anywhere in the release path. Three
# pieces make that possible, and none of them needs Wine:
#
#   * the mingw-w64 cross compiler, which turns openemux-launcher.c into the
#     OpenEmux.exe that starts the bundle;
#   * zstd + tar, which unpack the MSYS2 MINGW64 packages providing GTK 4,
#     libadwaita and Python *for Windows*;
#   * NSIS, which has a native Linux build -- makensis compiles the installer
#     here as an ordinary Linux program.
#
# NSIS rather than the Inno Setup named in issue #118: Inno's compiler is a
# 32-bit Windows binary, so it would drag Wine, an i386 architecture and an
# out-of-band download of an unversioned .exe into an otherwise self-contained
# Debian image. NSIS produces the same installer this project needs -- per-user
# install with no UAC prompt, a Start Menu shortcut and an uninstaller -- and
# comes from apt.
#
# The GTK stack itself is never *built* here. It is downloaded already compiled
# for Windows from the MSYS2 repository; see packaging/windows/msys2_packages.py.
#
# Pinned by digest, not by tag: `ubuntu:24.04` is a moving target, so two builds
# of the same commit months apart produced different artifacts and a regression
# from a base-image update was indistinguishable from a code regression
# (issue #255). Re-pin deliberately -- `docker manifest inspect debian:bookworm` prints
# the current digest -- so a base-image change is a commit somebody reviewed.
FROM debian:bookworm@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      python3 \
      zstd \
      tar \
      zip \
      xz-utils \
      gcc-mingw-w64-x86-64 \
      binutils-mingw-w64-x86-64 \
      nsis \
      imagemagick \
      libglib2.0-bin \
      libgtk-4-bin \
 && rm -rf /var/lib/apt/lists/*

# ImageMagick's bookworm policy can refuse to write some formats. The build only
# ever converts the project's own PNG logo into an .ico, so the ICO coder has to
# be allowed; the edit is a no-op when the policy does not restrict it.
RUN sed -i 's|<policy domain="coder" rights="none" pattern="ICO" />||' \
      /etc/ImageMagick-6/policy.xml 2>/dev/null || true

WORKDIR /work

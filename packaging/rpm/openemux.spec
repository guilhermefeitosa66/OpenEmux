# Built from a self-contained tree (pure-Python app + a vendored RetroArch
# AppImage), so skip debuginfo and the binary-reprocessing steps that would try
# to strip/mangle the bundled AppImage, and declare Requires by hand.
%global debug_package %{nil}
%global __brp_strip %{nil}
%global __brp_strip_static_archive %{nil}
%global __brp_strip_comment_note %{nil}
%global __brp_mangle_shebangs %{nil}
%global __brp_check_rpaths %{nil}
%global __requires_exclude .*
%global __provides_exclude .*

Name:           openemux
Version:        %{version}
Release:        1%{?dist}
Summary:        Linux-native emulator frontend for RetroArch

License:        MIT
URL:            https://github.com/guilhermefeitosa66/OpenEmux
BuildArch:      x86_64
AutoReqProv:    no

# Targets Fedora 40+ (libadwaita >= 1.5, required by the Adwaita UI).
Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4 >= 4.6
Requires:       libadwaita >= 1.5
Requires:       python3-pyyaml
Requires:       librsvg2
Requires:       adwaita-icon-theme
Requires:       shared-mime-info
Recommends:     fuse-libs

%description
OpenEmux is a GTK4/Adwaita frontend that manages a ROM library and launches
games through RetroArch, inspired by OpenEmu. It bundles a RetroArch AppImage
and downloads libretro cores on first launch.

%install
rm -rf %{buildroot}
DESTDIR=%{buildroot} ROOT_DIR=%{repo_root} sh %{repo_root}/packaging/common/stage_tree.sh

%files
/opt/openemux
/usr/bin/openemux
/usr/share/applications/io.github.guilhermefeitosa66.OpenEmux.desktop
/usr/share/icons/hicolor/512x512/apps/io.github.guilhermefeitosa66.OpenEmux.png
%license /usr/share/doc/openemux/copyright

%post
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || :
fi

%postun
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%changelog
* Mon Jul 20 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.3.0-1
- Recognize ROMs inside .zip archives; extract for cores that need a real file
- Import ROMs from the UI, by button or drag and drop
- Map controls with the gamepad itself; up to four gamepad ports
- Optional ScreenScraper cover source, including cartridge labels
- Rotating tips status bar and a customizable fullscreen toggle
- Cancellable cover sync, console icons throughout, context menus

* Fri Jul 17 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.2.0-1
- Per-console cover proportions and separate cartridge-label images
- Redesigned All library view with per-game console labels
- Startup check for new releases
- First native .deb and .rpm packages

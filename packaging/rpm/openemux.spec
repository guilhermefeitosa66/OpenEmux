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
/usr/share/icons/hicolor/*/apps/io.github.guilhermefeitosa66.OpenEmux.png
/usr/share/pixmaps/io.github.guilhermefeitosa66.OpenEmux.png
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
* Thu Jul 23 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.6.0-1
- Add a View Mode selector: cover grid, cartridge grid and a compact list
- Add zoom controls for thumbnails (50%-200%), with Ctrl+plus/minus/0
- Sort the library by name, recently played, recently added, size or platform
- Track play history per ROM to support the recently-played order
- Follow the desktop language on first launch instead of defaulting to English
- Open the primary menu from the gamepad and restore focus after dialogs close
- Steer with the right analog stick as well as the left one
- Fix gamepad remapping capturing UI navigation instead of the binding

* Tue Jul 21 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.5.2-1
- Fix cartridge frames and cover art not rendering in the AppImage
- Degrade to the plain cover when a cartridge cannot be composited

* Tue Jul 21 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.5.1-1
- Fix the AppImage failing to start with "usr/bin/python3: not found"

* Tue Jul 21 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.5.0-1
- Navigate the whole library with a gamepad (RetroArch button convention)
- Full keyboard navigation plus shortcuts for play, rename, delete, favorite,
  rescan, import and cover sync
- Show what each control does in the bottom bar, per input device
- Lay the game grid out like an icon view, with fixed card sizes per console
- Fix the launcher picking a python3 without PyGObject (pyenv/conda/asdf)
- Stop a source run's desktop entry from shadowing the packaged one
- Drop Flatpak packaging

* Tue Jul 21 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.4.0-1
- Render every game inside its console cartridge, from vector artwork, on by default
- Turn the favorite star on a cover into a button
- Rename a ROM from the context menu, carrying artwork and playlists along
- Delete a ROM from the context menu, moving the file to the system trash
- Select several ROMs by dragging, then delete them or sync only their covers

* Mon Jul 20 2026 Guilherme Feitoza <guilhermefeitosa66@gmail.com> - 1.3.1-1
- Keep the sidebar context menu open instead of closing it on button release
- Show icons next to context menu entries
- Add a three-dot button on ROM covers and sidebar consoles to open the menu
- Move the favorite star to the top-left corner of the cover

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

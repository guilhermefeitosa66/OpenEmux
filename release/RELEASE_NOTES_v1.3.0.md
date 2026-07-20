# OpenEmux 1.3.0

Almost everything here comes from one piece of user feedback. Someone finished Aladdin on SNES with OpenEmux and then wrote down exactly what got in their way. That list became this release.

## ROMs inside .zip archives

The scanner recognizes ROMs inside `.zip` archives. The archive stays compressed and is handed to RetroArch, which loads it natively for cores that read ROM data from memory (snes9x, Nestopia, mGBA, Genesis Plus GX and others). Zipped ROMs list under the inner file's name, so cover lookups keep matching the real game title.

Cores flagged `needs_fullpath` — the disc-based systems (`PS`, `PSP`, `SATURN`, `MCD`, `PCECD`, `GC`) — open a path themselves, so RetroArch's internal archive support does not apply to them. Importing a `.zip` for one of those **extracts** it instead, flattening inner folders so a `.cue`'s track references still resolve, and the import reports the unpacking rather than leaving the difference invisible.

`.7z` is not supported: it would require `py7zr`, which the project does not vendor.

## Importing ROMs from the UI

- **Import ROMs** and **Sync covers** buttons in the main window header bar.
- **Drag and drop** ROMs anywhere onto the window, including onto the empty-library screen.
- Directories are walked recursively; archives are routed by their inner contents.
- Byte-identical duplicates are skipped; differing files are renamed `name (2).ext`.
- Importing from the **All** or **Favorites** view asks which console to file under, defaulting to automatic detection so mixed batches still resolve per file.

## Controller mapping with the controller

Input mapping was keyboard-only. You can now capture a binding by pressing the button on the pad. The reader talks to evdev directly with no new dependencies and reproduces the button and axis numbering used by RetroArch's `udev` joypad driver, so a captured binding matches what the emulator sees.

**Up to four gamepad ports**, each configured independently and opt-in per port. Global hotkeys stay on port 1 — RetroArch keeps a single global hotkey set, so emitting them from port 2 would clobber port 1.

Note: capture for port N listens to the Nth pad in `/dev/input/event*` order. That ordering matches RetroArch's udev enumeration but is not guaranteed to match its port assignment. With fewer pads connected than the port you picked, capture refuses explicitly rather than reading the wrong pad.

## ScreenScraper cover source (opt-in)

An optional second cover source alongside libretro thumbnails, including **cartridge label** art. The libretro path is unchanged and remains the default.

**This requires credentials to work.** The ScreenScraper API v2 mandates developer credentials (`devid`/`devpassword`) on every request; anonymous access is not possible and OpenEmux ships none. Each user also needs their own account, otherwise requests draw on a very small shared quota. The integration is complete and tested but inert until credentials are supplied — which is why it is off by default.

## Everything else

- **Cover sync can be stopped** while it runs. Cancellation is polled between ROMs and between candidate URLs, so stopping costs at most one in-flight request. Covers already downloaded are kept, and the remaining ROMs are not counted as errors.
- **Tips status bar** at the bottom of the window, marked with 💡, rotating through real shortcuts derived from the live key bindings. Translated to all seven supported languages and switchable off in Preferences → System.
- **Fullscreen toggle** is now a rebindable action in the input mapping (`input_toggle_fullscreen`, default `F`) instead of a fixed RetroArch default.
- **Right-click a ROM → Show in file manager**, which selects the file itself via the freedesktop FileManager1 interface rather than just opening its folder.
- **Right-click a console in the sidebar** for rescan, import, cover sync and open folder, scoped to that console.
- **Console icons** in the preference selectors and on the BIOS page.

## Fixes

- Zipped ROMs were indexed but discarded when the playlist was read, so they never appeared in the library and a manual rescan did not help.
- Console dropdowns stuttered while scrolling: icons were re-read and re-decoded from disk on every list-item bind. They are now decoded once into a cached texture.
- The cover-sync and import progress banners rendered their counter twice, as `(3/40) (3/40)`.
- The longest cover-source option was ellipsized and unreadable.

## Downloads

| Package | Requirements |
|---|---|
| AppImage | Any x86_64 Linux |
| `.deb` | Ubuntu 24.04+ / Debian with libadwaita 1.5+ |
| `.rpm` | Fedora 40+ |

On older distributions, use the AppImage.

**Full changelog:** https://github.com/guilhermefeitosa66/OpenEmux/compare/v1.2.0...v1.3.0

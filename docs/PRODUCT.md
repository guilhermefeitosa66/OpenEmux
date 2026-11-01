# OpenEmux — Product direction

This document says what OpenEmux is, what it deliberately is not, and how its
interface looks and speaks. Read it before proposing a change to the
experience: a pull request can be technically sound and still pull the app
somewhere it is not meant to go, and reviews point here when that happens.

It describes the app as it is today. Where the code falls short of a rule (and
in a few places it does), the gap is written down next to the rule instead of
being hidden. For *how* to contribute (branches, commits, what a complete pull
request contains) read [CONTRIBUTING.md](../CONTRIBUTING.md); for how to build
and run the app, the [Developer Guide](DEVELOPMENT.md).

## Product vision

**OpenEmux is a library first.** You browse a cover-art library of the games
you own, pick one and play. Everything else (scanning, covers, cores, input
profiles, shaders) exists to make those three steps feel effortless, and the
frontend gets out of the way once the game starts: the in-game controls live
inside RetroArch, not in a second layer on top of it (see
[the in-game controls live inside RetroArch](DEVELOPMENT.md#the-in-game-controls-live-inside-retroarch)).

**It is inspired by OpenEmu.** OpenEmu made retro gaming on the Mac feel
effortless and beautiful; OpenEmux brings a similar experience to the Linux
desktop, and to Windows through the same GTK/libadwaita interface. It is not a
fork, uses no OpenEmu code, and is not affiliated with or endorsed by the
OpenEmu Team; the console icons are OpenEmu's artwork, redistributed under its
BSD license. The README states the relationship in full, and that statement is
the reference:
[OpenEmux and OpenEmu](../README.md#openemux-and-openemu). The Android app is
an independent design; everything below the "Design system" heading is about
the desktop app.

**Who it is for.** People who have their own games and want a simple,
good-looking library on their desktop, with a controller in hand and no config
file in sight. It is not built for people who want to tune emulators: they
already have RetroArch, and OpenEmux never stands between them and it.

## Principles

- **Simplicity and clarity over options.** A new setting is a cost every user
  pays in reading, and a new screen more so. When a choice can be made well on
  the user's behalf, make it.
- **Sane defaults: it works after first boot.** The first-boot bootstrap
  creates the directories, seeds the input profiles and playlists and downloads
  the libretro cores, so a user with ROMs can play without opening Preferences.
  A feature that only works after configuration is not finished.
- **Plain, literal naming.** "Black", not "Onyx"; "Red", not "Crimson". The
  cartridge colors are the live example: black, white, red, blue, green,
  yellow, orange, purple, pink, teal, gold and clear. A name says what the
  thing is, in words a user already knows.
- **Offline-first and private.** No OpenEmux account, no telemetry, no ads.
  The network is used for things the user can see and trace back to an action
  or a setting: downloading cores and shaders (libretro Buildbot), cover art
  (libretro thumbnails, the project's artwork mirror, ScreenScraper), the
  update check, and the optional services a user signs into themselves
  (ScreenScraper, RetroAchievements). The library, the config and the play
  history stay on the machine.
- **RetroArch/libretro is the only emulation backend.** OpenEmux launches
  RetroArch (bundled or the system's) with a libretro core. Plans for embedded
  cores were evaluated and dropped; optimizing how RetroArch is used is the
  direction.
- **No ROMs, no BIOS, ever.** OpenEmux plays the games you own. It does not
  ship, download, link to or help find game or BIOS files.
- **UI and logic stay apart.** GTK and libadwaita code lives in
  `src/openemux/ui/`, everything else in `src/openemux/core/`, so the logic is
  tested without a display and the interface stays a thin layer over it.

## Non-goals

These are directions the project has ruled out. A pull request toward one of
them will be declined however well it is written, so raise it in an issue
first if you think the reasoning should change.

- **A RetroArch settings panel.** OpenEmux exposes what a library user needs.
  Per-console core choice, input mapping and shaders are the ceiling of what it
  configures, not a floor to build up from. Anything beyond that is RetroArch's
  own menu, one hotkey away in game.
- **A generic launcher.** It is not a frontend for Steam, native Linux games or
  arbitrary executables.
- **A different toolkit.** No web, Electron or Qt interface, and no second UI
  stack next to GTK 4 and libadwaita.
- **Heavy new frameworks or runtime dependencies.** Each one is something every
  package format (AppImage, .deb, .rpm, Arch, Flatpak, Windows) has to ship and
  keep working. A small, well-maintained library for a real need is fine,
  discussed in an issue; a framework is not.
- **Accounts or cloud services of its own.** No sign-in, no sync service, no
  server the project would have to run.
- **ROM or BIOS sourcing,** in any form (see Principles).

## Design system

The desktop app follows the
[GNOME Human Interface Guidelines](https://developer.gnome.org/hig/) and is
built from libadwaita. The rule that governs everything below: **prefer a stock
Adwaita widget or style class over custom code or CSS.** Custom styling exists
only where Adwaita has nothing to offer, and `style.css` says so in its first
line.

### Structure

The window is one shape, everywhere:

- `Adw.ApplicationWindow` → `Adw.ToastOverlay` → `Adw.NavigationSplitView`,
  with the console list as the sidebar (260–360 px wide, 28% of the window) and
  the library as the content (`src/openemux/ui/window.py`,
  `src/openemux/ui/console_sidebar.py`).
- Each pane is an `Adw.NavigationPage` holding an `Adw.ToolbarView` with an
  `Adw.HeaderBar`. Primary actions sit in the header bar; the primary menu
  holds Settings, Keyboard Shortcuts, Welcome, Report a Bug… and About
  OpenEmux.
- Settings live in one `Adw.PreferencesDialog` built from
  `Adw.PreferencesGroup`s and stock rows: `ActionRow`, `ComboRow`, `SwitchRow`,
  `SpinRow`, `EntryRow`, `PasswordEntryRow`, `ExpanderRow`
  (`src/openemux/ui/preferences.py`). A new setting is a row in an existing
  group before it is a new group, and a new group before it is a new page.
- Empty states are `Adw.StatusPage`s: an icon, one line saying what is
  missing, and the action that fixes it (`src/openemux/ui/library_pages.py`).
  Today they stop short of that: none carries an action button, and a
  console's empty page shows its playlist path as the description. New empty
  states follow the rule, and existing ones gain the action when a change
  touches them.
- The welcome tour is an `Adw.Carousel` inside an `Adw.Clamp`
  (`src/openemux/ui/welcome.py`).

Telling the user something has one right widget for each situation:

| Situation | Widget |
|---|---|
| Something happened and needs no answer ("Cover saved") | `Adw.Toast` |
| Something is still true or still running (a scan, a sync, an available update) | `Adw.Banner` (`src/openemux/ui/task_banner.py`) |
| The user has to decide, or the action destroys something | `Adw.AlertDialog` |

### Color and themes

- **No custom palette.** `style.css` defines no theme colors of its own; it uses
  Adwaita's named colors (`@accent_bg_color`, `@window_bg_color`,
  `@card_bg_color`, `@headerbar_bg_color`, `@warning_color`, `@error_bg_color`
  and so on), with tints made by `alpha()`. That is what keeps the app right in
  both themes and with every accent color the desktop offers.
- **The exceptions are few and deliberate:** the favorite gold (`#f6c90e`),
  and the white glyphs, dark scrims and drop shadows laid over cover art,
  which have to read on any image rather than on the theme. A new hard-coded color needs the same kind of reason.
- **Light and dark come from Adwaita.** There is no dark-specific CSS. The
  user's choice (System, Light, Dark; `ui.theme` in the config) is applied by
  `src/openemux/ui/theming.py`, the only module that sets the color scheme; the
  window only listens for the dark flag to keep its theme button's icon right.

### Spacing, shape and type

- **Spacing and padding** come from Adwaita's containers and style classes
  first. Where `style.css` sets padding, it uses small steps (mostly 4, 6, 8
  and 12 px); match the rule next to the one you are adding.
- **Corners** are 5–13 px, with 8 px the most common, and pills use `999px`.
- **Type** comes from Adwaita's style classes: `title-1`…`title-4`,
  `heading`, `caption`, `dim-label`, `monospace`. The only custom font sizes
  are the small ones already present (0.8–0.95em, for badges and key hints).
  Do not add a new size to get emphasis; use a class.
- **Reuse the existing custom classes** before adding one. They come in a
  handful of families, each with its own heading in `style.css`: the ROM cards
  and list rows (`.rom-card`, `.rom-row`, `.rom-cover`, `.rom-title`, …), the
  play overlay and badges on cover art, the console list's drag-and-drop
  markers, the tip bar and its key caps (`.tip-bar`, `.hint-key`), the context
  menus, and the log panel.

### Iconography

- **Symbolic icons** (`*-symbolic`) from the icon theme for every control.
  Each name the app uses also has a bundled fallback in
  `src/openemux/ui/assets/icons/symbolic/`, so it renders on a desktop whose
  theme lacks it; `tests/test_icon_assets.py` keeps that set complete.
- **Console icons** are OpenEmu's artwork, in
  `src/openemux/ui/assets/icons/systems/`, credited in
  [ATTRIBUTION.md](../src/openemux/ui/assets/icons/ATTRIBUTION.md).
- **Cartridge frames** are one SVG per console in
  `src/openemux/ui/assets/images/cartridges/`, each in twelve color variants
  plus the default.
- No new non-symbolic icon set, and no icon font.

### Adaptive layout

The window adapts at one breakpoint, in `src/openemux/ui/window.py`:

- **Below 550sp** the split view collapses into one pane with navigation
  between them, and the per-console settings buttons leave the content header.

The window's minimum size is 360 × 420 px, so every view, dialog and new
control must work at 360 px wide. Check with `make devbox-res RES=520x900`
(and narrower) in the [devbox](DEVELOPMENT.md).

### Accessibility

- **Every action is reachable without a mouse**, by keyboard and by gamepad
  (`src/openemux/ui/navigation.py`). An action with an accelerator is listed in
  the Keyboard Shortcuts window.
- **Focus rings** for keyboard and gamepad navigation are drawn only while it
  is in use: the window carries `.keynav-active` and the custom focus styles
  hang off that class.
- **Contrast follows the theme** because colors are Adwaita's named colors (see
  above); a hard-coded color is also a contrast risk.
- **Icon-only controls have a tooltip** today, and that is the whole baseline:
  the app sets no explicit accessible names or descriptions yet. New code gives
  every icon-only control both a tooltip and an accessible label, and existing
  controls gain one when a change touches them.

### Writing for the UI

- **Sentence case** for new strings: "Sync covers", "Add to playlist". Older
  labels in Title Case still exist ("Console Order", "Cores per Console");
  convert them when a change touches them, not in a sweep of their own.
- **Short, literal, no jargon.** Say what the user gets, not what RetroArch
  calls it: "Settings", not an option name from `retroarch.cfg`.
- **Typography:** a real ellipsis "…" (not three dots) for actions that open a
  dialog and for work in progress; curly quotes and apostrophes. Some older
  strings still use "..."; the same convert-when-touched rule applies.
- **Every string is translatable.** It goes through `tr()` with a key present in
  all eight locales in `src/openemux/i18n/locales/`, translated for real.
  English is the source of truth.

## Contribution fit

**Welcome without discussion** (open the pull request directly):

- bug fixes;
- corrections to existing translations (a new language is claimed through
  the translation form first, see [CONTRIBUTING.md](../CONTRIBUTING.md));
- polish that brings the app closer to this document (a missing tooltip, a
  Title Case label, a hard-coded color that has an Adwaita name);
- tests and documentation.

**Open an issue first** (and wait for a reply) for anything that changes the
experience: a new screen, setting or workflow, a new dependency, a new network
call or service, a change to how games are launched, or anything that touches
a principle or non-goal above.

**The quality bar** for every pull request, whichever list it is on:

- 100% coverage of the code it adds;
- [`tests/regression/TESTBOOK.md`](../tests/regression/TESTBOOK.md) updated
  when user-facing behavior changes;
- every new string in every locale;
- a UI change seen running, in the devbox, not only in the test suite;
- the commit format and credit rules in [CONTRIBUTING.md](../CONTRIBUTING.md).

A change to the design system itself (a new widget pattern, a new custom
class family, a new breakpoint) updates this document in the same pull
request, so it keeps describing the app as it is.

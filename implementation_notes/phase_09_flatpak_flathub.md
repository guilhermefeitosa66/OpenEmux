# Phase 09 — Flatpak packaging & Flathub submission

Status: **packaging complete, builds & runs**; ready to submit once a release
tag is cut. App ID: **`io.github.guilhermefeitosa66.OpenEmux`**.

## What was built

- **`pyproject.toml`** — makes `openemux` a pip-installable package (src-layout)
  with a console entry point (`openemux = openemux.main:main`), dynamic version from
  `openemux.__version__`, and packaged UI assets/CSS/i18n. PyGObject/pycairo come
  from the GNOME runtime, so only **PyYAML** is a declared dependency.
- **`packaging/flatpak/`**:
  - `io.github.guilhermefeitosa66.OpenEmux.yaml` — the manifest.
  - `…​.metainfo.xml` — AppStream metadata (passes `appstreamcli validate`).
  - `…​.desktop` — desktop entry (passes `desktop-file-validate`).
  - `…​.png` — 512×512 square icon.
  - `python3-pyyaml.yaml` — offline PyYAML source (pinned sdist + sha256).
- **App-side Flatpak awareness** (guarded, native/AppImage behavior unchanged):
  - `core/paths.py`: `is_running_in_flatpak()`, `get_real_home()`.
  - `core/retroarch_launcher.py`: in a sandbox, launch RetroArch via
    `flatpak-spawn --host flatpak run org.libretro.RetroArch`, resolving cores
    from the RetroArch Flatpak's dir under the real home.
  - `core/config.py`: default ROMs path under the real home; buildbot core
    updater disabled in Flatpak.
  - `core/first_boot.py`: skip the core/shader download step in Flatpak.
  - `main.py`: skip self-installed desktop integration in Flatpak.

## Architecture decision: delegate to the RetroArch Flatpak

RetroArch is **not bundled**. The official `org.libretro.RetroArch` Flatpak is
built on the KDE/Qt runtime, while OpenEmux needs the GNOME runtime — bundling
RetroArch from source would mean porting it + its cores onto a foreign runtime
(large, fragile, and duplicates an existing Flathub app). Instead OpenEmux
launches the RetroArch Flatpak on the host via `flatpak-spawn`; RetroArch manages
its own cores (users download them via RetroArch's Online Updater). Verified:
`flatpak-spawn` is present in the sandbox, and with `--filesystem=home` the
sandbox's `$HOME` is the real home, so OpenEmux and RetroArch see the same
absolute ROM/core paths.

**Users must install RetroArch:** `flatpak install flathub org.libretro.RetroArch`
(stated in the metainfo description).

## Build & run locally (verified working)

```bash
flatpak install -y --user flathub org.gnome.Platform//50 org.gnome.Sdk//50 org.flatpak.Builder
flatpak run org.flatpak.Builder --user --force-clean --install \
  .flatpak-build-dir packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml
flatpak run io.github.guilhermefeitosa66.OpenEmux
```
Confirmed: PyYAML builds offline, `pip install .` installs the app into `/app`,
the metainfo/desktop/icon export, and the app launches and loads the library.

To iterate against **uncommitted** changes, temporarily set the `openemux` module
source in the manifest to `- type: dir` / `path: ../..` instead of the git source.

## Linter status

`flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest <file>`
passes except three items, all expected:

| Item | Why | Action |
|------|-----|--------|
| `finish-args-home-filesystem-access` | `--filesystem=home` for the ROM library + cover writing | Justify in the PR (routine for library managers) |
| `finish-args-flatpak-spawn-access` | `--talk-name=org.freedesktop.Flatpak` to launch the RetroArch Flatpak | Justify in the PR |
| `appstream-external-screenshot-url` | Screenshots point at GitHub raw URLs | Flathub's build pipeline mirrors screenshots automatically; no action, or self-host later |

## Before submitting to Flathub
1. **Cut a release** that includes this packaging (e.g. tag `v1.1.0`) and set the
   manifest's `openemux` module source to that `commit:` (and matching `tag:`). It
   is currently pinned to the rename commit on `main`.
2. Optionally bump `openemux.__version__` + metainfo `<releases>` for the new tag.

## Flathub submission steps
1. Fork `flathub/flathub`; `git clone --branch=new-pr git@github.com:<you>/flathub.git`.
2. `git checkout -b io.github.guilhermefeitosa66.OpenEmux new-pr`.
3. Copy in the manifest + local sources (`python3-pyyaml.yaml`); the manifest's
   git source already points at this repo.
4. Commit, push, and open a PR **targeting `new-pr`**, titled
   `Add io.github.guilhermefeitosa66.OpenEmux`. In the PR description, justify the
   `--filesystem=home` and `flatpak-spawn` permissions (RetroArch delegation).
5. Comment `bot, build` to trigger the test build; iterate on reviewer feedback.

## Notes
- A test build is installed locally as `io.github.guilhermefeitosa66.OpenEmux`;
  remove with `flatpak uninstall --user io.github.guilhermefeitosa66.OpenEmux`.
- The app ID was renamed from `org.openemux.OpenEmux` (which would require owning
  openemux.org) to the code-hosting ID, updated across code + AppImage + Flatpak.
  The already-published v1.0.0 GitHub release/AppImage keep the old ID; the next
  AppImage build will use the new ID.

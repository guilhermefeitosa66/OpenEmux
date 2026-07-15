# Phase 07: First-Boot Bootstrap

## Goal
Deliver a transparent first-run setup that prepares OpenEmux and RetroArch with minimal user friction.

## Scope
- Detect first boot and run a blocking setup flow before opening the main library UI.
- Ensure `~/.openemux` baseline is fully created (config, runtime dir, playlists, input profiles).
- Ensure ROM canonical folder tree exists (`<roms>/<SYSTEM>/`, `<roms>/<SYSTEM>/covers`, `<roms>/<SYSTEM>/bios`).
- Run a RetroArch core bootstrap using official Buildbot endpoints and install all available Linux x86_64 cores.
- Expose progress to users via loading window and step/status subtitles.
- Persist setup status for retry and observability.

## Delivered
- New `FirstBootBootstrapper` orchestrating setup steps with persisted state.
- New `RetroArchBuildbotUpdater` for manifest parsing + downloads + core installation.
- First-boot loading window with progress updates and localized status labels.
- Startup integration in app activation flow:
  - run bootstrap when pending
  - open app normally when completed
  - allow retry via Settings > System
- Bootstrap status persisted in `config.yaml` (`setup.bootstrap.*`).

## Failure Policy
- If setup fails (network/offline/partial updater failures), OpenEmux continues to open.
- Bootstrap state is marked `failed` and can be retried from Settings > System.

## Next
- Add optional "core subset only" mode to reduce first-boot duration.
- Add checksum/signature validation for downloaded core artifacts.
- Add optional background-only mode for non-blocking first boot.


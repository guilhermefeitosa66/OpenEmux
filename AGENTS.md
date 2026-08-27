# Repository Guidelines

## Project Structure & Module Organization
- `src/openemux/` holds the Python package.
- `src/openemux/core/` contains core logic (config, scanning, playlists, runtime, covers, input mapping).
- `src/openemux/ui/` contains GTK4 UI code, widgets, assets, and styling (`style.css`).
- `vendors/` hosts runtime artifacts (RetroArch AppImage).
- `tests/` contains unit tests for core modules (`scanner`, `cover_sync`, `input_actions`, `input_profiles`).
- Root scripts and build metadata live in `Makefile`, `run.sh`, and `requirements.txt`.

## Build, Test, and Development Commands
- `make bootstrap` installs system dependencies, creates the venv, and installs Python deps.
- `make run` runs the app with `PYTHONPATH=src` and the project venv.
- `make check-retroarch` validates RetroArch availability (vendored AppImage or system binary).
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` runs the unit test suite.
- `make clean` removes the venv and `__pycache__` directories.
- `./run.sh` runs the app with the system Python (useful for quick local checks).

## Coding Style & Naming Conventions
- Python code uses 4-space indentation and PEP 8-style naming (`snake_case` for functions/vars, `PascalCase` for classes).
- Modules are organized by responsibility (`core` vs `ui`). Keep UI logic in `src/openemux/ui/` and non-UI logic in `src/openemux/core/`.
- No formatter or linter is configured yet; keep changes small and readable and avoid reformatting unrelated code.

## Testing Guidelines
- There is an automated unit test suite under `tests/` using Python `unittest`.
- Run tests with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
- When changing UI/runtime behavior, still do a manual smoke test via `make run` and exercise the flow you touched.

## Commit & Pull Request Guidelines
- Existing commits use short conventional summaries such as `fix: ...`, `feat: ...`, `refactor: ...`, `chore: ...`, `Phase N: ...`, or `Initial commit: ...`. Follow this style for consistency.
- Keep commits focused (one logical change per commit).
- PRs should include a concise summary, testing notes (or “not run”), and screenshots for UI changes.

## Configuration Tips
- Default ROM path is `~/games/roms/` (configurable in the app config).
- The library now uses canonical system folders (e.g., `FC`, `SFC`, `GBA`, etc.) and supports many additional systems via `src/openemux/core/systems.py`.
- Runtime defaults to RetroArch. Configure `runtime.retroarch.binary` and `runtime.retroarch.cores` in `~/.openemux/config.yaml` if auto-detection does not match your system.
- Input profiles are stored per console in `~/.openemux/input/<CONSOLE>.config`.

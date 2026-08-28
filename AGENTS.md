# Repository Guidelines

## Project Structure & Module Organization
- `src/openemux/` holds the Python package.
- `src/openemux/core/` contains core logic (config, scanning, playlists, runtime, covers, input mapping).
- `src/openemux/ui/` contains GTK4 UI code, widgets, assets, and styling (`style.css`).
- `vendors/` hosts runtime artifacts (RetroArch AppImage).
- `tests/` contains the unit suite: the `core/` modules plus the UI logic that imports cleanly headless. It needs the GTK4/Adwaita typelibs — see [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md#tests).
- Root scripts and build metadata live in `Makefile`, `pyproject.toml`, and the `requirements*.lock` files.

## Build, Test, and Development Commands
- `make bootstrap` installs system dependencies, creates the venv, and installs Python deps.
- `make run` runs the app with `PYTHONPATH=src` and the project venv.
- `make check-retroarch` validates RetroArch availability (vendored AppImage or system binary).
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` runs the unit test suite.
- `make lint` runs the correctness-only ruff configuration that CI gates on.
- `make clean` removes the venv and `__pycache__` directories.

## Coding Style & Naming Conventions
- Python code uses 4-space indentation and PEP 8-style naming (`snake_case` for functions/vars, `PascalCase` for classes).
- Modules are organized by responsibility (`core` vs `ui`). Keep UI logic in `src/openemux/ui/` and non-UI logic in `src/openemux/core/`.
- No formatter, deliberately, and the linter (`make lint`) is correctness-only: it has no opinion about quotes, line length or import order. Keep changes small and readable and avoid reformatting unrelated code.

## Testing Guidelines
- There is an automated unit test suite under `tests/` using Python `unittest`.
- Run tests with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
- When changing UI/runtime behavior, exercise the flow you touched in the real app. Use the devbox
  (`make devbox-app`, `make devbox-shot`) rather than `make run`, which takes the developer's screen —
  see [`devbox/README.md`](devbox/README.md). `make smoke` is the automated version: it starts the app,
  waits for the window and quits.
- Any change to user-facing behavior updates `tests/regression/TESTBOOK.md` in the same PR.

## Commit & Pull Request Guidelines
- Commits are `[issue-<id>] <type>: <summary>` — the issue reference first, then Conventional Commits (`fix:`, `feat:`, `refactor:`, `chore:`). Work with no issue behind it uses `[no-issue]`.
- Keep commits focused (one logical change per commit).
- PRs should include a concise summary, testing notes (or “not run”), and screenshots for UI changes.

## Configuration Tips
- Default ROM path is `~/games/roms/` (configurable in the app config).
- The library now uses canonical system folders (e.g., `FC`, `SFC`, `GBA`, etc.) and supports many additional systems via `src/openemux/core/systems.py`.
- Runtime defaults to RetroArch. Configure `runtime.retroarch.binary` and `runtime.retroarch.cores` in `~/.openemux/config.yaml` if auto-detection does not match your system.
- Input profiles are stored per console in `~/.openemux/input/<CONSOLE>.config`.

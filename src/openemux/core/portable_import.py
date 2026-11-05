"""Bring the data of an installed OpenEmux into a portable folder (issue #768).

Someone who ran the installer, or an older zip, has everything in
``%USERPROFILE%\\.openemux``. The portable zip offers to copy it into its own
``data\\`` folder: on the first start of an empty portable folder, and from
Preferences afterwards.

The profile is only ever read. The copy goes to a staging directory beside the
target, the paths that pointed into the profile are rewritten there, and a
manifest written *last* says the copy is complete. Only then is it swapped in,
by :func:`apply_pending_import`, at the start of the next process (or by the
first-start offer, before anything else holds the folder): a store keeps
caches in memory while the app runs, and Windows refuses to rename a folder
with a file open in it. An interrupted copy has no manifest and is thrown away,
so a working portable folder is never replaced by half of one.

Everything here is a no-op off a portable install.
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from openemux.core import paths
from openemux.core.atomic_write import atomic_write_lines, atomic_write_text
from openemux.core.paths import (
    PATH_ERRORS,
    PORTABLE_DATA_DIR,
    STORE_FILENAMES,
    portable_root,
    profile_config_dir,
    profile_roms_dir,
)

logger = logging.getLogger(__name__)

#: The two folders an import brings in, as they are named under ``data\\``.
CONFIG_NAME = "openemux"
ROMS_NAME = "roms"

#: Beside the targets, under ``data\\``.
STAGING_DIR = "openemux.import-staging"
BACKUP_SUFFIX = ".before-import"

#: Written last into the staging directory: without it the copy is not done.
MANIFEST = "import.json"

#: Left in the imported config dir; the start after it drops the backups.
DONE_MARKER = "import.done"

#: Regenerated on every run (per-launch files, download caches), not data.
SKIPPED_DIRS = ("runtime", "cache")

#: Room left on the disk after the copy, so the app can still write a log.
SPACE_MARGIN = 64 * 1024 * 1024

#: The stores keyed by ROM path, under ``rom_overrides`` (YAML).
ROM_KEYED_YAML = ("cores", "shaders", "cartridge_colors")

#: First-boot steps an import owes again: they set up the profile's RetroArch.
REOPENED_BOOTSTRAP_STEPS = ("retroarch_environment", "retroarch_download_all_cores")


class PortableImportError(Exception):
    """An import that did not happen, and why.

    ``reason`` is ``"no_space"`` (``needed`` and ``free`` in bytes) or
    ``"failed"`` (the message is the OS error, for the user to read).
    """

    def __init__(self, reason, message="", needed=0, free=0):
        super().__init__(message or reason)
        self.reason = reason
        self.needed = needed
        self.free = free


@dataclass
class ImportPlan:
    """What an import copies: ``(source file, path under the staging dir)``."""

    config_source: Path
    roms_source: Path = None
    files: list = field(default_factory=list)
    dirs: list = field(default_factory=list)
    total_bytes: int = 0


def importable_profile():
    """The profile's config dir when a portable install could import it.

    ``None`` off a portable install, or when the profile holds no
    ``config.yaml`` -- nothing there is an OpenEmux library.
    """
    if portable_root() is None:
        return None
    source = profile_config_dir()
    return source if (source / STORE_FILENAMES["config"]).is_file() else None


def profile_roms_folder():
    """The profile's default ROM folder, when it exists and could be copied."""
    if portable_root() is None:
        return None
    source = profile_roms_dir()
    return source if source.is_dir() else None


def should_offer_on_first_start(config_manager):
    """Whether the first start of this portable folder asks to import.

    Only before the first boot has filled the folder, and only until the user
    has said no once (Preferences still offers it).
    """
    return (
        importable_profile() is not None
        and config_manager.bootstrap_needs_run()
        and not config_manager.get_portable_import_dismissed()
    )


def folder_size(folder):
    """Bytes in the regular files under ``folder``; symlinks are not followed."""
    total = 0
    for _rel_dir, _dirs, files in _walk(Path(folder)):
        for _rel, size in files:
            total += size
    return total


def _walk(folder, skipped=()):
    """``(relative dir, [relative subdirs], [(relative file, size)])`` per dir.

    ``skipped`` names top-level folders left out. Symlinks are neither
    followed nor copied: one into the profile would copy it twice, one out of
    it would copy whatever it points at.
    """
    for current, dirs, files in os.walk(folder, followlinks=False):
        current = Path(current)
        rel_dir = current.relative_to(folder)
        if rel_dir == Path("."):
            dirs[:] = [d for d in dirs if d not in skipped]
        dirs[:] = [d for d in dirs if not (current / d).is_symlink()]
        entries = []
        for name in files:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            entries.append((rel_dir / name, path.stat().st_size))
        yield rel_dir, [rel_dir / d for d in dirs], entries


def plan_import(include_roms=False):
    """What importing the profile would copy, or ``None`` with nothing to import."""
    source = importable_profile()
    if source is None:
        return None
    plan = ImportPlan(config_source=source)
    sources = [(source, CONFIG_NAME, SKIPPED_DIRS)]
    roms = profile_roms_folder() if include_roms else None
    if roms is not None:
        plan.roms_source = roms
        sources.append((roms, ROMS_NAME, ()))
    for folder, name, skipped in sources:
        plan.dirs.append(Path(name))
        for rel_dir, subdirs, files in _walk(folder, skipped):
            plan.dirs.extend(Path(name) / d for d in subdirs)
            for rel, size in files:
                plan.files.append((folder / rel, Path(name) / rel))
                plan.total_bytes += size
    return plan


def check_free_space(plan):
    """Raise :class:`PortableImportError` when the copy would not fit."""
    needed = plan.total_bytes + SPACE_MARGIN
    free = shutil.disk_usage(portable_root()).free
    if free < needed:
        raise PortableImportError("no_space", needed=needed, free=free)


def staging_dir():
    root = portable_root()
    return None if root is None else root / PORTABLE_DATA_DIR / STAGING_DIR


def run_import(plan, progress=None):
    """Copy ``plan`` into the staging directory, ready for the next start.

    ``progress(copied_bytes, total_bytes)`` is called after every file, from
    the calling thread. Raises :class:`PortableImportError`; whatever went
    wrong, no staging directory is left behind and the portable folder is
    exactly as it was.
    """
    check_free_space(plan)
    staging = staging_dir()
    try:
        if staging.exists():
            shutil.rmtree(staging)
        for rel in plan.dirs:
            (staging / rel).mkdir(parents=True, exist_ok=True)
        copied = 0
        for source, rel in plan.files:
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
            copied += source.stat().st_size
            if progress is not None:
                progress(copied, plan.total_bytes)
        rewrite_paths(staging / CONFIG_NAME, import_mapping(plan))
        manifest = {
            "config_source": str(plan.config_source),
            "roms_source": str(plan.roms_source) if plan.roms_source else None,
            "files": len(plan.files),
            "bytes": plan.total_bytes,
            "created_at": time.time(),
        }
        atomic_write_text(staging / MANIFEST, json.dumps(manifest, indent=2))
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise PortableImportError("failed", str(exc)) from exc
    logger.info(
        "portable import staged: files=%d bytes=%d roms=%s",
        len(plan.files),
        plan.total_bytes,
        plan.roms_source is not None,
    )


def import_mapping(plan):
    """``[(old absolute folder, the folder it becomes)]`` for the rewrite."""
    data = portable_root() / PORTABLE_DATA_DIR
    mapping = [(plan.config_source, data / CONFIG_NAME)]
    if plan.roms_source is not None:
        mapping.append((plan.roms_source, data / ROMS_NAME))
    return mapping


def _same_part(left, right):
    # Windows paths are case-insensitive; portable mode only exists there,
    # and the suite fakes it on Linux.
    if paths.IS_WINDOWS:
        return left.casefold() == right.casefold()
    return left == right


def remap_path(value, mapping):
    """``value`` moved from an old folder to its new one, in stored form.

    Matched on whole path components, so ``.openemux2`` is not inside
    ``.openemux``. A path outside every old folder -- ROMs on another disk --
    and anything that is not an absolute path come back untouched.
    """
    if not isinstance(value, str) or not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        return value
    parts = path.parts
    for old, new in mapping:
        old_parts = Path(old).parts
        if len(parts) < len(old_parts):
            continue
        if all(_same_part(a, b) for a, b in zip(parts, old_parts)):
            return paths.to_stored_path(Path(new).joinpath(*parts[len(old_parts):]))
    return value


def rewrite_paths(config_dir, mapping):
    """Rewrite, in a copied config dir, every stored path the mapping moves.

    The stores part 2 made portable (issue #767): the path settings of
    ``config.yaml``, every ``.list`` file (console playlists, favorites,
    collections), the per-game stores keyed by ROM path and the play history.
    A file that does not parse is left as it is; its store quarantines it on
    load, as it would have in the profile.
    """
    config_dir = Path(config_dir)
    _rewrite_config(config_dir / STORE_FILENAMES["config"], mapping)
    for list_file in sorted(config_dir.rglob("*.list")):
        _rewrite_list(list_file, mapping)
    for name in ROM_KEYED_YAML:
        _rewrite_rom_keyed_yaml(config_dir / STORE_FILENAMES[name], mapping)
    _rewrite_play_history(config_dir / STORE_FILENAMES["play_history"], mapping)


def _load_yaml(path):
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _rewrite_config(path, mapping):
    from openemux.core.config import PATH_SETTINGS

    config = _load_yaml(path)
    if config is None:
        return
    for keys in PATH_SETTINGS:
        section = config
        for key in keys[:-1]:
            section = section.get(key)
            if not isinstance(section, dict):
                break
        else:
            if keys[-1] in section:
                section[keys[-1]] = remap_path(section[keys[-1]], mapping)
    _reopen_retroarch_bootstrap(config)
    # Its first boot is pending again, which alone would ask to import once more.
    portable = config.get("portable")
    if not isinstance(portable, dict):
        portable = config["portable"] = {}
    portable["import_offer_dismissed"] = True
    atomic_write_text(path, yaml.safe_dump(config))


def _reopen_retroarch_bootstrap(config):
    """Owe the first-boot steps that wrote outside the copied folder again.

    The profile's first boot set up *its* RetroArch: the installer's cores
    directory and ``runtime\\``, neither of which is copied. The zip ships its
    RetroArch with an empty ``cores\\``, so an import that kept "done" would
    open a library where nothing launches. The other steps stay done; the
    cores step only fetches what is missing.
    """
    setup = config.get("setup")
    bootstrap = setup.get("bootstrap") if isinstance(setup, dict) else None
    if not isinstance(bootstrap, dict):
        return
    completed = bootstrap.get("completed_steps")
    if isinstance(completed, list):
        bootstrap["completed_steps"] = [
            step for step in completed if step not in REOPENED_BOOTSTRAP_STEPS
        ]
    bootstrap["status"] = "pending"
    bootstrap["retry_requested"] = False


def _rewrite_list(path, mapping):
    with open(path, "r", encoding="utf-8", errors=PATH_ERRORS) as handle:
        lines = [line.strip() for line in handle]
    atomic_write_lines(
        path, [remap_path(line, mapping) for line in lines if line], errors=PATH_ERRORS
    )


def _rewrite_rom_keyed_yaml(path, mapping):
    data = _load_yaml(path)
    if data is None or not isinstance(data.get("rom_overrides"), dict):
        return
    data["rom_overrides"] = {
        remap_path(str(key), mapping): value for key, value in data["rom_overrides"].items()
    }
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=True))


def _rewrite_play_history(path, mapping):
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    data = {remap_path(str(key), mapping): value for key, value in data.items()}
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True))


def apply_pending_import():
    """Swap a staged import in. Runs before anything opens the config dir.

    Returns ``None`` off a portable install or with nothing staged,
    ``"applied"`` once the import is in place, ``"discarded"`` when an
    interrupted copy (no manifest) was thrown away, and ``"failed"`` when a
    rename was refused: everything already moved is put back, and the staged
    copy waits for the next start.
    """
    root = portable_root()
    if root is None:
        return None
    data = root / PORTABLE_DATA_DIR
    _drop_backups_after_import(data)
    staging = data / STAGING_DIR
    if not staging.is_dir():
        return None
    if not (staging / MANIFEST).is_file():
        shutil.rmtree(staging, ignore_errors=True)
        logger.info("portable import discarded: the copy was not finished")
        return "discarded"
    names = [name for name in (CONFIG_NAME, ROMS_NAME) if (staging / name).is_dir()]
    done = []
    try:
        for name in names:
            _swap_one(data, staging, name)
            done.append(name)
    except OSError as exc:
        for name in reversed(done):
            _unswap_one(data, staging, name)
        logger.warning("portable import not applied yet: %s", exc)
        return "failed"
    atomic_write_text(data / CONFIG_NAME / DONE_MARKER, "")
    shutil.rmtree(staging, ignore_errors=True)
    logger.info("portable import applied: %s", ", ".join(names))
    return "applied"


def _swap_one(data, staging, name):
    """``data/<name>`` → backup, staged copy → ``data/<name>``; undone on failure."""
    target = data / name
    backup = data / (name + BACKUP_SUFFIX)
    if backup.exists():
        shutil.rmtree(backup)
    moved_old = False
    if target.exists():
        target.rename(backup)
        moved_old = True
    try:
        (staging / name).rename(target)
    except OSError:
        if moved_old:
            backup.rename(target)
        raise


def _unswap_one(data, staging, name):
    target = data / name
    target.rename(staging / name)
    backup = data / (name + BACKUP_SUFFIX)
    if backup.exists():
        backup.rename(target)


def _drop_backups_after_import(data):
    """The start after an import: it worked, so the old folders can go."""
    marker = data / CONFIG_NAME / DONE_MARKER
    if not marker.is_file():
        return
    for name in (CONFIG_NAME, ROMS_NAME):
        shutil.rmtree(data / (name + BACKUP_SUFFIX), ignore_errors=True)
    marker.unlink()

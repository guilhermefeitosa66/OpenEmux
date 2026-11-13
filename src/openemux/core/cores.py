"""Discover the libretro cores installed on this machine.

The launcher only ever asked "does this specific core exist?". Choosing a core
per console or per ROM needs the other direction: *which* cores are installed,
and which of them can run a given system. This module answers that by scanning
the directories in :func:`core_search_dirs` -- the same list the launcher
resolves Automatic through -- and reading the ``.info`` sidecar files RetroArch
ships, so the picker can show a core's real name ("Snes9x") rather than its
filename.

A core is matched to a console two ways, unioned:

* it is one of the console's curated ``runtime_core_candidates`` (works even
  when no ``.info`` is present, e.g. a Flatpak core directory), or
* its ``.info`` ``database`` field names the console's libretro system, the
  same identifier used for thumbnails.
"""

import copy
import json
import logging
import threading
from pathlib import Path

import yaml

from openemux.core.atomic_write import atomic_write_text
from openemux.core.state_recovery import quarantine_state_file
from openemux.core.paths import from_stored_path, get_real_home, store_path, with_stored_keys
from openemux.core.platform import (
    CORE_SUFFIX,
    bundled_core_dir,
    core_stem,
    system_core_dirs,
    user_retroarch_dirs,
)
from openemux.core.systems import (
    SYSTEM_IDS,
    curated_core_filenames,
    get_runtime_core_candidates,
    get_thumbnail_system,
)

logger = logging.getLogger(__name__)

#: Bump when what the catalog cache stores changes shape.
CATALOG_CACHE_VERSION = 1

# A RetroArch installed as a Flatpak keeps its cores under its own app dir.
RETROARCH_FLATPAK_ID = "org.libretro.RetroArch"

DEFAULT_CORES_CONFIG_FILE = store_path("cores")
DEFAULT_CORES_CONFIG = {
    "version": 1,
    # Per-ROM core overrides keyed by absolute ROM path. The per-console
    # override lives in config.yaml (runtime.retroarch.cores), which the
    # launcher already reads; only the per-ROM level needs its own store.
    "rom_overrides": {},
}


def core_search_dirs(project_root=None):
    """Every directory a core is looked for in, first match wins.

    User config first, then the Flatpak, the vendored bundle, a RetroArch the
    user installed themselves and the distribution's own locations. This is
    the one list: the launcher resolves Automatic through it and the pickers
    list what is installed from it, so a core the launcher would run is a core
    the pickers can offer.
    """
    real_home = get_real_home()
    dirs = [
        real_home / ".config" / "retroarch" / "cores",
        real_home / ".var" / "app" / RETROARCH_FLATPAK_ID / "config" / "retroarch" / "cores",
    ]
    if project_root:
        dirs.append(Path(project_root) / "vendors" / "retroarch-assets" / "cores")
        # The bundled Windows RetroArch runs portable, so it keeps its cores
        # beside the executable. That is also where the updater downloads them,
        # which is what leaves a user's own RetroArch install untouched.
        bundled = bundled_core_dir(project_root)
        if bundled:
            dirs.append(bundled)
    # Searched, never written to: a RetroArch the user installed themselves.
    dirs.extend(user_retroarch_dirs())
    dirs.extend(Path(p) for p in system_core_dirs())
    return dirs


def humanize_core_filename(filename):
    stem = core_stem(filename)
    if stem.endswith("_libretro"):
        stem = stem[: -len("_libretro")]
    text = stem.replace("_", " ").replace("-", " ").strip()
    return text.title() if text else filename


def parse_core_info(path):
    """Pull the fields we care about out of a libretro ``.info`` file."""
    fields = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fields
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"')
        if key in ("corename", "display_name", "systemname", "database", "display_version"):
            fields[key] = value
    return fields


class CoreInfo:
    def __init__(self, filename, path, display_name, database="", core_name="", version=""):
        self.filename = filename
        self.path = path
        self.display_name = display_name
        self.database = database
        # The .info ``corename`` and ``display_version``: what a save state is
        # tied to when it travels to another device (issue #588).
        self.core_name = core_name
        self.version = version

    def matches_system(self, system_name):
        if not system_name or not self.database:
            return False
        return system_name in [db.strip() for db in self.database.split("|")]


def pickable_core_filenames(info_dirs):
    """Every core some picker would list, from the ``.info`` files on disk.

    The curated candidates of every console, plus each core whose ``.info``
    ``database`` names a supported system -- the same rule
    :meth:`CoreCatalog.cores_for_console` applies. The deferred sweep after
    the first boot used to fetch all ~240 cores the buildbot builds; the
    ~200 no picker ever shows are left out unless the user opts in (issue
    908). Spelled with this platform's extension, like the catalogs.
    """
    systems = {name for name in (get_thumbnail_system(system) for system in SYSTEM_IDS) if name}
    wanted = set(curated_core_filenames())
    seen = set()
    for base in info_dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        for info_path in sorted(base.glob("*.info")):
            if info_path.stem in seen:
                continue
            seen.add(info_path.stem)
            fields = parse_core_info(info_path)
            databases = {db.strip() for db in fields.get("database", "").split("|") if db.strip()}
            if databases & systems:
                wanted.add(info_path.stem + CORE_SUFFIX)
    return sorted(wanted)


class CoreCatalog:
    """What is installed, scanned once and kept on disk between runs.

    The scan parses one ``.info`` per core; after the deferred sweep that
    is a couple of hundred files, and it used to run on the main thread at
    the first right-click on a card (issue 908). The result is cached as
    JSON beside the config, keyed by the mtimes of the core directories, so
    a start whose directories did not move loads it with one read; and the
    window warms the catalog on a worker after the first frame, so the
    first menu finds it ready. One instance serves the window and the
    launcher.
    """

    def __init__(self, project_root=None, core_dirs=None, cache_file=None):
        self.core_dirs = [Path(d) for d in (core_dirs or core_search_dirs(project_root))]
        self.cache_file = Path(cache_file) if cache_file is not None else None
        self._cores = None
        self._lock = threading.RLock()

    def _stamps(self):
        """``{directory: mtime_ns}`` of the directories that exist."""
        stamps = {}
        for base in self.core_dirs:
            try:
                stamps[str(base)] = base.stat().st_mtime_ns
            except OSError:
                continue
        return stamps

    def _scan(self):
        # ``.info`` files are keyed by the core's stem; a core may have its .so
        # in one directory (a Flatpak bundle) and its .info in another (the
        # user config), so index them independently.
        infos = {}
        so_paths = {}
        for base in self.core_dirs:
            if not base.exists():
                continue
            for info_path in base.glob("*.info"):
                infos.setdefault(info_path.stem, parse_core_info(info_path))
            for so_path in base.glob("*" + CORE_SUFFIX):
                # First directory wins, matching the launcher's resolution order.
                so_paths.setdefault(so_path.name, so_path)

        cores = {}
        for filename, so_path in so_paths.items():
            info = infos.get(core_stem(filename), {})
            display = info.get("corename") or info.get("display_name") or humanize_core_filename(filename)
            cores[filename] = CoreInfo(
                filename=filename,
                path=str(so_path),
                display_name=display,
                database=info.get("database", ""),
                core_name=info.get("corename", ""),
                version=info.get("display_version", ""),
            )
        return cores

    # -- the on-disk cache ---------------------------------------------------
    def _load_cache(self, stamps):
        if self.cache_file is None:
            return None
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            quarantine_state_file(self.cache_file, exc)
            return None
        if (
            not isinstance(raw, dict)
            or raw.get("version") != CATALOG_CACHE_VERSION
            or raw.get("stamps") != stamps
            or not isinstance(raw.get("cores"), dict)
        ):
            return None
        cores = {}
        for filename, entry in raw["cores"].items():
            cores[filename] = CoreInfo(
                filename=filename,
                path=entry.get("path", ""),
                display_name=entry.get("display_name") or humanize_core_filename(filename),
                database=entry.get("database", ""),
                core_name=entry.get("core_name", ""),
                version=entry.get("version", ""),
            )
        return cores

    def _store_cache(self, stamps, cores):
        if self.cache_file is None:
            return
        payload = {
            "version": CATALOG_CACHE_VERSION,
            "stamps": stamps,
            "cores": {
                filename: {
                    "path": core.path,
                    "display_name": core.display_name,
                    "database": core.database,
                    "core_name": core.core_name,
                    "version": core.version,
                }
                for filename, core in cores.items()
            },
        }
        try:
            atomic_write_text(self.cache_file, json.dumps(payload, sort_keys=True), durable=False)
        except OSError as exc:
            logger.debug("core catalog cache not written: %s", exc)

    def installed(self):
        with self._lock:
            if self._cores is None:
                stamps = self._stamps()
                cores = self._load_cache(stamps)
                if cores is None:
                    cores = self._scan()
                    self._store_cache(stamps, cores)
                self._cores = cores
            return self._cores

    def warm_up(self):
        """Have the scan done, for a worker thread after the first frame."""
        self.installed()

    def is_ready(self):
        return self._cores is not None

    def refresh(self):
        """Forget the last scan, so the next question rescans the directories.

        The scan is cached for the window's lifetime, which used to be fine
        because every core arrived before the window opened. Since issue #442
        most of them arrive afterwards, in the background.
        """
        with self._lock:
            self._cores = None

    def is_installed(self, core_filename):
        return bool(core_filename) and core_filename in self.installed()

    def path_for(self, core_filename):
        core = self.installed().get(core_filename)
        return core.path if core else None

    def display_name_for(self, core_filename):
        core = self.installed().get(core_filename)
        if core:
            return core.display_name
        return humanize_core_filename(core_filename) if core_filename else ""

    def identity_for(self, core_filename):
        """``(core_name, version)`` of an installed core; empty strings when unknown."""
        core = self.installed().get(core_filename) if core_filename else None
        if core is None:
            return "", ""
        return core.core_name, core.version

    def find_by_identity(self, core_name, version):
        """The installed core with exactly this name and version, or ``None``.

        Both must be non-empty: a core whose version is unknown never matches,
        since nothing says its save states would load.
        """
        if not core_name or not version:
            return None
        for core in self.installed().values():
            if core.core_name == core_name and core.version == version:
                return core
        return None

    def find_by_name(self, core_name):
        """The first installed core whose ``corename`` is ``core_name``, or ``None``."""
        if not core_name:
            return None
        for _, core in sorted(self.installed().items()):
            if core.core_name == core_name:
                return core
        return None

    def cores_for_console(self, console):
        """Installed cores that can run ``console``, preferred order first.

        The console's curated candidates come first, in their own order (that
        is the order Automatic resolves through); any further installed core
        whose ``.info`` claims the system follows, alphabetically.
        """
        candidates = get_runtime_core_candidates(console)
        system_name = get_thumbnail_system(console)
        installed = self.installed()

        ordered = []
        seen = set()
        for filename in candidates:
            core = installed.get(filename)
            if core and filename not in seen:
                ordered.append(core)
                seen.add(filename)

        extra = []
        for filename, core in installed.items():
            if filename in seen:
                continue
            if core.matches_system(system_name):
                extra.append(core)
        extra.sort(key=lambda c: c.display_name.lower())
        return ordered + extra


class CoreConfigStore:
    """Per-ROM core overrides, persisted as YAML at ``cores.config``."""

    def __init__(self, config_file=DEFAULT_CORES_CONFIG_FILE):
        self.config_file = Path(config_file).expanduser()

    def load(self):
        if not self.config_file.exists():
            return copy.deepcopy(DEFAULT_CORES_CONFIG)
        try:
            raw = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"not a mapping: {type(raw).__name__}")
            data = copy.deepcopy(DEFAULT_CORES_CONFIG)
            data["version"] = int(raw.get("version", 1))
            overrides = {}
            for key, value in (raw.get("rom_overrides") or {}).items():
                if key and value:
                    overrides[from_stored_path(str(key))] = str(value)
            data["rom_overrides"] = overrides
            return data
        except Exception as exc:
            # Defaults here mean "no per-ROM core pinned anywhere", and the
            # next set_rom_core would write that emptiness back over the
            # user's pins. Keep the file (issue #209).
            quarantine_state_file(self.config_file, exc)
            return copy.deepcopy(DEFAULT_CORES_CONFIG)

    def save(self, data):
        payload = copy.deepcopy(DEFAULT_CORES_CONFIG)
        payload["version"] = int((data or {}).get("version", 1))
        overrides = {}
        for key, value in ((data or {}).get("rom_overrides") or {}).items():
            if key and value:
                overrides[str(key)] = str(value)
        payload["rom_overrides"] = overrides
        stored = dict(payload, rom_overrides=with_stored_keys(overrides))
        atomic_write_text(self.config_file, yaml.safe_dump(stored, sort_keys=True))
        return payload

    def get_rom_core(self, rom_path):
        return self.load().get("rom_overrides", {}).get(str(rom_path))

    def set_rom_core(self, rom_path, core_filename):
        """Set (or with ``core_filename=None`` clear) a ROM's core override."""
        data = self.load()
        overrides = data.setdefault("rom_overrides", {})
        key = str(rom_path)
        if core_filename:
            overrides[key] = str(core_filename)
        else:
            overrides.pop(key, None)
        return self.save(data)

    def repath_rom(self, old_path, new_path):
        data = self.load()
        overrides = data.get("rom_overrides", {})
        entry = overrides.pop(str(old_path), None)
        if entry is None:
            return
        overrides[str(new_path)] = entry
        self.save(data)

    def forget_rom(self, rom_path):
        data = self.load()
        overrides = data.get("rom_overrides", {})
        if overrides.pop(str(rom_path), None) is not None:
            self.save(data)

"""Discover the libretro cores installed on this machine.

The launcher only ever asked "does this specific core exist?". Choosing a core
per console or per ROM needs the other direction: *which* cores are installed,
and which of them can run a given system. This module answers that by scanning
the same directories the launcher searches and reading the ``.info`` sidecar
files RetroArch ships, so the picker can show a core's real name ("Snes9x")
rather than its filename.

A core is matched to a console two ways, unioned:

* it is one of the console's curated ``runtime_core_candidates`` (works even
  when no ``.info`` is present, e.g. a Flatpak core directory), or
* its ``.info`` ``database`` field names the console's libretro system, the
  same identifier used for thumbnails.
"""

import copy
from pathlib import Path

import yaml

from openemux.core.paths import get_real_home
from openemux.core.systems import (
    get_runtime_core_candidates,
    get_thumbnail_system,
    resolve_system_id,
)

# Mirrors RetroArchLauncher's search order: user config first, then Flatpak,
# the vendored bundle, and the common system locations.
RETROARCH_FLATPAK_ID = "org.libretro.RetroArch"

DEFAULT_CONFIG_DIR = Path.home() / ".openemux"
DEFAULT_CORES_CONFIG_FILE = DEFAULT_CONFIG_DIR / "cores.config"
DEFAULT_CORES_CONFIG = {
    "version": 1,
    # Per-ROM core overrides keyed by absolute ROM path. The per-console
    # override lives in config.yaml (runtime.retroarch.cores), which the
    # launcher already reads; only the per-ROM level needs its own store.
    "rom_overrides": {},
}

SYSTEM_CORE_DIRS = [
    "/usr/lib/libretro",
    "/usr/lib64/libretro",
    "/usr/lib/x86_64-linux-gnu/libretro",
    "/usr/local/lib/libretro",
]


def core_search_dirs(project_root=None):
    real_home = get_real_home()
    dirs = [
        real_home / ".config" / "retroarch" / "cores",
        real_home / ".var" / "app" / RETROARCH_FLATPAK_ID / "config" / "retroarch" / "cores",
    ]
    if project_root:
        dirs.append(Path(project_root) / "vendors" / "retroarch-assets" / "cores")
    dirs.extend(Path(p) for p in SYSTEM_CORE_DIRS)
    return dirs


def humanize_core_filename(filename):
    stem = filename[:-3] if filename.endswith(".so") else filename
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
        if key in ("corename", "display_name", "systemname", "database"):
            fields[key] = value
    return fields


class CoreInfo:
    def __init__(self, filename, path, display_name, database=""):
        self.filename = filename
        self.path = path
        self.display_name = display_name
        self.database = database

    def matches_system(self, system_name):
        if not system_name or not self.database:
            return False
        return system_name in [db.strip() for db in self.database.split("|")]


class CoreCatalog:
    def __init__(self, project_root=None, core_dirs=None):
        self.core_dirs = [Path(d) for d in (core_dirs or core_search_dirs(project_root))]
        self._cores = None

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
            for so_path in base.glob("*.so"):
                # First directory wins, matching the launcher's resolution order.
                so_paths.setdefault(so_path.name, so_path)

        cores = {}
        for filename, so_path in so_paths.items():
            info = infos.get(filename[:-3], {})
            display = info.get("corename") or info.get("display_name") or humanize_core_filename(filename)
            cores[filename] = CoreInfo(
                filename=filename,
                path=str(so_path),
                display_name=display,
                database=info.get("database", ""),
            )
        return cores

    def installed(self):
        if self._cores is None:
            self._cores = self._scan()
        return self._cores

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
        except Exception:
            return copy.deepcopy(DEFAULT_CORES_CONFIG)
        data = copy.deepcopy(DEFAULT_CORES_CONFIG)
        data["version"] = int(raw.get("version", 1))
        overrides = {}
        for key, value in (raw.get("rom_overrides") or {}).items():
            if key and value:
                overrides[str(key)] = str(value)
        data["rom_overrides"] = overrides
        return data

    def save(self, data):
        payload = copy.deepcopy(DEFAULT_CORES_CONFIG)
        payload["version"] = int((data or {}).get("version", 1))
        overrides = {}
        for key, value in ((data or {}).get("rom_overrides") or {}).items():
            if key and value:
                overrides[str(key)] = str(value)
        payload["rom_overrides"] = overrides
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
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

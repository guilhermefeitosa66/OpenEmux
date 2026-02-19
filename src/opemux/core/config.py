import shutil
from datetime import datetime
from pathlib import Path

import yaml

from opemux.core.input_profiles import InputProfileManager
from opemux.core.systems import LEGACY_ID_MAP, SYSTEM_IDS, resolve_system_id

DEFAULT_CONFIG_DIR = Path.home() / ".opemux"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_ROMS_PATH = Path.home() / "games" / "roms"
DEFAULT_PLAYLISTS_DIR = DEFAULT_CONFIG_DIR / "playlists"
DEFAULT_INPUT_DIR = DEFAULT_CONFIG_DIR / "input"
DEFAULT_RUNTIME_DIR = DEFAULT_CONFIG_DIR / "runtime"
MIGRATION_VERSION = 2

DEFAULT_CONFIG = {
    "locale": "en",
    "roms_path": str(DEFAULT_ROMS_PATH),
    "consoles": list(SYSTEM_IDS),
    "runtime": {
        "mode": "retroarch_wrapper",
        "console_backend": {system_id: "retroarch_wrapper" for system_id in SYSTEM_IDS},
        "retroarch": {
            "binary": "vendors/RetroArch-Linux-x86_64.AppImage",
            "extra_flags": [],
            "cores": {system_id: [] for system_id in SYSTEM_IDS},
        },
    },
    "controls": {
        "profiles": {system_id: {} for system_id in SYSTEM_IDS}
    },
    "ui": {
        "render_cartridge_overlay": False,
    },
    "covers": {
        "providers": ["libretro_thumbnails"],
        "preferred_ext_order": ["png", "jpg", "webp"],
        "sync": {
            "provider": "libretro_thumbnails",
            "policy": "missing_only",
            "matching_mode": "normalized_region_priority",
            "region_priority": ["USA", "World", "Europe", "Japan"],
            "name_cleanup": True,
        },
    },
    "library": {
        "playlists_dir": str(DEFAULT_PLAYLISTS_DIR),
        "auto_scan_on_first_open": True,
        "migration": {"version": 0},
    },
}


def _merge_defaults(defaults, data):
    merged = dict(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, config_file=DEFAULT_CONFIG_FILE):
        self.config_file = config_file
        self.input_profiles = InputProfileManager(DEFAULT_INPUT_DIR)
        self.config = self.load_config()

    def load_config(self):
        if not self.config_file.exists():
            return self.create_default_config()

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
                config = _merge_defaults(DEFAULT_CONFIG, raw)
                config = self._migrate_runtime_config(config)
                if config != raw:
                    self.save_config(config)
                return config
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.create_default_config()

    def create_default_config(self):
        config = _merge_defaults(DEFAULT_CONFIG, {})
        config = self._migrate_runtime_config(config)
        self.save_config(config)
        return config

    def _migrate_runtime_config(self, config):
        runtime = config.get("runtime", {})
        runtime.setdefault("mode", "retroarch_wrapper")
        runtime.setdefault("console_backend", {})
        runtime.setdefault("retroarch", {})
        runtime["retroarch"].setdefault("binary", "vendors/RetroArch-Linux-x86_64.AppImage")
        runtime["retroarch"].setdefault("extra_flags", [])
        runtime["retroarch"].setdefault("cores", {})

        migrated_backend = {}
        for key, mode in runtime.get("console_backend", {}).items():
            canonical = resolve_system_id(key)
            if canonical in SYSTEM_IDS:
                migrated_backend[canonical] = mode
        runtime["console_backend"] = migrated_backend

        migrated_cores = {}
        for key, hints in runtime["retroarch"].get("cores", {}).items():
            canonical = resolve_system_id(key)
            if canonical in SYSTEM_IDS:
                migrated_cores[canonical] = hints
        runtime["retroarch"]["cores"] = migrated_cores

        for system_id in SYSTEM_IDS:
            runtime["console_backend"].setdefault(system_id, "retroarch_wrapper")
            runtime["retroarch"]["cores"].setdefault(system_id, [])

        config["runtime"] = runtime

        controls = config.get("controls", {})
        controls.setdefault("profiles", {})
        migrated_profiles = {}
        for key, profile in controls["profiles"].items():
            canonical = resolve_system_id(key)
            if canonical in SYSTEM_IDS:
                migrated_profiles[canonical] = profile
        controls["profiles"] = migrated_profiles
        for system_id in SYSTEM_IDS:
            controls["profiles"].setdefault(system_id, {})
        config["controls"] = controls

        ui = config.get("ui", {})
        ui.setdefault("render_cartridge_overlay", False)
        config["ui"] = ui

        config.setdefault("locale", "en")
        config["consoles"] = [system_id for system_id in config.get("consoles", SYSTEM_IDS) if resolve_system_id(system_id) in SYSTEM_IDS]
        if not config["consoles"]:
            config["consoles"] = list(SYSTEM_IDS)
        else:
            config["consoles"] = [resolve_system_id(system_id) for system_id in config["consoles"]]

        covers = config.get("covers", {})
        covers.setdefault("sync", {})
        covers["sync"].setdefault("provider", "libretro_thumbnails")
        covers["sync"].setdefault("policy", "missing_only")
        covers["sync"].setdefault("matching_mode", "normalized_region_priority")
        covers["sync"].setdefault("region_priority", ["USA", "World", "Europe", "Japan"])
        covers["sync"].setdefault("name_cleanup", True)
        config["covers"] = covers

        library = config.get("library", {})
        library.setdefault("playlists_dir", str(DEFAULT_PLAYLISTS_DIR))
        library.setdefault("auto_scan_on_first_open", True)
        library.setdefault("migration", {})
        library["migration"].setdefault("version", 0)
        config["library"] = library
        return config

    def save_config(self, config=None):
        if config:
            self.config = config

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_roms_path(self):
        return Path(self.config.get("roms_path", DEFAULT_ROMS_PATH))

    def get_locale(self):
        return self.config.get("locale", "en")

    def get_console_dir(self, system_id):
        canonical = resolve_system_id(system_id)
        return self.get_roms_path() / canonical

    def get_console_covers_dir(self, system_id):
        return self.get_console_dir(system_id) / "covers"

    def get_console_bios_dir(self, system_id):
        return self.get_console_dir(system_id) / "bios"

    def get_covers_dir(self):
        covers_cfg = self.config.get("covers", {}).get("dir")
        if covers_cfg:
            return Path(covers_cfg)
        return self.get_roms_path()

    def get_cover_sync_settings(self):
        sync = self.config.get("covers", {}).get("sync", {})
        return {
            "matching_mode": sync.get("matching_mode", "normalized_region_priority"),
            "region_priority": sync.get("region_priority", ["USA", "World", "Europe", "Japan"]),
            "name_cleanup": bool(sync.get("name_cleanup", True)),
        }

    def get_ui_settings(self):
        ui = self.config.get("ui", {})
        return {
            "render_cartridge_overlay": bool(ui.get("render_cartridge_overlay", False)),
        }

    def set_render_cartridge_overlay(self, enabled):
        ui = self.config.setdefault("ui", {})
        ui["render_cartridge_overlay"] = bool(enabled)
        self.save_config()

    def get_runtime_mode(self):
        return self.config.get("runtime", {}).get("mode", "retroarch_wrapper")

    def get_runtime_mode_for_console(self, console):
        canonical = resolve_system_id(console)
        runtime = self.config.get("runtime", {})
        per_console = runtime.get("console_backend", {})
        return per_console.get(canonical, runtime.get("mode", "retroarch_wrapper"))

    def get_playlists_dir(self):
        return Path(self.config.get("library", {}).get("playlists_dir", DEFAULT_PLAYLISTS_DIR))

    def get_input_dir(self):
        return DEFAULT_INPUT_DIR

    def get_runtime_dir(self):
        return DEFAULT_RUNTIME_DIR

    def auto_scan_on_first_open(self):
        return bool(self.config.get("library", {}).get("auto_scan_on_first_open", True))

    def get_controls_profile(self, console):
        canonical = resolve_system_id(console)
        return self.config.get("controls", {}).get("profiles", {}).get(canonical, {})

    def get_input_profile(self, console):
        return self.input_profiles.load_profile(console)

    def save_input_profile(self, console, profile):
        return self.input_profiles.save_profile(console, profile)

    def reset_input_profile(self, console):
        return self.input_profiles.reset_console(console)

    def ensure_input_profiles(self):
        self.input_profiles.ensure_default_profiles(SYSTEM_IDS)

    def get_retroarch_binary(self):
        return self.config.get("runtime", {}).get("retroarch", {}).get("binary", "retroarch")

    def get_retroarch_extra_flags(self):
        return self.config.get("runtime", {}).get("retroarch", {}).get("extra_flags", [])

    def get_retroarch_core_hints(self, console):
        canonical = resolve_system_id(console)
        return self.config.get("runtime", {}).get("retroarch", {}).get("cores", {}).get(canonical, [])

    def ensure_rom_directories(self):
        base_path = self.get_roms_path()
        self.get_playlists_dir().mkdir(parents=True, exist_ok=True)
        self.get_runtime_dir().mkdir(parents=True, exist_ok=True)

        for system_id in SYSTEM_IDS:
            self.get_console_dir(system_id).mkdir(parents=True, exist_ok=True)
            self.get_console_covers_dir(system_id).mkdir(parents=True, exist_ok=True)
            self.get_console_bios_dir(system_id).mkdir(parents=True, exist_ok=True)

        self._run_library_migration_if_needed(base_path)

        for system_id in SYSTEM_IDS:
            self.get_console_dir(system_id).mkdir(parents=True, exist_ok=True)
            self.get_console_covers_dir(system_id).mkdir(parents=True, exist_ok=True)
            self.get_console_bios_dir(system_id).mkdir(parents=True, exist_ok=True)

        self.ensure_input_profiles()

    def _run_library_migration_if_needed(self, base_path):
        migration = self.config.setdefault("library", {}).setdefault("migration", {})
        if int(migration.get("version", 0)) >= MIGRATION_VERSION:
            return

        playlists_dir = self.get_playlists_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = playlists_dir / f"_migration_backup_{timestamp}"
        backup_created = False

        for old_id_raw, new_id in LEGACY_ID_MAP.items():
            old_id = old_id_raw.lower()
            old_playlist = playlists_dir / f"{old_id}.list"
            new_playlist = playlists_dir / f"{new_id}.list"
            if old_playlist.exists():
                if not backup_created:
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_created = True
                shutil.copy2(old_playlist, backup_dir / old_playlist.name)
                if not new_playlist.exists():
                    shutil.copy2(old_playlist, new_playlist)

            old_dir = base_path / old_id
            new_dir = base_path / new_id
            if old_dir.exists() and old_dir.is_dir():
                self._move_tree_contents(old_dir, new_dir, skip_dirs={"covers", "bios"})
                self._move_tree_contents(old_dir / "covers", new_dir / "covers")
                self._move_tree_contents(old_dir / "bios", new_dir / "bios")
                self._remove_empty_tree(old_dir)

            legacy_covers_dir = base_path / "covers" / old_id
            if legacy_covers_dir.exists():
                self._move_tree_contents(legacy_covers_dir, new_dir / "covers")
                self._remove_empty_tree(legacy_covers_dir)

        legacy_global_covers = base_path / "covers"
        self._remove_empty_tree(legacy_global_covers)

        migration["version"] = MIGRATION_VERSION
        self.save_config()

    def _move_tree_contents(self, src_dir, dst_dir, skip_dirs=None):
        src_dir = Path(src_dir)
        dst_dir = Path(dst_dir)
        if not src_dir.exists() or not src_dir.is_dir():
            return

        skip_dirs = {entry.lower() for entry in (skip_dirs or set())}
        dst_dir.mkdir(parents=True, exist_ok=True)

        for entry in src_dir.iterdir():
            if entry.is_dir() and entry.name.lower() in skip_dirs:
                continue

            target = dst_dir / entry.name
            if target.exists():
                if entry.is_dir():
                    self._move_tree_contents(entry, target)
                    self._remove_empty_tree(entry)
                continue

            shutil.move(str(entry), str(target))

    def _remove_empty_tree(self, path):
        path = Path(path)
        if not path.exists() or not path.is_dir():
            return
        for child in list(path.iterdir()):
            if child.is_dir():
                self._remove_empty_tree(child)
        if not any(path.iterdir()):
            path.rmdir()

import shutil
from datetime import datetime
from pathlib import Path

import yaml

from opemux.i18n import normalize_locale
from opemux.core.input_profiles import InputProfileManager
from opemux.core.shaders import ShaderConfigStore
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
            "updater": {
                "mode": "buildbot_all_cores",
                "enabled": True,
                "core_dir": None,
                "cores_base_url": "https://buildbot.libretro.com/nightly/linux/x86_64/latest/",
                "core_info_base_url": "https://buildbot.libretro.com/assets/frontend/info.zip",
                "shader_glsl_url": "https://buildbot.libretro.com/assets/frontend/shaders_glsl.zip",
                "shader_slang_url": "https://buildbot.libretro.com/assets/frontend/shaders_slang.zip",
                "request_timeout_sec": 30,
                "retries": 3,
                "parallel_downloads": 4,
            },
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
    "setup": {
        "bootstrap": {
            "version": 1,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "completed_steps": [],
            "failed_step": None,
            "last_error": None,
            "retry_count": 0,
            "retry_requested": False,
        }
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
        self.shaders = ShaderConfigStore()
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
        runtime["retroarch"].setdefault("updater", {})
        runtime["retroarch"]["updater"].setdefault("mode", "buildbot_all_cores")
        runtime["retroarch"]["updater"].setdefault("enabled", True)
        runtime["retroarch"]["updater"].setdefault("core_dir", None)
        runtime["retroarch"]["updater"].setdefault(
            "cores_base_url",
            "https://buildbot.libretro.com/nightly/linux/x86_64/latest/",
        )
        runtime["retroarch"]["updater"].setdefault(
            "core_info_base_url",
            "https://buildbot.libretro.com/assets/frontend/info.zip",
        )
        runtime["retroarch"]["updater"].setdefault(
            "shader_glsl_url",
            "https://buildbot.libretro.com/assets/frontend/shaders_glsl.zip",
        )
        runtime["retroarch"]["updater"].setdefault(
            "shader_slang_url",
            "https://buildbot.libretro.com/assets/frontend/shaders_slang.zip",
        )
        runtime["retroarch"]["updater"].setdefault("request_timeout_sec", 30)
        runtime["retroarch"]["updater"].setdefault("retries", 3)
        runtime["retroarch"]["updater"].setdefault("parallel_downloads", 4)

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

        config["locale"] = normalize_locale(config.get("locale", "en"))
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

        setup = config.get("setup", {})
        setup.setdefault("bootstrap", {})
        bootstrap = setup["bootstrap"]
        bootstrap.setdefault("version", 1)
        bootstrap.setdefault("status", "pending")
        bootstrap.setdefault("started_at", None)
        bootstrap.setdefault("finished_at", None)
        bootstrap.setdefault("completed_steps", [])
        bootstrap.setdefault("failed_step", None)
        bootstrap.setdefault("last_error", None)
        bootstrap.setdefault("retry_count", 0)
        bootstrap.setdefault("retry_requested", False)
        if not isinstance(bootstrap.get("completed_steps"), list):
            bootstrap["completed_steps"] = []
        setup["bootstrap"] = bootstrap
        config["setup"] = setup
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

    def set_roms_path(self, path_value):
        new_path = Path(path_value).expanduser()
        self.config["roms_path"] = str(new_path)
        self.save_config()

    def get_locale(self):
        return normalize_locale(self.config.get("locale", "en"))

    def set_locale(self, locale):
        self.config["locale"] = normalize_locale(locale)
        self.save_config()

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

    def get_retroarch_updater_settings(self):
        updater = self.config.get("runtime", {}).get("retroarch", {}).get("updater", {})
        return {
            "mode": updater.get("mode", "buildbot_all_cores"),
            "enabled": bool(updater.get("enabled", True)),
            "core_dir": updater.get("core_dir"),
            "cores_base_url": updater.get(
                "cores_base_url",
                "https://buildbot.libretro.com/nightly/linux/x86_64/latest/",
            ),
            "core_info_base_url": updater.get(
                "core_info_base_url",
                "https://buildbot.libretro.com/assets/frontend/info.zip",
            ),
            "shader_glsl_url": updater.get(
                "shader_glsl_url",
                "https://buildbot.libretro.com/assets/frontend/shaders_glsl.zip",
            ),
            "shader_slang_url": updater.get(
                "shader_slang_url",
                "https://buildbot.libretro.com/assets/frontend/shaders_slang.zip",
            ),
            "request_timeout_sec": int(updater.get("request_timeout_sec", 30)),
            "retries": int(updater.get("retries", 3)),
            "parallel_downloads": int(updater.get("parallel_downloads", 4)),
        }

    def get_shaders_config_file(self):
        return self.shaders.config_file

    def get_shader_settings(self):
        return self.shaders.get_settings()

    def get_shader_for_console(self, console):
        return self.shaders.get_console_shader(console)

    def set_shader_for_console(self, console, shader_id):
        return self.shaders.set_console_shader(console, shader_id)

    def set_show_all_shaders(self, enabled):
        return self.shaders.set_show_all_shaders(enabled)

    def reset_shader_defaults(self):
        return self.shaders.reset_defaults()

    def get_bootstrap_state(self):
        return self.config.get("setup", {}).get("bootstrap", {})

    def bootstrap_needs_run(self):
        state = self.get_bootstrap_state()
        status = state.get("status", "pending")
        return bool(state.get("retry_requested", False)) or status in ("pending", "running")

    def start_bootstrap_run(self):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        bootstrap["status"] = "running"
        bootstrap["started_at"] = datetime.utcnow().isoformat() + "Z"
        bootstrap["finished_at"] = None
        bootstrap["failed_step"] = None
        bootstrap["last_error"] = None
        bootstrap["retry_requested"] = False
        self.save_config()

    def mark_bootstrap_step_completed(self, step_id):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        completed_steps = bootstrap.setdefault("completed_steps", [])
        if step_id not in completed_steps:
            completed_steps.append(step_id)
        self.save_config()

    def finish_bootstrap_success(self):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        bootstrap["status"] = "completed"
        bootstrap["finished_at"] = datetime.utcnow().isoformat() + "Z"
        bootstrap["failed_step"] = None
        bootstrap["last_error"] = None
        bootstrap["retry_requested"] = False
        self.save_config()

    def finish_bootstrap_failure(self, step_id, error_message):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        bootstrap["status"] = "failed"
        bootstrap["finished_at"] = datetime.utcnow().isoformat() + "Z"
        bootstrap["failed_step"] = step_id
        bootstrap["last_error"] = str(error_message)
        bootstrap["retry_requested"] = False
        self.save_config()

    def request_bootstrap_retry(self):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        bootstrap["retry_requested"] = True
        bootstrap["status"] = "pending"
        bootstrap["retry_count"] = int(bootstrap.get("retry_count", 0)) + 1
        self.save_config()

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

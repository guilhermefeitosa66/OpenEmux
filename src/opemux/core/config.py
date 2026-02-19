import yaml
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".opemux"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_ROMS_PATH = Path.home() / "games" / "roms"
DEFAULT_COVERS_DIR = DEFAULT_ROMS_PATH / "covers"
DEFAULT_PLAYLISTS_DIR = DEFAULT_CONFIG_DIR / "playlists"

DEFAULT_CONFIG = {
    "locale": "en",
    "roms_path": str(DEFAULT_ROMS_PATH),
    "consoles": ["nes", "snes", "gba"],
    "runtime": {
        "mode": "retroarch_wrapper",
        "console_backend": {
            "nes": "retroarch_wrapper",
            "snes": "retroarch_wrapper",
            "gba": "retroarch_wrapper",
        },
        "retroarch": {
            "binary": "vendors/RetroArch-Linux-x86_64.AppImage",
            "extra_flags": [],
            "cores": {
                "nes": [],
                "snes": [],
                "gba": [],
            },
        },
    },
    "controls": {
        "profiles": {
            "nes": {},
            "snes": {},
            "gba": {},
        }
    },
    "covers": {
        "dir": str(DEFAULT_COVERS_DIR),
        "providers": ["libretro_thumbnails"],
        "preferred_ext_order": ["png", "jpg", "webp"],
        "sync": {
            "provider": "libretro_thumbnails",
            "policy": "missing_only",
        },
    },
    "library": {
        "playlists_dir": str(DEFAULT_PLAYLISTS_DIR),
        "auto_scan_on_first_open": True,
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
        self.config = self.load_config()

    def load_config(self):
        if not self.config_file.exists():
            return self.create_default_config()

        try:
            with open(self.config_file, 'r') as f:
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

        for console in ("nes", "snes", "gba"):
            runtime["console_backend"].setdefault(console, "retroarch_wrapper")
            runtime["retroarch"]["cores"].setdefault(console, [])

        config["runtime"] = runtime
        config.setdefault("locale", "en")
        covers = config.get("covers", {})
        covers.setdefault("sync", {})
        covers["sync"].setdefault("provider", "libretro_thumbnails")
        covers["sync"].setdefault("policy", "missing_only")
        config["covers"] = covers

        library = config.get("library", {})
        library.setdefault("playlists_dir", str(DEFAULT_PLAYLISTS_DIR))
        library.setdefault("auto_scan_on_first_open", True)
        config["library"] = library
        return config

    def save_config(self, config=None):
        if config:
            self.config = config
        
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                yaml.safe_dump(self.config, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_roms_path(self):
        return Path(self.config.get("roms_path", DEFAULT_ROMS_PATH))

    def get_locale(self):
        return self.config.get("locale", "en")

    def get_covers_dir(self):
        covers_cfg = self.config.get("covers", {}).get("dir")
        if covers_cfg:
            return Path(covers_cfg)
        return self.get_roms_path() / "covers"

    def get_runtime_mode(self):
        return self.config.get("runtime", {}).get("mode", "retroarch_wrapper")

    def get_runtime_mode_for_console(self, console):
        runtime = self.config.get("runtime", {})
        per_console = runtime.get("console_backend", {})
        return per_console.get(console, runtime.get("mode", "retroarch_wrapper"))

    def get_playlists_dir(self):
        return Path(self.config.get("library", {}).get("playlists_dir", DEFAULT_PLAYLISTS_DIR))

    def auto_scan_on_first_open(self):
        return bool(self.config.get("library", {}).get("auto_scan_on_first_open", True))

    def get_controls_profile(self, console):
        return self.config.get("controls", {}).get("profiles", {}).get(console, {})

    def get_retroarch_binary(self):
        return self.config.get("runtime", {}).get("retroarch", {}).get("binary", "retroarch")

    def get_retroarch_extra_flags(self):
        return self.config.get("runtime", {}).get("retroarch", {}).get("extra_flags", [])

    def get_retroarch_core_hints(self, console):
        return self.config.get("runtime", {}).get("retroarch", {}).get("cores", {}).get(console, [])

    def ensure_rom_directories(self):
        base_path = self.get_roms_path()
        self.get_playlists_dir().mkdir(parents=True, exist_ok=True)
        for console in self.config.get("consoles", []):
            (base_path / console).mkdir(parents=True, exist_ok=True)
            (self.get_covers_dir() / console).mkdir(parents=True, exist_ok=True)

import yaml
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".opemux"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_ROMS_PATH = Path.home() / "games" / "roms"
DEFAULT_COVERS_DIR = DEFAULT_ROMS_PATH / "covers"

DEFAULT_CONFIG = {
    "roms_path": str(DEFAULT_ROMS_PATH),
    "consoles": ["nes", "snes", "gba"],
    "runtime": {
        "mode": "external_wrapper",
        "external_kiosk": True,
        "prefer_windowed": True,
        "external_flags": {
            "nes": [],
            "snes": [],
            "gba": [],
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
        "providers": ["screenscraper"],
        "preferred_ext_order": ["png", "jpg", "webp"],
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
        runtime.setdefault("prefer_windowed", True)

        if runtime.get("prefer_windowed", True):
            fullscreen_tokens = {"--fullscreen", "-f", "-fullscreen"}
            flags_by_console = runtime.get("external_flags", {})
            for console, flags in flags_by_console.items():
                flags_by_console[console] = [
                    flag for flag in flags if str(flag).strip() not in fullscreen_tokens
                ]
            runtime["external_flags"] = flags_by_console

        config["runtime"] = runtime
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

    def get_covers_dir(self):
        covers_cfg = self.config.get("covers", {}).get("dir")
        if covers_cfg:
            return Path(covers_cfg)
        return self.get_roms_path() / "covers"

    def get_runtime_mode(self):
        return self.config.get("runtime", {}).get("mode", "external_wrapper")

    def is_external_kiosk_enabled(self):
        return bool(self.config.get("runtime", {}).get("external_kiosk", True))

    def get_external_flags(self, console):
        return self.config.get("runtime", {}).get("external_flags", {}).get(console, [])

    def prefer_windowed_runtime(self):
        return bool(self.config.get("runtime", {}).get("prefer_windowed", True))

    def get_controls_profile(self, console):
        return self.config.get("controls", {}).get("profiles", {}).get(console, {})

    def ensure_rom_directories(self):
        base_path = self.get_roms_path()
        for console in self.config.get("consoles", []):
            (base_path / console).mkdir(parents=True, exist_ok=True)
            (self.get_covers_dir() / console).mkdir(parents=True, exist_ok=True)

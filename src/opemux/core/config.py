import os
import yaml
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".opemux"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_ROMS_PATH = Path.home() / "games" / "roms"

class ConfigManager:
    def __init__(self, config_file=DEFAULT_CONFIG_FILE):
        self.config_file = config_file
        self.config = self.load_config()

    def load_config(self):
        if not self.config_file.exists():
            return self.create_default_config()
        
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or self.create_default_config()
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.create_default_config()

    def create_default_config(self):
        config = {
            "roms_path": str(DEFAULT_ROMS_PATH),
            "consoles": ["nes", "snes", "gba"]
        }
        self.save_config(config)
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

    def ensure_rom_directories(self):
        base_path = self.get_roms_path()
        for console in self.config.get("consoles", []):
            (base_path / console).mkdir(parents=True, exist_ok=True)

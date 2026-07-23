import copy
from pathlib import Path

import yaml

from openemux.core.paths import get_project_root
from openemux.core.systems import SYSTEM_IDS, resolve_system_id

DEFAULT_CONFIG_DIR = Path.home() / ".openemux"
DEFAULT_SHADERS_CONFIG_FILE = DEFAULT_CONFIG_DIR / "shaders.config"
DISABLED_SHADER_ID = "disabled"

HANDHELD_SHADER_CONSOLES = {"GBA", "GBC", "GB", "NDS"}
SHORT_SHADER_IDS = [
    DISABLED_SHADER_ID,
    "dot",
    "geom-crt",
    "newpixie-crt",
    "zfast-crt",
    "crt-royale",
    "sharp-bilinear-simple",
]

SHADER_DEFINITIONS = {
    "dot": {
        "label": "Dot",
        "aliases": ["dot", "dotmask", "dot_mask", "dot-matrix"],
    },
    "geom-crt": {
        "label": "Geom CRT",
        "aliases": ["geom-crt", "crt-geom", "geom"],
    },
    "newpixie-crt": {
        "label": "NewPixie CRT",
        "aliases": ["newpixie-crt", "newpixie"],
    },
    "zfast-crt": {
        "label": "zfast CRT",
        "aliases": ["zfast-crt", "zfast"],
    },
    "crt-royale": {
        "label": "CRT Royale",
        "aliases": ["crt-royale", "royale"],
    },
    "sharp-bilinear-simple": {
        "label": "Sharp Bilinear Simple",
        "aliases": ["sharp-bilinear-simple", "sharp-bilinear", "bilinear-simple"],
    },
}

DEFAULT_SHADER_CONFIG = {
    "version": 1,
    "show_all_shaders": False,
    "console_overrides": {},
    # Per-ROM overrides keyed by absolute ROM path. They win over the console
    # setting; "use the console setting" is the absence of an entry here.
    "rom_overrides": {},
}


def normalize_shader_id(shader_id):
    value = (shader_id or "").strip().lower()
    if not value or value in {"none", "off", "disable", "disabled"}:
        return DISABLED_SHADER_ID
    return value


def resolve_default_shader_id(console_id):
    canonical = resolve_system_id(console_id)
    if canonical in HANDHELD_SHADER_CONSOLES:
        return "dot"
    if canonical in SYSTEM_IDS:
        return "geom-crt"
    return DISABLED_SHADER_ID


def _humanize_shader_id(shader_id):
    text = str(shader_id).replace("_", " ").replace("-", " ")
    parts = [part for part in text.split(" ") if part]
    return " ".join(part.upper() if part in {"crt"} else part.capitalize() for part in parts)


class ShaderConfigStore:
    def __init__(self, config_file=DEFAULT_SHADERS_CONFIG_FILE):
        self.config_file = Path(config_file).expanduser()

    def load(self):
        # Deep copies: the nested override dicts must never be aliases of the
        # module-level default, or mutating a loaded config would rewrite the
        # default for every store in the process.
        if not self.config_file.exists():
            return copy.deepcopy(DEFAULT_SHADER_CONFIG)

        try:
            raw = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return copy.deepcopy(DEFAULT_SHADER_CONFIG)

        data = copy.deepcopy(DEFAULT_SHADER_CONFIG)
        data["version"] = int(raw.get("version", 1))
        data["show_all_shaders"] = bool(raw.get("show_all_shaders", False))
        overrides = {}
        for key, value in (raw.get("console_overrides") or {}).items():
            canonical = resolve_system_id(key)
            if canonical not in SYSTEM_IDS:
                continue
            overrides[canonical] = normalize_shader_id(value)
        data["console_overrides"] = overrides

        rom_overrides = {}
        for key, value in (raw.get("rom_overrides") or {}).items():
            if not key:
                continue
            rom_overrides[str(key)] = normalize_shader_id(value)
        data["rom_overrides"] = rom_overrides
        return data

    def save(self, settings):
        payload = dict(DEFAULT_SHADER_CONFIG)
        payload["version"] = int((settings or {}).get("version", 1))
        payload["show_all_shaders"] = bool((settings or {}).get("show_all_shaders", False))

        overrides = {}
        for console in SYSTEM_IDS:
            raw_value = ((settings or {}).get("console_overrides") or {}).get(console)
            if not raw_value:
                continue
            value = normalize_shader_id(raw_value)
            if value == resolve_default_shader_id(console):
                continue
            overrides[console] = value
        payload["console_overrides"] = overrides

        rom_overrides = {}
        for key, raw_value in ((settings or {}).get("rom_overrides") or {}).items():
            if not key or not raw_value:
                continue
            rom_overrides[str(key)] = normalize_shader_id(raw_value)
        payload["rom_overrides"] = rom_overrides

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
        return payload

    def get_settings(self):
        return self.load()

    def get_show_all_shaders(self):
        return bool(self.load().get("show_all_shaders", False))

    def set_show_all_shaders(self, enabled):
        data = self.load()
        data["show_all_shaders"] = bool(enabled)
        return self.save(data)

    def get_console_shader(self, console_id):
        canonical = resolve_system_id(console_id)
        data = self.load()
        override = data.get("console_overrides", {}).get(canonical)
        if override:
            return normalize_shader_id(override)
        return resolve_default_shader_id(canonical)

    def set_console_shader(self, console_id, shader_id):
        canonical = resolve_system_id(console_id)
        if canonical not in SYSTEM_IDS:
            return self.load()
        data = self.load()
        value = normalize_shader_id(shader_id)
        default_value = resolve_default_shader_id(canonical)
        overrides = data.setdefault("console_overrides", {})
        if value == default_value:
            overrides.pop(canonical, None)
        else:
            overrides[canonical] = value
        return self.save(data)

    def reset_defaults(self):
        data = self.load()
        data["console_overrides"] = {}
        return self.save(data)

    # -- per-ROM overrides -------------------------------------------------
    def get_rom_shader(self, rom_path):
        """The ROM's own shader override, or ``None`` to follow the console."""
        override = self.load().get("rom_overrides", {}).get(str(rom_path))
        return normalize_shader_id(override) if override else None

    def get_effective_shader(self, rom_path, console_id):
        """The shader that will actually run: per-ROM first, then per-console."""
        override = self.get_rom_shader(rom_path)
        if override:
            return override
        return self.get_console_shader(console_id)

    def set_rom_shader(self, rom_path, console_id, shader_id):
        """Set (or with ``shader_id=None`` clear) a ROM's shader override.

        Passing the console's effective shader clears the override too, so the
        file does not carry an entry that merely repeats the console setting.
        """
        data = self.load()
        overrides = data.setdefault("rom_overrides", {})
        key = str(rom_path)
        if shader_id is None:
            overrides.pop(key, None)
            return self.save(data)
        value = normalize_shader_id(shader_id)
        if value == self.get_console_shader(console_id):
            overrides.pop(key, None)
        else:
            overrides[key] = value
        return self.save(data)

    def repath_rom(self, old_path, new_path):
        """Follow a renamed ROM so its override is not orphaned."""
        data = self.load()
        overrides = data.get("rom_overrides", {})
        entry = overrides.pop(str(old_path), None)
        if entry is None:
            return
        overrides[str(new_path)] = entry
        self.save(data)

    def forget_rom(self, rom_path):
        """Drop a deleted ROM's override so the file does not accumulate dead entries."""
        data = self.load()
        overrides = data.get("rom_overrides", {})
        if overrides.pop(str(rom_path), None) is not None:
            self.save(data)


class ShaderCatalog:
    def __init__(self, runtime_dir=None, project_root=None):
        self.runtime_dir = Path(runtime_dir or (DEFAULT_CONFIG_DIR / "runtime")).expanduser()
        self.project_root = Path(project_root).expanduser() if project_root else get_project_root()
        self._index = None

    def label_for_shader(self, shader_id):
        shader_id = normalize_shader_id(shader_id)
        if shader_id == DISABLED_SHADER_ID:
            return "Disabled"
        if shader_id in SHADER_DEFINITIONS:
            return SHADER_DEFINITIONS[shader_id]["label"]
        return _humanize_shader_id(shader_id)

    def get_options(self, show_all=False):
        if not show_all:
            return [(shader_id, self.label_for_shader(shader_id)) for shader_id in SHORT_SHADER_IDS]
        ids = [DISABLED_SHADER_ID]
        seen = {DISABLED_SHADER_ID}
        for shader_id in self.list_available_shader_ids():
            if shader_id in seen:
                continue
            seen.add(shader_id)
            ids.append(shader_id)
        for shader_id in SHORT_SHADER_IDS:
            if shader_id in seen:
                continue
            seen.add(shader_id)
            ids.append(shader_id)
        return [(shader_id, self.label_for_shader(shader_id)) for shader_id in ids]

    def list_available_shader_ids(self):
        index = self._ensure_index()
        return sorted(index.keys())

    def resolve_shader_path(self, shader_id):
        shader_id = normalize_shader_id(shader_id)
        if shader_id == DISABLED_SHADER_ID:
            return None
        index = self._ensure_index()
        backend_order = ("glsl", "slang")
        for candidate_id in self._candidate_ids(shader_id):
            item = index.get(candidate_id)
            if not item:
                continue
            for backend in backend_order:
                path = item.get(backend)
                if path:
                    return str(path)
        return None

    def _candidate_ids(self, shader_id):
        ids = [normalize_shader_id(shader_id)]
        definition = SHADER_DEFINITIONS.get(shader_id, {})
        for alias in definition.get("aliases", []):
            alias_id = normalize_shader_id(alias)
            if alias_id not in ids:
                ids.append(alias_id)
        return ids

    def _ensure_index(self):
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def _build_index(self):
        index = {}
        for preset_path in self._iter_shader_presets():
            backend = "glsl" if preset_path.suffix.lower() == ".glslp" else "slang"
            stem_id = normalize_shader_id(preset_path.stem)
            item = index.setdefault(stem_id, {})
            current = item.get(backend)
            if current is None or len(str(preset_path)) < len(str(current)):
                item[backend] = preset_path
        return index

    def _iter_shader_presets(self):
        suffixes = ("*.glslp", "*.slangp")
        for base_dir in self._shader_search_dirs():
            if not base_dir.exists():
                continue
            for pattern in suffixes:
                for preset in base_dir.rglob(pattern):
                    if preset.is_file():
                        yield preset

    def _shader_search_dirs(self):
        return [
            self.runtime_dir / "shaders_glsl",
            self.runtime_dir / "shaders_slang",
            self.project_root / "vendors" / "retroarch-assets" / "shaders_glsl",
            self.project_root / "vendors" / "retroarch-assets" / "shaders_slang",
            Path.home() / ".config" / "retroarch" / "shaders" / "shaders_glsl",
            Path.home() / ".config" / "retroarch" / "shaders" / "shaders_slang",
            Path.home() / ".config" / "retroarch" / "shaders",
            Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "shaders" / "shaders_glsl",
            Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "shaders" / "shaders_slang",
            Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "shaders",
        ]

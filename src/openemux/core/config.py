import copy
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from openemux.i18n import detect_system_locale, normalize_locale
from openemux.core.atomic_write import atomic_write_text
from openemux.core.platform import BUILDBOT_OS, VENDORED_RETROARCH
from openemux.core.state_recovery import quarantine_state_file
from openemux.core.library_view import (
    DEFAULT_SORT_ORDER,
    DEFAULT_ZOOM,
    DISPLAY_KEYS,
    normalize_display_value,
    normalize_sort_order,
    normalize_view_mode,
    normalize_zoom,
    renders_cartridge,
    resolve_display_settings,
    view_mode_from_legacy,
)
from openemux.core.input_profiles import InputProfileManager
from openemux.core.paths import default_config_dir, get_real_home, store_path, is_running_in_flatpak
from openemux.core.cores import CoreConfigStore
from openemux.core.cartridge_colors import CartridgeColorStore
from openemux.core.core_options import CoreOptionsStore
from openemux.core.retroachievements import AchievementsStore
from openemux.core.shaders import ShaderConfigStore
from openemux.core.systems import LEGACY_ID_MAP, SYSTEM_IDS, resolve_system_id
from openemux.core.theme import DEFAULT_THEME, normalize_theme
from openemux.core.update_checker import (
    DEFAULT_API_URL as DEFAULT_UPDATE_API_URL,
    DEFAULT_DOWNLOAD_URL as DEFAULT_UPDATE_DOWNLOAD_URL,
    DEFAULT_TIMEOUT as DEFAULT_UPDATE_TIMEOUT,
)

logger = logging.getLogger(__name__)


def _utc_stamp():
    """An ISO-8601 UTC timestamp ending in ``Z``.

    ``datetime.utcnow()`` returned a naive value that the callers labelled UTC
    by appending the ``Z`` themselves; it is deprecated since Python 3.12 --
    the version CI runs and the one Ubuntu 24.04 and Fedora 40 ship -- and is
    slated for removal (issue #235). The string is byte-for-byte what the old
    call produced, so timestamps already written to config.yaml keep parsing.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _try_mkdir(directory, failures):
    """Create ``directory``; record it in ``failures`` if that is not possible.

    The library layout is 93 directories on a path the user chooses, which
    can be a read-only mount, a full disk, or a drive that went away. None of
    that is a reason for the app to stop (issue #234).
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.warning("directory not created: path=%s error=%s", directory, exc)
        failures.append(directory)
        return False

# Private app data lives under ~/.openemux; the ROM library under ~/games/roms.
# Derived from paths.store_path, which is the one place that knows where the
# config directory is -- see the note there (issue #239).
DEFAULT_CONFIG_DIR = default_config_dir()
DEFAULT_CONFIG_FILE = store_path("config")
DEFAULT_ROMS_PATH = get_real_home() / "games" / "roms"
DEFAULT_PLAYLISTS_DIR = store_path("playlists")
DEFAULT_INPUT_DIR = store_path("input")
DEFAULT_RUNTIME_DIR = store_path("runtime")
# Save states live under OpenEmux's own tree (issue #73), one directory per
# console, so the app can list and manage them instead of RetroArch's default.
DEFAULT_STATES_DIR = store_path("states")
MIGRATION_VERSION = 2

# The buildbot serves cores per platform: .so under nightly/linux/x86_64 and
# .dll under nightly/windows/x86_64. One constant rather than the three copies
# of this literal that used to live in DEFAULT_CONFIG, the migration and the
# getter -- three copies of a platform-dependent value is three chances to fix
# only two of them. The info/shader URLs below are platform-neutral.
DEFAULT_CORES_BASE_URL = f"https://buildbot.libretro.com/nightly/{BUILDBOT_OS}/x86_64/latest/"

#: Everything the RetroArch buildbot updater needs, in one place.
#:
#: These URLs and timeouts used to be spelled out three times over -- in
#: DEFAULT_CONFIG, in the setdefault calls of _migrate_runtime_config, and in
#: the fallbacks of get_retroarch_updater_settings. Changing a URL meant
#: changing it in triplicate, or the copies drifted apart in silence
#: (issue #239).
#:
#: ``enabled`` is the one value that is not simply a default: a fresh config
#: turns the updater off inside Flatpak, where core management belongs to the
#: RetroArch Flatpak's own updater and OpenEmux must not download cores. A
#: config that already exists keeps whatever it says, and an older one that
#: predates the key is read as on -- which is what it was.
UPDATER_DEFAULTS = {
    "mode": "buildbot_all_cores",
    "enabled": True,
    "core_dir": None,
    "cores_base_url": DEFAULT_CORES_BASE_URL,
    "core_info_base_url": "https://buildbot.libretro.com/assets/frontend/info.zip",
    "shader_glsl_url": "https://buildbot.libretro.com/assets/frontend/shaders_glsl.zip",
    "shader_slang_url": "https://buildbot.libretro.com/assets/frontend/shaders_slang.zip",
    "request_timeout_sec": 30,
    "retries": 3,
    "parallel_downloads": 4,
}

# Bumped when a UI default changes in a way that should reach configs written
# before it. Only the switch to the new default is forced, once: whatever the
# user picks in Preferences afterwards sticks.
UI_SETTINGS_VERSION = 1

# Cover art source selection. "libretro" is the historical (and default)
# behavior: libretro thumbnails only, no credentials required. The
# ScreenScraper-backed options are opt-in and require the user to configure
# their own ScreenScraper account (see core/screenscraper.py).
COVER_SOURCE_LIBRETRO = "libretro"
COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER = "libretro_then_screenscraper"
COVER_SOURCE_SCREENSCRAPER = "screenscraper"
COVER_SOURCES = (
    COVER_SOURCE_LIBRETRO,
    COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER,
    COVER_SOURCE_SCREENSCRAPER,
)
DEFAULT_COVER_SOURCE = COVER_SOURCE_LIBRETRO

COVER_ART_TYPE_BOXART = "boxart"
COVER_ART_TYPE_CARTRIDGE_LABEL = "cartridge_label"
COVER_ART_TYPES = (COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL)
DEFAULT_COVER_ART_TYPE = COVER_ART_TYPE_BOXART

# Artwork providers as an ordered list (issue #76). Order is precedence: the
# topmost enabled provider serving a kind is tried first, the rest are
# fallbacks. What each provider *can* serve is fixed here; what it is *asked*
# to serve is the per-provider "kinds" selection in the config.
ARTWORK_PROVIDER_IDS = ("libretro", "screenscraper", "openemux")
ARTWORK_PROVIDER_KINDS_AVAILABLE = {
    "libretro": (COVER_ART_TYPE_BOXART,),
    "screenscraper": (COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL),
    "openemux": (COVER_ART_TYPE_BOXART,),
}
# Fresh-install precedence: the project's own mirror first (fully under our
# control, no quotas), libretro second, ScreenScraper last (quota'd, and the
# only one needing credentials). Migrated configs keep the order their old
# cover_source enum meant instead.
DEFAULT_ARTWORK_PROVIDERS = [
    {"id": "openemux", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
    {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
    {
        "id": "screenscraper",
        "enabled": True,
        "kinds": [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL],
    },
]


def normalize_artwork_providers(value):
    """Coerce a stored provider list to a full, valid, ordered configuration.

    Configured order and enabled flags win; unknown ids are dropped;
    providers the config does not mention (a fresh id shipped in an update)
    are appended with their defaults, so a new provider shows up without a
    migration. ``kinds`` always equals the provider's capabilities: an
    enabled provider serves everything it can (per-kind opt-outs were dropped
    from the UI), so a stored partial selection must not silently linger.
    """
    defaults_by_id = {entry["id"]: entry for entry in DEFAULT_ARTWORK_PROVIDERS}
    normalized = []
    seen = set()
    for raw in value or []:
        if not isinstance(raw, dict):
            continue
        provider_id = raw.get("id")
        if provider_id not in defaults_by_id or provider_id in seen:
            continue
        normalized.append(
            {
                "id": provider_id,
                "enabled": bool(raw.get("enabled", True)),
                "kinds": list(ARTWORK_PROVIDER_KINDS_AVAILABLE[provider_id]),
            }
        )
        seen.add(provider_id)
    for entry in DEFAULT_ARTWORK_PROVIDERS:
        if entry["id"] not in seen:
            normalized.append({k: (list(v) if isinstance(v, list) else v) for k, v in entry.items()})
    return normalized


def migrate_cover_source_to_providers(cover_source, cover_art_type=None):
    """Derive the provider list an existing ``cover_source`` config meant.

    The old enum picked which sources ran and in what order: order/enabled
    carry over, the project mirror closes the chain exactly as it already
    did. Kinds are not migrated -- an enabled provider serves everything it
    can (``cover_art_type`` is accepted for the call site's sake and
    ignored).
    """
    source = normalize_cover_source(cover_source)

    libretro = {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]}
    screenscraper = {
        "id": "screenscraper",
        "enabled": source != COVER_SOURCE_LIBRETRO,
        "kinds": [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL],
    }
    openemux = {"id": "openemux", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]}

    if source == COVER_SOURCE_SCREENSCRAPER:
        libretro["enabled"] = False
        return [screenscraper, libretro, openemux]
    return [libretro, screenscraper, openemux]


def normalize_cover_source(value):
    return value if value in COVER_SOURCES else DEFAULT_COVER_SOURCE


def normalize_cover_art_type(value):
    return value if value in COVER_ART_TYPES else DEFAULT_COVER_ART_TYPE

#: ``runtime.game_window`` when nothing is stored (issue #199): games play
#: inside an OpenEmux window wherever that is possible.
DEFAULT_GAME_WINDOW = True

DEFAULT_CONFIG = {
    # Placeholder only: until the user picks a language from the menu, the
    # locale is resolved from the desktop's on every load (see
    # _migrate_runtime_config). "locale_selected_by_user" is deliberately
    # absent, like "ui.version": _merge_defaults would stamp it on every config
    # it touches and the migration could no longer tell an older one apart.
    "locale": "en",
    "roms_path": str(DEFAULT_ROMS_PATH),
    "consoles": list(SYSTEM_IDS),
    "runtime": {
        "mode": "retroarch_wrapper",
        # RetroArch's UDP command channel (issue #69): written into every
        # runtime override so the running game can be controlled live. 0 picks
        # a free port per launch, which is the only way to be sure the commands
        # reach *our* RetroArch and not a standalone one the user is also
        # running (issue #227). A non-zero value pins the port.
        "network_cmd_port": 0,
        # Master volume in dB (0 = unity), persisted so the level chosen for
        # one loud game carries into the next launch.
        "master_volume_db": 0.0,
        # Play inside an OpenEmux window instead of RetroArch's own (issue
        # #199). On by default; off leaves RetroArch to open its own window.
        # Needs an X11/XWayland session either way -- see
        # openemux.core.game_window_support.
        "game_window": DEFAULT_GAME_WINDOW,
        "console_backend": {system_id: "retroarch_wrapper" for system_id in SYSTEM_IDS},
        "retroarch": {
            "binary": VENDORED_RETROARCH,
            "extra_flags": [],
            # Which audio driver RetroArch is told to use (issue #176).
            # "auto" picks one the host actually offers, because the global
            # retroarch.cfg may name a driver the bundled build lacks --
            # which kills audio, and with it the clock RetroArch paces
            # emulation by. "inherit" restores the pre-#176 behaviour; any
            # other value is passed through for deliberate JACK/ALSA setups.
            "audio_driver": "auto",
            "cores": {system_id: [] for system_id in SYSTEM_IDS},
            "updater": {
                **UPDATER_DEFAULTS,
                # In Flatpak, core management is delegated to the RetroArch
                # Flatpak's own updater; OpenEmux must not download cores.
                "enabled": not is_running_in_flatpak(),
            },
        },
    },
    "controls": {
        "profiles": {system_id: {} for system_id in SYSTEM_IDS}
    },
    "ui": {
        # "version" is deliberately absent here: _merge_defaults would stamp it
        # on every config it touches and the one-time switch below would never
        # see an older one. The migration owns that key.
        "render_cartridge_overlay": True,
        "show_tips": True,
        "gamepad_navigation": True,
        # Light, dark, or whatever the desktop is doing (issue #198).
        "theme": DEFAULT_THEME,
    },
    "updates": {
        "check_on_startup": True,
        "api_url": DEFAULT_UPDATE_API_URL,
        "download_url": DEFAULT_UPDATE_DOWNLOAD_URL,
        "timeout_seconds": DEFAULT_UPDATE_TIMEOUT,
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
            # Cover source order. "libretro" (default) preserves the historical
            # behavior exactly; the ScreenScraper options are opt-in and need
            # the user's own credentials (see core/screenscraper.py).
            "cover_source": DEFAULT_COVER_SOURCE,
            "cover_art_type": DEFAULT_COVER_ART_TYPE,
            "screenscraper_user": "",
            "screenscraper_password": "",
            "screenscraper_devid": "",
            "screenscraper_devpassword": "",
        },
    },
    "library": {
        "playlists_dir": str(DEFAULT_PLAYLISTS_DIR),
        "auto_scan_on_first_open": True,
        # How an imported ROM gets into the library: a copy, or a symbolic
        # link to where it already lives (issue #298).
        "import_mode": "copy",
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


def read_game_window_setting(config_file=DEFAULT_CONFIG_FILE):
    """Read ``runtime.game_window`` straight off disk, changing nothing.

    ``main.py`` needs the answer before GTK is imported, to decide whether the
    app must run as an X11 client (issue #199) -- far too early for a
    ConfigManager, whose constructor creates and migrates the config file on
    the way. A config that is absent, unreadable or not a mapping simply means
    the default.
    """
    try:
        with open(config_file, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        runtime = (raw or {}).get("runtime") or {}
        return bool(runtime.get("game_window", DEFAULT_GAME_WINDOW))
    except Exception:
        return DEFAULT_GAME_WINDOW


def _merge_defaults(defaults, data):
    # Deep copy, not dict(): a shallow copy hands out the very dicts and lists
    # inside DEFAULT_CONFIG, so writing to the loaded config (a migration
    # stamping a version, a setter) would edit the defaults for the whole
    # process and leak into every config built afterwards.
    merged = copy.deepcopy(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, config_file=DEFAULT_CONFIG_FILE):
        self.config_file = Path(config_file)
        # Every store sits beside config.yaml, wherever that is. They used to
        # default to ~/.openemux independently of it, so a ConfigManager
        # pointed elsewhere -- as every test points it -- still read and wrote
        # input profiles, shaders, per-ROM cores, cartridge colours and play
        # history under the user's real home (issue #239).
        self.config_dir = self.config_file.parent
        # One writer at a time: save_config runs from the GTK main thread, the
        # volume-persist timer, the bootstrap worker and atexit (issue #208).
        self._save_lock = threading.RLock()
        self.input_profiles = InputProfileManager(self.store_path("input"))
        self.shaders = ShaderConfigStore(self.store_path("shaders"))
        self.cores = CoreConfigStore(self.store_path("cores"))
        self.cartridge_colors = CartridgeColorStore(self.store_path("cartridge_colors"))
        # Per-console core options (issue #296), beside the per-console core
        # and shader choices they sit next to in the UI.
        self.core_options = CoreOptionsStore(self.store_path("core_options"))
        # The RetroAchievements account (issue #300). Its own file, owner-only:
        # it holds a token, and config.yaml is not a credential store.
        self.achievements = AchievementsStore(self.store_path("achievements"))
        self.config = self.load_config()

    def store_path(self, name):
        """The default path of one store, beside this manager's config file.

        ``name`` is a key of :data:`openemux.core.paths.STORE_FILENAMES`.
        """
        return store_path(name, config_dir=self.config_dir)

    def get_play_history_file(self):
        """Where the last-played timestamps live (issue #239).

        On the manager rather than as a module default, so a history opened
        against a throwaway config directory stays in it.
        """
        return self.store_path("play_history")

    def load_config(self):
        """Read ``config.yaml``, keeping it if it cannot be read.

        A YAML syntax error or a file that parses to something that is not a
        mapping used to end in ``create_default_config()``, which writes the
        defaults straight over the broken file: the ROM path, the credentials,
        the locale and the per-console cores destroyed by the recovery rather
        than by whatever damaged the file. The unreadable file is set aside as
        ``config.yaml.broken-<timestamp>`` first, so it can still be opened
        and read back (issue #209).
        """
        if not self.config_file.exists():
            return self.create_default_config()

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if not isinstance(raw, dict):
                # A scalar or a list: _merge_defaults would raise on it, and
                # there is nothing here to merge. Corrupt, not empty.
                raise ValueError(f"config.yaml is not a mapping: {type(raw).__name__}")
            config = _merge_defaults(DEFAULT_CONFIG, raw)
            config = self._migrate_runtime_config(config)
            if config != raw:
                self.save_config(config)
            return config
        except Exception as e:
            logger.error("config unreadable: %s", e)
            quarantine_state_file(self.config_file, e)
            return self.create_default_config()

    def create_default_config(self):
        config = _merge_defaults(DEFAULT_CONFIG, {})
        config = self._migrate_runtime_config(config)
        self.save_config(config)
        return config

    def _migrate_runtime_config(self, config):
        runtime = config.get("runtime", {})
        runtime.setdefault("mode", "retroarch_wrapper")
        # 55355 is RetroArch's own default, which is exactly the port a
        # standalone RetroArch is already listening on -- both bind it and the
        # kernel decides which one hears us. Nobody chose that number, so it
        # migrates to "pick a free one per launch" (issue #227). A port the
        # user actually set is left alone.
        from openemux.core.retroarch_command import (
            AUTO_NETWORK_CMD_PORT,
            DEFAULT_NETWORK_CMD_PORT,
        )

        if runtime.get("network_cmd_port") == DEFAULT_NETWORK_CMD_PORT:
            runtime["network_cmd_port"] = AUTO_NETWORK_CMD_PORT
        runtime.setdefault("console_backend", {})
        runtime.setdefault("retroarch", {})
        runtime["retroarch"].setdefault("binary", VENDORED_RETROARCH)
        runtime["retroarch"].setdefault("extra_flags", [])
        runtime["retroarch"].setdefault("cores", {})
        updater = runtime["retroarch"].setdefault("updater", {})
        for key, value in UPDATER_DEFAULTS.items():
            updater.setdefault(key, value)

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
        if int(ui.get("version", 0) or 0) < UI_SETTINGS_VERSION:
            # The cartridge look shipped off while it was beta and is the
            # default now, so a config written before that switches over once.
            ui["render_cartridge_overlay"] = True
            ui["version"] = UI_SETTINGS_VERSION
        ui.setdefault("render_cartridge_overlay", True)
        ui.setdefault("show_tips", True)
        ui.setdefault("gamepad_navigation", True)
        # The view mode supersedes the cartridge switch, which could only say
        # "cartridge or plain cover". A config written before it carries its
        # choice over. Like "version", the key is absent from DEFAULT_CONFIG so
        # _merge_defaults cannot stamp it and hide the older config.
        if "view_mode" not in ui:
            ui["view_mode"] = view_mode_from_legacy(ui["render_cartridge_overlay"])
        ui["view_mode"] = normalize_view_mode(ui["view_mode"])
        # Kept in step so anything still reading the old key sees the truth.
        ui["render_cartridge_overlay"] = renders_cartridge(ui["view_mode"])
        ui["zoom"] = normalize_zoom(ui.get("zoom", DEFAULT_ZOOM))
        ui["sort_order"] = normalize_sort_order(ui.get("sort_order", DEFAULT_SORT_ORDER))
        config["ui"] = ui

        updates = config.get("updates", {})
        updates.setdefault("check_on_startup", True)
        updates.setdefault("api_url", DEFAULT_UPDATE_API_URL)
        updates.setdefault("download_url", DEFAULT_UPDATE_DOWNLOAD_URL)
        updates.setdefault("timeout_seconds", DEFAULT_UPDATE_TIMEOUT)
        config["updates"] = updates

        # Language precedence: the user's own choice, then the desktop's
        # locale, then English.
        chosen = config.get("locale_selected_by_user")
        if chosen is None:
            # Config written before the flag existed. A non-English locale in
            # there can only have come from the language menu, so it counts as
            # a choice; one still sitting on the old "en" default never had a
            # choice made and starts following the desktop.
            chosen = normalize_locale(config.get("locale", "en")) != "en"
        config["locale_selected_by_user"] = bool(chosen)
        config["locale"] = (
            normalize_locale(config.get("locale", "en"))
            if chosen
            else detect_system_locale()
        )
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
        # Added after 1.2.0. Existing configs get the libretro-only default, so
        # nothing changes for them until the user opts in.
        covers["sync"].setdefault("cover_source", DEFAULT_COVER_SOURCE)
        covers["sync"]["cover_source"] = normalize_cover_source(covers["sync"]["cover_source"])
        covers["sync"].setdefault("cover_art_type", DEFAULT_COVER_ART_TYPE)
        covers["sync"]["cover_art_type"] = normalize_cover_art_type(covers["sync"]["cover_art_type"])
        covers["sync"].setdefault("screenscraper_user", "")
        covers["sync"].setdefault("screenscraper_password", "")
        covers["sync"].setdefault("screenscraper_devid", "")
        covers["sync"].setdefault("screenscraper_devpassword", "")
        # Issue #76: the provider list replaces the cover_source enum. A config
        # that predates it gets the list its enum meant; the enum keys stay so
        # a downgrade still finds them.
        if "providers" not in covers["sync"]:
            covers["sync"]["providers"] = migrate_cover_source_to_providers(
                covers["sync"].get("cover_source"),
                covers["sync"].get("cover_art_type"),
            )
        covers["sync"]["providers"] = normalize_artwork_providers(covers["sync"]["providers"])
        config["covers"] = covers

        library = config.get("library", {})
        library.setdefault("playlists_dir", str(DEFAULT_PLAYLISTS_DIR))
        library.setdefault("auto_scan_on_first_open", True)
        library.setdefault("import_mode", "copy")
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
        """Persist the config, atomically and one writer at a time.

        Two things used to go wrong here (issue #208). A crash mid-write left
        a truncated ``config.yaml`` behind, taking the ROM path, the
        credentials and the bootstrap state with it -- ``atomic_write_text``
        answers that. And ``save_config`` is called from four threads (the GTK
        main thread on every preference change, the volume-persist timer, the
        bootstrap worker, the atexit flush), so two dumps could interleave
        into the same file and ``yaml.safe_dump`` could iterate ``self.config``
        while another thread mutated it. The lock serialises the writers, and
        the snapshot is taken under it so the dump reads a dict nobody else
        holds.
        """
        with self._save_lock:
            if config:
                self.config = config
            snapshot = copy.deepcopy(self.config)
            try:
                atomic_write_text(self.config_file, yaml.safe_dump(snapshot))
            except Exception as e:
                logger.error("config not saved: %s", e)

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
        # An explicit pick from the language menu outranks the desktop locale
        # from here on, including on the next launch.
        self.config["locale_selected_by_user"] = True
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
            "cover_source": normalize_cover_source(sync.get("cover_source", DEFAULT_COVER_SOURCE)),
            "cover_art_type": normalize_cover_art_type(sync.get("cover_art_type", DEFAULT_COVER_ART_TYPE)),
            "screenscraper_user": str(sync.get("screenscraper_user", "") or ""),
            "screenscraper_password": str(sync.get("screenscraper_password", "") or ""),
            "screenscraper_devid": str(sync.get("screenscraper_devid", "") or ""),
            "screenscraper_devpassword": str(sync.get("screenscraper_devpassword", "") or ""),
            "providers": normalize_artwork_providers(sync.get("providers")),
        }

    def get_artwork_providers(self):
        """The ordered artwork provider list (issue #76), always normalized."""
        sync = self.config.get("covers", {}).get("sync", {})
        return normalize_artwork_providers(sync.get("providers"))

    def set_artwork_providers(self, providers):
        """Persist the whole provider list (order, enabled flags, kinds)."""
        normalized = normalize_artwork_providers(providers)
        covers = self.config.setdefault("covers", {})
        covers.setdefault("sync", {})["providers"] = normalized
        self.save_config()
        return normalized

    def set_cover_sync_setting(self, key, value):
        """Persist a single cover-sync setting, normalizing the known enums."""
        if key == "cover_source":
            value = normalize_cover_source(value)
        elif key == "cover_art_type":
            value = normalize_cover_art_type(value)
        covers = self.config.setdefault("covers", {})
        covers.setdefault("sync", {})[key] = value
        self.save_config()

    def get_ui_settings(self):
        ui = self.config.get("ui", {})
        view_mode = normalize_view_mode(ui.get("view_mode"))
        return {
            "view_mode": view_mode,
            "zoom": normalize_zoom(ui.get("zoom", DEFAULT_ZOOM)),
            "sort_order": normalize_sort_order(ui.get("sort_order", DEFAULT_SORT_ORDER)),
            # Derived, not stored twice: the view mode is the source of truth.
            "render_cartridge_overlay": renders_cartridge(view_mode),
            "show_tips": bool(ui.get("show_tips", True)),
            "gamepad_navigation": bool(ui.get("gamepad_navigation", True)),
            "show_welcome_on_startup": bool(ui.get("show_welcome_on_startup", True)),
            "theme": normalize_theme(ui.get("theme", DEFAULT_THEME)),
        }

    def set_theme(self, theme):
        ui = self.config.setdefault("ui", {})
        ui["theme"] = normalize_theme(theme)
        self.save_config()
        return ui["theme"]

    def get_update_settings(self):
        updates = self.config.get("updates", {})
        try:
            timeout = int(updates.get("timeout_seconds", DEFAULT_UPDATE_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_UPDATE_TIMEOUT
        return {
            "check_on_startup": bool(updates.get("check_on_startup", True)),
            "api_url": str(updates.get("api_url") or DEFAULT_UPDATE_API_URL),
            "download_url": str(updates.get("download_url") or DEFAULT_UPDATE_DOWNLOAD_URL),
            "timeout_seconds": timeout,
        }

    def get_view_mode(self):
        return normalize_view_mode(self.config.get("ui", {}).get("view_mode"))

    def set_view_mode(self, view_mode):
        ui = self.config.setdefault("ui", {})
        ui["view_mode"] = normalize_view_mode(view_mode)
        ui["render_cartridge_overlay"] = renders_cartridge(ui["view_mode"])
        self.save_config()

    def get_zoom(self):
        return normalize_zoom(self.config.get("ui", {}).get("zoom", DEFAULT_ZOOM))

    def set_zoom(self, zoom):
        ui = self.config.setdefault("ui", {})
        ui["zoom"] = normalize_zoom(zoom)
        self.save_config()

    def get_sort_order(self):
        return normalize_sort_order(self.config.get("ui", {}).get("sort_order"))

    def set_sort_order(self, order):
        ui = self.config.setdefault("ui", {})
        ui["sort_order"] = normalize_sort_order(order)
        self.save_config()

    def set_render_cartridge_overlay(self, enabled):
        """Legacy entry point: the cartridge frame is a view mode now."""
        self.set_view_mode(view_mode_from_legacy(bool(enabled)))

    # ----- per-scope layout overrides -------------------------------------
    def get_scope_overrides(self):
        """Clean map of scope -> partial {view_mode?, sort_order?, zoom?}."""
        raw = self.config.get("ui", {}).get("scope_overrides", {}) or {}
        cleaned = {}
        for scope, override in raw.items():
            if not isinstance(override, dict):
                continue
            entry = {}
            for key in DISPLAY_KEYS:
                if override.get(key) is not None:
                    entry[key] = normalize_display_value(key, override[key])
            if entry:
                cleaned[str(scope)] = entry
        return cleaned

    def get_display_settings(self, scope):
        """Resolved view_mode/sort_order/zoom for a scope, global as the base."""
        resolved = resolve_display_settings(
            self.get_ui_settings(), self.get_scope_overrides(), scope
        )
        resolved["render_cartridge_overlay"] = renders_cartridge(resolved["view_mode"])
        return resolved

    def has_scope_override(self, scope):
        return scope in self.get_scope_overrides()

    def set_scope_display(self, scope, key, value):
        """Override one display key for a scope (used once it diverges)."""
        if key not in DISPLAY_KEYS:
            return
        overrides = self.config.setdefault("ui", {}).setdefault("scope_overrides", {})
        entry = overrides.setdefault(str(scope), {})
        entry[key] = normalize_display_value(key, value)
        self.save_config()

    def enable_scope_override(self, scope):
        """Start a scope's own layout, seeded from the current global values."""
        base = self.get_ui_settings()
        overrides = self.config.setdefault("ui", {}).setdefault("scope_overrides", {})
        overrides[str(scope)] = {key: base[key] for key in DISPLAY_KEYS}
        self.save_config()

    def clear_scope_override(self, scope):
        """Drop a scope's override so it follows the global layout again."""
        overrides = self.config.setdefault("ui", {}).setdefault("scope_overrides", {})
        if overrides.pop(str(scope), None) is not None:
            self.save_config()

    def set_show_tips(self, enabled):
        ui = self.config.setdefault("ui", {})
        ui["show_tips"] = bool(enabled)
        self.save_config()

    def set_gamepad_navigation(self, enabled):
        ui = self.config.setdefault("ui", {})
        ui["gamepad_navigation"] = bool(enabled)
        self.save_config()

    def get_show_welcome_on_startup(self):
        return bool(self.config.get("ui", {}).get("show_welcome_on_startup", True))

    def set_show_welcome_on_startup(self, enabled):
        ui = self.config.setdefault("ui", {})
        ui["show_welcome_on_startup"] = bool(enabled)
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

    def get_states_dir(self):
        return DEFAULT_STATES_DIR

    def get_console_states_dir(self, console):
        return DEFAULT_STATES_DIR / resolve_system_id(console)

    def get_network_cmd_port(self):
        """The pinned command port, or 0 to pick a free one per launch."""
        try:
            return int(self.config.get("runtime", {}).get("network_cmd_port", 0))
        except (TypeError, ValueError):
            return 0

    def get_master_volume_db(self):
        from openemux.core.retroarch_command import clamp_volume_db

        return clamp_volume_db(self.config.get("runtime", {}).get("master_volume_db", 0.0))

    def set_master_volume_db(self, value):
        from openemux.core.retroarch_command import clamp_volume_db

        runtime = self.config.setdefault("runtime", {})
        runtime["master_volume_db"] = clamp_volume_db(value)
        self.save_config()

    def get_game_window_enabled(self):
        """Whether games play inside an OpenEmux window (issue #199).

        The preference on its own -- ask
        ``game_window_support.game_window_active`` before acting on it, since
        the session may not be able to host an embedded window at all.
        """
        return bool(self.config.get("runtime", {}).get("game_window", DEFAULT_GAME_WINDOW))

    def set_game_window_enabled(self, enabled):
        runtime = self.config.setdefault("runtime", {})
        runtime["game_window"] = bool(enabled)
        self.save_config()

    # -- global input tuning (issues #154, #155) ---------------------------
    def get_input_tuning(self):
        """Every tuning value, clamped, with RetroArch's defaults filled in."""
        from openemux.core import input_tuning

        stored = self.config.get("input", {}) or {}
        return {
            name: input_tuning.clamp(name, stored.get(name, input_tuning.default_for(name)))
            for name in input_tuning.INPUT_TUNING
        }

    def get_input_tuning_value(self, name):
        return self.get_input_tuning()[name]

    def set_input_tuning_value(self, name, value):
        from openemux.core import input_tuning

        section = self.config.setdefault("input", {})
        section[name] = input_tuning.clamp(name, value)
        self.save_config()
        return section[name]

    def auto_scan_on_first_open(self):
        return bool(self.config.get("library", {}).get("auto_scan_on_first_open", True))

    def get_import_mode(self):
        """``copy`` or ``link`` -- how an import puts a ROM in the library."""
        from openemux.core.rom_importer import normalize_import_mode

        return normalize_import_mode(
            self.config.get("library", {}).get("import_mode", "copy")
        )

    def set_import_mode(self, mode):
        from openemux.core.rom_importer import normalize_import_mode

        library = self.config.setdefault("library", {})
        library["import_mode"] = normalize_import_mode(mode)
        self.save_config()
        return library["import_mode"]

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

    def get_retroarch_audio_driver(self):
        """The raw ``audio_driver`` setting; see core/audio_driver.py (#176)."""
        return (
            self.config.get("runtime", {})
            .get("retroarch", {})
            .get("audio_driver", "auto")
        )

    def get_retroarch_core_hints(self, console):
        canonical = resolve_system_id(console)
        return self.config.get("runtime", {}).get("retroarch", {}).get("cores", {}).get(canonical, [])

    def get_console_core_override(self, console):
        """The per-console core the user pinned, or ``None`` for Automatic."""
        hints = self.get_retroarch_core_hints(console)
        return hints[0] if hints else None

    def set_console_core_override(self, console, core_filename):
        """Pin a console's core (a bare filename), or clear it with ``None``."""
        canonical = resolve_system_id(console)
        if canonical not in SYSTEM_IDS:
            return
        cores = self.config.setdefault("runtime", {}).setdefault("retroarch", {}).setdefault("cores", {})
        cores[canonical] = [core_filename] if core_filename else []
        self.save_config()

    def get_rom_core_override(self, rom_path):
        return self.cores.get_rom_core(rom_path)

    def set_rom_core(self, rom_path, core_filename):
        return self.cores.set_rom_core(rom_path, core_filename)

    def repath_rom_core(self, old_path, new_path):
        return self.cores.repath_rom(old_path, new_path)

    def forget_rom_core(self, rom_path):
        return self.cores.forget_rom(rom_path)

    def get_retroarch_updater_settings(self):
        """The updater's settings, with :data:`UPDATER_DEFAULTS` behind them."""
        updater = self.config.get("runtime", {}).get("retroarch", {}).get("updater", {})
        resolved = {
            key: updater.get(key, value) for key, value in UPDATER_DEFAULTS.items()
        }
        # The three the caller relies on being the right type: a hand-edited
        # config can put a string where a number belongs.
        resolved["enabled"] = bool(resolved["enabled"])
        for key in ("request_timeout_sec", "retries", "parallel_downloads"):
            resolved[key] = int(resolved[key])
        return resolved

    def get_shaders_config_file(self):
        return self.shaders.config_file

    def get_shader_settings(self):
        return self.shaders.get_settings()

    def get_shader_for_console(self, console):
        return self.shaders.get_console_shader(console)

    def set_shader_for_console(self, console, shader_id):
        return self.shaders.set_console_shader(console, shader_id)

    def get_shader_for_rom(self, rom_path, console):
        return self.shaders.get_effective_shader(rom_path, console)

    def get_rom_shader_override(self, rom_path):
        return self.shaders.get_rom_shader(rom_path)

    def set_rom_shader(self, rom_path, console, shader_id):
        return self.shaders.set_rom_shader(rom_path, console, shader_id)

    def repath_rom_shader(self, old_path, new_path):
        return self.shaders.repath_rom(old_path, new_path)

    def forget_rom_shader(self, rom_path):
        return self.shaders.forget_rom(rom_path)

    def set_show_all_shaders(self, enabled):
        return self.shaders.set_show_all_shaders(enabled)

    # -- cartridge shell colors (issue #79): same shape as the shader overrides
    def get_cartridge_color_for_console(self, console):
        return self.cartridge_colors.get_console_color(console)

    def set_cartridge_color_for_console(self, console, color_id):
        return self.cartridge_colors.set_console_color(console, color_id)

    def get_cartridge_color_for_rom(self, rom_path, console):
        return self.cartridge_colors.get_effective_color(rom_path, console)

    def get_rom_cartridge_color_override(self, rom_path):
        return self.cartridge_colors.get_rom_color(rom_path)

    def set_rom_cartridge_color(self, rom_path, console, color_id):
        return self.cartridge_colors.set_rom_color(rom_path, console, color_id)

    def repath_rom_cartridge_color(self, old_path, new_path):
        return self.cartridge_colors.repath_rom(old_path, new_path)

    def forget_rom_cartridge_color(self, rom_path):
        return self.cartridge_colors.forget_rom(rom_path)

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
        bootstrap["started_at"] = _utc_stamp()
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
        bootstrap["finished_at"] = _utc_stamp()
        bootstrap["failed_step"] = None
        bootstrap["last_error"] = None
        bootstrap["retry_requested"] = False
        self.save_config()

    def finish_bootstrap_failure(self, step_id, error_message):
        bootstrap = self.config.setdefault("setup", {}).setdefault("bootstrap", {})
        bootstrap["status"] = "failed"
        bootstrap["finished_at"] = _utc_stamp()
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
        """Lay out the library: three directories per console, plus its own.

        Returns the paths it could not create. Every call site can carry on
        without them -- the app shows an empty library rather than failing --
        and one of them is the "change ROMs folder" handler, where the
        exception escaped into the GTK main loop and took the window's
        callback down with it (issue #234). A folder the user picked on an
        unwritable disk is a thing to report, not to crash on.

        The loop used to run twice, before and after the migration; the
        migration creates whatever it moves into, so once, after it, is
        enough.
        """
        base_path = self.get_roms_path()
        failed = []
        _try_mkdir(self.get_playlists_dir(), failed)
        _try_mkdir(self.get_runtime_dir(), failed)

        try:
            self._run_library_migration_if_needed(base_path)
        except OSError as exc:
            logger.warning("library migration could not run: error=%s", exc)
            failed.append(base_path)

        for system_id in SYSTEM_IDS:
            _try_mkdir(self.get_console_dir(system_id), failed)
            _try_mkdir(self.get_console_covers_dir(system_id), failed)
            _try_mkdir(self.get_console_bios_dir(system_id), failed)

        try:
            self.ensure_input_profiles()
        except OSError as exc:
            logger.warning("input profiles could not be seeded: error=%s", exc)

        if failed:
            logger.warning(
                "library layout incomplete: unwritable=%d first=%s",
                len(failed),
                failed[0],
            )
        return failed

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

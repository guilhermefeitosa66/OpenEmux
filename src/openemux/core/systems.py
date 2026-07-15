SYSTEMS = [
    {
        "id": "A2600",
        "display_name": "Atari 2600",
        "aliases": [],
        "extensions": [".a26", ".bin", ".rom"],
        "thumbnail_system": "Atari - 2600",
        "runtime_core_candidates": ["stella_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "A5200",
        "display_name": "Atari 5200",
        "aliases": [],
        "extensions": [".a52", ".bin", ".rom"],
        "thumbnail_system": "Atari - 5200",
        "runtime_core_candidates": ["atari800_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "A7800",
        "display_name": "Atari 7800",
        "aliases": [],
        "extensions": [".a78", ".bin"],
        "thumbnail_system": "Atari - 7800",
        "runtime_core_candidates": ["prosystem_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "LYNX",
        "display_name": "Atari Lynx",
        "aliases": [],
        "extensions": [".lnx"],
        "thumbnail_system": "Atari - Lynx",
        "runtime_core_candidates": ["mednafen_lynx_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "CV",
        "display_name": "ColecoVision",
        "aliases": [],
        "extensions": [".col", ".rom", ".bin"],
        "thumbnail_system": "Coleco - ColecoVision",
        "runtime_core_candidates": ["bluemsx_libretro.so", "gearcoleco_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "FDS",
        "display_name": "Famicom Disk System",
        "aliases": [],
        "extensions": [".fds"],
        "thumbnail_system": "Nintendo - Family Computer Disk System",
        "runtime_core_candidates": ["nestopia_libretro.so", "fceumm_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "FC",
        "display_name": "Nintendo (NES) / Famicom",
        "aliases": ["nes", "NES"],
        "extensions": [".nes"],
        "thumbnail_system": "Nintendo - Nintendo Entertainment System",
        "runtime_core_candidates": ["nestopia_libretro.so", "fceumm_libretro.so", "mesen_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "GB",
        "display_name": "Game Boy",
        "aliases": [],
        "extensions": [".gb"],
        "thumbnail_system": "Nintendo - Game Boy",
        "runtime_core_candidates": ["gambatte_libretro.so", "mgba_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "GBC",
        "display_name": "Game Boy Color",
        "aliases": [],
        "extensions": [".gbc"],
        "thumbnail_system": "Nintendo - Game Boy Color",
        "runtime_core_candidates": ["gambatte_libretro.so", "mgba_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "GBA",
        "display_name": "Game Boy Advance",
        "aliases": ["gba", "Gba"],
        "extensions": [".gba"],
        "thumbnail_system": "Nintendo - Game Boy Advance",
        "runtime_core_candidates": ["mgba_libretro.so", "gpsp_libretro.so"],
        "icon_name": "phone-symbolic",
    },
    {
        "id": "GG",
        "display_name": "Game Gear",
        "aliases": [],
        "extensions": [".gg"],
        "thumbnail_system": "Sega - Game Gear",
        "runtime_core_candidates": ["genesis_plus_gx_libretro.so", "gearsystem_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "INTV",
        "display_name": "Intellivision",
        "aliases": [],
        "extensions": [".int", ".bin", ".rom"],
        "thumbnail_system": "Mattel - Intellivision",
        "runtime_core_candidates": ["freeintv_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "NGP",
        "display_name": "NeoGeo Pocket",
        "aliases": [],
        "extensions": [".ngp", ".ngc"],
        "thumbnail_system": "SNK - Neo Geo Pocket",
        "runtime_core_candidates": ["mednafen_ngp_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "N64",
        "display_name": "Nintendo 64",
        "aliases": [],
        "extensions": [".n64", ".z64", ".v64"],
        "thumbnail_system": "Nintendo - Nintendo 64",
        "runtime_core_candidates": ["mupen64plus_next_libretro.so", "parallel_n64_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "NDS",
        "display_name": "Nintendo DS",
        "aliases": [],
        "extensions": [".nds"],
        "thumbnail_system": "Nintendo - Nintendo DS",
        "runtime_core_candidates": ["desmume_libretro.so", "melonds_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "GC",
        "display_name": "Nintendo GameCube",
        "aliases": [],
        "extensions": [".iso", ".gcm", ".ciso", ".rvz"],
        "thumbnail_system": "Nintendo - GameCube",
        "runtime_core_candidates": ["dolphin_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "O2",
        "display_name": "Odyssey2 / Videopac+",
        "aliases": [],
        "extensions": [".bin", ".rom"],
        "thumbnail_system": "Magnavox - Odyssey2",
        "runtime_core_candidates": ["o2em_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "SG1000",
        "display_name": "SG-1000",
        "aliases": [],
        "extensions": [".sg", ".bin"],
        "thumbnail_system": "Sega - SG-1000",
        "runtime_core_candidates": ["genesis_plus_gx_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "S32X",
        "display_name": "Sega 32X",
        "aliases": [],
        "extensions": [".32x", ".bin", ".md"],
        "thumbnail_system": "Sega - 32X",
        "runtime_core_candidates": ["picodrive_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "MCD",
        "display_name": "Sega CD / Mega CD",
        "aliases": [],
        "extensions": [".cue", ".chd", ".iso"],
        "thumbnail_system": "Sega - Mega-CD - Sega CD",
        "runtime_core_candidates": ["genesis_plus_gx_libretro.so", "picodrive_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "MD",
        "display_name": "Sega Genesis / Mega Drive",
        "aliases": [],
        "extensions": [".md", ".gen", ".bin", ".smd"],
        "thumbnail_system": "Sega - Mega Drive - Genesis",
        "runtime_core_candidates": ["genesis_plus_gx_libretro.so", "picodrive_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "SMS",
        "display_name": "Sega Master System",
        "aliases": [],
        "extensions": [".sms", ".bin"],
        "thumbnail_system": "Sega - Master System - Mark III",
        "runtime_core_candidates": ["genesis_plus_gx_libretro.so", "gearsystem_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "SATURN",
        "display_name": "Sega Saturn",
        "aliases": [],
        "extensions": [".cue", ".chd", ".iso"],
        "thumbnail_system": "Sega - Saturn",
        "runtime_core_candidates": ["mednafen_saturn_libretro.so", "kronos_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "PS",
        "display_name": "Sony PlayStation",
        "aliases": [],
        "extensions": [".cue", ".chd", ".pbp", ".iso", ".bin"],
        "thumbnail_system": "Sony - PlayStation",
        "runtime_core_candidates": ["mednafen_psx_libretro.so", "pcsx_rearmed_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "PSP",
        "display_name": "Sony PSP",
        "aliases": [],
        "extensions": [".iso", ".cso", ".pbp"],
        "thumbnail_system": "Sony - PlayStation Portable",
        "runtime_core_candidates": ["ppsspp_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "SFC",
        "display_name": "Super Nintendo (SNES)",
        "aliases": ["snes", "SNES"],
        "extensions": [".sfc", ".smc"],
        "thumbnail_system": "Nintendo - Super Nintendo Entertainment System",
        "runtime_core_candidates": ["snes9x_libretro.so", "bsnes_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "PCE",
        "display_name": "TurboGrafx-16 / PC Engine / SuperGrafx",
        "aliases": [],
        "extensions": [".pce", ".sgx", ".bin"],
        "thumbnail_system": "NEC - PC Engine - TurboGrafx 16",
        "runtime_core_candidates": ["mednafen_pce_fast_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "PCECD",
        "display_name": "TurboGrafx-CD / PC Engine CD",
        "aliases": [],
        "extensions": [".cue", ".chd", ".iso"],
        "thumbnail_system": "NEC - PC Engine CD - TurboGrafx-CD",
        "runtime_core_candidates": ["mednafen_supergrafx_libretro.so", "mednafen_pce_fast_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "VECTREX",
        "display_name": "Vectrex",
        "aliases": [],
        "extensions": [".vec", ".bin"],
        "thumbnail_system": "GCE - Vectrex",
        "runtime_core_candidates": ["vecx_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "VB",
        "display_name": "Virtual Boy",
        "aliases": [],
        "extensions": [".vb", ".vboy", ".bin"],
        "thumbnail_system": "Nintendo - Virtual Boy",
        "runtime_core_candidates": ["mednafen_vb_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
    {
        "id": "WS",
        "display_name": "WonderSwan",
        "aliases": [],
        "extensions": [".ws", ".wsc"],
        "thumbnail_system": "Bandai - WonderSwan",
        "runtime_core_candidates": ["mednafen_wswan_libretro.so"],
        "icon_name": "applications-games-symbolic",
    },
]

SYSTEMS_BY_ID = {system["id"]: system for system in SYSTEMS}
SYSTEM_IDS = [system["id"] for system in SYSTEMS]

LEGACY_ID_MAP = {
    "NES": "FC",
    "SNES": "SFC",
    "GBA": "GBA",
}

ALIAS_TO_ID = {}
for system in SYSTEMS:
    ALIAS_TO_ID[system["id"].upper()] = system["id"]
    for alias in system.get("aliases", []):
        ALIAS_TO_ID[str(alias).upper()] = system["id"]


def resolve_system_id(value):
    if value is None:
        return None
    key = str(value).strip().upper()
    key = LEGACY_ID_MAP.get(key, key)
    return ALIAS_TO_ID.get(key, key)


def get_system(value):
    system_id = resolve_system_id(value)
    return SYSTEMS_BY_ID.get(system_id)


def get_system_display_name(value):
    system = get_system(value)
    if system:
        return system["display_name"]
    return str(value).upper()


def get_supported_extensions(value):
    system = get_system(value)
    if not system:
        return []
    return [ext.lower() for ext in system.get("extensions", [])]


def get_runtime_core_candidates(value):
    system = get_system(value)
    if not system:
        return []
    return list(system.get("runtime_core_candidates", []))


def get_thumbnail_system(value):
    system = get_system(value)
    if not system:
        return None
    return system.get("thumbnail_system")


def get_icon_name(value):
    system = get_system(value)
    if not system:
        return "applications-games-symbolic"
    return system.get("icon_name", "applications-games-symbolic")

from copy import deepcopy

from openemux.core.systems import get_runtime_core_candidates, resolve_system_id

# Requirement entries:
# - {"file": "<filename>", "cores": ["core_libretro.so", ...]?}
# - {"any_of": ["file1", "file2"], "cores": [...]} (satisfied if any file exists)
CONSOLE_BIOS_REQUIREMENTS = {
    "A5200": {
        "required": [
            {"file": "5200.rom"},
        ],
        "optional": [
            {"file": "ATARIXL.ROM"},
            {"file": "ATARIBAS.ROM"},
            {"file": "ATARIOSA.ROM"},
            {"file": "ATARIOSB.ROM"},
        ],
    },
    "LYNX": {
        "required": [
            {"file": "lynxboot.img"},
        ],
        "optional": [],
    },
    "FDS": {
        "required": [
            {"file": "disksys.rom", "cores": ["nestopia_libretro.so", "fceumm_libretro.so"]},
        ],
        "optional": [
            {"file": "gamegenie.nes", "cores": ["fceumm_libretro.so"]},
        ],
    },
    "GG": {
        "required": [],
        "optional": [
            {"file": "bios.gg", "cores": ["gearsystem_libretro.so"]},
        ],
    },
    "INTV": {
        "required": [
            {"file": "exec.bin"},
            {"file": "grom.bin"},
        ],
        "optional": [],
    },
    "MCD": {
        "required": [
            {
                "any_of": ["bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"],
                "cores": ["genesis_plus_gx_libretro.so", "picodrive_libretro.so"],
            },
        ],
        "optional": [
            {"file": "bios_MD.bin", "cores": ["genesis_plus_gx_libretro.so"]},
        ],
    },
    "NDS": {
        "required": [],
        "optional": [
            {"file": "bios7.bin", "cores": ["desmume_libretro.so", "melonds_libretro.so"]},
            {"file": "bios9.bin", "cores": ["desmume_libretro.so", "melonds_libretro.so"]},
            {"file": "firmware.bin", "cores": ["desmume_libretro.so", "melonds_libretro.so"]},
            {"file": "dsi_bios7.bin", "cores": ["melonds_libretro.so"]},
            {"file": "dsi_bios9.bin", "cores": ["melonds_libretro.so"]},
            {"file": "dsi_firmware.bin", "cores": ["melonds_libretro.so"]},
            {"file": "dsi_nand.bin", "cores": ["melonds_libretro.so"]},
        ],
    },
    "O2": {
        "required": [
            {"file": "o2rom.bin"},
        ],
        "optional": [
            {"file": "c52.bin"},
            {"file": "g7400.bin"},
            {"file": "jopac.bin"},
        ],
    },
    "PCECD": {
        "required": [
            {
                "any_of": ["syscard3.pce", "syscard2.pce", "syscard1.pce", "gexpress.pce"],
                "cores": ["mednafen_pce_fast_libretro.so", "mednafen_supergrafx_libretro.so"],
            }
        ],
        "optional": [],
    },
    "PS": {
        "required": [
            {
                "any_of": [
                    "scph5500.bin",
                    "scph5501.bin",
                    "scph5502.bin",
                    "PSXONPSP660.bin",
                    "ps1_rom.bin",
                    "scph101.bin",
                    "scph7001.bin",
                    "scph1001.bin",
                ],
                "cores": ["mednafen_psx_libretro.so", "pcsx_rearmed_libretro.so"],
            }
        ],
        "optional": [],
    },
    "SATURN": {
        "required": [
            {
                "any_of": ["sega_101.bin", "mpr-17933.bin"],
                "cores": ["mednafen_saturn_libretro.so"],
            },
            {
                "any_of": ["saturn_bios.bin", "sega_101.bin", "mpr-17933.bin"],
                "cores": ["kronos_libretro.so"],
            },
        ],
        "optional": [
            {"file": "mpr-18811-mx.ic1", "cores": ["mednafen_saturn_libretro.so", "kronos_libretro.so"]},
            {"file": "mpr-19367-mx.ic1", "cores": ["mednafen_saturn_libretro.so", "kronos_libretro.so"]},
        ],
    },
    "SMS": {
        "required": [],
        "optional": [
            {"file": "bios.sms", "cores": ["gearsystem_libretro.so"]},
        ],
    },
    "GC": {
        "required": [],
        "optional": [
            {"file": "IPL.bin", "cores": ["dolphin_libretro.so"]},
        ],
    },
}


def _entry_key(entry):
    if "file" in entry:
        return f"file::{entry['file']}::cores::{','.join(sorted(entry.get('cores', [])))}"
    names = sorted(entry.get("any_of", []))
    return f"any::{','.join(names)}::cores::{','.join(sorted(entry.get('cores', [])))}"


def _core_matches_entry(entry, core_filename):
    cores = entry.get("cores", [])
    if not cores:
        return True
    return core_filename in cores


def get_console_bios_requirements(console):
    system_id = resolve_system_id(console)
    raw = CONSOLE_BIOS_REQUIREMENTS.get(system_id)
    if not raw:
        return {"required": [], "optional": []}
    return {
        "required": deepcopy(raw.get("required", [])),
        "optional": deepcopy(raw.get("optional", [])),
    }


def get_console_bios_union(console):
    system_id = resolve_system_id(console)
    requirements = get_console_bios_requirements(system_id)
    seen_required = set()
    seen_optional = set()
    required = []
    optional = []

    for entry in requirements.get("required", []):
        key = _entry_key(entry)
        if key in seen_required:
            continue
        seen_required.add(key)
        required.append(deepcopy(entry))

    for entry in requirements.get("optional", []):
        key = _entry_key(entry)
        if key in seen_optional:
            continue
        seen_optional.add(key)
        optional.append(deepcopy(entry))

    return {"required": required, "optional": optional}


def get_required_for_core(console, core_filename):
    system_id = resolve_system_id(console)
    requirements = get_console_bios_requirements(system_id)
    return [entry for entry in requirements.get("required", []) if _core_matches_entry(entry, core_filename)]


def get_optional_for_core(console, core_filename):
    system_id = resolve_system_id(console)
    requirements = get_console_bios_requirements(system_id)
    return [entry for entry in requirements.get("optional", []) if _core_matches_entry(entry, core_filename)]


def consoles_with_bios_entries():
    result = []
    for system_id in CONSOLE_BIOS_REQUIREMENTS:
        data = CONSOLE_BIOS_REQUIREMENTS.get(system_id, {})
        if data.get("required") or data.get("optional"):
            result.append(system_id)
    return sorted(result)


def has_any_bios_requirement(console):
    system_id = resolve_system_id(console)
    data = CONSOLE_BIOS_REQUIREMENTS.get(system_id, {})
    return bool(data.get("required") or data.get("optional"))


def get_console_candidate_cores(console):
    return get_runtime_core_candidates(console)

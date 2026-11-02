"""What a selection of games becomes on the wire, and the receiver's first look.

The sending side turns rom dicts (the scanner's ``{name, path, console}``)
into the manifest of ``docs/share-protocol.md`` section 10: every file a game
needs to be played on the other device, with the source path of each item
kept aside for the upload. The receiving side checks each game and item
beyond the envelope :func:`protocol.validate_manifest` already checked, so one
bad item is answered ``skip`` rather than failing the whole offer.

Pure apart from reading the files it describes; no GTK, no network.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from openemux.core.bios_importer import canonical_bios_names
from openemux.core.save_backup import is_battery_save
from openemux.core.save_states import list_states
from openemux.core.scanner import _CUE_FILE_RE
from openemux.core.scraper import COVER_ART, LABEL_ART, find_local_art
from openemux.core.share.protocol import (
    ITEM_KINDS,
    KIND_BATTERY_SAVE,
    KIND_BIOS,
    KIND_COVER,
    KIND_LABEL,
    KIND_ROM,
    KIND_STATE,
    MAIN_ROLES,
    MAX_ITEMS,
    PART_ROLES,
    ErrorCode,
    ShareError,
    SkipReason,
    is_hex,
    is_safe_file_name,
)
from openemux.core.systems import SYSTEM_IDS, resolve_system_id

logger = logging.getLogger(__name__)

#: Items up to this size carry a sha256. Bigger ones (disc images) rely on TLS
#: and an exact Content-Length: hashing a CHD of several GB before every send
#: would double the time.
HASH_LIMIT = 64 * 1024 * 1024
HASH_CHUNK = 1024 * 1024
#: Suffixes that make up a unit rather than a core's save beside it.
_UNIT_SUFFIXES = (".cue", ".m3u")
STATE_SLOTS = range(10)
AUTO_SLOT = "auto"


@dataclass
class Unit:
    """A ROM's files: the main one first, each with its role."""

    main: Path
    parts: list

    @property
    def multi(self):
        return len(self.parts) > 1


@dataclass
class BuiltManifest:
    manifest: dict
    sources: dict = field(default_factory=dict)
    excluded: list = field(default_factory=list)


@dataclass
class ValidatedGame:
    """A manifest game after the receiver's structural check.

    ``items`` are the well-formed ones; ``rejected`` maps every other item id
    to the reason it is answered ``skip``.
    """

    game_id: str
    console: str
    title: str
    metadata: dict
    items: list
    rejected: dict


# -- units ---------------------------------------------------------------

def _is_bare(name):
    return bool(name) and "/" not in name and "\\" not in name and name not in (".", "..")


def _cue_references(cue_path):
    """The file names a cue sheet references, or ``None`` when unreadable."""
    try:
        lines = cue_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    names = []
    for line in lines:
        match = _CUE_FILE_RE.match(line)
        if match:
            name = (match.group(1) or match.group(2) or "").strip()
            if name:
                names.append(name)
    return names


def _m3u_entries(m3u_path):
    try:
        lines = m3u_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _referenced(directory, names, role, parts):
    """Append ``names`` to ``parts``; ``False`` when one leaves the directory or is missing."""
    for name in names:
        path = directory / name
        if not _is_bare(name) or not path.is_file():
            return False
        if all(existing != path for existing, _ in parts):
            parts.append((path, role))
    return True


def collect_unit(rom):
    """The files a ROM is made of, or ``None`` when one is missing.

    A ``.cue`` brings every file it references (role ``bin``); an ``.m3u``
    brings its discs (role ``disc``) and each disc's own cue references. A
    reference that leaves the cue's directory cannot travel without breaking
    the cue, so such a unit is not offered.
    """
    main = Path(rom["path"])
    if not main.is_file():
        return None
    suffix = main.suffix.lower()
    directory = main.parent
    if suffix == ".cue":
        parts = [(main, "cue")]
        names = _cue_references(main)
        if names is None or not _referenced(directory, names, "bin", parts):
            return None
        return Unit(main, parts)
    if suffix == ".m3u":
        parts = [(main, "m3u")]
        discs = _m3u_entries(main)
        if discs is None or not _referenced(directory, discs, "disc", parts):
            return None
        for disc in discs:
            if disc.lower().endswith(".cue"):
                names = _cue_references(directory / disc)
                if names is None or not _referenced(directory, names, "bin", parts):
                    return None
        return Unit(main, parts)
    return Unit(main, [(main, "main")])


# -- the sending side ----------------------------------------------------

def battery_saves(unit, console):
    """The core saves beside the unit's main file: same stem, then a dot."""
    prefix = f"{unit.main.stem}."
    taken = {path for path, _ in unit.parts}
    saves = []
    for sibling in sorted(unit.main.parent.iterdir()):
        if sibling in taken or not sibling.name.startswith(prefix):
            continue
        if sibling.suffix.lower() in _UNIT_SUFFIXES:
            continue
        if is_battery_save(sibling, console):
            saves.append(sibling)
    return saves


def _auto_state(console_states, stem):
    """The newest ``<stem>.state.auto``, in the console dir or a per-core one."""
    if not console_states.is_dir():
        return None
    candidates = [console_states / f"{stem}.state.auto"]
    candidates += [entry / f"{stem}.state.auto" for entry in console_states.iterdir() if entry.is_dir()]
    found = [path for path in candidates if path.is_file()]
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def state_core(state_path, console_states, effective):
    """``(core, core_version)`` a state belongs to.

    A state filed in a per-core subdirectory (``sort_savestates_enable``)
    belongs to the core named after it; any other to the game's effective
    core. A version nobody knows is ``""``, which never matches on the
    receiver.
    """
    if state_path.parent != console_states:
        name = state_path.parent.name
        return name, effective["catalog_version"](name)
    return effective["core"], effective["version"]


def _metadata(rom_path, config, playlists, catalog):
    metadata = {}
    if playlists is not None and playlists.is_favorite(rom_path):
        metadata["favorite"] = True
    color = config.get_rom_cartridge_color_override(rom_path)
    if color:
        metadata["cartridge_color"] = color
    core_name, _ = catalog.identity_for(config.get_rom_core_override(rom_path))
    if core_name:
        metadata["core"] = core_name
    shader = config.get_rom_shader_override(rom_path)
    if shader:
        metadata["shader"] = shader
    return metadata


def _game_files(rom, unit, console, roms_dir, states_dir, catalog, resolve_core):
    """``[(kind, path, extra)]`` for one game, in manifest order."""
    files = [(KIND_ROM, path, {"role": role}) for path, role in unit.parts]
    files += [(KIND_BATTERY_SAVE, path, {}) for path in battery_saves(unit, console)]

    console_states = Path(states_dir) / console
    core_path = resolve_core(console, rom["path"])
    core_name, version = catalog.identity_for(Path(core_path).name if core_path else None)

    def catalog_version(name):
        core = catalog.find_by_name(name)
        return core.version if core else ""

    effective = {"core": core_name, "version": version, "catalog_version": catalog_version}
    states = [(state.path, state.slot) for state in list_states(console_states, unit.main)]
    auto = _auto_state(console_states, unit.main.stem)
    if auto is not None:
        states.append((auto, AUTO_SLOT))
    for path, slot in states:
        core, core_version = state_core(path, console_states, effective)
        files.append((KIND_STATE, path, {"state": {"core": core, "core_version": core_version, "slot": slot}}))

    title = rom.get("name") or unit.main.stem
    for kind, art_kind in ((KIND_COVER, COVER_ART), (KIND_LABEL, LABEL_ART)):
        art = find_local_art(Path(roms_dir), console, title, art_kind)
        if art is not None:
            files.append((kind, art, {}))
    return files


def bios_files(roms_dir, console):
    """``[(name, path)]``: the catalog BIOS of ``console`` this device has.

    Read from ``<roms>/<console>/bios/`` -- the folder
    ``ConfigManager.get_console_bios_dir`` names -- and matched against the
    console's catalog without regard to case; ``name`` is the catalog's
    spelling, which is what a core opens. A file with the exact spelling wins
    over a case variant. Nothing else in the folder is ever offered.
    """
    expected = canonical_bios_names(console)
    directory = Path(roms_dir) / console / "bios"
    found = {}
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    for entry in entries:
        canonical = expected.get(entry.name.lower())
        if canonical is None or not entry.is_file():
            continue
        if canonical not in found or entry.name == canonical:
            found[canonical] = entry
    return sorted(found.items())


def _bios_entries(roms_dir, console, room):
    """``[((kind, path, extra), stat)]`` of the console's BIOS, or ``None`` when they cannot go now.

    ``None`` when one cannot be read or they need more than ``room`` items.
    """
    try:
        entries = [((KIND_BIOS, path, {"name": name}), path.stat()) for name, path in bios_files(roms_dir, console)]
    except OSError as exc:
        logger.warning("share manifest: %s BIOS left for a later game: %s", console, exc)
        return None
    return entries if len(entries) <= room else None


def _sendable_name(name):
    return is_safe_file_name(name) and not name.startswith(".")


def _sha256(path, on_bytes, cancel):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise ShareError(ErrorCode.CANCELLED, "cancelled while hashing")
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            on_bytes(len(chunk))
    return digest.hexdigest()


def build_manifest(roms, *, roms_dir, states_dir, catalog, resolve_core, config, playlists=None,
                   hash_limit=HASH_LIMIT, on_progress=None, cancel=None):
    """The manifest for ``roms``, the source of every item, and what was left out.

    ``resolve_core(console, rom_path)`` is the launcher's core resolution
    (``RetroArchLauncher.resolve_core_path``). Hashing reads every file up to
    ``hash_limit``, so this runs off the UI thread: ``on_progress(done,
    total)`` reports the hashed bytes and setting ``cancel`` (an Event) stops
    it with ``ShareError(cancelled)``.
    """
    built = BuiltManifest({"games": [], "total_size": 0, "file_count": 0})
    count = 0
    pending = []
    #: Consoles whose BIOS a game already carries: they travel once.
    carried = set()
    for rom in roms:
        console = resolve_system_id(rom.get("console", ""))
        if console not in SYSTEM_IDS:
            built.excluded.append({"rom": rom, "reason": SkipReason.UNSUPPORTED_CONSOLE})
            continue
        unit = collect_unit(rom)
        if unit is None:
            built.excluded.append({"rom": rom, "reason": SkipReason.UNIT_INCOMPLETE})
            continue
        try:
            files = _game_files(rom, unit, console, roms_dir, states_dir, catalog, resolve_core)
            stats = [path.stat() for _, path, _ in files]
        except OSError as exc:
            logger.warning("share manifest: %s left out: %s", rom.get("path"), exc)
            built.excluded.append({"rom": rom, "reason": SkipReason.UNIT_INCOMPLETE})
            continue
        if not all(_sendable_name(path.name) for _, path, _ in files):
            built.excluded.append({"rom": rom, "reason": SkipReason.INVALID_ITEM})
            continue
        if count + len(files) > MAX_ITEMS:
            built.excluded.append({"rom": rom, "reason": SkipReason.TOO_MANY_ITEMS})
            continue
        if console not in carried:
            # The BIOS never cost the game its place: one that cannot be read,
            # or that would not fit, is left for the next game of the console.
            bios = _bios_entries(roms_dir, console, MAX_ITEMS - count - len(files))
            if bios is not None:
                files += [entry for entry, _ in bios]
                stats += [stat for _, stat in bios]
                carried.add(console)
        count += len(files)

        game_id = f"g{len(built.manifest['games']) + 1}"
        game = {"id": game_id, "console": console, "title": rom.get("name") or unit.main.stem, "items": []}
        metadata = _metadata(rom["path"], config, playlists, catalog)
        if metadata:
            game["metadata"] = metadata
        for index, ((kind, path, extra), stat) in enumerate(zip(files, stats), start=1):
            item = {"id": f"{game_id}i{index}", "kind": kind, "name": extra.get("name", path.name),
                    "size": stat.st_size, "mtime": int(stat.st_mtime)}
            if kind == KIND_ROM and unit.multi:
                item["part"] = {"unit": game_id, "role": extra["role"]}
            if "state" in extra:
                item["state"] = extra["state"]
            game["items"].append(item)
            built.sources[item["id"]] = path
            built.manifest["total_size"] += stat.st_size
            if stat.st_size <= hash_limit:
                pending.append(item)
        built.manifest["games"].append(game)
    built.manifest["file_count"] = count

    total = sum(item["size"] for item in pending)
    done = [0]

    def on_bytes(n):
        done[0] += n
        if on_progress is not None:
            on_progress(done[0], total)

    for item in pending:
        item["sha256"] = _sha256(built.sources[item["id"]], on_bytes, cancel)
    return built


# -- the receiving side --------------------------------------------------

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_receivable_name(name):
    """A bare file name the receiver will write: never a path, never a dotfile."""
    return is_safe_file_name(name) and not name.startswith(".")


def _item_problem(item):
    """Why a manifest item cannot be used as it is, or ``None``."""
    if item.get("kind") not in ITEM_KINDS:
        return SkipReason.INVALID_ITEM
    if not is_receivable_name(item.get("name")):
        return SkipReason.INVALID_ITEM
    if not _is_int(item.get("size")) or item["size"] < 0 or not _is_number(item.get("mtime")):
        return SkipReason.INVALID_ITEM
    if "sha256" in item and not is_hex(item["sha256"], 64):
        return SkipReason.INVALID_ITEM
    part = item.get("part")
    if part is not None and (
        item["kind"] != KIND_ROM or not isinstance(part, dict)
        or not isinstance(part.get("unit"), str) or part.get("role") not in PART_ROLES
    ):
        return SkipReason.INVALID_ITEM
    if item["kind"] == KIND_STATE and not _valid_state(item.get("state")):
        return SkipReason.INVALID_ITEM
    return None


def _valid_state(state):
    if not isinstance(state, dict):
        return False
    if not isinstance(state.get("core"), str) or not isinstance(state.get("core_version"), str):
        return False
    slot = state.get("slot")
    return slot == AUTO_SLOT or (_is_int(slot) and slot in STATE_SLOTS)


def is_main_rom(item):
    part = item.get("part")
    return part is None or part["role"] in MAIN_ROLES


def validate_items(manifest):
    """Every game of ``manifest``, its usable items and why the others are not.

    A game needs exactly one main ROM item (a single file, or a unit's cue,
    m3u or main part); without one nothing of it can be placed, and every
    item is rejected. Items without a string id cannot even be answered, so
    they are dropped.
    """
    games = []
    for game in manifest.get("games", []):
        items, rejected = [], {}
        for item in game.get("items", []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            problem = _item_problem(item)
            if problem:
                rejected[item["id"]] = problem
            else:
                items.append(item)
        mains = [item for item in items if item["kind"] == KIND_ROM and is_main_rom(item)]
        if len(mains) != 1:
            rejected.update({item["id"]: SkipReason.INVALID_ITEM for item in items})
            items = []
        metadata = game.get("metadata")
        games.append(ValidatedGame(
            game_id=str(game.get("id", "")),
            console=str(game.get("console", "")),
            title=str(game.get("title", "")),
            metadata=metadata if isinstance(metadata, dict) else {},
            items=items,
            rejected=rejected,
        ))
    return games

"""Where every offered file would go, and whether it goes at all.

The receiver's decisions, made before anything is written: each item of an
offer is mapped to a target path computed here (a name from the wire is only
ever a suffix), checked against what the library already has under the
conflict policy for its kind, and the bytes still to come are checked against
the free space of every filesystem they would land on. Nothing here writes;
``receive.IncomingTransfer`` carries a plan out.

Defaults, per kind (the caller overrides any of them, per kind or per item):

* a ROM the library already has, byte for byte, is skipped; one with the
  same name and other content is kept beside it under a free name;
* battery saves and save states keep the newest -- strictly newer, so a tie
  keeps the local file and an older save never replaces a newer one;
* a cover or label the library already has is skipped: the user's own art wins;
* a BIOS file goes to the console's BIOS folder under the receiver's catalog
  spelling; the same file already there is skipped, and a different one is
  kept -- the local BIOS wins unless the user picks "Replace" (issue 677).
"""

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from openemux.core.archives import ARCHIVE_EXTENSIONS
from openemux.core.bios_importer import canonical_bios_names
from openemux.core.save_backup import (
    ON_COLLISION_KEEP_BOTH,
    ON_COLLISION_NEWEST,
    ON_COLLISION_OVERWRITE,
    ON_COLLISION_SKIP,
    SHARE_COLLISION_POLICIES,
    should_replace,
)
from openemux.core.save_states import list_states
from openemux.core.scraper import COVER_ART, LABEL_ART, SUPPORTED_COVER_EXTS, find_local_art
from openemux.core.share.manifest import (
    AUTO_SLOT,
    _auto_state,
    is_main_rom,
    is_receivable_name,
    validate_items,
)
from openemux.core.share.protocol import (
    KIND_BATTERY_SAVE,
    KIND_BIOS,
    KIND_COVER,
    KIND_LABEL,
    KIND_ROM,
    KIND_STATE,
    MAX_FILE_NAME_BYTES,
    SkipReason,
)
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)

ACTION_SEND = "send"
ACTION_SKIP = "skip"

DEFAULT_POLICIES = {
    KIND_ROM: ON_COLLISION_KEEP_BOTH,
    KIND_BATTERY_SAVE: ON_COLLISION_NEWEST,
    KIND_STATE: ON_COLLISION_NEWEST,
    KIND_COVER: ON_COLLISION_SKIP,
    KIND_LABEL: ON_COLLISION_SKIP,
    KIND_BIOS: ON_COLLISION_SKIP,
}
#: Kept free on every filesystem after the transfer.
SPACE_RESERVE = 64 * 1024 * 1024
#: Folder names the scanner treats as something else (art, BIOS).
_RESERVED_DIRS = {"covers", "labels", "bios"}
_ART_SUFFIXES = {f".{ext}" for ext in SUPPORTED_COVER_EXTS}
_ART_DIRS = {KIND_COVER: COVER_ART, KIND_LABEL: LABEL_ART}
#: The order a commit places things in; the receive side relies on it.
COMMIT_ORDER = (KIND_ROM, KIND_BATTERY_SAVE, KIND_STATE, KIND_COVER, KIND_LABEL, KIND_BIOS)
STATE_KEEP_BOTH_SLOTS = range(1, 10)
#: What a target name leaves free of the 255 bytes a file name may take: the
#: stage's temporary name (``.<name>.XXXXXXXX.tmp``) adds 14 bytes to it, and
#: a replaced file moved aside (``.<name>.share-old-<offer id>``) 34.
NAME_HEADROOM = 34

ROM_NEW = "new"
ROM_KEPT_BOTH = "kept_both"
ROM_REPLACED = "replaced"
ROM_EXISTING = "existing"
ROM_ABSENT = "absent"
#: ROM outcomes after which the game's metadata is applied in full.
ROM_PLACED = (ROM_NEW, ROM_KEPT_BOTH)


@dataclass
class Decision:
    item_id: str
    kind: str
    action: str
    reason: str = None
    target: Path = None
    policy: str = None
    replaces: Path = None
    size: int = 0
    mtime: float = 0
    sha256: str = None
    name: str = ""
    game_id: str = ""


@dataclass
class GamePlan:
    game_id: str
    console: str
    title: str
    metadata: dict
    rom_status: str = ROM_ABSENT
    rom_path: Path = None
    decisions: list = field(default_factory=list)
    #: Why the rest of the game is skipped when its ROM is ``absent``.
    absent_reason: str = SkipReason.USER_UNCHECKED


def state_compatible(state, catalog):
    """A state loads only in the exact core that made it: name and version, both known."""
    return catalog.find_by_identity(state.get("core", ""), state.get("core_version", "")) is not None


def _fits(name):
    return len(name.encode("utf-8")) + NAME_HEADROOM <= MAX_FILE_NAME_BYTES


def free_stem(stem, paths_for, taken, blocked=None):
    """``stem``, or ``stem (2)``, ``stem (3)``... -- the first whose paths are all free.

    ``paths_for(candidate)`` lists the paths a candidate would occupy; a path
    is free when nothing exists there and no other decision of the same plan
    reserved it, so two incoming games never pick the same name. ``blocked``
    rules a candidate out on its own terms.
    """
    candidate, n = stem, 1
    while True:
        paths = paths_for(candidate)
        free = all(not os.path.lexists(p) and p not in taken for p in paths)
        if free and not (blocked and blocked(candidate)):
            return candidate
        n += 1
        candidate = f"{stem} ({n})"


def free_name(directory, stem, suffix, taken):
    directory = Path(directory)
    return directory / (free_stem(stem, lambda s: [directory / f"{s}{suffix}"], taken) + suffix)


def _same_content(path, item):
    try:
        if path.stat().st_size != item["size"]:
            return False
        if "sha256" not in item:
            return True
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == item["sha256"]
    except OSError:
        return False


def _inside(target, base):
    try:
        Path(target).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


class ReceivePlan:
    def __init__(self, games, reserve=SPACE_RESERVE):
        self.games = games
        self.reserve = reserve

    def decisions(self):
        return [decision for game in self.games for decision in game.decisions]

    def to_send(self):
        """The ``send`` decisions, in commit order: ROM parts, saves, states, art."""
        sends = [d for d in self.decisions() if d.action == ACTION_SEND]
        return sorted(sends, key=lambda d: COMMIT_ORDER.index(d.kind))

    def answer_items(self):
        answer = []
        for decision in self.decisions():
            entry = {"id": decision.item_id, "action": decision.action}
            if decision.action == ACTION_SKIP:
                entry["reason"] = decision.reason
            answer.append(entry)
        return answer

    def space_check(self):
        """``[{path, needed, free, ok}]``, one per filesystem the files land on."""
        groups = {}
        for decision in self.to_send():
            ancestor = decision.target.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            device = os.stat(ancestor).st_dev
            group = groups.setdefault(device, {"path": str(ancestor), "needed": 0})
            group["needed"] += decision.size
        checks = []
        for group in groups.values():
            free = shutil.disk_usage(group["path"]).free
            checks.append({**group, "free": free, "ok": group["needed"] + self.reserve <= free})
        return checks

    def ok_to_accept(self, checks=None):
        return all(check["ok"] for check in (self.space_check() if checks is None else checks))


class _Planner:
    def __init__(self, roms_dir, states_dir, catalog, policies, overrides, unchecked):
        self.roms_dir = Path(roms_dir)
        self.states_dir = Path(states_dir)
        self.catalog = catalog
        self.policies = dict(DEFAULT_POLICIES)
        self.policies.update({k: v for k, v in (policies or {}).items() if v in SHARE_COLLISION_POLICIES})
        self.overrides = {k: v for k, v in (overrides or {}).items() if v in SHARE_COLLISION_POLICIES}
        self.unchecked = set(unchecked)
        self.taken = set()

    def policy(self, item):
        return self.overrides.get(item["id"], self.policies[item["kind"]])

    def skip(self, plan, item, reason):
        plan.decisions.append(Decision(
            item["id"], item.get("kind", ""), ACTION_SKIP, reason,
            name=item.get("name", ""), game_id=plan.game_id,
        ))

    def send(self, plan, item, target, base, policy=None, replaces=None):
        if not _fits(target.name) or not _inside(target, base):
            return self.skip(plan, item, SkipReason.INVALID_ITEM)
        self.taken.add(target)
        plan.decisions.append(Decision(
            item["id"], item["kind"], ACTION_SEND, None, target, policy, replaces,
            item["size"], item["mtime"], item.get("sha256"), item["name"], plan.game_id,
        ))

    # -- a game ----------------------------------------------------------

    def plan_game(self, validated):
        console = resolve_system_id(validated.console)
        plan = GamePlan(validated.game_id, console, validated.title, validated.metadata)
        for item_id, reason in validated.rejected.items():
            self.skip(plan, {"id": item_id}, reason)
        items = validated.items
        if console not in SYSTEM_IDS:
            for item in items:
                self.skip(plan, item, SkipReason.UNSUPPORTED_CONSOLE)
            return plan
        if validated.game_id in self.unchecked:
            self.unchecked.update(item["id"] for item in items)
        roms = [item for item in items if item["kind"] == KIND_ROM]
        if not items:
            return plan
        main = next(item for item in roms if is_main_rom(item))
        if not self._valid_rom_unit(console, main, roms):
            for item in items:
                self.skip(plan, item, SkipReason.INVALID_ITEM)
            return plan
        stem, rom_dir, final_stem = self.plan_rom(plan, console, main, roms)
        art_title = validated.title
        if plan.rom_status == ROM_KEPT_BOTH and Path(main["name"]).suffix.lower() not in ARCHIVE_EXTENSIONS:
            art_title = final_stem
        for item in items:
            if item["kind"] == KIND_ROM:
                continue
            if item["id"] in self.unchecked:
                self.skip(plan, item, SkipReason.USER_UNCHECKED)
            elif item["kind"] == KIND_BIOS:
                # A console's BIOS is no part of the game: it goes whatever
                # became of the ROM.
                self.plan_bios(plan, console, item)
            elif plan.rom_status == ROM_ABSENT:
                self.skip(plan, item, plan.absent_reason)
            elif item["kind"] == KIND_BATTERY_SAVE:
                self.plan_save(plan, console, item, stem, rom_dir, final_stem)
            elif item["kind"] == KIND_STATE:
                self.plan_state(plan, console, item, final_stem)
            else:
                self.plan_art(plan, console, item, art_title)
        return plan

    @staticmethod
    def _valid_rom_unit(console, main, roms):
        suffix = Path(main["name"]).suffix.lower()
        role = (main.get("part") or {}).get("role")
        if role == "m3u":
            return suffix == ".m3u"
        accepted = {ext.lower() for ext in get_supported_extensions(console)} | set(ARCHIVE_EXTENSIONS)
        if suffix not in accepted:
            return False
        # A single-file game is its main file alone.
        return main.get("part") is not None or len(roms) == 1

    # -- the ROM unit ----------------------------------------------------

    def plan_rom(self, plan, console, main, roms):
        """Decide every part of the unit as one; returns the names the rest follow."""
        console_dir = self.roms_dir / console
        name = main["name"]
        stem, suffix = Path(name).stem, Path(name).suffix
        multi = main.get("part") is not None
        parts = [item for item in roms if item is not main]
        default_dir = console_dir / stem if multi else console_dir
        candidates = [default_dir / name] + ([console_dir / name] if multi else [])
        existing = next((path for path in candidates if path.is_file()), None)

        def finish(status, rom_path, rom_dir, final_stem):
            plan.rom_status, plan.rom_path = status, rom_path
            return stem, rom_dir, final_stem

        if main["id"] in self.unchecked:
            for item in roms:
                self.skip(plan, item, SkipReason.USER_UNCHECKED)
            if existing is None:
                return finish(ROM_ABSENT, None, None, stem)
            return finish(ROM_EXISTING, existing, existing.parent, stem)

        if existing is not None and all(
            _same_content(existing.parent / item["name"], item) for item in roms
        ):
            for item in roms:
                self.skip(plan, item, SkipReason.EXISTS_SKIP)
            return finish(ROM_EXISTING, existing, existing.parent, stem)

        policy = self.policy(main)
        taken_here = any(path in self.taken for path in candidates)
        def invalid():
            plan.absent_reason = SkipReason.INVALID_ITEM
            return finish(ROM_ABSENT, None, None, stem)

        if existing is None and not taken_here and not (multi and self._dir_blocked(default_dir, roms)):
            if not self.send_unit(plan, [(item, default_dir / item["name"]) for item in roms],
                                  console_dir, policy):
                return invalid()
            return finish(ROM_NEW, default_dir / name, default_dir, stem)

        if existing is not None and policy != ON_COLLISION_KEEP_BOTH:
            if policy == ON_COLLISION_SKIP or not should_replace(existing, main["mtime"], policy):
                for item in roms:
                    self.skip(plan, item, SkipReason.EXISTS_SKIP)
                return finish(ROM_EXISTING, existing, existing.parent, stem)
            pairs = [(item, existing.parent / item["name"]) for item in roms]
            if not self.send_unit(plan, pairs, console_dir, policy, replacing=True):
                return invalid()
            return finish(ROM_REPLACED, existing, existing.parent, stem)

        # Keep both: the unit gets a free name; a multi-file unit also a free
        # folder. Its other parts keep their names -- the cue or m3u
        # references them by name.
        if multi:
            final_stem = free_stem(
                stem, lambda s: [console_dir / s, console_dir / f"{s}{suffix}"], self.taken,
                blocked=lambda s: s.lower() in _RESERVED_DIRS,
            )
            rom_dir = console_dir / final_stem
        else:
            final_stem = free_stem(stem, lambda s: [console_dir / f"{s}{suffix}"], self.taken)
            rom_dir = console_dir
        main_target = rom_dir / f"{final_stem}{suffix}"
        pairs = [(main, main_target)] + [(item, rom_dir / item["name"]) for item in parts]
        if not self.send_unit(plan, pairs, console_dir, ON_COLLISION_KEEP_BOTH):
            return invalid()
        if multi:
            self.taken.add(rom_dir)
        return finish(ROM_KEPT_BOTH, main_target, rom_dir, final_stem)

    def send_unit(self, plan, pairs, base, policy, replacing=False):
        """Send every part of a ROM unit, or none of them.

        A cue placed without one of its tracks is a broken game in the
        library, so one part that cannot go makes the whole unit
        ``invalid_item``. Returns whether the unit is sent.
        """
        if not all(_fits(target.name) and _inside(target, base) for _, target in pairs):
            for item, _ in pairs:
                self.skip(plan, item, SkipReason.INVALID_ITEM)
            return False
        for item, target in pairs:
            replaces = target if replacing and target.exists() else None
            self.send(plan, item, target, base, policy, replaces=replaces)
        return True

    def _dir_blocked(self, directory, roms):
        """A unit folder that cannot take this unit as it is named."""
        if directory.name.lower() in _RESERVED_DIRS or directory in self.taken:
            return True
        return any(os.path.lexists(directory / item["name"]) for item in roms)

    # -- saves, states, art ----------------------------------------------

    def resolve_conflict(self, plan, item, target, base, existing, keep_both):
        """Send, skip or keep both for an item whose target may be taken.

        ``existing`` is the local file the item would replace (it may sit at
        another path than ``target``: a state in a per-core folder, a cover
        with another extension). ``keep_both()`` returns where the incoming
        copy goes beside it, or ``None`` when it has nowhere to go.
        """
        if existing is None and target not in self.taken:
            return self.send(plan, item, target, base)
        if existing is None:
            return self.skip(plan, item, SkipReason.EXISTS_SKIP)
        policy = self.policy(item)
        if policy == ON_COLLISION_KEEP_BOTH:
            other = keep_both()
            if other is None:
                return self.skip(plan, item, SkipReason.EXISTS_SKIP)
            return self.send(plan, item, other, base, policy)
        if policy == ON_COLLISION_SKIP or not should_replace(existing, item["mtime"], policy):
            return self.skip(plan, item, SkipReason.EXISTS_SKIP)
        return self.send(plan, item, target, base, policy, replaces=existing)

    def plan_save(self, plan, console, item, stem, rom_dir, final_stem):
        name = item["name"]
        suffix = Path(name).suffix.lower()
        rom_suffixes = {ext.lower() for ext in get_supported_extensions(console)}
        if (
            not name.startswith(f"{stem}.")
            or suffix in rom_suffixes or suffix in _ART_SUFFIXES or suffix in (".cue", ".m3u")
        ):
            return self.skip(plan, item, SkipReason.INVALID_ITEM)
        target = rom_dir / f"{final_stem}{name[len(stem):]}"

        def keep_both():
            # RetroArch only loads <stem>.srm: the incoming copy is kept beside
            # it for a manual restore, and the save the game loads stays.
            stamp = datetime.fromtimestamp(item["mtime"], timezone.utc).strftime("%Y%m%d-%H%M%S")
            return free_name(rom_dir, f"{target.name}.shared-{stamp}", "", self.taken)

        existing = target if target.exists() else None
        self.resolve_conflict(plan, item, target, self.roms_dir / console, existing, keep_both)

    def plan_state(self, plan, console, item, final_stem):
        state = item["state"]
        if not state_compatible(state, self.catalog):
            return self.skip(plan, item, SkipReason.INCOMPATIBLE_STATE)
        console_states = self.states_dir / console
        slot = state["slot"]
        target = console_states / _state_name(final_stem, slot)
        # list_states takes a ROM path and keys on its stem; the dummy suffix
        # keeps a stem with dots in it whole.
        local_slots = {s.slot: s.path for s in list_states(console_states, f"{final_stem}.rom")}
        if target.exists():
            existing = target
        elif slot == AUTO_SLOT:
            existing = _auto_state(console_states, final_stem)
        else:
            existing = local_slots.get(slot)

        def keep_both():
            for free in STATE_KEEP_BOTH_SLOTS:
                candidate = console_states / _state_name(final_stem, free)
                if free not in local_slots and not candidate.exists() and candidate not in self.taken:
                    return candidate
            return None

        self.resolve_conflict(plan, item, target, console_states, existing, keep_both)

    def plan_art(self, plan, console, item, title):
        suffix = Path(item["name"]).suffix.lower()
        if suffix not in _ART_SUFFIXES or not is_receivable_name(f"{title}{suffix}"):
            return self.skip(plan, item, SkipReason.INVALID_ITEM)
        art_kind = _ART_DIRS[item["kind"]]
        base = self.roms_dir / console / art_kind
        target = base / f"{title}{suffix}"
        existing = target if target.exists() else find_local_art(self.roms_dir, console, title, art_kind)
        # Keeping both copies of a cover means nothing: the library shows one.
        self.resolve_conflict(plan, item, target, base, existing, lambda: None)


    def plan_bios(self, plan, console, item):
        canonical = canonical_bios_names(console).get(item["name"].lower())
        if canonical is None:
            return self.skip(plan, item, SkipReason.INVALID_ITEM)
        base = self.roms_dir / console / "bios"
        target = base / canonical
        if target in self.taken or ("sha256" in item and _same_content(target, item)):
            # The same BIOS is already there (or already coming): nothing to
            # ask about, and nothing to upload. Only a hash says so: a
            # console's BIOS dumps share a size (every PS one is 512 KiB), so
            # one that comes without a hash is a conflict, never a match.
            return self.skip(plan, item, SkipReason.EXISTS_SKIP)
        if os.path.lexists(target) and not target.is_file():
            return self.skip(plan, item, SkipReason.INVALID_ITEM)
        existing = target if target.exists() else None
        # A core opens its BIOS by name: a second copy beside it is useless.
        self.resolve_conflict(plan, item, target, base, existing, lambda: None)


def _state_name(stem, slot):
    if slot == AUTO_SLOT:
        return f"{stem}.state.auto"
    return f"{stem}.state{slot}" if slot else f"{stem}.state"


def plan_receive(manifest, *, roms_dir, states_dir, catalog, policies=None, overrides=None,
                 unchecked=(), reserve=SPACE_RESERVE):
    """Decide every item of ``manifest``; nothing is written.

    ``policies`` (``{kind: policy}``) replaces the defaults for a kind,
    ``overrides`` (``{item_id: policy}``) for one item, and ``unchecked``
    holds the game or item ids the user deselected. Policies are the
    ``save_backup`` ones: ``skip``, ``newest``, ``overwrite``, ``keep_both``.
    """
    planner = _Planner(roms_dir, states_dir, catalog, policies, overrides, unchecked)
    games = [planner.plan_game(validated) for validated in validate_items(manifest)]
    return ReceivePlan(games, reserve)


__all__ = [
    "ACTION_SEND", "ACTION_SKIP", "DEFAULT_POLICIES", "Decision", "GamePlan", "ReceivePlan",
    "ON_COLLISION_KEEP_BOTH", "ON_COLLISION_NEWEST", "ON_COLLISION_OVERWRITE", "ON_COLLISION_SKIP",
    "free_name", "free_stem", "plan_receive", "state_compatible",
]

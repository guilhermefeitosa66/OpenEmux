import hashlib
import os
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from openemux.core.share import placement
from openemux.core.share.placement import (
    ROM_ABSENT,
    ROM_EXISTING,
    ROM_KEPT_BOTH,
    ROM_NEW,
    ROM_REPLACED,
    free_name,
    plan_receive,
    state_compatible,
)
from tests.share_fixtures import PNG_BYTES, make_catalog, temp_library

SNES9X = {"core": "Snes9x", "core_version": "1.62.3"}


def item(item_id, kind, name, data=b"new", mtime=2000, hashed=True, **extra):
    entry = {"id": item_id, "kind": kind, "name": name, "size": len(data), "mtime": mtime, **extra}
    if hashed:
        entry["sha256"] = hashlib.sha256(data).hexdigest()
    return entry


def game(items, game_id="g1", console="SFC", title="Game", **extra):
    return {"id": game_id, "console": console, "title": title, "items": items, **extra}


def manifest(*games):
    return {"games": list(games), "total_size": 0, "file_count": 0}


def cue_items(game_id="g1", stem="Game", bins=(b"t1", b"t2"), hashed=True):
    unit = {"unit": game_id}
    items = [item(f"{game_id}c", "rom", f"{stem}.cue", b"cue", part={**unit, "role": "cue"}, hashed=hashed)]
    for n, data in enumerate(bins, start=1):
        items.append(item(f"{game_id}b{n}", "rom", f"Track {n}.bin", data, part={**unit, "role": "bin"},
                          hashed=hashed))
    return items


class PlacementTestCase(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})

    def plan(self, m, **kwargs):
        return plan_receive(m, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog, **kwargs)

    def decisions(self, plan):
        return {d.item_id: d for d in plan.decisions()}

    def answers(self, plan):
        return {entry["id"]: entry.get("reason", "send") for entry in plan.answer_items()}

    def target(self, plan, item_id):
        return self.decisions(plan)[item_id].target.relative_to(self.lib.root).as_posix()

    def sfc(self, *extra, data=b"new", title="Game"):
        return manifest(game([item("r", "rom", "Game.sfc", data)] + list(extra), title=title))


class RomTests(PlacementTestCase):
    def test_a_new_single_file_rom(self):
        plan = self.plan(self.sfc())
        self.assertEqual(self.target(plan, "r"), "roms/SFC/Game.sfc")
        self.assertEqual((plan.games[0].rom_status, plan.games[0].rom_path),
                         (ROM_NEW, self.lib.roms / "SFC" / "Game.sfc"))
        self.assertEqual(plan.answer_items(), [{"id": "r", "action": "send"}])

    def test_an_identical_rom_is_skipped_by_hash_or_by_size(self):
        self.lib.file("roms/SFC/Game.sfc", b"new")
        plan = self.plan(self.sfc())
        self.assertEqual((self.answers(plan), plan.games[0].rom_status), ({"r": "exists_skip"}, ROM_EXISTING))
        unhashed = manifest(game([item("r", "rom", "Game.sfc", b"new", hashed=False)]))
        self.assertEqual(self.answers(self.plan(unhashed)), {"r": "exists_skip"})

    def test_a_different_rom_is_kept_beside_with_its_saves_states_and_art(self):
        self.lib.file("roms/SFC/Game.sfc", b"old")
        self.lib.file("roms/SFC/Game (2).sfc", b"older")
        plan = self.plan(self.sfc(
            item("s", "battery_save", "Game.srm"),
            item("t", "state", "Game.state1", state={**SNES9X, "slot": 1}),
            item("c", "cover", "Game.png", PNG_BYTES),
        ))
        self.assertEqual(plan.games[0].rom_status, ROM_KEPT_BOTH)
        self.assertEqual([self.target(plan, i) for i in "rstc"], [
            "roms/SFC/Game (3).sfc", "roms/SFC/Game (3).srm", "states/SFC/Game (3).state1",
            "roms/SFC/covers/Game (3).png",
        ])

    def test_a_kept_archive_keeps_its_art_title(self):
        self.lib.file("roms/SFC/Game.zip", b"old")
        plan = self.plan(manifest(game([
            item("r", "rom", "Game.zip"), item("c", "cover", "Game.png", PNG_BYTES),
        ])))
        self.assertEqual(self.target(plan, "r"), "roms/SFC/Game (2).zip")
        self.assertEqual(self.target(plan, "c"), "roms/SFC/covers/Game.png")

    def test_rom_policies_on_a_different_rom(self):
        self.lib.file("roms/SFC/Game.sfc", b"old", mtime=1000)
        local = self.lib.roms / "SFC" / "Game.sfc"
        for policy, mtime, expected, status in (
            ("skip", 3000, "exists_skip", ROM_EXISTING),
            ("newest", 1000, "exists_skip", ROM_EXISTING),
            ("newest", 3000, "send", ROM_REPLACED),
            ("overwrite", 10, "send", ROM_REPLACED),
        ):
            m = manifest(game([item("r", "rom", "Game.sfc", mtime=mtime)]))
            plan = self.plan(m, overrides={"r": policy})
            self.assertEqual((self.answers(plan)["r"], plan.games[0].rom_status), (expected, status), policy)
            if expected == "send":
                self.assertEqual(self.decisions(plan)["r"].replaces, local)
        plan = self.plan(manifest(game([item("r", "rom", "Game.sfc", mtime=3000)])), policies={"rom": "newest"})
        self.assertEqual(plan.games[0].rom_status, ROM_REPLACED)

    def test_unknown_policies_fall_back_to_the_defaults(self):
        self.lib.file("roms/SFC/Game.sfc", b"old")
        plan = self.plan(self.sfc(), policies={"rom": "explode"}, overrides={"r": "nope"})
        self.assertEqual(plan.games[0].rom_status, ROM_KEPT_BOTH)

    def test_two_incoming_games_never_pick_the_same_name(self):
        m = manifest(
            game([item("a", "rom", "Game.sfc", b"one")], game_id="g1"),
            game([item("b", "rom", "Game.sfc", b"two")], game_id="g2"),
            game([item("c", "rom", "Game.sfc", b"three")], game_id="g3"),
        )
        plan = self.plan(m)
        self.assertEqual([self.target(plan, i) for i in "abc"],
                         ["roms/SFC/Game.sfc", "roms/SFC/Game (2).sfc", "roms/SFC/Game (3).sfc"])

    def test_unsupported_rom_suffixes(self):
        for name in ("x.exe", "Game.m3u"):
            plan = self.plan(manifest(game([item("r", "rom", name), item("s", "battery_save", "x.srm")])))
            self.assertEqual(self.answers(plan), {"r": "invalid_item", "s": "invalid_item"}, name)

    def test_a_single_main_rom_cannot_bring_loose_parts(self):
        m = manifest(game([item("r", "rom", "Game.sfc"),
                           item("b", "rom", "x.bin", part={"unit": "g1", "role": "bin"})]))
        self.assertEqual(self.answers(self.plan(m)), {"r": "invalid_item", "b": "invalid_item"})

    def test_archives_are_accepted_roms(self):
        plan = self.plan(manifest(game([item("r", "rom", "Other.zip")])))
        self.assertEqual(self.answers(plan), {"r": "send"})


class UnitTests(PlacementTestCase):
    def ps(self, *extra, **kwargs):
        return manifest(game(cue_items(**kwargs) + list(extra), console="PS"))

    def test_a_multi_file_unit_goes_in_its_own_folder(self):
        plan = self.plan(self.ps(item("s", "battery_save", "Game.srm")))
        self.assertEqual([self.target(plan, i) for i in ("g1c", "g1b1", "g1b2", "s")], [
            "roms/PS/Game/Game.cue", "roms/PS/Game/Track 1.bin", "roms/PS/Game/Track 2.bin",
            "roms/PS/Game/Game.srm",
        ])

    def test_an_identical_unit_already_flat_in_the_console_folder(self):
        self.lib.file("roms/PS/Game.cue", b"cue")
        self.lib.file("roms/PS/Track 1.bin", b"t1")
        self.lib.file("roms/PS/Track 2.bin", b"t2")
        plan = self.plan(self.ps(item("s", "battery_save", "Game.srm")))
        self.assertEqual(self.answers(plan)["g1b2"], "exists_skip")
        self.assertEqual(plan.games[0].rom_path, self.lib.roms / "PS" / "Game.cue")
        self.assertEqual(self.target(plan, "s"), "roms/PS/Game.srm")

    def test_a_different_unit_is_kept_in_a_free_folder(self):
        self.lib.file("roms/PS/Game/Game.cue", b"other")
        self.lib.file("roms/PS/Game (2).cue", b"flat")
        plan = self.plan(self.ps(item("t", "state", "Game.state", state={**SNES9X, "slot": 0})))
        self.assertEqual([self.target(plan, i) for i in ("g1c", "g1b1", "t")], [
            "roms/PS/Game (3)/Game (3).cue", "roms/PS/Game (3)/Track 1.bin", "states/PS/Game (3).state",
        ])

    def test_a_unit_replacing_one_keeps_the_existing_folder(self):
        self.lib.file("roms/PS/Game/Game.cue", b"other", mtime=10)
        plan = self.plan(self.ps(), overrides={"g1c": "newest"})
        d = self.decisions(plan)
        self.assertEqual(plan.games[0].rom_status, ROM_REPLACED)
        self.assertEqual((d["g1c"].replaces, d["g1b1"].replaces), (self.lib.roms / "PS/Game/Game.cue", None))

    def test_a_folder_already_holding_some_parts(self):
        self.lib.file("roms/PS/Game/Track 1.bin", b"someone else's")
        plan = self.plan(self.ps())
        self.assertEqual(self.target(plan, "g1c"), "roms/PS/Game (2)/Game (2).cue")

    def test_a_unit_with_one_part_that_cannot_go_is_left_out_whole(self):
        # The cue fits as it is named; one track's name leaves no room for the
        # temporary name a stage writes it under.
        long_bin = "b" * 230 + ".bin"
        items = cue_items()
        items[2]["name"] = long_bin
        plan = self.plan(manifest(game(items + [item("s", "battery_save", "Game.srm")], console="PS")))
        self.assertEqual(self.answers(plan), {
            "g1c": "invalid_item", "g1b1": "invalid_item", "g1b2": "invalid_item", "s": "invalid_item",
        })
        self.assertEqual((plan.games[0].rom_status, plan.games[0].rom_path), (ROM_ABSENT, None))

    def test_a_replacing_or_kept_unit_with_a_part_that_cannot_go(self):
        long_bin = "b" * 230 + ".bin"
        for overrides in ({"g1c": "overwrite"}, {}):
            self.setUp()
            self.lib.file("roms/PS/Game/Game.cue", b"other", mtime=10)
            items = cue_items()
            items[2]["name"] = long_bin
            plan = self.plan(manifest(game(items, console="PS")), overrides=overrides)
            self.assertEqual(set(self.answers(plan).values()), {"invalid_item"}, overrides)
            self.assertEqual(plan.games[0].rom_status, ROM_ABSENT, overrides)

    def test_reserved_folder_names(self):
        plan = self.plan(manifest(game(cue_items(stem="covers"), console="PS")))
        self.assertEqual(self.target(plan, "g1c"), "roms/PS/covers (2)/covers (2).cue")

    def test_m3u_units(self):
        unit = {"unit": "g1"}
        m = manifest(game([
            item("m", "rom", "Game.m3u", part={**unit, "role": "m3u"}),
            item("d", "rom", "Disc 1.chd", part={**unit, "role": "disc"}),
        ], console="PS"))
        plan = self.plan(m)
        self.assertEqual(self.target(plan, "d"), "roms/PS/Game/Disc 1.chd")
        bad = manifest(game([item("m", "rom", "Game.cue", part={**unit, "role": "m3u"})], console="PS"))
        self.assertEqual(self.answers(self.plan(bad)), {"m": "invalid_item"})


class SaveTests(PlacementTestCase):
    def test_policies(self):
        local = self.lib.file("roms/SFC/Game.srm", b"local", mtime=1000)
        self.lib.file("roms/SFC/Game.sfc", b"new")
        cases = (
            (None, 999, "exists_skip"), (None, 1000, "exists_skip"), (None, 1001, "send"),
            ("skip", 5000, "exists_skip"), ("overwrite", 1, "send"),
        )
        for policy, mtime, expected in cases:
            m = self.sfc(item("s", "battery_save", "Game.srm", mtime=mtime))
            plan = self.plan(m, overrides={"s": policy} if policy else None)
            self.assertEqual(self.answers(plan)["s"], expected, (policy, mtime))
            if expected == "send":
                self.assertEqual(self.decisions(plan)["s"].replaces, local)

    def test_keep_both_keeps_the_copy_beside_it(self):
        self.lib.file("roms/SFC/Game.sfc", b"new")
        self.lib.file("roms/SFC/Game.srm", b"local")
        m = self.sfc(item("s", "battery_save", "Game.srm", mtime=1700000000))
        plan = self.plan(m, policies={"battery_save": "keep_both"})
        self.assertEqual(self.target(plan, "s"), "roms/SFC/Game.srm.shared-20231114-221320")

    def test_names_that_are_not_this_games_saves(self):
        for name in ("Other.srm", "Game.smc", "Game.png", "Game.cue", "Gamesrm"):
            plan = self.plan(self.sfc(item("s", "battery_save", name)))
            self.assertEqual(self.answers(plan)["s"], "invalid_item", name)

    def test_a_save_name_taken_twice_in_one_offer(self):
        plan = self.plan(self.sfc(item("a", "battery_save", "Game.srm"), item("b", "battery_save", "Game.srm")))
        self.assertEqual((self.answers(plan)["a"], self.answers(plan)["b"]), ("send", "exists_skip"))


class StateTests(PlacementTestCase):
    def state(self, slot=1, mtime=2000, item_id="t", **identity):
        name = "Game.state.auto" if slot == "auto" else f"Game.state{slot or ''}"
        return item(item_id, "state", name, mtime=mtime, state={**SNES9X, **identity, "slot": slot})

    def test_compatibility(self):
        self.assertTrue(state_compatible({**SNES9X, "slot": 1}, self.catalog))
        for identity in ({"core_version": "1.62"}, {"core": "snes9x"}, {"core": "", "core_version": ""}):
            self.assertFalse(state_compatible({**SNES9X, **identity}, self.catalog), identity)
            plan = self.plan(self.sfc(self.state(**identity)))
            self.assertEqual(self.answers(plan)["t"], "incompatible_state")

    def test_slots_and_auto(self):
        plan = self.plan(self.sfc(self.state(0, item_id="a"), self.state(4, item_id="b"),
                                  self.state("auto", item_id="c")))
        self.assertEqual([self.target(plan, i) for i in "abc"],
                         ["states/SFC/Game.state", "states/SFC/Game.state4", "states/SFC/Game.state.auto"])

    def test_newest_against_a_local_state(self):
        self.lib.file("states/SFC/Game.state1", mtime=2000)
        self.assertEqual(self.answers(self.plan(self.sfc(self.state(mtime=2000))))["t"], "exists_skip")
        self.assertEqual(self.answers(self.plan(self.sfc(self.state(mtime=2001))))["t"], "send")

    def test_a_local_state_in_a_per_core_folder(self):
        local = self.lib.file("states/SFC/Snes9x/Game.state1", mtime=100)
        plan = self.plan(self.sfc(self.state()))
        d = self.decisions(plan)["t"]
        self.assertEqual((self.target(plan, "t"), d.replaces), ("states/SFC/Game.state1", local))
        auto = self.lib.file("states/SFC/Snes9x/Game.state.auto", mtime=100)
        self.assertEqual(self.decisions(self.plan(self.sfc(self.state("auto"))))["t"].replaces, auto)

    def test_keep_both_takes_the_first_free_slot(self):
        for slot in (1, 2):
            self.lib.file(f"states/SFC/Game.state{slot}")
        self.lib.file("states/SFC/Snes9x/Game.state3")
        plan = self.plan(self.sfc(self.state(1, item_id="a"), self.state(2, item_id="b")),
                         policies={"state": "keep_both"})
        self.assertEqual([self.target(plan, i) for i in "ab"], ["states/SFC/Game.state4", "states/SFC/Game.state5"])

    def test_keep_both_with_no_free_slot(self):
        for slot in range(1, 10):
            self.lib.file(f"states/SFC/Game.state{slot}")
        plan = self.plan(self.sfc(self.state()), overrides={"t": "keep_both"})
        self.assertEqual(self.answers(plan)["t"], "exists_skip")

    def test_a_stem_with_dots(self):
        self.lib.file("states/SFC/Game.v2.state1")
        m = manifest(game([item("r", "rom", "Game.v2.sfc"),
                           item("t", "state", "Game.v2.state1", state={**SNES9X, "slot": 1})]))
        plan = self.plan(m, overrides={"t": "keep_both"})
        self.assertEqual(self.target(plan, "t"), "states/SFC/Game.v2.state2")


class ArtTests(PlacementTestCase):
    def test_new_art(self):
        plan = self.plan(self.sfc(item("c", "cover", "Game.png", PNG_BYTES), item("l", "label", "x.jpg", PNG_BYTES)))
        self.assertEqual([self.target(plan, i) for i in "cl"],
                         ["roms/SFC/covers/Game.png", "roms/SFC/labels/Game.jpg"])

    def test_existing_art_wins_by_default(self):
        self.lib.file("roms/SFC/covers/Game.jpg", PNG_BYTES, mtime=1)
        self.assertEqual(self.answers(self.plan(self.sfc(item("c", "cover", "Game.png"))))["c"], "exists_skip")
        plan = self.plan(self.sfc(item("c", "cover", "Game.png")), overrides={"c": "keep_both"})
        self.assertEqual(self.answers(plan)["c"], "exists_skip")
        plan = self.plan(self.sfc(item("c", "cover", "Game.png")), overrides={"c": "overwrite"})
        d = self.decisions(plan)["c"]
        self.assertEqual((self.target(plan, "c"), d.replaces.name), ("roms/SFC/covers/Game.png", "Game.jpg"))

    def test_bad_art(self):
        for title, name in (("Game", "Game.gif"), (".hidden", "x.png")):
            plan = self.plan(self.sfc(item("c", "cover", name), title=title))
            self.assertEqual(self.answers(plan)["c"], "invalid_item", name)


class GameLevelTests(PlacementTestCase):
    def test_unsupported_console(self):
        m = manifest(game([item("r", "rom", "Game.adf"), item("x", "hologram", "x")], console="AMIGA"))
        self.assertEqual(self.answers(self.plan(m)), {"x": "invalid_item", "r": "unsupported_console"})

    def test_console_aliases(self):
        plan = self.plan(manifest(game([item("r", "rom", "Game.sfc")], console="SNES")))
        self.assertEqual(self.target(plan, "r"), "roms/SFC/Game.sfc")

    def test_user_unchecked_game_and_items(self):
        m = self.sfc(item("s", "battery_save", "Game.srm"))
        self.assertEqual(self.answers(self.plan(m, unchecked={"g1"})), {"r": "user_unchecked", "s": "user_unchecked"})
        plan = self.plan(m, unchecked={"s"})
        self.assertEqual(self.answers(plan), {"r": "send", "s": "user_unchecked"})

    def test_an_unchecked_rom_places_its_saves_beside_the_local_one(self):
        m = self.sfc(item("s", "battery_save", "Game.srm"))
        plan = self.plan(m, unchecked={"r"})
        self.assertEqual((self.answers(plan), plan.games[0].rom_status),
                         ({"r": "user_unchecked", "s": "user_unchecked"}, ROM_ABSENT))
        self.lib.file("roms/SFC/Game.sfc", b"different")
        plan = self.plan(m, unchecked={"r"})
        self.assertEqual((self.answers(plan), plan.games[0].rom_status),
                         ({"r": "user_unchecked", "s": "send"}, ROM_EXISTING))

    def test_a_game_with_no_usable_items(self):
        plan = self.plan(manifest(game([])))
        self.assertEqual(plan.answer_items(), [])

    def test_names_leave_room_for_the_temporary_and_moved_aside_names(self):
        fits = "a" * (255 - placement.NAME_HEADROOM - 4)
        plan = self.plan(manifest(game([item("r", "rom", f"{fits}.sfc")])))
        self.assertEqual(self.answers(plan)["r"], "send")
        plan = self.plan(manifest(game([item("r", "rom", f"{fits}a.sfc")])))
        self.assertEqual(self.answers(plan)["r"], "invalid_item")
        # Not only a ROM: a save whose name leaves no such room is refused alone.
        plan = self.plan(self.sfc(item("s", "battery_save", "Game." + "s" * 230)))
        self.assertEqual(self.answers(plan), {"r": "send", "s": "invalid_item"})

    def test_names_too_long_after_renaming(self):
        long_stem = "a" * (255 - placement.NAME_HEADROOM - 7)
        self.lib.file(f"roms/SFC/{long_stem}.sfc", b"old")
        plan = self.plan(manifest(game([item("r", "rom", f"{long_stem}.sfc")])))
        self.assertEqual(self.answers(plan)["r"], "invalid_item")

    def test_a_target_outside_its_base_is_refused(self):
        with mock.patch.object(placement, "_inside", return_value=False):
            self.assertEqual(self.answers(self.plan(self.sfc()))["r"], "invalid_item")
        self.assertFalse(placement._inside(self.lib.root / "x", self.lib.roms))

    def test_free_name(self):
        directory = self.lib.root / "d"
        self.lib.file("d/a.srm")
        self.assertEqual(free_name(directory, "a", ".srm", set()).name, "a (2).srm")
        self.assertEqual(free_name(directory, "a", ".srm", {directory / "a (2).srm"}).name, "a (3).srm")

    def test_same_content_on_an_unreadable_file(self):
        self.lib.file("roms/SFC/Game.sfc", b"new")
        with mock.patch("builtins.open", side_effect=OSError("io")):
            plan = self.plan(self.sfc())
        self.assertEqual(plan.games[0].rom_status, ROM_KEPT_BOTH)


Usage = namedtuple("Usage", "total used free")


class SpaceTests(PlacementTestCase):
    def test_enough_space(self):
        plan = self.plan(self.sfc(data=b"x" * 10))
        [check] = plan.space_check()
        self.assertEqual((check["path"], check["needed"], check["ok"]), (str(self.lib.root), 10, True))
        self.assertTrue(plan.ok_to_accept())

    def test_the_reserve_counts(self):
        plan = self.plan(self.sfc(data=b"x" * 10), reserve=100)
        with mock.patch.object(placement.shutil, "disk_usage", return_value=Usage(0, 0, 109)):
            self.assertFalse(plan.ok_to_accept())
        with mock.patch.object(placement.shutil, "disk_usage", return_value=Usage(0, 0, 110)):
            self.assertTrue(plan.ok_to_accept())

    def test_short_on_one_of_two_filesystems(self):
        plan = self.plan(self.sfc(item("t", "state", "Game.state1", b"s" * 5, state={**SNES9X, "slot": 1}),
                                  data=b"x" * 10), reserve=0)
        self.lib.roms.mkdir()
        self.lib.states.mkdir()
        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if Path(path) == self.lib.states:
                return os.stat_result((result.st_mode, 0, result.st_dev + 1) + tuple(result)[3:])
            return result

        def usage(path):
            return Usage(0, 0, 100 if Path(path) == self.lib.roms else 3)

        with mock.patch.object(placement.os, "stat", side_effect=fake_stat), \
                mock.patch.object(placement.shutil, "disk_usage", side_effect=usage):
            checks = plan.space_check()
        self.assertEqual(sorted((Path(c["path"]).name, c["needed"], c["free"], c["ok"]) for c in checks),
                         [("roms", 10, 100, True), ("states", 5, 3, False)])
        self.assertFalse(plan.ok_to_accept(checks))

    def test_to_send_is_in_commit_order(self):
        plan = self.plan(self.sfc(item("c", "cover", "Game.png", PNG_BYTES),
                                  item("t", "state", "Game.state1", state={**SNES9X, "slot": 1}),
                                  item("s", "battery_save", "Game.srm")))
        self.assertEqual([d.item_id for d in plan.to_send()], ["r", "s", "t", "c"])



class BiosTests(PlacementTestCase):
    """A console's BIOS lands in its BIOS folder (issue 677)."""

    def ps(self, *extra, rom=b"rom"):
        return manifest(game([item("r", "rom", "Game.chd", rom)] + list(extra), console="PS"))

    def test_a_new_bios_goes_to_the_bios_folder_under_the_catalog_spelling(self):
        plan = self.plan(self.ps(item("b", "bios", "SCPH5501.BIN", b"bios")))
        self.assertEqual(self.target(plan, "b"), "roms/PS/bios/scph5501.bin")
        self.assertEqual(plan.to_send()[-1].item_id, "b")
        self.assertEqual(placement.DEFAULT_POLICIES["bios"], "skip")

    def test_a_name_the_console_does_not_expect_is_refused(self):
        for name in ("notes.txt", "bios7.bin"):
            plan = self.plan(self.ps(item("b", "bios", name, b"bios")))
            self.assertEqual(self.answers(plan)["b"], "invalid_item", name)

    def test_the_same_bios_is_skipped_without_a_conflict(self):
        self.lib.file("roms/PS/bios/scph5501.bin", b"bios", mtime=1)
        plan = self.plan(self.ps(item("b", "bios", "scph5501.bin", b"bios")), policies={"bios": "overwrite"})
        self.assertEqual(self.answers(plan)["b"], "exists_skip")
        self.assertIsNone(self.decisions(plan)["b"].replaces)

    def test_a_different_bios_is_kept_unless_replaced(self):
        existing = self.lib.file("roms/PS/bios/scph5501.bin", b"mine", mtime=1)
        m = self.ps(item("b", "bios", "scph5501.bin", b"theirs"))
        self.assertEqual(self.answers(self.plan(m))["b"], "exists_skip")
        replaced = self.decisions(self.plan(m, overrides={"b": "overwrite"}))["b"]
        self.assertEqual((replaced.action, replaced.replaces), ("send", existing))
        # Keeping both means nothing: a core opens one name.
        self.assertEqual(self.answers(self.plan(m, overrides={"b": "keep_both"}))["b"], "exists_skip")

    def test_a_folder_under_the_bios_name_is_refused(self):
        (self.lib.roms / "PS" / "bios" / "scph5501.bin").mkdir(parents=True)
        plan = self.plan(self.ps(item("b", "bios", "scph5501.bin", b"bios")))
        self.assertEqual(self.answers(plan)["b"], "invalid_item")

    def test_the_same_bios_twice_in_one_offer_goes_once(self):
        m = manifest(
            game([item("r", "rom", "One.chd"), item("b", "bios", "scph5501.bin", b"bios")], console="PS"),
            game([item("r2", "rom", "Two.chd"), item("b2", "bios", "scph5501.bin", b"bios")],
                 game_id="g2", console="PS"),
        )
        self.assertEqual({k: v for k, v in self.answers(self.plan(m)).items() if k.startswith("b")},
                         {"b": "send", "b2": "exists_skip"})

    def test_bios_go_whatever_became_of_the_rom(self):
        self.lib.file("roms/PS/Game.chd", b"rom")
        plan = self.plan(self.ps(item("b", "bios", "scph5501.bin", b"bios")))
        self.assertEqual(plan.games[0].rom_status, ROM_EXISTING)
        self.assertEqual(self.answers(plan), {"r": "exists_skip", "b": "send"})

    def test_unchecked_bios_and_unchecked_games_are_skipped(self):
        m = self.ps(item("b", "bios", "scph5501.bin", b"bios"))
        self.assertEqual(self.answers(self.plan(m, unchecked={"b"}))["b"], "user_unchecked")
        self.assertEqual(self.answers(self.plan(m, unchecked={"g1"}))["b"], "user_unchecked")


if __name__ == "__main__":
    unittest.main()

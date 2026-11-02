import hashlib
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

from openemux.core.share import manifest as manifest_module
from openemux.core.share.manifest import (
    build_manifest,
    collect_unit,
    is_receivable_name,
    validate_items,
)
from openemux.core.share.protocol import ShareError, SkipReason, validate_manifest
from tests.share_fixtures import (
    PNG_BYTES,
    FakeConfig,
    FakePlaylists,
    core_file,
    make_catalog,
    temp_library,
)

VECTORS = Path(__file__).parent / "data" / "share_vectors.json"


class ManifestTestCase(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {
            "snes9x": ("Snes9x", "1.62.3"),
            "bsnes": ("bsnes", "115"),
            "noinfo": None,
        })
        self.core = core_file("snes9x")
        self.config = FakeConfig()

    def build(self, roms, **kwargs):
        kwargs.setdefault("resolve_core", lambda console, path: f"/cores/{self.core}" if self.core else None)
        kwargs.setdefault("config", self.config)
        return build_manifest(
            roms, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog, **kwargs
        )

    def items(self, built, game=0):
        return built.manifest["games"][game]["items"]

    def names(self, built, game=0):
        return [(item["kind"], item["name"]) for item in self.items(built, game)]


class UnitTests(ManifestTestCase):
    def test_single_file(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        unit = collect_unit(rom)
        self.assertFalse(unit.multi)
        self.assertEqual(unit.parts, [(Path(rom["path"]), "main")])

    def test_cue_with_two_bins_is_one_unit(self):
        rom = self.lib.cue_game("PS", "Game")
        unit = collect_unit(rom)
        self.assertTrue(unit.multi)
        self.assertEqual([(p.name, role) for p, role in unit.parts],
                         [("Game.cue", "cue"), ("Track 1.bin", "bin"), ("Track 2.bin", "bin")])

    def test_cue_lines_that_name_no_file(self):
        self.lib.file("roms/PS/Track 1.bin")
        cue = self.lib.file("roms/PS/Game.cue", 'REM a comment\nFILE "   " BINARY\nFILE "Track 1.bin" BINARY\n')
        self.assertEqual([p.name for p, _ in collect_unit({"path": str(cue)}).parts], ["Game.cue", "Track 1.bin"])

    def test_a_bin_referenced_twice_is_listed_once(self):
        rom = self.lib.cue_game("PS", "Game", bins=("Track 1.bin", "Track 1.bin"))
        self.assertEqual(len(collect_unit(rom).parts), 2)

    def test_incomplete_or_escaping_cues_are_not_units(self):
        missing = self.lib.cue_game("PS", "Missing")
        (self.lib.roms / "PS" / "Track 2.bin").unlink()
        self.assertIsNone(collect_unit(missing))
        for name, reference in (("Up", "../x.bin"), ("Down", "tracks/x.bin"), ("Back", "tracks\\x.bin")):
            self.lib.file("roms/PS/tracks/x.bin")
            self.lib.file("roms/x.bin")
            cue = self.lib.file(f"roms/PS/{name}.cue", f'FILE "{reference}" BINARY\n')
            self.assertIsNone(collect_unit({"path": str(cue)}), name)

    def test_unreadable_files(self):
        self.assertIsNone(collect_unit({"path": str(self.lib.roms / "nope.sfc")}))
        cue = self.lib.file("roms/PS/Game.cue", "")
        with mock.patch.object(Path, "read_text", side_effect=OSError("gone")):
            self.assertIsNone(collect_unit({"path": str(cue)}))
        m3u = self.lib.file("roms/PS/Game.m3u", "")
        with mock.patch.object(Path, "read_text", side_effect=OSError("gone")):
            self.assertIsNone(collect_unit({"path": str(m3u)}))

    def test_m3u_with_two_discs_one_of_them_a_cue(self):
        self.lib.cue_game("PS", "Disc 1", bins=("Disc 1.bin",))
        self.lib.file("roms/PS/Disc 2.chd", b"chd")
        m3u = self.lib.file("roms/PS/Game.m3u", "# a comment\nDisc 1.cue\n\nDisc 2.chd\n")
        unit = collect_unit({"path": str(m3u)})
        self.assertEqual([(p.name, role) for p, role in unit.parts], [
            ("Game.m3u", "m3u"), ("Disc 1.cue", "disc"), ("Disc 2.chd", "disc"), ("Disc 1.bin", "bin"),
        ])

    def test_m3u_with_a_missing_disc_or_track(self):
        m3u = self.lib.file("roms/PS/Game.m3u", "Disc 1.cue\n")
        self.assertIsNone(collect_unit({"path": str(m3u)}))
        self.lib.file("roms/PS/Disc 1.cue", 'FILE "Disc 1.bin" BINARY\n')
        self.assertIsNone(collect_unit({"path": str(m3u)}))

    def test_archives_travel_as_they_are(self):
        rom = self.lib.rom("SFC", "Game.zip")
        self.assertEqual(collect_unit(rom).parts, [(Path(rom["path"]), "main")])


class BuildTests(ManifestTestCase):
    def test_single_file_game(self):
        rom = self.lib.rom("SFC", "Game.sfc", b"abc", mtime=1700000000)
        built = self.build([rom])
        game = built.manifest["games"][0]
        self.assertEqual((game["id"], game["console"], game["title"]), ("g1", "SFC", "Game"))
        self.assertNotIn("metadata", game)
        self.assertEqual(game["items"], [{
            "id": "g1i1", "kind": "rom", "name": "Game.sfc", "size": 3, "mtime": 1700000000,
            "sha256": hashlib.sha256(b"abc").hexdigest(),
        }])
        self.assertEqual(built.sources, {"g1i1": Path(rom["path"])})
        self.assertEqual((built.manifest["total_size"], built.manifest["file_count"]), (3, 1))
        validate_manifest(built.manifest)

    def test_console_aliases_are_sent_canonical(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        rom["console"] = "SNES"
        self.assertEqual(self.build([rom]).manifest["games"][0]["console"], "SFC")

    def test_cue_unit_carries_its_roles(self):
        built = self.build([self.lib.cue_game("PS", "Game")])
        self.assertEqual([item["part"] for item in self.items(built)], [
            {"unit": "g1", "role": "cue"}, {"unit": "g1", "role": "bin"}, {"unit": "g1", "role": "bin"},
        ])

    def test_battery_saves(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        self.lib.file("roms/SFC/Game.srm")
        self.lib.file("roms/SFC/Game.data.szsnes")
        self.lib.file("roms/SFC/Game.smc")          # another ROM sharing the stem
        self.lib.file("roms/SFC/Game.png")          # art, not a save
        self.lib.file("roms/SFC/Game (Rev 1).srm")  # another game's save
        self.lib.file("roms/SFC/.Game.srm.x.tmp")   # a temp file
        self.assertEqual(self.names(self.build([rom])), [
            ("rom", "Game.sfc"), ("battery_save", "Game.data.szsnes"), ("battery_save", "Game.srm"),
        ])

    def test_a_cue_units_saves_leave_its_m3u_and_cue_alone(self):
        rom = self.lib.cue_game("PS", "Game")
        self.lib.file("roms/PS/Game.m3u", "Game.cue\n")
        self.lib.file("roms/PS/Game.srm")
        self.assertEqual([n for n in self.names(self.build([rom])) if n[0] == "battery_save"],
                         [("battery_save", "Game.srm")])

    def test_states_slots_and_auto_with_the_effective_core(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        self.lib.file("states/SFC/Game.state")
        self.lib.file("states/SFC/Game.state3")
        self.lib.file("states/SFC/Game.state.auto")
        self.lib.file("states/SFC/Game.state3.png")
        states = [item for item in self.items(self.build([rom])) if item["kind"] == "state"]
        self.assertEqual([(s["name"], s["state"]) for s in states], [
            ("Game.state", {"core": "Snes9x", "core_version": "1.62.3", "slot": 0}),
            ("Game.state3", {"core": "Snes9x", "core_version": "1.62.3", "slot": 3}),
            ("Game.state.auto", {"core": "Snes9x", "core_version": "1.62.3", "slot": "auto"}),
        ])

    def test_a_state_in_a_per_core_folder_belongs_to_that_core(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        self.lib.file("states/SFC/bsnes/Game.state1")
        self.lib.file("states/SFC/Unknown/Game.state2")
        self.lib.file("states/SFC/bsnes/Game.state.auto", mtime=100)
        self.lib.file("states/SFC/Game.state.auto", mtime=50)
        states = {s["name"]: s["state"] for s in self.items(self.build([rom])) if s["kind"] == "state"}
        self.assertEqual(states["Game.state1"], {"core": "bsnes", "core_version": "115", "slot": 1})
        self.assertEqual(states["Game.state2"], {"core": "Unknown", "core_version": "", "slot": 2})
        self.assertEqual(states["Game.state.auto"], {"core": "bsnes", "core_version": "115", "slot": "auto"})

    def test_a_core_without_info_or_none_at_all(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        self.lib.file("states/SFC/Game.state1")
        self.core = core_file("noinfo")
        self.assertEqual(self.items(self.build([rom]))[1]["state"]["core_version"], "")
        self.core = None
        self.assertEqual(self.items(self.build([rom]))[1]["state"], {"core": "", "core_version": "", "slot": 1})

    def test_cover_and_label(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        self.assertEqual(self.names(self.build([rom])), [("rom", "Game.sfc")])
        self.lib.file("roms/SFC/covers/Game.jpg", PNG_BYTES)
        self.lib.file("roms/SFC/labels/Game.png", PNG_BYTES)
        self.assertEqual(self.names(self.build([rom]))[1:], [("cover", "Game.jpg"), ("label", "Game.png")])

    def test_only_overrides_and_the_favorite_are_sent(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        path = rom["path"]
        self.config = FakeConfig(colors={path: "black"}, cores={path: core_file("bsnes")},
                                 shaders={path: "crt-easymode"})
        built = self.build([rom], playlists=FakePlaylists([path]))
        self.assertEqual(built.manifest["games"][0]["metadata"], {
            "favorite": True, "cartridge_color": "black", "core": "bsnes", "shader": "crt-easymode",
        })
        self.config = FakeConfig(cores={path: core_file("gone")})
        self.assertNotIn("metadata", self.build([rom], playlists=FakePlaylists()).manifest["games"][0])

    def test_excluded_games(self):
        cue = self.lib.cue_game("PS", "Broken")
        (self.lib.roms / "PS" / "Track 1.bin").unlink()
        # A dotfile is a name the receiver refuses; so is one over 255 bytes,
        # which most filesystems cannot even hold.
        hidden = self.lib.rom("SFC", ".hidden.sfc")
        roms = [{"name": "?", "path": "/nowhere", "console": "AMIGA"}, cue, hidden]
        built = self.build(roms)
        self.assertEqual(built.manifest["games"], [])
        self.assertEqual([e["reason"] for e in built.excluded], [
            SkipReason.UNSUPPORTED_CONSOLE, SkipReason.UNIT_INCOMPLETE, SkipReason.INVALID_ITEM,
        ])

    def test_a_file_vanishing_while_building(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        with mock.patch.object(manifest_module, "battery_saves", side_effect=OSError("gone")):
            built = self.build([rom])
        self.assertEqual(built.excluded, [{"rom": rom, "reason": SkipReason.UNIT_INCOMPLETE}])

    def test_the_item_limit(self):
        roms = [self.lib.rom("SFC", f"G{n}.sfc") for n in range(3)]
        with mock.patch.object(manifest_module, "MAX_ITEMS", 2):
            built = self.build(roms)
        self.assertEqual(len(built.manifest["games"]), 2)
        self.assertEqual(built.excluded, [{"rom": roms[2], "reason": SkipReason.TOO_MANY_ITEMS}])
        self.assertEqual(built.manifest["file_count"], 2)

    def test_hash_only_up_to_the_limit(self):
        small = self.lib.rom("SFC", "Small.sfc", b"ab")
        big = self.lib.rom("SFC", "Big.sfc", b"abcdef")
        progress = []
        built = self.build([small, big], hash_limit=4, on_progress=lambda d, t: progress.append((d, t)))
        self.assertIn("sha256", self.items(built, 0)[0])
        self.assertNotIn("sha256", self.items(built, 1)[0])
        self.assertEqual(progress, [(2, 2)])
        self.assertEqual(built.manifest["total_size"], 8)

    def test_cancel_while_hashing(self):
        rom = self.lib.rom("SFC", "Game.sfc")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ShareError) as caught:
            self.build([rom], cancel=cancel)
        self.assertEqual(caught.exception.code, "cancelled")


class ValidateTests(unittest.TestCase):
    def game(self, items, **extra):
        return {"games": [{"id": "g1", "console": "SFC", "title": "Game", "items": items, **extra}],
                "total_size": 0, "file_count": len(items)}

    def rom(self, item_id="i1", **extra):
        return {"id": item_id, "kind": "rom", "name": "Game.sfc", "size": 1, "mtime": 1, **extra}

    def test_a_good_game(self):
        save = {"id": "i2", "kind": "battery_save", "name": "Game.srm", "size": 1, "mtime": 1.5}
        state = {"id": "i3", "kind": "state", "name": "Game.state1", "size": 1, "mtime": 1,
                 "state": {"core": "Snes9x", "core_version": "1", "slot": "auto"}}
        [game] = validate_items(self.game([self.rom(sha256="a" * 64), save, state], metadata={"favorite": True}))
        self.assertEqual(([i["id"] for i in game.items], game.rejected), (["i1", "i2", "i3"], {}))
        self.assertEqual((game.game_id, game.console, game.title, game.metadata),
                         ("g1", "SFC", "Game", {"favorite": True}))

    def test_bad_items_become_invalid_item(self):
        bad = [
            {"id": "k", "kind": "hologram", "name": "x.bin", "size": 1, "mtime": 1},
            {"id": "n1", "kind": "cover", "name": "../evil.png", "size": 1, "mtime": 1},
            {"id": "n2", "kind": "cover", "name": ".hidden.png", "size": 1, "mtime": 1},
            {"id": "n3", "kind": "cover", "name": "a/b.png", "size": 1, "mtime": 1},
            {"id": "s", "kind": "cover", "name": "c.png", "size": -1, "mtime": 1},
            {"id": "b", "kind": "cover", "name": "c.png", "size": True, "mtime": 1},
            {"id": "m", "kind": "cover", "name": "c.png", "size": 1, "mtime": "now"},
            {"id": "h", "kind": "cover", "name": "c.png", "size": 1, "mtime": 1, "sha256": "zz"},
            {"id": "p1", "kind": "cover", "name": "c.png", "size": 1, "mtime": 1, "part": {"unit": "g1", "role": "bin"}},
            {"id": "p2", "kind": "rom", "name": "t.bin", "size": 1, "mtime": 1, "part": {"unit": "g1", "role": "track"}},
            {"id": "p3", "kind": "rom", "name": "t.bin", "size": 1, "mtime": 1, "part": "g1"},
            {"id": "t1", "kind": "state", "name": "Game.state1", "size": 1, "mtime": 1},
            {"id": "t2", "kind": "state", "name": "Game.state1", "size": 1, "mtime": 1,
             "state": {"core": "x", "core_version": 1, "slot": 1}},
            {"id": "t3", "kind": "state", "name": "Game.state1", "size": 1, "mtime": 1,
             "state": {"core": "x", "core_version": "1", "slot": 10}},
            {"id": "t4", "kind": "state", "name": "Game.state1", "size": 1, "mtime": 1,
             "state": {"core": "x", "core_version": "1", "slot": True}},
        ]
        [game] = validate_items(self.game([self.rom()] + bad + ["junk", {"kind": "rom"}]))
        self.assertEqual([i["id"] for i in game.items], ["i1"])
        self.assertEqual(game.rejected, {item["id"]: SkipReason.INVALID_ITEM for item in bad})

    def test_a_game_needs_exactly_one_main_rom(self):
        save = {"id": "i2", "kind": "battery_save", "name": "Game.srm", "size": 1, "mtime": 1}
        for items in ([save], [self.rom("a"), self.rom("b"), save]):
            [game] = validate_items(self.game(items))
            self.assertEqual(game.items, [])
            self.assertEqual(set(game.rejected), {item["id"] for item in items})

    def test_odd_game_fields(self):
        [game] = validate_items({"games": [{"items": [self.rom()], "metadata": "x"}]})
        self.assertEqual((game.game_id, game.console, game.metadata), ("", "", {}))

    def test_receivable_names(self):
        self.assertTrue(is_receivable_name("Game.sfc"))
        for name in ("", ".hidden", "a/b", "..", None, "a" * 256):
            self.assertFalse(is_receivable_name(name), name)


class SharedVectorTests(unittest.TestCase):
    def test_the_manifest_sample_validates(self):
        sample = json.loads(VECTORS.read_text(encoding="utf-8"))["manifest_sample"]
        validate_manifest(sample)
        [game] = validate_items(sample)
        self.assertEqual(game.rejected, {})
        self.assertEqual({item["kind"] for item in game.items}, {"rom", "battery_save", "state", "cover", "bios"})



class BiosTests(ManifestTestCase):
    """A console's BIOS go with the first of its games (issue 677)."""

    def test_catalog_bios_are_found_under_the_catalog_spelling(self):
        self.lib.file("roms/PS/bios/SCPH5501.BIN", b"bios")
        self.lib.file("roms/PS/bios/scph1001.bin", b"other")
        self.lib.file("roms/PS/bios/notes.txt", b"mine")
        self.lib.file("roms/PS/bios/bios7.bin", b"a DS BIOS")
        (self.lib.roms / "PS" / "bios" / "scph7001.bin").mkdir()
        self.assertEqual(
            [(name, path.name) for name, path in manifest_module.bios_files(self.lib.roms, "PS")],
            [("scph1001.bin", "scph1001.bin"), ("scph5501.bin", "SCPH5501.BIN")],
        )

    def test_the_exact_spelling_wins_over_a_case_variant(self):
        self.lib.file("roms/PS/bios/SCPH5501.BIN", b"variant")
        if (self.lib.roms / "PS" / "bios" / "scph5501.bin").exists():
            self.skipTest("a case-insensitive filesystem holds one spelling only")
        self.lib.file("roms/PS/bios/scph5501.bin", b"exact")
        self.lib.file("roms/PS/bios/Scph5501.Bin", b"variant too")
        [(name, path)] = manifest_module.bios_files(self.lib.roms, "PS")
        self.assertEqual((name, path.name), ("scph5501.bin", "scph5501.bin"))

    def test_no_bios_folder_is_no_bios(self):
        self.assertEqual(manifest_module.bios_files(self.lib.roms, "PS"), [])

    def test_only_the_first_game_of_a_console_carries_them(self):
        self.lib.file("roms/PS/bios/scph5501.bin", b"bios", mtime=1234)
        self.lib.file("roms/FDS/bios/disksys.rom", b"fds")
        first = self.lib.rom("PS", "First.chd")
        second = self.lib.rom("PS", "Second.chd")
        fds = self.lib.rom("FDS", "Disk.fds")
        built = self.build([first, second, fds])
        self.assertEqual(self.names(built, 0), [("rom", "First.chd"), ("bios", "scph5501.bin")])
        self.assertEqual(self.names(built, 1), [("rom", "Second.chd")])
        self.assertEqual(self.names(built, 2), [("rom", "Disk.fds"), ("bios", "disksys.rom")])
        bios = self.items(built, 0)[1]
        self.assertEqual((bios["size"], bios["mtime"]), (4, 1234))
        self.assertEqual(bios["sha256"], hashlib.sha256(b"bios").hexdigest())
        self.assertTrue(built.sources[bios["id"]].samefile(self.lib.roms / "PS" / "bios" / "scph5501.bin"))
        self.assertEqual(built.manifest["file_count"], 5)

    def test_a_game_left_out_hands_them_to_the_next_one(self):
        self.lib.file("roms/PS/bios/scph5501.bin", b"bios")
        missing = {"name": "Gone", "path": str(self.lib.roms / "PS" / "Gone.chd"), "console": "PS"}
        kept = self.lib.rom("PS", "Kept.chd")
        built = self.build([missing, kept])
        self.assertEqual(self.names(built, 0), [("rom", "Kept.chd"), ("bios", "scph5501.bin")])


if __name__ == "__main__":
    unittest.main()

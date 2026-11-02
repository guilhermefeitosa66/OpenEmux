"""What the user picked to send, over a real built manifest (#589)."""

import unittest
from unittest import mock

from openemux.core.share import selection
from openemux.core.share.manifest import build_manifest
from openemux.core.share.protocol import SkipReason
from tests.share_fixtures import PNG_BYTES, FakeConfig, FakePlaylists, make_catalog, temp_library


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})
        self.full = self.lib.rom("SFC", "Full.sfc", b"rom" * 10)
        self.lib.file("roms/SFC/Full.srm", b"save", mtime=3000)
        self.lib.file("roms/SFC/Full.rtc", b"rtc", mtime=4000)
        self.lib.file("states/SFC/Full.state1", b"s1")
        self.lib.file("states/SFC/Full.state2", b"s2")
        self.lib.file("roms/SFC/covers/Full.png", PNG_BYTES)
        self.lib.file("roms/SFC/labels/Full.png", PNG_BYTES)
        self.bare = self.lib.rom("FC", "Bare.nes", b"nes")
        self.odd = {"name": "Odd", "path": str(self.lib.roms / "XX" / "Odd.bin"), "console": "XX"}

    def build(self, roms, favorites=()):
        return build_manifest(
            roms, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog,
            resolve_core=lambda console, path: None, config=FakeConfig(),
            playlists=FakePlaylists(favorites),
        )

    def test_roms_for_console_reads_the_playlist(self):
        playlists = mock.Mock()
        playlists.load_playlist.return_value = iter([self.full])
        self.assertEqual(selection.roms_for_console(playlists, "SFC"), [self.full])
        playlists.load_playlist.assert_called_once_with("SFC")

    def test_inventory_groups_each_game(self):
        built = self.build([self.full, self.bare, self.odd], favorites=[self.full["path"]])
        games, excluded = selection.inventory(built)
        full, bare = games
        self.assertEqual(full["key"], self.full["path"])
        self.assertEqual(list(full["groups"]), [c for c in selection.CATEGORIES if c != selection.BIOS])
        self.assertEqual(full["groups"]["battery"]["count"], 2)
        self.assertEqual(full["groups"]["battery"]["mtime"], 4000)
        self.assertEqual(full["groups"]["states"]["count"], 2)
        self.assertEqual(full["groups"]["game"]["name"], "Full.sfc")
        self.assertEqual(full["size"], built.manifest["games"][0]["items"][0]["size"] + 4 + 3 + 2 + 2 + 2 * len(PNG_BYTES))
        self.assertEqual(list(bare["groups"]), ["game"])
        self.assertEqual(bare["console"], "FC")
        self.assertEqual(excluded, [{"title": "Odd", "console": "XX", "reason": SkipReason.UNSUPPORTED_CONSOLE}])

    def test_unchecking_groups_drops_their_items_and_recounts(self):
        built = self.build([self.full, self.bare], favorites=[self.full["path"]])
        key = self.full["path"]
        picked = selection.apply_selection(built, {(key, "states"), (key, "cover"), (key, "details")})
        game = picked.manifest["games"][0]
        self.assertEqual([i["kind"] for i in game["items"]], ["rom", "battery_save", "battery_save", "label"])
        self.assertNotIn("metadata", game)
        self.assertIn("metadata", built.manifest["games"][0])
        self.assertEqual(picked.manifest["file_count"], 5)
        self.assertEqual(set(picked.sources), {i["id"] for g in picked.manifest["games"] for i in g["items"]})
        summary = selection.summarize(picked)
        self.assertEqual(summary["titles"], ["Full", "Bare"])
        self.assertEqual((summary["games"], summary["files"]), (2, 5))
        self.assertEqual(summary["size"], sum(i["size"] for g in picked.manifest["games"] for i in g["items"]))

    def test_unchecking_the_game_leaves_the_whole_game_out(self):
        built = self.build([self.full, self.bare])
        picked = selection.apply_selection(built, {(self.full["path"], "game")})
        self.assertEqual([g["title"] for g in picked.manifest["games"]], ["Bare"])
        self.assertEqual(selection.summarize(selection.apply_selection(built, set()))["games"], 2)

    def test_kept_roms_drops_the_unchecked_games_and_the_excluded(self):
        roms = [self.odd, self.full, self.bare]
        built = self.build(roms)
        self.assertEqual(selection.kept_roms(built, roms, set()), [self.full, self.bare])
        self.assertEqual(selection.kept_roms(built, roms, {(self.full["path"], "game")}), [self.bare])
        # A group unchecked keeps its game: apply_selection drops the group.
        self.assertEqual(selection.kept_roms(built, roms, {(self.bare["path"], "states")}), [self.full, self.bare])



class BiosSelectionTests(unittest.TestCase):
    """The BIOS group is the console's, whichever game carries it (issue 677)."""

    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {})
        self.lib.file("roms/PS/bios/scph5501.bin", b"bios")
        self.lib.file("roms/PS/bios/scph1001.bin", b"bios two")
        self.first = self.lib.rom("PS", "First.chd")
        self.second = self.lib.rom("PS", "Second.chd")
        self.roms = [self.first, self.second]

    def build(self, roms):
        return build_manifest(
            roms, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog,
            resolve_core=lambda console, path: None, config=FakeConfig(),
        )

    def kinds(self, picked):
        return [[(i["kind"], i["name"]) for i in g["items"]] for g in picked.manifest["games"]]

    def test_the_carrier_lists_a_bios_group(self):
        games, _ = selection.inventory(self.build(self.roms))
        first, second = games
        self.assertEqual(list(first["groups"]), ["game", "bios"])
        self.assertEqual((first["groups"]["bios"]["count"], first["groups"]["bios"]["size"]), (2, 12))
        self.assertEqual(list(second["groups"]), ["game"])
        self.assertEqual(selection.group_key(first, "bios"), ("bios:PS", "bios"))
        self.assertEqual(selection.group_key(first, "game"), (self.first["path"], "game"))

    def test_unchecking_bios_holds_for_the_console(self):
        built = self.build(self.roms)
        picked = selection.apply_selection(built, {(selection.bios_key("PS"), "bios")})
        self.assertEqual(self.kinds(picked), [[("rom", "First.chd")], [("rom", "Second.chd")]])
        self.assertEqual(picked.manifest["file_count"], 2)

    def test_a_carrier_left_out_hands_its_bios_on(self):
        built = self.build(self.roms)
        picked = selection.apply_selection(built, {(self.first["path"], "game")})
        self.assertEqual(self.kinds(picked), [[
            ("rom", "Second.chd"), ("bios", "scph1001.bin"), ("bios", "scph5501.bin"),
        ]])
        self.assertEqual(set(picked.sources), {i["id"] for g in picked.manifest["games"] for i in g["items"]})
        # The send rebuilds from the kept games alone: the same files go.
        rebuilt = self.build(selection.kept_roms(built, self.roms, {(self.first["path"], "game")}))
        self.assertEqual(selection.summarize(rebuilt)["files"], selection.summarize(picked)["files"])

    def test_a_carrier_left_out_with_bios_unchecked_sends_none(self):
        built = self.build(self.roms)
        unchecked = {(self.first["path"], "game"), (selection.bios_key("PS"), "bios")}
        self.assertEqual(self.kinds(selection.apply_selection(built, unchecked)), [[("rom", "Second.chd")]])


if __name__ == "__main__":
    unittest.main()

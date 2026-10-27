"""Share nearby's words and numbers (#589): every code, reason and size has text."""

import os
import time
import unittest

from openemux.core.share import display
from openemux.core.share.placement import plan_receive
from openemux.core.share.protocol import ErrorCode, SkipReason
from openemux.i18n import LOCALE_TRANSLATIONS, tr
from tests.share_fixtures import PNG_BYTES, make_catalog, temp_library
from tests.test_share_placement import game, item, manifest


def t(key, **kwargs):
    return tr("en", key, **kwargs)


class FormatSizeTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(display.format_size(0, t), "0 B")
        self.assertEqual(display.format_size(999, t), "999 B")
        self.assertEqual(display.format_size(1000, t), "1 kB")
        self.assertEqual(display.format_size(999_499, t), "999 kB")
        self.assertEqual(display.format_size(1_500_000, t), "1.5 MB")
        self.assertEqual(display.format_size(2_300_000_000, t), "2.3 GB")


class WordsTests(unittest.TestCase):
    def test_plural_picks_the_key_by_count(self):
        self.assertEqual(display.plural(t, 1, "share.offer.games.one", "share.offer.games.many"), "1 game")
        self.assertEqual(display.plural(t, 3, "share.offer.games.one", "share.offer.games.many"), "3 games")

    def test_paths_are_named_in_a_stable_order(self):
        self.assertEqual(display.paths_label(frozenset(), t), "")
        self.assertEqual(display.paths_label({"beacon"}, t), "beacon")
        self.assertEqual(display.paths_label({"beacon", "mdns"}, t), "mDNS and beacon")
        self.assertEqual(display.paths_label({"manual", "beacon", "mdns"}, t), "mDNS, beacon and address")

    def test_platforms_fall_back_to_desktop(self):
        self.assertEqual(display.platform_icon("phone"), "phone-symbolic")
        self.assertEqual(display.platform_icon("tablet"), "tablet-symbolic")
        self.assertEqual(display.platform_icon("toaster"), "computer-symbolic")
        self.assertEqual(display.platform_key("toaster"), "share.platform.desktop")
        self.assertEqual(display.platform_key("phone"), "share.platform.phone")

    def test_every_error_code_has_text(self):
        codes = [v for k, v in vars(ErrorCode).items() if not k.startswith("_")]
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(display.error_key(code), LOCALE_TRANSLATIONS["en"])
        self.assertEqual(display.error_key("weird"), "share.error.generic")
        self.assertEqual(display.error_key(ErrorCode.DECLINED), "share.error.declined")

    def test_every_skip_reason_has_text(self):
        reasons = [v for k, v in vars(SkipReason).items() if not k.startswith("_")]
        for reason in reasons:
            with self.subTest(reason=reason):
                self.assertIn(display.reason_key(reason), LOCALE_TRANSLATIONS["en"])
        self.assertEqual(display.reason_key("weird"), "share.reason.invalid_item")

    def test_every_skip_reason_has_text_for_the_sender(self):
        reasons = [v for k, v in vars(SkipReason).items() if not k.startswith("_")]
        for reason in reasons + [None, "weird"]:
            with self.subTest(reason=reason):
                self.assertIn(display.sender_reason_key(reason), LOCALE_TRANSLATIONS["en"])
        self.assertEqual(display.sender_reason_key(SkipReason.EXISTS_SKIP), "share.reason.sent.exists_skip")
        self.assertEqual(display.sender_reason_key(None), "share.reason.sent.not_accepted")
        self.assertEqual(display.sender_reason_key(SkipReason.INVALID_ITEM), "share.reason.sent.cant_place")

    def test_item_kinds(self):
        self.assertEqual(display.item_kind_label("rom", t), "Game")
        self.assertEqual(display.item_kind_label("battery_save", t), "Battery Save")
        self.assertEqual(display.item_kind_label("cover", t), "Cover")
        self.assertEqual(display.item_kind_label("label", t), "Cartridge Label")
        self.assertEqual(display.item_kind_label("state", t, slot=3), "State, Slot 3")
        self.assertEqual(display.item_kind_label("state", t, slot=None), "State, Slot 0")
        self.assertEqual(display.item_kind_label("state", t, slot="auto"), "Auto State")
        self.assertEqual(display.item_kind_label("weird", t), "Game")

    def test_countdown_and_code(self):
        self.assertEqual(display.countdown(60), "1:00")
        self.assertEqual(display.countdown(42.7), "0:42")
        self.assertEqual(display.countdown(-3), "0:00")
        self.assertEqual(display.spaced_digits("482 913"), "4 8 2 9 1 3")

    def test_format_date_is_local_time(self):
        stamp = time.mktime((2026, 10, 27, 9, 5, 0, 0, 0, -1))
        self.assertEqual(display.format_date(stamp), "2026-10-27 09:05")


class ConflictRowsTests(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})

    def plan(self, m, **kwargs):
        return plan_receive(m, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog, **kwargs)

    def test_rows_for_each_existing_file_with_both_dates(self):
        self.lib.file("roms/SFC/Game.sfc", b"old rom", mtime=1000)
        self.lib.file("roms/SFC/Game.srm", b"old save", mtime=5000)
        self.lib.file("roms/SFC/covers/Game.png", PNG_BYTES, mtime=1000)
        self.lib.file("states/SFC/Game.state1", b"old", mtime=1000)
        m = manifest(game([
            item("r", "rom", "Game.sfc", b"new rom"),
            item("s", "battery_save", "Game.srm", b"new save", mtime=2000),
            item("st", "state", "Game.state1", b"new", state={"core": "Snes9x", "core_version": "1.62.3", "slot": 1}),
            item("c", "cover", "Game.png", PNG_BYTES),
            item("n", "battery_save", "Game.rtc", b"fresh"),
        ]))
        rows = {row["item_id"]: row for row in display.conflict_rows(self.plan(m, policies=display.PROBE_POLICIES), m)}
        self.assertEqual(sorted(rows), ["c", "r", "s", "st"])
        self.assertEqual(rows["s"]["yours"], 5000)
        self.assertEqual(rows["s"]["incoming"], 2000)
        self.assertFalse(rows["s"]["newer"])
        self.assertTrue(rows["r"]["newer"])
        self.assertEqual(rows["st"]["slot"], 1)
        self.assertEqual(rows["r"]["game"], "Game")
        self.assertEqual(rows["c"]["policies"], ("skip", "overwrite"))
        self.assertEqual(rows["r"]["policies"], display.POLICIES)

    def test_a_multi_file_rom_is_one_row_and_identical_files_none(self):
        unit = {"unit": "g1"}
        self.lib.file("roms/PS/Disc/Disc.cue", b"cue old", mtime=1000)
        self.lib.file("roms/PS/Disc/Track 1.bin", b"bin old", mtime=1000)
        self.lib.file("roms/SFC/Same.sfc", b"same", mtime=2000)
        m = manifest(
            game([
                item("c", "rom", "Disc.cue", b"cue new", part={**unit, "role": "cue"}),
                item("b", "rom", "Track 1.bin", b"bin new", part={**unit, "role": "bin"}),
            ], console="PS", title="Disc"),
            game([item("x", "rom", "Same.sfc", b"same", mtime=2000)], game_id="g2", title="Same"),
        )
        rows = display.conflict_rows(self.plan(m, policies=display.PROBE_POLICIES), m)
        self.assertEqual([row["item_id"] for row in rows], ["c"])

    def test_a_file_gone_since_the_plan_is_no_row(self):
        path = self.lib.file("roms/SFC/Game.sfc", b"old", mtime=1000)
        m = manifest(game([item("r", "rom", "Game.sfc", b"new")]))
        probe = self.plan(m, policies=display.PROBE_POLICIES)
        os.remove(path)
        self.assertEqual(display.conflict_rows(probe, m), [])


if __name__ == "__main__":
    unittest.main()

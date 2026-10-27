"""Games delivered and not delivered at the end of a transfer (#614)."""

import unittest

from openemux.core.share import report
from openemux.core.share.manifest import BuiltManifest
from openemux.core.share.placement import (
    ACTION_SEND,
    ACTION_SKIP,
    ROM_ABSENT,
    ROM_EXISTING,
    ROM_NEW,
    ROM_REPLACED,
    Decision,
    GamePlan,
    ReceivePlan,
)
from openemux.core.share.protocol import KIND_BATTERY_SAVE, KIND_COVER, KIND_ROM, SkipReason


def item(item_id, kind=KIND_ROM, role=None):
    entry = {"id": item_id, "kind": kind, "name": f"{item_id}.bin", "size": 1, "mtime": 0}
    if role is not None:
        entry["part"] = {"role": role}
    return entry


def game(title, *items, console="SFC"):
    return {"title": title, "console": console, "items": list(items)}


def built(*games, excluded=()):
    return BuiltManifest({"games": list(games)}, {}, list(excluded))


def skip(item_id, reason):
    return {"item_id": item_id, "reason": reason}


class SendReportTests(unittest.TestCase):
    def test_every_game_sent_is_complete(self):
        got = report.send_report(
            built(game("A", item("a")), game("B", item("b"), item("bs", KIND_BATTERY_SAVE))),
            {"status": "done", "sent": ["a", "b", "bs"], "skipped": []},
        )
        self.assertEqual((got.delivered, got.total, got.missing), (2, 2, []))
        self.assertTrue(got.complete)

    def test_a_game_the_receiver_skips_is_not_counted_as_sent(self):
        # The bug: three selected, the receiver left one out, "3 Games Sent".
        got = report.send_report(
            built(game("A", item("a")), game("B", item("b")), game("C", item("c"), console="FC")),
            {"status": "done", "sent": ["a", "b"], "skipped": [skip("c", SkipReason.USER_UNCHECKED)]},
        )
        self.assertEqual((got.delivered, got.total), (2, 3))
        self.assertFalse(got.complete)
        self.assertEqual(got.missing, [{"title": "C", "console": "FC", "reason": SkipReason.USER_UNCHECKED,
                                       "excluded": False}])

    def test_a_rom_already_there_with_nothing_else_is_not_sent(self):
        got = report.send_report(
            built(game("A", item("a"), item("as", KIND_BATTERY_SAVE))),
            {"sent": [], "skipped": [skip("a", SkipReason.EXISTS_SKIP), skip("as", SkipReason.EXISTS_SKIP)]},
        )
        self.assertEqual(got.delivered, 0)
        self.assertEqual(got.missing[0]["reason"], SkipReason.EXISTS_SKIP)

    def test_a_rom_already_there_with_a_newer_save_is_delivered(self):
        got = report.send_report(
            built(game("A", item("a"), item("as", KIND_BATTERY_SAVE))),
            {"sent": ["as"], "skipped": [skip("a", SkipReason.EXISTS_SKIP)]},
        )
        self.assertEqual((got.delivered, got.missing), (1, []))

    def test_a_unit_with_one_part_left_out_is_not_delivered(self):
        cue = game("Disc", item("bin1", role="track"), item("cue", role="cue"), item("bin2", role="track"))
        got = report.send_report(
            built(cue),
            {"sent": ["cue", "bin1"], "skipped": [skip("bin2", SkipReason.UNIT_INCOMPLETE)]},
        )
        self.assertEqual(got.delivered, 0)
        self.assertEqual(got.missing[0]["reason"], SkipReason.UNIT_INCOMPLETE)

    def test_the_main_rom_reason_comes_first(self):
        cue = game("Disc", item("bin1", role="track"), item("cue", role="cue"))
        got = report.send_report(
            built(cue),
            {"sent": [], "skipped": [skip("bin1", SkipReason.INVALID_ITEM),
                                     skip("cue", SkipReason.UNSUPPORTED_CONSOLE)]},
        )
        self.assertEqual(got.missing[0]["reason"], SkipReason.UNSUPPORTED_CONSOLE)

    def test_a_rom_missing_from_the_answer_has_no_reason(self):
        got = report.send_report(
            built(game("A", item("a"))),
            {"sent": [], "skipped": [skip("a", None), "junk"]},
        )
        self.assertEqual(got.missing, [{"title": "A", "console": "SFC", "reason": None, "excluded": False}])

    def test_a_game_with_nothing_sent_and_no_rom_has_no_reason(self):
        got = report.send_report(built(game("Art", item("c", KIND_COVER))), {"sent": None, "skipped": None})
        self.assertEqual(got.missing[0]["reason"], None)

    def test_games_the_real_build_excluded_are_listed_and_counted(self):
        excluded = [
            {"rom": {"name": "Gone", "console": "GBA", "path": "/r/GBA/Gone.gba"}, "reason": SkipReason.UNIT_INCOMPLETE},
            {"rom": {"path": "/r/FC/Nameless.nes"}, "reason": SkipReason.INVALID_ITEM},
        ]
        got = report.send_report(built(game("A", item("a")), excluded=excluded), {"sent": ["a"]})
        self.assertEqual((got.delivered, got.total), (1, 3))
        self.assertEqual(got.missing, [
            {"title": "Gone", "console": "GBA", "reason": SkipReason.UNIT_INCOMPLETE, "excluded": True},
            {"title": "Nameless", "console": "", "reason": SkipReason.INVALID_ITEM, "excluded": True},
        ])

    def test_an_empty_manifest(self):
        got = report.send_report(built(), {})
        self.assertEqual((got.delivered, got.total, got.complete), (0, 0, True))


def decision(item_id, action, kind=KIND_ROM, reason=None):
    return Decision(item_id, kind, action, reason)


def plan_game(game_id, status, *decisions, title=None, console="SFC", absent=SkipReason.USER_UNCHECKED):
    return GamePlan(game_id, console, title or game_id, {}, rom_status=status,
                    decisions=list(decisions), absent_reason=absent)


class ReceiveReportTests(unittest.TestCase):
    def test_placed_replaced_and_existing_with_a_send_are_received(self):
        plan = ReceivePlan([
            plan_game("new", ROM_NEW, decision("a", ACTION_SEND)),
            plan_game("replaced", ROM_REPLACED, decision("b", ACTION_SEND)),
            plan_game("existing", ROM_EXISTING, decision("c", ACTION_SKIP, reason=SkipReason.EXISTS_SKIP),
                      decision("cs", ACTION_SEND, KIND_BATTERY_SAVE)),
        ])
        got = report.receive_report(plan)
        self.assertEqual((got.delivered, got.total, got.missing), (3, 3, []))

    def test_a_game_already_there_is_listed_as_such(self):
        plan = ReceivePlan([
            plan_game("dup", ROM_EXISTING, decision("a", ACTION_SKIP, reason=SkipReason.EXISTS_SKIP), title="Dup"),
        ])
        got = report.receive_report(plan)
        self.assertEqual(got.missing, [{"title": "Dup", "console": "SFC", "reason": SkipReason.EXISTS_SKIP,
                                       "excluded": False}])

    def test_an_absent_game_gives_its_rom_reason(self):
        plan = ReceivePlan([
            plan_game("odd", ROM_ABSENT, decision("c", ACTION_SKIP, KIND_COVER, SkipReason.UNSUPPORTED_CONSOLE),
                      decision("a", ACTION_SKIP, reason=SkipReason.INVALID_ITEM), console="XX"),
        ])
        self.assertEqual(report.receive_report(plan).missing[0]["reason"], SkipReason.INVALID_ITEM)

    def test_an_absent_game_without_a_rom_decision_gives_any_reason_then_its_own(self):
        plan = ReceivePlan([
            plan_game("rejected", ROM_ABSENT, decision("x", ACTION_SKIP, "", SkipReason.INVALID_ITEM)),
            plan_game("empty", ROM_ABSENT, absent=SkipReason.UNIT_INCOMPLETE),
        ])
        reasons = [entry["reason"] for entry in report.receive_report(plan).missing]
        self.assertEqual(reasons, [SkipReason.INVALID_ITEM, SkipReason.UNIT_INCOMPLETE])

    def test_games_the_user_unchecked_are_left_out(self):
        plan = ReceivePlan([
            plan_game("kept", ROM_NEW, decision("a", ACTION_SEND)),
            plan_game("dropped", ROM_ABSENT, decision("b", ACTION_SKIP, reason=SkipReason.USER_UNCHECKED)),
        ])
        got = report.receive_report(plan, unchecked={"dropped"})
        self.assertEqual((got.delivered, got.total, got.missing), (1, 1, []))


if __name__ == "__main__":
    unittest.main()

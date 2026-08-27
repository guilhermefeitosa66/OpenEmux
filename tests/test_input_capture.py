"""The state machine behind "press a button for this action".

It lived inside `OpenEmuxPreferences`, tangled with the button labels and the
prompt it drives, so only one rule of it could be tested -- which action has to
let go of a token (issue #281). The rest of the machine (map-all's walk,
Escape, a press arriving after a cancel) had no test at all, and the dialog
sits around 10% coverage (issue #238).

The collision cases here are the ones `tests/test_preferences.py` carried
before the machine moved out.
"""

import unittest

from openemux.core.input_capture import InputCaptureSession


GBA = {
    "a": "0",
    "b": "1",
    "select": "6",
    "start": "7",
    "enable_hotkey": "6",
    "save_state": "2",
    "load_state": "3",
}


def _session(bindings=None, sequence=("a", "b", "start")):
    session = InputCaptureSession()
    session.load(dict(bindings if bindings is not None else GBA), list(sequence))
    return session


class ActionsHoldingTests(unittest.TestCase):
    def _holding(self, action, value, bindings=None):
        return _session(bindings).actions_holding(action, value)

    def test_a_hotkey_on_the_token_has_to_let_go(self):
        # The reported case: GBA "B" onto the Xbox X button, which the save
        # state hotkey holds.
        self.assertEqual(self._holding("b", "2"), ["save_state"])

    def test_a_gameplay_button_on_the_token_has_to_let_go(self):
        self.assertEqual(self._holding("a", "1"), ["b"])

    def test_enable_hotkey_keeps_the_button_it_shares(self):
        # It ships on Select's token on purpose: a hotkey that only fires
        # while a modifier is held is a shared button, not a conflict (#124).
        self.assertEqual(self._holding("b", "6"), ["select"])
        self.assertEqual(self._holding("enable_hotkey", "7"), [])

    def test_binding_a_button_to_what_it_already_has_releases_nothing(self):
        self.assertEqual(self._holding("b", "1"), [])

    def test_an_empty_capture_releases_nothing(self):
        self.assertEqual(self._holding("b", ""), [])

    def test_every_holder_is_released(self):
        bindings = dict(GBA, load_state="2", save_state="2")
        self.assertEqual(
            sorted(self._holding("b", "2", bindings)), ["load_state", "save_state"]
        )


class StoringABindingTests(unittest.TestCase):
    def test_the_token_is_normalized_before_it_is_stored(self):
        session = _session()
        session.set_binding("a", "  F1  ")
        self.assertEqual(session.binding_for("a"), "f1")

    def test_the_action_that_lost_the_token_is_left_blank(self):
        session = _session()
        released = session.set_binding("b", "2")
        self.assertEqual(released, ["save_state"])
        self.assertEqual(session.binding_for("save_state"), "")
        self.assertEqual(session.binding_for("b"), "2")

    def test_clearing_a_binding_leaves_it_empty_rather_than_absent(self):
        # The dialog writes the buffer back on save; an action that is simply
        # missing falls back to what was on disk, so a cleared binding has to
        # be an empty string, not a hole.
        session = _session()
        session.set_binding("b", "")
        self.assertIn("b", session.bindings)
        self.assertEqual(session.bindings["b"], "")


class OneCaptureTests(unittest.TestCase):
    def test_nothing_is_armed_to_begin_with(self):
        self.assertFalse(_session().capturing)

    def test_arming_one_action_is_not_a_sequence(self):
        session = _session()
        session.start("a")
        self.assertTrue(session.capturing)
        self.assertEqual(session.active_action, "a")
        self.assertFalse(session.sequence_mode)

    def test_a_press_stores_it_and_asks_for_nothing_more(self):
        session = _session()
        session.start("a")
        outcome = session.commit("5")
        self.assertEqual(outcome.action, "a")
        self.assertIsNone(outcome.next_action)
        self.assertFalse(outcome.finished)
        self.assertEqual(session.binding_for("a"), "5")

    def test_a_press_reports_what_it_took_away(self):
        session = _session()
        session.start("a")
        self.assertEqual(session.commit("2").released, ["save_state"])

    def test_a_press_that_arrives_after_a_cancel_is_dropped(self):
        # The gamepad reader runs on its own thread: a button pressed just as
        # the user hit Escape lands here with nothing armed.
        session = _session()
        session.start("a")
        session.cancel()
        self.assertIsNone(session.commit("5"))
        self.assertEqual(session.binding_for("a"), "0")

    def test_cancelling_reports_what_was_armed(self):
        session = _session()
        session.start("a")
        cancelled = session.cancel()
        self.assertEqual(cancelled.action, "a")
        self.assertFalse(cancelled.was_sequence)
        self.assertFalse(session.capturing)


class MapAllTests(unittest.TestCase):
    def test_it_arms_the_first_action_of_the_walk(self):
        session = _session(sequence=("a", "b", "start"))
        self.assertEqual(session.begin_sequence(), "a")
        self.assertTrue(session.sequence_mode)

    def test_a_walk_over_nothing_arms_nothing(self):
        session = _session(sequence=())
        self.assertIsNone(session.begin_sequence())
        self.assertFalse(session.capturing)

    def test_each_press_arms_the_next_action(self):
        session = _session(sequence=("a", "b", "start"))
        session.begin_sequence()
        self.assertEqual(session.commit("0").next_action, "b")
        self.assertEqual(session.commit("1").next_action, "start")

    def test_the_last_press_finishes_the_walk(self):
        session = _session(sequence=("a", "b"))
        session.begin_sequence()
        session.commit("0")
        outcome = session.commit("1")
        self.assertIsNone(outcome.next_action)
        self.assertTrue(outcome.finished)

    def test_the_whole_walk_is_stored(self):
        session = _session(sequence=("a", "b", "start"))
        session.begin_sequence()
        for token in ("4", "5", "9"):
            session.commit(token)
        self.assertEqual(session.binding_for("a"), "4")
        self.assertEqual(session.binding_for("b"), "5")
        self.assertEqual(session.binding_for("start"), "9")

    def test_cancelling_mid_walk_says_a_walk_died(self):
        session = _session(sequence=("a", "b", "start"))
        session.begin_sequence()
        session.commit("0")
        cancelled = session.cancel()
        self.assertEqual(cancelled.action, "b")
        self.assertTrue(cancelled.was_sequence)

    def test_a_second_walk_starts_from_the_top(self):
        session = _session(sequence=("a", "b"))
        session.begin_sequence()
        session.commit("0")
        session.cancel()
        self.assertEqual(session.begin_sequence(), "a")
        self.assertEqual(session.commit("7").next_action, "b")


class LoadingAnotherDeviceTests(unittest.TestCase):
    def test_it_replaces_the_buffer_and_disarms(self):
        session = _session()
        session.begin_sequence()
        session.load({"a": "z"}, ["a"])
        self.assertEqual(session.bindings, {"a": "z"})
        self.assertFalse(session.capturing)
        self.assertFalse(session.sequence_mode)

    def test_the_buffer_is_a_copy_of_what_it_was_handed(self):
        original = {"a": "z"}
        session = InputCaptureSession()
        session.load(original, ["a"])
        session.set_binding("a", "x")
        self.assertEqual(original, {"a": "z"})


if __name__ == "__main__":
    unittest.main()

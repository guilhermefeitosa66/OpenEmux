"""Big Picture's pause menu: its state and the RetroArch commands (issue 957)."""

import unittest

from openemux.core import pause_session as ps


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.answer = True
        self.clock = Clock()

        def send(command):
            self.sent.append(command)
            return self.answer

        self.session = ps.PauseSession(send, clock=self.clock)


class ThePauseSession(SessionCase):
    def test_minutes(self):
        self.assertEqual(self.session.played_minutes(), 0)
        self.clock.now += 61 * 12
        self.assertEqual(self.session.played_minutes(), 12)

    def test_pause_and_resume_send_one_toggle_each(self):
        self.assertTrue(self.session.pause())
        self.assertTrue(self.session.pause())
        self.assertTrue(self.session.resume())
        self.assertTrue(self.session.resume())
        self.assertEqual(self.sent, [ps.PAUSE, ps.PAUSE])

    def test_a_dead_channel_changes_nothing(self):
        self.answer = False
        s = self.session
        self.assertFalse(s.pause())
        self.assertFalse(s.paused)
        s.paused = True
        self.assertFalse(s.resume())
        self.assertTrue(s.paused)
        self.assertFalse(s.toggle_fast_forward())
        self.assertFalse(s.toggle_slow_motion())
        self.assertFalse(s.toggle_mute())
        self.assertEqual((s.fast_forward, s.slow_motion, s.muted), (False, False, False))

    def test_slots(self):
        s = self.session
        self.assertEqual(s.step_slot(1), 1)
        self.assertEqual(s.set_slot(42), ps.MAX_SLOT)
        self.assertEqual(s.step_slot(-20), ps.MIN_SLOT)
        self.assertEqual(ps.clamp_slot("x"), ps.MIN_SLOT)
        s.set_slot(3)
        s.save()
        s.load()
        s.load_slot(5)
        self.assertEqual(self.sent, ["SAVE_STATE_SLOT 3", "LOAD_STATE_SLOT 3", "LOAD_STATE_SLOT 5"])

    def test_the_other_actions(self):
        s = self.session
        s.restart()
        s.screenshot()
        s.quit()
        self.assertTrue(s.toggle_fast_forward())
        self.assertTrue(s.toggle_slow_motion())
        self.assertTrue(s.toggle_mute())
        self.assertTrue((s.fast_forward, s.slow_motion, s.muted) == (True, True, True))
        self.assertEqual(self.sent, [ps.RESET, ps.SCREENSHOT, ps.QUIT, ps.FAST_FORWARD, ps.SLOW_MOTION, ps.MUTE])

    def test_retroarch_menu_unpauses_first(self):
        self.session.pause()
        self.session.retroarch_menu()
        self.assertEqual(self.sent, [ps.PAUSE, ps.PAUSE, ps.MENU])

    def test_hardcore_has_no_speed_changes(self):
        s = ps.PauseSession(self.sent.append, hardcore=True)
        self.assertFalse(s.speed_allowed)
        self.assertFalse(s.toggle_fast_forward())
        self.assertFalse(s.toggle_slow_motion())
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()

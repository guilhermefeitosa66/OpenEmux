"""The two ways first boot could end with the user stuck (issue #215).

Only the pure parts: whether a crashed worker still produces a result, and
whether a close should stop and ask. Both dialogs need a display; the rules do
not.
"""

import unittest

from openemux.main import OpenEmuxApplication
from openemux.ui.first_boot_window import FirstBootWindow


class _Bootstrapper:
    def __init__(self, outcome):
        self.outcome = outcome
        self.events = []

    def run(self, on_event=None):
        if on_event:
            on_event({"type": "bootstrap_started"})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class GuardedBootstrapWorkerTests(unittest.TestCase):
    def _run(self, outcome):
        events = []
        bootstrapper = _Bootstrapper(outcome)
        result = OpenEmuxApplication._run_bootstrap_guarded(bootstrapper, events.append)
        return result, events

    def test_a_normal_run_passes_its_result_through(self):
        result, events = self._run({"success": True})
        self.assertEqual(result, {"success": True})
        self.assertEqual(events, [{"type": "bootstrap_started"}])

    def test_a_reported_failure_passes_through_untouched(self):
        expected = {"success": False, "failed_step": "playlists_seed", "error": "boom"}
        result, _ = self._run(expected)
        self.assertEqual(result, expected)

    def test_a_crash_outside_the_step_loop_still_ends_the_flow(self):
        # The reported freeze: start_bootstrap_run() writes the config, so a
        # full disk raises before the guarded loop is even entered. The worker
        # died, _finish_bootstrap_flow was never queued, and the window sat
        # there forever.
        result, _ = self._run(OSError("No space left on device"))
        self.assertFalse(result["success"])
        self.assertIsNone(result["failed_step"])
        self.assertIn("No space left on device", result["error"])

    def test_even_a_bare_exception_comes_back_as_a_failure(self):
        result, _ = self._run(RuntimeError())
        self.assertFalse(result["success"])
        self.assertIn("error", result)


class CloseConfirmationTests(unittest.TestCase):
    def _needs(self, finished, confirmed):
        return FirstBootWindow._needs_close_confirmation(finished, confirmed)

    def test_closing_mid_setup_asks_first(self):
        self.assertTrue(self._needs(False, False))

    def test_closing_after_setup_finished_just_closes(self):
        # What _finish_bootstrap_flow does: the run is over, so the app's own
        # close must not put a dialog in front of the user.
        self.assertFalse(self._needs(True, False))

    def test_the_confirmed_quit_is_not_asked_about_twice(self):
        self.assertFalse(self._needs(False, True))


class _Label:
    def __init__(self):
        self.text = ""

    def set_text(self, value):
        self.text = value


class _Progress(_Label):
    def __init__(self):
        super().__init__()
        self.fraction = 0.0

    def set_fraction(self, value):
        self.fraction = value


class _WindowStub:
    """Just the widgets handle_event writes to, so the real method can run."""

    def __init__(self):
        self.locale = "en"
        self._setup_finished = False
        self._close_confirmed = False
        self.subtitle_label = _Label()
        self.status_label = _Label()
        self.progress = _Progress()


class TerminalEventTests(unittest.TestCase):
    def _handle(self, event):
        stub = _WindowStub()
        FirstBootWindow.handle_event(stub, event)
        return stub

    def test_a_completed_run_releases_the_close(self):
        stub = self._handle({"type": "bootstrap_completed"})
        self.assertTrue(stub._setup_finished)
        self.assertEqual(stub.progress.fraction, 1.0)

    def test_a_failed_run_releases_the_close_and_shows_the_error(self):
        # A failed bootstrap is over too: the user must be able to close the
        # window and get to the app, which is what makes the error readable.
        stub = self._handle({"type": "bootstrap_failed", "error": "No space left"})
        self.assertTrue(stub._setup_finished)
        self.assertEqual(stub.status_label.text, "No space left")

    def test_a_step_in_flight_does_not_release_the_close(self):
        stub = self._handle(
            {"type": "step_started", "label_key": "bootstrap.step.config", "index": 1, "total_steps": 6}
        )
        self.assertFalse(stub._setup_finished)
        self.assertTrue(
            FirstBootWindow._needs_close_confirmation(
                stub._setup_finished, stub._close_confirmed
            )
        )


class _Dialog:
    """Enough of Adw.AlertDialog for _on_close_response to answer."""


class ConfirmedQuitTests(unittest.TestCase):
    class _Stub:
        def __init__(self):
            self._close_confirmed = False
            self._setup_finished = False
            self.closed = False

        def close(self):
            self.closed = True

    def _respond(self, response):
        stub = self._Stub()
        FirstBootWindow._on_close_response(stub, _Dialog(), response)
        return stub

    def test_quit_confirms_and_closes(self):
        stub = self._respond("quit")
        self.assertTrue(stub.closed)
        self.assertTrue(stub._close_confirmed)
        # The close() it just asked for must not be intercepted again.
        self.assertFalse(
            FirstBootWindow._needs_close_confirmation(
                stub._setup_finished, stub._close_confirmed
            )
        )

    def test_keeping_setup_neither_closes_nor_arms_the_next_close(self):
        stub = self._respond("keep")
        self.assertFalse(stub.closed)
        self.assertFalse(stub._close_confirmed)
        self.assertTrue(
            FirstBootWindow._needs_close_confirmation(
                stub._setup_finished, stub._close_confirmed
            )
        )


if __name__ == "__main__":
    unittest.main()

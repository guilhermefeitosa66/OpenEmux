"""The application object and the first-boot window it opens.

`app.py` sat at 32% and `ui/first_boot_window.py` at 40%: between them they
own what happens before the library exists -- the icon and theme setup that has
to run before the first window is drawn, the once-per-process housekeeping
sweep, the bootstrap worker and the progress screen it drives, and the
last-line-of-defence that stops a game outliving the app.

Every test here builds a real `OpenEmuxApplication` against a throwaway home,
so the bootstrap never downloads a core and nothing is written to the
developer's own `~/.openemux`.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.isolated_home import IsolatedHome

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    Adw.init()

    from openemux import app as app_module
    from openemux.app import OpenEmuxApplication
    from openemux.ui.first_boot_window import FirstBootWindow


class _ApplicationCase(unittest.TestCase):
    """A real application whose every path is redirected into a temp home."""

    def setUp(self):
        self.home = IsolatedHome()
        self.config = self.home.start()
        self.addCleanup(self.home.stop)
        config_patch = mock.patch.object(
            app_module, "ConfigManager", lambda *a, **kw: self.config
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # The real constructor, on purpose -- it is seven statements of
        # application setup worth executing. It is never registered here, so
        # the shared application id reaches no session bus.
        self.app = OpenEmuxApplication()
        self.addCleanup(self.app.quit)


@needs_display
class ActivatingTheApplicationTests(_ApplicationCase):
    def setUp(self):
        super().setUp()
        for name in ("_present_main_window", "_start_bootstrap_flow"):
            patcher = mock.patch.object(OpenEmuxApplication, name)
            setattr(self, name.lstrip("_"), patcher.start())
            self.addCleanup(patcher.stop)
        housekeeping = mock.patch.object(app_module, "run_startup_housekeeping")
        self.housekeeping = housekeeping.start()
        self.addCleanup(housekeeping.stop)

    def test_a_ready_library_goes_straight_to_the_main_window(self):
        self.app.do_activate()
        self.present_main_window.assert_called_once()
        self.start_bootstrap_flow.assert_not_called()

    def test_the_theme_is_applied_before_the_first_window_is_drawn(self):
        # Setting the scheme afterwards repaints a window the user is already
        # looking at (issue #198).
        with mock.patch("openemux.ui.theming.apply_theme") as apply_theme:
            self.app.do_activate()
        apply_theme.assert_called_once_with(
            self.config.get_ui_settings()["theme"]
        )

    def test_the_bundled_icons_are_registered_before_any_window_exists(self):
        with mock.patch("openemux.ui.icons.register_bundled_icons") as register:
            self.app.do_activate()
        register.assert_called_once()

    def test_the_housekeeping_sweep_runs_once_per_process(self):
        # A re-activation must not sweep under a download this same process
        # still has open (issue #221).
        self.app.do_activate()
        self.app.do_activate()
        self.housekeeping.assert_called_once()

    def test_a_library_that_never_finished_setup_opens_the_bootstrap(self):
        with mock.patch.object(
            app_module.FirstBootBootstrapper, "needs_bootstrap", return_value=True
        ):
            self.app.do_activate()
        self.start_bootstrap_flow.assert_called_once_with(
            initial_boot=True, parent=None
        )
        self.present_main_window.assert_not_called()

    def test_a_second_activation_mid_bootstrap_re_presents_that_window(self):
        window = mock.Mock()
        self.app._bootstrap_running = True
        self.app._bootstrap_window = window
        self.app.do_activate()
        window.present.assert_called_once()
        self.present_main_window.assert_not_called()

    def test_a_second_activation_with_no_bootstrap_window_is_harmless(self):
        self.app._bootstrap_running = True
        self.app._bootstrap_window = None
        self.app.do_activate()
        self.present_main_window.assert_not_called()


@needs_display
class ThePathOutTests(_ApplicationCase):
    def test_quitting_takes_a_running_game_with_it(self):
        # Closing the library window already stops it; this covers Ctrl+Q, a
        # quit action and the session going away.
        runtime = mock.Mock()
        runtime.is_running.return_value = True
        self.app.main_window = mock.Mock(runtime_manager=runtime)
        with mock.patch.object(Adw.Application, "do_shutdown"):
            self.app.do_shutdown()
        runtime.stop_active.assert_called_once_with(block=True)

    def test_quitting_with_no_game_running_stops_nothing(self):
        runtime = mock.Mock()
        runtime.is_running.return_value = False
        self.app.main_window = mock.Mock(runtime_manager=runtime)
        with mock.patch.object(Adw.Application, "do_shutdown"):
            self.app.do_shutdown()
        runtime.stop_active.assert_not_called()

    def test_quitting_before_a_window_exists_is_harmless(self):
        with mock.patch.object(Adw.Application, "do_shutdown"):
            self.app.do_shutdown()


@needs_display
class PresentingTheMainWindowTests(_ApplicationCase):
    def test_the_first_present_builds_the_window_and_its_two_notices(self):
        window = mock.Mock()
        with mock.patch.object(app_module, "OpenEmuxWindow", return_value=window):
            self.app._present_main_window()
        self.assertIs(self.app.main_window, window)
        window.present.assert_called_once()
        window.maybe_show_welcome.assert_called_once()
        window.maybe_report_recovered_state.assert_called_once()

    def test_a_second_present_re_presents_the_window_that_is_there(self):
        window = mock.Mock()
        self.app.main_window = window
        with mock.patch.object(app_module, "OpenEmuxWindow") as build:
            self.app._present_main_window()
        build.assert_not_called()
        window.present.assert_called_once()


@needs_display
class TheBootstrapFlowTests(_ApplicationCase):
    def setUp(self):
        super().setUp()
        self.windows = []
        window_patch = mock.patch.object(
            app_module, "FirstBootWindow", self._build_window
        )
        window_patch.start()
        self.addCleanup(window_patch.stop)
        thread_patch = mock.patch.object(app_module, "Thread")
        self.thread = thread_patch.start()
        self.addCleanup(thread_patch.stop)

    def _build_window(self, **kwargs):
        window = mock.Mock()
        window.kwargs = kwargs
        self.windows.append(window)
        return window

    def test_starting_the_flow_shows_the_progress_screen_off_the_main_thread(self):
        self.app._start_bootstrap_flow(initial_boot=True)
        self.assertTrue(self.app._bootstrap_running)
        self.windows[0].present.assert_called_once()
        self.thread.assert_called_once()

    def test_the_worker_runs_the_bootstrap_and_reports_back_on_the_main_loop(self):
        with mock.patch.object(
            app_module.FirstBootBootstrapper, "run", return_value={"success": True}
        ), mock.patch.object(app_module.GLib, "idle_add") as idle_add:
            self.app._start_bootstrap_flow(initial_boot=True)
            self.thread.call_args.kwargs["target"]()
        self.assertEqual(
            idle_add.call_args[0][:2],
            (self.app._finish_bootstrap_flow, {"success": True}),
        )

    def test_every_worker_event_is_handed_to_the_main_loop_too(self):
        events = []

        def _run(_bootstrapper, on_event=None):
            on_event({"type": "step_started"})
            return {"success": True}

        with mock.patch.object(
            app_module.FirstBootBootstrapper, "run", _run
        ), mock.patch.object(
            app_module.GLib, "idle_add", lambda fn, *a: events.append((fn, a))
        ):
            self.app._start_bootstrap_flow(initial_boot=True)
            self.thread.call_args.kwargs["target"]()
        self.assertEqual(events[0][0], self.app._deliver_bootstrap_event)

    def test_a_retry_from_the_ui_starts_the_flow_and_records_the_request(self):
        self.assertTrue(self.app.request_bootstrap_retry_from_ui(None))
        self.assertTrue(self.config.get_bootstrap_state()["retry_requested"])

    def test_a_retry_while_one_runs_is_refused(self):
        self.app._bootstrap_running = True
        self.assertFalse(self.app.request_bootstrap_retry_from_ui(None))

    def test_an_event_reaches_the_window_it_belongs_to(self):
        window = mock.Mock()
        self.app._bootstrap_window = window
        self.assertFalse(
            self.app._deliver_bootstrap_event(window, {"type": "step_started"})
        )
        window.handle_event.assert_called_once()

    def test_an_event_for_a_window_that_is_gone_is_dropped(self):
        # The worker outlives a closed window by design; reaching through the
        # attribute afterwards took the thread down with it.
        self.app._bootstrap_window = None
        stale = mock.Mock()
        self.app._deliver_bootstrap_event(stale, {"type": "step_started"})
        stale.handle_event.assert_not_called()

    def test_finishing_closes_the_progress_screen_without_asking(self):
        window = mock.Mock()
        self.app._bootstrap_window = window
        self.app._bootstrap_running = True
        with mock.patch.object(OpenEmuxApplication, "_present_main_window"):
            self.assertFalse(
                self.app._finish_bootstrap_flow({"success": True}, initial_boot=True)
            )
        window.finish.assert_called_once()
        window.close.assert_called_once()
        self.assertIsNone(self.app._bootstrap_window)
        self.assertFalse(self.app._bootstrap_running)

    def test_an_initial_boot_opens_the_library_once_setup_is_over(self):
        with mock.patch.object(OpenEmuxApplication, "_present_main_window") as present:
            self.app._finish_bootstrap_flow({"success": True}, initial_boot=True)
        present.assert_called_once()

    def test_a_retry_reports_back_to_the_library_that_asked_for_it(self):
        window = mock.Mock()
        self.app.main_window = window
        result = {"success": False, "failed_step": "cores_download"}
        self.app._finish_bootstrap_flow(result, initial_boot=False)
        window.on_bootstrap_finished.assert_called_once_with(result)


class TheGuardedBootstrapWorkerTests(unittest.TestCase):
    """Issue #215: a crash outside the step loop left the window frozen."""

    def test_a_normal_run_passes_its_result_through(self):
        bootstrapper = mock.Mock()
        bootstrapper.run.return_value = {"success": True}
        if not HAVE_DISPLAY:
            self.skipTest("the application module needs the GTK stack")
        self.assertEqual(
            OpenEmuxApplication._run_bootstrap_guarded(bootstrapper, None),
            {"success": True},
        )

    def test_a_crash_around_the_loop_still_comes_back_shaped_like_a_failure(self):
        if not HAVE_DISPLAY:
            self.skipTest("the application module needs the GTK stack")
        bootstrapper = mock.Mock()
        bootstrapper.run.side_effect = OSError("No space left on device")
        result = OpenEmuxApplication._run_bootstrap_guarded(bootstrapper, None)
        self.assertFalse(result["success"])
        self.assertIsNone(result["failed_step"])
        self.assertIn("No space left on device", result["error"])


@needs_display
class TheFirstBootWindowTests(_ApplicationCase):
    def setUp(self):
        super().setUp()
        self.window = FirstBootWindow(application=self.app, locale="en")
        self.addCleanup(self.window.destroy)

    def test_it_opens_at_zero_percent_with_the_initial_subtitle(self):
        self.assertEqual(self.window.progress.get_text(), "0%")
        self.assertEqual(self.window.progress.get_fraction(), 0.0)
        self.assertTrue(self.window.subtitle_label.get_text())

    def test_a_retry_is_modal_over_the_window_that_asked_for_it(self):
        parent = Adw.ApplicationWindow(application=self.app)
        self.addCleanup(parent.destroy)
        window = FirstBootWindow(application=self.app, parent=parent)
        self.addCleanup(window.destroy)
        self.assertTrue(window.get_modal())
        self.assertIs(window.get_transient_for(), parent)

    def test_a_step_moves_the_bar_and_names_what_is_running(self):
        self.window.handle_event(
            {
                "type": "step_started",
                "label_key": "bootstrap.title",
                "index": 1,
                "total_steps": 4,
            }
        )
        self.assertEqual(self.window.progress.get_text(), "25%")

    def test_a_step_with_no_label_leaves_the_subtitle_alone(self):
        before = self.window.subtitle_label.get_text()
        self.window.handle_event(
            {"type": "step_completed", "index": 2, "total_steps": 4}
        )
        self.assertEqual(self.window.subtitle_label.get_text(), before)

    def test_a_step_reporting_its_own_progress_says_how_far_it_is(self):
        self.window.handle_event(
            {"type": "step_progress", "current": 3, "total": 9, "message": "seeding"}
        )
        self.assertEqual(self.window.status_label.get_text(), "seeding (3/9)")

    def test_a_core_download_names_the_core_and_the_tally(self):
        self.window.handle_event(
            {
                "type": "download_progress",
                "current": 2,
                "total": 30,
                "core_name": "snes9x",
            }
        )
        self.assertIn("snes9x", self.window.status_label.get_text())

    def test_a_completed_bootstrap_fills_the_bar_and_clears_the_status(self):
        self.window.handle_event({"type": "bootstrap_completed"})
        self.assertEqual(self.window.progress.get_fraction(), 1.0)
        self.assertEqual(self.window.progress.get_text(), "100%")
        self.assertEqual(self.window.status_label.get_text(), "")
        self.assertTrue(self.window._setup_finished)

    def test_a_failed_bootstrap_shows_the_error_it_ended_with(self):
        self.window.handle_event(
            {"type": "bootstrap_failed", "error": "no network"}
        )
        self.assertEqual(self.window.status_label.get_text(), "no network")
        self.assertTrue(self.window._setup_finished)

    def test_an_event_it_does_not_know_changes_nothing(self):
        before = self.window.progress.get_fraction()
        self.window.handle_event({"type": "something else"})
        self.assertEqual(self.window.progress.get_fraction(), before)


@needs_display
class ClosingTheFirstBootWindowTests(_ApplicationCase):
    """Issue #215: closing mid-download ends the app and kills the worker."""

    def setUp(self):
        super().setUp()
        self.window = FirstBootWindow(application=self.app, locale="en")
        self.addCleanup(self.window.destroy)

    def test_closing_mid_setup_asks_first_and_refuses_this_close(self):
        with mock.patch.object(Adw.AlertDialog, "present"):
            self.assertTrue(self.window._on_close_request())

    def test_closing_after_the_run_is_over_just_closes(self):
        self.window.finish()
        self.assertFalse(self.window._on_close_request())

    def test_a_confirmed_quit_is_not_asked_about_twice(self):
        self.window._close_confirmed = True
        self.assertFalse(self.window._on_close_request())

    def test_keeping_the_setup_going_leaves_the_window_up(self):
        self.window._on_close_response(None, "keep")
        self.assertFalse(self.window._close_confirmed)

    def test_quitting_anyway_closes_the_window_for_good(self):
        with mock.patch.object(self.window, "close") as close:
            self.window._on_close_response(None, "quit")
        self.assertTrue(self.window._close_confirmed)
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()

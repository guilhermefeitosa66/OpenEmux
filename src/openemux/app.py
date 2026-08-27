"""The GTK application object, and the import that brings GTK up with it.

Split out of ``main`` so that importing ``main`` costs nothing: ``from
gi.repository import Gtk`` runs ``Gtk.init()`` and opens the display, and the
module-level work that has to precede it was writing to the developer's real
home directory every time a test imported a helper (issue #244).

Nothing here runs at import time beyond bringing GTK up, which is what a
caller asking for the application object is asking for. Reach it through
``openemux.main.build_application()``, which runs ``prepare_process()`` first.
"""

import logging
import traceback
from threading import Thread

from openemux.core.startup_logging import append_startup_error
from openemux.main import APP_ID

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
except Exception:
    append_startup_error(
        "Failed to import GTK stack (gi/Gtk/Adw). On Debian/Ubuntu/Mint install "
        "the introspection typelibs: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 "
        "(or run 'make install-sys-deps').",
        exc_text=traceback.format_exc(),
    )
    raise

# Gtk is not referenced here, and is imported anyway: importing it is what
# runs Gtk.init(), which opens the display. Adw pulls it in too, but leaving
# that implicit would make the app's initialisation depend on an import inside
# libadwaita's overrides.
from gi.repository import Gtk  # noqa: F401
from gi.repository import Adw, GLib
from openemux.ui.window import OpenEmuxWindow
from openemux.ui.first_boot_window import FirstBootWindow
from openemux.core.config import ConfigManager
from openemux.core.first_boot import FirstBootBootstrapper
from openemux.core.housekeeping import run_startup_housekeeping


class OpenEmuxApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=gi.repository.Gio.ApplicationFlags.FLAGS_NONE)
        self.config_manager = ConfigManager()
        self._bootstrap_running = False
        self._bootstrap_window = None
        self._housekeeping_done = False
        self.main_window = None

    def do_activate(self):
        # Register the vendored symbolic icons before any window exists, so
        # every lookup can fall back to them when the host theme lacks a name.
        from openemux.ui.icons import register_bundled_icons
        register_bundled_icons()

        # Before the first window is drawn: setting the scheme afterwards
        # repaints a window the user is already looking at (issue #198).
        from openemux.ui.theming import apply_theme
        apply_theme(self.config_manager.get_ui_settings()["theme"])

        if self._bootstrap_running:
            if self._bootstrap_window:
                self._bootstrap_window.present()
            return

        # Retention for everything the app writes and never reads back: the
        # per-launch runtime files, the buildbot download cache and the
        # artwork-manager temp directories (issue #221). Cheap -- a couple of
        # directory listings -- and best-effort, so it cannot delay or block
        # the first window. Before the bootstrap check on purpose: a first boot
        # is exactly when a previous failed one may have left a cache behind.
        # Once per process: a re-activation must not sweep under a download or
        # an artwork window this same process still has open.
        if not self._housekeeping_done:
            self._housekeeping_done = True
            run_startup_housekeeping(self.config_manager)

        bootstrapper = FirstBootBootstrapper(self.config_manager)
        if bootstrapper.needs_bootstrap():
            self._start_bootstrap_flow(initial_boot=True, parent=None)
            return

        self._present_main_window()

    def do_shutdown(self):
        # Last line of defence against a game outliving the app. Closing the
        # library window already stops it; this covers every other way the
        # app can end (Ctrl+Q, a quit action, the session going away), where
        # nothing else is left running to notice the process.
        runtime = getattr(self.main_window, "runtime_manager", None)
        if runtime is not None and runtime.is_running():
            runtime.stop_active(block=True)
        Adw.Application.do_shutdown(self)

    def _present_main_window(self):
        if self.main_window:
            self.main_window.present()
            return
        self.config_manager.ensure_rom_directories()
        self.main_window = OpenEmuxWindow(application=self)
        self.main_window.present()
        self.main_window.maybe_show_welcome()
        self.main_window.maybe_report_recovered_state()

    def request_bootstrap_retry_from_ui(self, parent_window):
        if self._bootstrap_running:
            return False
        self.config_manager.request_bootstrap_retry()
        self._start_bootstrap_flow(initial_boot=False, parent=parent_window)
        return True

    def _start_bootstrap_flow(self, initial_boot, parent=None):
        self._bootstrap_running = True
        locale = self.config_manager.get_locale()
        self._bootstrap_window = FirstBootWindow(
            application=self,
            locale=locale,
            parent=parent,
        )
        self._bootstrap_window.present()
        bootstrapper = FirstBootBootstrapper(self.config_manager)
        window = self._bootstrap_window

        def _emit(evt):
            GLib.idle_add(self._deliver_bootstrap_event, window, evt)

        def _worker():
            result = self._run_bootstrap_guarded(bootstrapper, _emit)
            GLib.idle_add(self._finish_bootstrap_flow, result, initial_boot)

        Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _run_bootstrap_guarded(bootstrapper, on_event):
        """Run the bootstrap and always come back with a result.

        ``FirstBootBootstrapper.run`` guards each step handler, but not the
        config reads and writes around the loop -- and those touch the disk, so
        a full disk or an unwritable ``~/.openemux`` raises right past them. The
        worker thread then died silently: ``_finish_bootstrap_flow`` was never
        queued, ``_bootstrap_running`` stayed True, and the first-boot window
        sat there forever with no error and no way out. Relaunching just
        re-presented the same frozen window (issue #215).

        A crash here is still a failed bootstrap, and a failed bootstrap has a
        screen. It has to arrive shaped like one.
        """
        try:
            return bootstrapper.run(on_event=on_event)
        except Exception as exc:
            logging.getLogger(__name__).exception("bootstrap worker crashed")
            return {"success": False, "failed_step": None, "error": str(exc)}

    def _deliver_bootstrap_event(self, window, event):
        """Hand a worker event to the window, if that window is still ours.

        The worker outlives a closed window by design (it is a daemon thread),
        and reaching through ``self._bootstrap_window`` after the flow ended
        raised inside the worker -- taking the thread, and the flow, with it.
        """
        if window is not None and window is self._bootstrap_window:
            window.handle_event(event)
        return False

    def _finish_bootstrap_flow(self, result, initial_boot):
        self._bootstrap_running = False
        if self._bootstrap_window:
            # The window asks for confirmation before closing mid-run; this
            # close is the run being over, so it must not ask.
            self._bootstrap_window.finish()
            self._bootstrap_window.close()
            self._bootstrap_window = None

        if initial_boot:
            self._present_main_window()

        if self.main_window and hasattr(self.main_window, "on_bootstrap_finished"):
            self.main_window.on_bootstrap_finished(result)
        return False


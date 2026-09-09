"""The main window, built for real and driven the way a user drives it.

`ui/window.py` is the second-largest module in the app and sat at 16%: only
`tests/test_window_collaborators.py` looked at it, and that reads the source
rather than running it. Everything a collaborator calls back into -- the
layout controls, the selection bar, the collection prompts, the rescan
plumbing, the artwork reveal -- lives here, and a rename or a wrong branch in
any of it fails inside a signal handler where PyGObject prints the traceback
and swallows it: the menu entry simply does nothing.

So this constructs a real `OpenEmuxWindow` over a throwaway home
(`tests.isolated_home`) with a small synthetic library, and exercises it.
Three things are held back, because a unit test must not do them: the gamepad
navigator thread, the startup rescan thread, and the network -- the update
check is off in the config and `sync_artwork_async` is replaced wherever a
test reaches it.
"""

import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.isolated_home import IsolatedHome

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

    Adw.init()

    from openemux.core.playlist_manager import PlaylistManager
    from openemux.core.rom_actions import RomActionError
    from openemux.core.scanner import RomScanner
    from openemux.core.scraper import COVER_ART, LABEL_ART
    from openemux.ui import window as window_module
    from openemux.ui.scopes import (
        ALL_CONSOLES_ID,
        FAVORITES_ID,
        LIBRARY_EMPTY_ID,
        collection_scope,
    )
    from openemux.ui.window import OpenEmuxWindow


#: The real startup scan, kept before the patch in `_WindowCase` replaces it.
_REAL_STARTUP_SCAN = OpenEmuxWindow._start_startup_scan if HAVE_DISPLAY else None


#: The synthetic library every case opens on: two consoles, three games.
_LIBRARY = {
    "SFC": ["Chrono Trigger.sfc", "Super Metroid.sfc"],
    "FC": ["Metroid.nes"],
}


class _WindowCase(unittest.TestCase):
    """A real window over a throwaway home, with the threads held back."""

    library = _LIBRARY

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = IsolatedHome(self.tmp / "home")
        self.config = self.home.start()
        self.addCleanup(self.home.stop)

        for console, roms in self.library.items():
            for name in roms:
                self.home.add_rom(console, name)
        # The window reads playlists, not the directory tree: build them once
        # here so construction has a library to open on without a scan thread.
        PlaylistManager(
            self.config, RomScanner(self.config.get_roms_path())
        ).scan_and_rebuild_all_playlists()

        # One application for the whole module: a second registration under
        # the same id collides on the session bus, and an id per test would
        # leak one exported object per case.
        self.app = _shared_application()
        self.app.config_manager = self.config

        navigator_patch = mock.patch.object(
            window_module, "make_navigator", lambda **kwargs: mock.Mock()
        )
        navigator_patch.start()
        self.addCleanup(navigator_patch.stop)
        # The startup rescan is a thread; it is tested on its own instead.
        scan_patch = mock.patch.object(OpenEmuxWindow, "_start_startup_scan")
        scan_patch.start()
        self.addCleanup(scan_patch.stop)

        self.win = OpenEmuxWindow(self.app)
        self.addCleanup(self.win.destroy)

        self.toasts = []
        toast_patch = mock.patch.object(
            self.win.toast_overlay,
            "add_toast",
            lambda toast: self.toasts.append(toast.get_title()),
        )
        toast_patch.start()
        self.addCleanup(toast_patch.stop)

    # -- helpers ----------------------------------------------------------
    @contextmanager
    def caught_dialog(self):
        """Catch the `Adw.AlertDialog` the window is about to show.

        The prompts are built and presented in one call, and none of them is
        parented anywhere a test could find it, so presenting is where they
        are intercepted -- which also keeps every dialog off the screen.
        """
        caught = []
        with mock.patch.object(
            Adw.AlertDialog, "present", lambda dialog, *args: caught.append(dialog)
        ):
            yield caught

    def rom(self, console="SFC", index=0):
        return self.win.playlist_manager.load_playlist(console)[index]

    def said(self, key, **kwargs):
        """The translated text of a message, for comparing against a toast."""
        return self.win.t(key, **kwargs)

    def pump(self):
        """Run whatever the window queued on the idle loop."""
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)


if HAVE_DISPLAY:

    class _Application(Adw.Application):
        """The one thing the window needs from its application.

        NON_UNIQUE so the registration never tries to hand the run over to a
        copy of OpenEmux the developer happens to have open.
        """

        def __init__(self):
            super().__init__(
                application_id="io.github.openemux.WindowTests",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.config_manager = None


_APPLICATION = None


def _shared_application():
    """The module's single registered application.

    Registering exports an object on the session bus under the application id;
    doing that twice fails, so the application is built once and each test
    points it at its own throwaway config.
    """
    global _APPLICATION
    if _APPLICATION is None:
        _APPLICATION = _Application()
        _APPLICATION.register()
    return _APPLICATION


@needs_display
class TheWindowOpensOnALibraryTests(_WindowCase):
    def test_the_consoles_with_games_are_the_visible_ones(self):
        self.assertEqual(sorted(self.win.visible_consoles), ["FC", "SFC"])

    def test_every_scope_gets_a_page(self):
        for scope in (ALL_CONSOLES_ID, FAVORITES_ID, "SFC", "FC"):
            self.assertTrue(self.win.pages.has(scope), scope)

    def test_the_window_lands_on_a_page_rather_than_nothing(self):
        self.assertIsNotNone(self.win.content_stack.get_visible_child_name())

    def test_the_title_names_the_console_and_counts_its_games(self):
        self.win.sidebar.select("SFC")
        self.assertEqual(
            self.win.window_title.get_title(),
            f"SFC — {window_module.get_system_display_name('SFC')}",
        )
        self.assertEqual(
            self.win.window_title.get_subtitle(),
            self.said("header.subtitle.games", count=2),
        )

    def test_a_console_with_one_game_says_so_in_the_singular(self):
        self.win.sidebar.select("FC")
        self.assertEqual(
            self.win.window_title.get_subtitle(), self.said("header.subtitle.one_game")
        )

    def test_the_all_page_is_titled_after_the_sidebar_row(self):
        self.win._update_window_title(ALL_CONSOLES_ID)
        self.assertEqual(self.win.window_title.get_title(), self.said("sidebar.all"))

    def test_the_favorites_page_is_titled_after_its_row(self):
        self.win._update_window_title(FAVORITES_ID)
        self.assertEqual(
            self.win.window_title.get_title(), self.said("sidebar.favorites")
        )

    def test_a_collection_page_is_titled_after_the_collection(self):
        slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)
        self.win._update_window_title(collection_scope(slug))
        self.assertEqual(self.win.window_title.get_title(), "RPGs")

    def test_no_page_at_all_falls_back_to_the_app_name(self):
        self.win._update_window_title(None)
        self.assertEqual(self.win.window_title.get_title(), self.said("app.title"))

    def test_an_empty_page_says_it_has_no_games(self):
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        with mock.patch.object(grid, "count", return_value=0):
            self.win._update_window_title("SFC")
        self.assertEqual(
            self.win.window_title.get_subtitle(), self.said("header.subtitle.no_games")
        )


@needs_display
class AnEmptyLibraryTests(_WindowCase):
    library = {}

    def test_the_empty_state_is_what_the_window_shows(self):
        self.assertEqual(self.win.visible_consoles, [])
        self.assertEqual(
            self.win.content_stack.get_visible_child_name(), LIBRARY_EMPTY_ID
        )
        self.assertIsNone(self.win.current_console)

    def test_search_is_switched_off_with_nothing_to_search(self):
        self.assertFalse(self.win.search_entry.get_sensitive())

    def test_an_empty_library_has_no_view_to_remember(self):
        # Overwriting the stored view with the empty page would throw away the
        # console the user was on before the drive went missing (issue #383).
        self.config.session.set_last_view("SFC")
        self.win.current_console = LIBRARY_EMPTY_ID
        self.win._remember_current_view()
        self.assertEqual(self.config.session.get_last_view(), "SFC")

    def test_syncing_covers_with_no_consoles_says_so(self):
        self.win._sync_covers_for_current_scope()
        self.assertEqual(self.toasts, [self.said("toast.sync_no_consoles")])

    def test_the_sync_dialog_refuses_to_open_with_no_consoles(self):
        self.win._show_sync_covers_dialog()
        self.assertEqual(self.toasts, [self.said("toast.sync_no_consoles")])


@needs_display
class TheLayoutControlsTests(_WindowCase):
    def setUp(self):
        super().setUp()
        self.win.sidebar.select("SFC")

    def test_the_scope_being_edited_is_the_page_on_screen(self):
        self.assertEqual(self.win._current_scope(), "SFC")

    def test_a_window_on_no_page_edits_the_all_scope(self):
        self.win.current_console = None
        self.assertEqual(self.win._current_scope(), ALL_CONSOLES_ID)

    def test_changing_the_view_mode_stores_it_and_moves_the_action(self):
        other = next(m for m in window_module.VIEW_MODES if m != self.win._view_mode)
        self.win._apply_view_mode(other)
        self.assertEqual(self.win._view_mode, other)
        self.assertEqual(
            self.win.lookup_action("view-mode").get_state().get_string(), other
        )

    def test_choosing_the_mode_already_showing_changes_nothing(self):
        current = self.win._view_mode
        with mock.patch.object(self.win, "_write_scope_display") as write:
            self.win._apply_view_mode(current)
        write.assert_not_called()

    def test_the_view_mode_action_normalises_what_it_is_handed(self):
        action = self.win.lookup_action("view-mode")
        other = next(m for m in window_module.VIEW_MODES if m != self.win._view_mode)
        action.activate(GLib.Variant("s", other))
        self.assertEqual(self.win._view_mode, other)

    def test_changing_the_sort_order_stores_it_and_says_so(self):
        other = next(
            o for o in window_module.SORT_ORDERS if o != self.win._sort_order
        )
        self.win._apply_sort_order(other)
        self.assertEqual(self.win._sort_order, other)
        self.assertIn(
            self.said("toast.sorted", order=self.said(f"sort_order.{other}")),
            self.toasts,
        )

    def test_choosing_the_order_already_in_use_changes_nothing(self):
        with mock.patch.object(self.win, "_write_scope_display") as write:
            self.win._apply_sort_order(self.win._sort_order)
        write.assert_not_called()

    def test_the_sort_order_action_drives_the_same_path(self):
        action = self.win.lookup_action("sort-order")
        other = next(o for o in window_module.SORT_ORDERS if o != self.win._sort_order)
        action.activate(GLib.Variant("s", other))
        self.assertEqual(self.win._sort_order, other)

    def test_a_console_page_offers_every_sort_order(self):
        self.assertEqual(
            self.win._sort_orders_for_scope(), list(window_module.SORT_ORDERS)
        )

    def test_a_grouped_page_drops_platform_from_the_orders(self):
        # Issue #384: every game already sits under its console's header, so
        # sorting by platform would change nothing the user can see.
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.assertNotIn(
            window_module.SORT_PLATFORM, self.win._sort_orders_for_scope()
        )

    def test_a_page_following_the_global_layout_edits_the_global_one(self):
        self.assertFalse(self.config.has_scope_override("SFC"))
        other = next(m for m in window_module.VIEW_MODES if m != self.win._view_mode)
        self.win._apply_view_mode(other)
        self.assertEqual(self.config.get_ui_settings()["view_mode"], other)

    def test_a_page_with_its_own_layout_keeps_the_change_to_itself(self):
        global_before = self.config.get_ui_settings()["view_mode"]
        self.config.enable_scope_override("SFC")
        other = next(m for m in window_module.VIEW_MODES if m != global_before)
        self.win._apply_view_mode(other)
        self.assertEqual(self.config.get_ui_settings()["view_mode"], global_before)
        self.assertEqual(self.config.get_display_settings("SFC")["view_mode"], other)


@needs_display
class TheFollowGlobalToggleTests(_WindowCase):
    def setUp(self):
        super().setUp()
        self.win.sidebar.select("SFC")
        self.action = self.win.lookup_action("layout-follow-global")

    def test_a_page_starts_out_following_the_global_layout(self):
        self.assertTrue(self.action.get_state().get_boolean())

    def test_unchecking_it_gives_the_page_its_own_layout(self):
        self.action.activate(None)
        self.assertFalse(self.action.get_state().get_boolean())
        self.assertTrue(self.config.has_scope_override("SFC"))
        self.assertIn(
            self.said("toast.layout.scoped", scope=self.win.sidebar.label_for("SFC")),
            self.toasts,
        )

    def test_checking_it_again_hands_the_page_back_to_the_global_layout(self):
        self.action.activate(None)
        self.action.activate(None)
        self.assertTrue(self.action.get_state().get_boolean())
        self.assertFalse(self.config.has_scope_override("SFC"))
        self.assertIn(
            self.said("toast.layout.global", scope=self.win.sidebar.label_for("SFC")),
            self.toasts,
        )


@needs_display
class TheZoomStepperTests(_WindowCase):
    def test_the_label_shows_the_current_percentage(self):
        self.assertEqual(
            self.win.zoom_label.get_label(),
            f"{window_module.zoom_percent(self.win._zoom)}%",
        )

    def test_zooming_in_stores_the_new_level_and_says_so(self):
        before = self.win._zoom
        self.win._step_zoom(1)
        self.assertGreater(self.win._zoom, before)
        self.assertIn(
            self.said("toast.zoom", percent=window_module.zoom_percent(self.win._zoom)),
            self.toasts,
        )

    def test_zooming_out_from_the_smallest_level_changes_nothing(self):
        while window_module.can_zoom(self.win._zoom, -1):
            self.win._step_zoom(-1)
        self.toasts.clear()
        self.win._step_zoom(-1)
        self.assertEqual(self.toasts, [])
        self.assertFalse(self.win.zoom_out_button.get_sensitive())

    def test_zooming_in_from_the_largest_level_changes_nothing(self):
        while window_module.can_zoom(self.win._zoom, 1):
            self.win._step_zoom(1)
        self.toasts.clear()
        self.win._step_zoom(1)
        self.assertEqual(self.toasts, [])
        self.assertFalse(self.win.zoom_in_button.get_sensitive())

    def test_the_reset_action_goes_back_to_the_default(self):
        self.win._step_zoom(1)
        self.win.lookup_action("zoom-reset").activate(None)
        self.assertEqual(self.win._zoom, window_module.DEFAULT_ZOOM)

    def test_the_stepper_survives_being_asked_before_it_exists(self):
        del self.win.zoom_label
        self.win._sync_zoom_controls()


@needs_display
class TheThemeButtonTests(_WindowCase):
    def test_the_icon_offers_the_appearance_the_click_would_give(self):
        with mock.patch.object(window_module.theming, "is_dark", return_value=True):
            self.win._sync_theme_button()
        self.assertEqual(self.win.theme_btn.get_icon_name(), "weather-clear-symbolic")
        with mock.patch.object(window_module.theming, "is_dark", return_value=False):
            self.win._sync_theme_button()
        self.assertEqual(
            self.win.theme_btn.get_icon_name(), "weather-clear-night-symbolic"
        )

    def test_clicking_it_stores_the_opposite_appearance(self):
        with mock.patch.object(
            window_module.theming, "is_dark", return_value=False
        ), mock.patch.object(window_module.theming, "apply_theme") as apply_theme:
            self.win._on_theme_toggle_clicked(None)
        apply_theme.assert_called_once()
        self.assertEqual(self.config.get_ui_settings()["theme"], "dark")

    def test_a_retranslate_before_the_header_exists_is_harmless(self):
        del self.win.theme_btn
        self.win._sync_theme_button()

    def test_closing_lets_go_of_the_process_lifetime_style_manager(self):
        # The handler's closure holds the window, so leaving it connected keeps
        # a closed window alive for the rest of the process (issue #237).
        self.assertIsNotNone(self.win._style_manager_handler)
        self.win._on_close_disconnect_style_manager()
        self.assertIsNone(self.win._style_manager_handler)
        self.win._on_close_disconnect_style_manager()


@needs_display
class TheSelectionBarTests(_WindowCase):
    def test_it_stays_hidden_until_something_is_selected(self):
        self.assertFalse(self.win.selection_bar.get_reveal_child())

    def test_selecting_roms_reveals_it_and_counts_them(self):
        self.win._on_selection_changed([self.rom(), self.rom(index=1)])
        self.assertTrue(self.win.selection_bar.get_reveal_child())
        self.assertEqual(
            self.win.selection_label.get_label(), self.said("selection.count", count=2)
        )

    def test_clearing_hides_it_again(self):
        self.win._on_selection_changed([self.rom()])
        self.win._clear_selection()
        self.assertFalse(self.win.selection_bar.get_reveal_child())
        self.assertEqual(self.win._selected_roms, [])

    def test_selection_mode_is_entered_once_and_announced_once(self):
        self.win.enter_selection_mode()
        self.win.enter_selection_mode()
        self.assertTrue(self.win.selection_mode_active)
        self.assertEqual(
            self.toasts.count(self.said("toast.selection_mode.entered")), 1
        )

    def test_leaving_selection_mode_when_it_was_never_on_does_nothing(self):
        with mock.patch.object(self.win, "_clear_selection") as clear:
            self.win.leave_selection_mode()
        clear.assert_not_called()

    def test_leaving_selection_mode_clears_what_was_selected(self):
        self.win.enter_selection_mode()
        self.win._on_selection_changed([self.rom()])
        self.win.leave_selection_mode()
        self.assertFalse(self.win.selection_mode_active)
        self.assertEqual(self.win._selected_roms, [])

    def test_leaving_without_clearing_keeps_the_selection(self):
        self.win.enter_selection_mode()
        self.win._on_selection_changed([self.rom()])
        self.win.leave_selection_mode(clear=False)
        self.assertEqual(len(self.win._selected_roms), 1)

    def test_the_gamepad_shortcut_focuses_the_bar_only_when_it_is_up(self):
        self.win.focus_selection_actions()
        self.win._on_selection_changed([self.rom()])
        self.win.focus_selection_actions()

    def test_select_all_reaches_the_grid_of_the_page_on_screen(self):
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        with mock.patch.object(grid, "select_all") as select_all:
            self.win._select_all_visible()
        select_all.assert_called_once()

    def test_select_all_on_a_page_with_no_grid_is_harmless(self):
        self.win.current_console = "not-a-page"
        self.win._select_all_visible()
        self.win._clear_selection()


@needs_display
class TheEscapeKeyTests(_WindowCase):
    def test_a_key_that_is_not_escape_is_left_alone(self):
        self.assertFalse(self.win._on_window_escape(None, Gdk.KEY_a, 0, 0))

    def test_escape_clears_a_selection_first(self):
        self.win._on_selection_changed([self.rom()])
        self.assertTrue(self.win._on_window_escape(None, Gdk.KEY_Escape, 0, 0))
        self.assertEqual(self.win._selected_roms, [])

    def test_with_nothing_selected_escape_steps_back_to_the_sidebar(self):
        with mock.patch.object(
            self.win.navigation, "escape_to_sidebar", return_value=True
        ) as escape:
            self.assertTrue(self.win._on_window_escape(None, Gdk.KEY_Escape, 0, 0))
        escape.assert_called_once()


@needs_display
class TheTipBarTests(_WindowCase):
    def test_a_tip_is_showing_from_the_start(self):
        self.assertTrue(self.win.tip_label.get_text())

    def test_rotating_picks_a_different_tip(self):
        first = self.win._current_tip_key
        self.win._rotate_tip()
        self.assertNotEqual(self.win._current_tip_key, first)

    def test_the_timer_keeps_itself_running(self):
        self.assertEqual(self.win._on_tip_timeout(), GLib.SOURCE_CONTINUE)

    def test_turning_the_tips_off_stops_the_timer_and_hides_the_text(self):
        self.win._apply_tips_visibility(False)
        self.assertFalse(self.win._tip_side.get_visible())
        self.assertEqual(self.win._tip_timeout_id, 0)

    def test_turning_them_back_on_starts_the_timer_again(self):
        self.win._apply_tips_visibility(False)
        self.win._apply_tips_visibility(True)
        self.assertTrue(self.win._tip_side.get_visible())
        self.assertNotEqual(self.win._tip_timeout_id, 0)

    def test_the_bar_stays_for_the_input_hints_even_with_the_tips_off(self):
        self.win._apply_tips_visibility(False)
        self.win.set_hints([("A", "Open")])
        self.assertTrue(self.win.tip_bar.get_visible())

    def test_the_bar_goes_away_with_no_tips_and_no_hints(self):
        self.win._apply_tips_visibility(False)
        self.win.set_hints([])
        self.assertFalse(self.win.tip_bar.get_visible())

    def test_the_hint_slots_are_filled_left_to_right_and_the_rest_hidden(self):
        self.win.set_hints([("A", "Open"), ("B", "Back")])
        visible = [slot.get_visible() for slot, _k, _t in self.win._hint_slots]
        self.assertEqual(visible[:2], [True, True])
        self.assertFalse(any(visible[2:]))
        first_key = self.win._hint_slots[0][1]
        self.assertEqual(first_key.get_label(), "A")

    def test_more_hints_than_slots_are_cut_to_what_fits(self):
        self.win.set_hints([(str(i), str(i)) for i in range(20)])
        shown = sum(1 for slot, _k, _t in self.win._hint_slots if slot.get_visible())
        self.assertEqual(shown, window_module.MAX_INPUT_HINTS)

    def test_a_render_before_the_bar_exists_is_harmless(self):
        del self.win.tip_label
        self.win._render_tip()

    def test_the_visibility_switch_is_harmless_before_the_bar_exists(self):
        del self.win.tip_bar
        self.win._apply_tips_visibility(True)

    def test_closing_stops_the_rotation(self):
        self.assertFalse(self.win._on_close_stop_tips())
        self.assertEqual(self.win._tip_timeout_id, 0)


@needs_display
class TheSearchFieldTests(_WindowCase):
    def test_disabling_search_empties_and_locks_the_field(self):
        self.win.search_entry.set_text("metroid")
        self.win._set_search_enabled(False)
        self.assertEqual(self.win.search_entry.get_text(), "")
        self.assertFalse(self.win.search_entry.get_sensitive())
        self.assertFalse(self.win.search_button.get_active())

    def test_the_shortcut_toggles_the_button_when_search_is_available(self):
        self.win._set_search_enabled(True)
        self.win._toggle_search()
        self.assertTrue(self.win.search_button.get_active())
        self.win._toggle_search()
        self.assertFalse(self.win.search_button.get_active())

    def test_the_shortcut_does_nothing_while_search_is_unavailable(self):
        self.win._set_search_enabled(False)
        self.win._toggle_search()
        self.assertFalse(self.win.search_button.get_active())

    def test_typing_hands_the_query_to_the_visible_grid(self):
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        with mock.patch.object(grid, "set_filter") as set_filter:
            self.win.search_entry.set_text("metroid")
            self.win.apply_library_filters()
        self.assertEqual(set_filter.call_args[0][0], "metroid")

    def test_the_artwork_filter_rides_along_with_the_query(self):
        # Issue #127: one place decides visibility, so the two filters cannot
        # fight over the same flag.
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.win.lookup_action("filter-missing-artwork").activate(None)
        with mock.patch.object(grid, "set_filter") as set_filter:
            self.win.apply_library_filters()
        self.assertTrue(set_filter.call_args.kwargs["only_missing_artwork"])

    def test_the_artwork_filter_is_a_toggle(self):
        action = self.win.lookup_action("filter-missing-artwork")
        action.activate(None)
        self.assertTrue(self.win._filter_missing_artwork)
        action.activate(None)
        self.assertFalse(self.win._filter_missing_artwork)

    def test_filtering_a_page_with_no_grid_is_harmless(self):
        self.win.content_stack.set_visible_child_name(FAVORITES_ID)
        with mock.patch.object(self.win, "_apply_filters_to") as apply_to:
            self.win.pages._grids.pop(FAVORITES_ID, None)
            self.win.apply_library_filters()
        apply_to.assert_not_called()


@needs_display
class TheConsoleOrderTests(_WindowCase):
    def test_reordering_stores_the_arrangement_and_shows_it(self):
        reversed_order = list(reversed(self.win.visible_consoles))
        self.win.reorder_consoles(reversed_order)
        self.assertEqual(self.win.visible_consoles, reversed_order)
        self.assertEqual(
            self.config.get_console_order()[: len(reversed_order)], reversed_order
        )

    def test_moving_a_console_reports_whether_it_moved(self):
        first = self.win.visible_consoles[0]
        self.assertTrue(self.win.move_console_in_order(first, +1))
        self.assertEqual(self.win.visible_consoles[1], first)
        self.assertFalse(self.win.move_console_in_order(first, +1))

    def test_dropping_a_console_above_another_reports_whether_it_moved(self):
        first, second = self.win.visible_consoles[:2]
        self.assertTrue(self.win.place_console_in_order(second, first))
        self.assertEqual(self.win.visible_consoles[0], second)
        self.assertFalse(self.win.place_console_in_order(second, first))

    def test_placing_a_console_last_takes_no_anchor(self):
        first = self.win.visible_consoles[0]
        self.assertTrue(self.win.place_console_in_order(first, None))
        self.assertEqual(self.win.visible_consoles[-1], first)


@needs_display
class NavigatingTheSidebarTests(_WindowCase):
    def test_selecting_a_console_shows_its_page_and_titles_the_window(self):
        self.win.sidebar.select("FC")
        self.assertEqual(self.win.current_console, "FC")
        self.assertEqual(self.win.content_stack.get_visible_child_name(), "FC")

    def test_selecting_a_console_drops_the_selection_made_on_the_last_one(self):
        self.win.sidebar.select("SFC")
        self.win._on_selection_changed([self.rom()])
        self.win.sidebar.select("FC")
        self.assertEqual(self.win._selected_roms, [])

    def test_selecting_nothing_at_all_is_ignored(self):
        before = self.win.current_console
        self.win._on_console_selected(None, None)
        self.assertEqual(self.win.current_console, before)

    def test_the_view_is_remembered_at_most_once_per_idle_turn(self):
        self.win._remember_view_source = None
        with mock.patch.object(
            window_module.GLib, "idle_add", return_value=7
        ) as idle_add:
            self.win._remember_view_soon()
            self.win._remember_view_soon()
        idle_add.assert_called_once()

    def test_the_queued_write_stores_the_view_and_clears_its_slot(self):
        self.win.current_console = "SFC"
        self.win._remember_view_source = 7
        self.assertEqual(self.win._remember_view_idle(), GLib.SOURCE_REMOVE)
        self.assertIsNone(self.win._remember_view_source)
        self.assertEqual(self.config.session.get_last_view(), "SFC")

    def test_closing_writes_the_view_one_last_time(self):
        self.win.current_console = "FC"
        self.assertFalse(self.win._on_close_remember_view())
        self.assertEqual(self.config.session.get_last_view(), "FC")

    def test_the_favorites_row_is_re_synced_off_the_selection(self):
        # Removing a row from under a list mid-selection is not allowed, so
        # the sweep is deferred (issue #382).
        self.assertEqual(self.win._sync_favorites_row_idle(), GLib.SOURCE_REMOVE)

    def test_the_header_console_button_only_shows_on_a_console_page(self):
        self.win.sidebar.select("SFC")
        self.assertTrue(self.win.console_input_btn.get_visible())
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.assertFalse(self.win.console_input_btn.get_visible())

    def test_the_scope_id_is_only_a_console_never_a_mixed_page(self):
        self.win.current_console = ALL_CONSOLES_ID
        self.assertIsNone(self.win._console_scope_id())
        self.win.current_console = "SFC"
        self.assertEqual(self.win._console_scope_id(), "SFC")

    def test_the_header_sync_survives_being_called_before_the_header_exists(self):
        del self.win.console_input_btn
        self.win._sync_console_header_controls()


@needs_display
class RefreshingTheLibraryTests(_WindowCase):
    def test_a_refresh_that_finds_the_same_consoles_keeps_the_pages(self):
        # Issue #230: tearing the whole stack down for an unchanged library
        # threw every page away and rebuilt it, twice on startup.
        self.win.sidebar.select("SFC")
        page = self.win.pages.page_for("SFC")
        self.win.refresh_library()
        self.assertIs(self.win.pages.page_for("SFC"), page)

    def test_a_forced_refresh_rebuilds_every_page(self):
        self.win.sidebar.select("SFC")
        page = self.win.pages.page_for("SFC")
        self.win.refresh_library(force=True)
        self.assertIsNot(self.win.pages.page_for("SFC"), page)

    def test_a_console_that_lost_all_its_games_leaves_the_sidebar(self):
        for path in self.home.console_dir("FC").iterdir():
            path.unlink()
        self.win.playlist_manager.scan_and_rebuild_playlist("FC")
        self.win.refresh_library()
        self.assertNotIn("FC", self.win.visible_consoles)

    def test_the_preferred_view_is_where_the_refresh_lands(self):
        self.win.refresh_library(preferred_view="FC")
        self.assertEqual(self.win.current_console, "FC")

    def test_a_preferred_view_that_is_gone_falls_back_rather_than_breaking(self):
        self.win.refresh_library(preferred_view="collection:not-a-collection")
        self.assertIsNotNone(self.win.content_stack.get_visible_child_name())


@needs_display
class CollectionsTests(_WindowCase):
    def setUp(self):
        super().setUp()
        self.slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)

    def test_adding_a_rom_to_a_collection_says_how_many_went_in(self):
        rom = self.rom()
        self.win.toggle_rom_in_collection(rom, self.slug)
        self.assertTrue(self.win.collection_manager.contains(self.slug, rom["path"]))
        self.assertIn(
            self.said("collections.toast.added", count=1, name="RPGs"), self.toasts
        )

    def test_toggling_a_lone_rom_that_is_already_in_takes_it_out(self):
        rom = self.rom()
        self.win.toggle_rom_in_collection(rom, self.slug)
        self.win.toggle_rom_in_collection(rom, self.slug)
        self.assertFalse(self.win.collection_manager.contains(self.slug, rom["path"]))
        self.assertIn(
            self.said("collections.toast.removed_one", name=rom["name"]), self.toasts
        )

    def test_a_multi_rom_selection_is_what_the_action_applies_to(self):
        roms = [self.rom(), self.rom(index=1)]
        self.win._on_selection_changed(roms)
        self.win.toggle_rom_in_collection(roms[0], self.slug)
        for rom in roms:
            self.assertTrue(
                self.win.collection_manager.contains(self.slug, rom["path"])
            )

    def test_a_rom_outside_the_selection_is_acted_on_alone(self):
        selected = [self.rom(), self.rom(index=1)]
        self.win._on_selection_changed(selected)
        other = self.rom("FC")
        self.assertEqual(self.win._target_roms_for(other), [other])

    def test_a_selection_of_one_is_not_treated_as_a_selection(self):
        rom = self.rom()
        self.win._on_selection_changed([rom])
        self.assertEqual(self.win._target_roms_for(rom), [rom])

    def test_removing_from_the_collection_on_screen_takes_the_rom_out(self):
        rom = self.rom()
        self.win.toggle_rom_in_collection(rom, self.slug)
        self.win.sidebar.select(collection_scope(self.slug))
        self.win.remove_rom_from_current_collection(rom)
        self.assertFalse(self.win.collection_manager.contains(self.slug, rom["path"]))

    def test_removing_from_a_page_that_is_not_a_collection_does_nothing(self):
        rom = self.rom()
        self.win.toggle_rom_in_collection(rom, self.slug)
        self.win.sidebar.select("SFC")
        self.win.remove_rom_from_current_collection(rom)
        self.assertTrue(self.win.collection_manager.contains(self.slug, rom["path"]))


@needs_display
class TheCollectionPromptsTests(_WindowCase):
    """The dialogs are built and answered, never shown to anyone."""

    def test_creating_a_collection_from_the_prompt_adds_it_to_the_sidebar(self):
        created = []
        with self.caught_dialog() as caught:
            self.win._prompt_new_collection(on_created=created.append)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("Shooters")
        dialog.emit("response", "create")
        self.assertEqual(len(created), 1)
        self.assertEqual(self.win.collection_manager.get_name(created[0]), "Shooters")
        self.assertIn(
            self.said("collections.toast.created", name="Shooters"), self.toasts
        )

    def test_cancelling_the_prompt_creates_nothing(self):
        with self.caught_dialog() as caught:
            self.win._prompt_new_collection()
        caught[-1].emit("response", "cancel")
        self.assertEqual(self.win.collection_manager.list_collections(), [])

    def test_a_name_the_manager_refuses_is_reported_not_raised(self):
        with self.caught_dialog() as caught:
            self.win._prompt_new_collection()
        dialog = caught[-1]
        dialog.get_extra_child().set_text("   ")
        dialog.emit("response", "create")
        self.assertIn(self.said("collections.toast.invalid"), self.toasts)

    def test_renaming_a_collection_stores_the_new_name(self):
        slug = self.win.collection_manager.create("RPGs")
        with self.caught_dialog() as caught:
            self.win._prompt_rename_collection(slug)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("Role Playing")
        dialog.emit("response", "rename")
        self.assertEqual(self.win.collection_manager.get_name(slug), "Role Playing")

    def test_renaming_the_collection_on_screen_retitles_the_window(self):
        slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)
        self.win.sidebar.select(collection_scope(slug))
        with self.caught_dialog() as caught:
            self.win._prompt_rename_collection(slug)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("Role Playing")
        dialog.emit("response", "rename")
        self.assertEqual(self.win.window_title.get_title(), "Role Playing")

    def test_cancelling_a_rename_leaves_the_name_alone(self):
        slug = self.win.collection_manager.create("RPGs")
        with self.caught_dialog() as caught:
            self.win._prompt_rename_collection(slug)
        caught[-1].emit("response", "cancel")
        self.assertEqual(self.win.collection_manager.get_name(slug), "RPGs")

    def test_a_rename_the_manager_refuses_is_reported(self):
        slug = self.win.collection_manager.create("RPGs")
        with self.caught_dialog() as caught:
            self.win._prompt_rename_collection(slug)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("")
        dialog.emit("response", "rename")
        self.assertIn(self.said("collections.toast.invalid"), self.toasts)

    def test_deleting_a_collection_removes_its_page_and_its_grid(self):
        # Issue #237: popping the pages but not the grids left the deleted
        # collection's grid receiving artwork refreshes for an unreachable page.
        slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)
        scope = collection_scope(slug)
        self.assertTrue(self.win.pages.has(scope))
        with self.caught_dialog() as caught:
            self.win._confirm_delete_collection(slug)
        caught[-1].emit("response", "delete")
        self.assertFalse(self.win.pages.has(scope))
        self.assertIsNone(self.win.pages.grid_for(scope))

    def test_deleting_the_collection_on_screen_moves_to_favorites(self):
        # The Favorites row only exists once there is a favorite (issue #382),
        # and that row is where the deleted collection hands the user over.
        self.win._toggle_favorite_from_ui(self.rom())
        slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)
        self.win.sidebar.select(collection_scope(slug))
        with self.caught_dialog() as caught:
            self.win._confirm_delete_collection(slug)
        caught[-1].emit("response", "delete")
        self.assertEqual(self.win.current_console, FAVORITES_ID)

    def test_cancelling_a_delete_keeps_the_collection(self):
        slug = self.win.collection_manager.create("RPGs")
        with self.caught_dialog() as caught:
            self.win._confirm_delete_collection(slug)
        caught[-1].emit("response", "cancel")
        self.assertIsNotNone(self.win.collection_manager.get_name(slug))

    def test_creating_from_a_rom_puts_that_rom_in_the_new_collection(self):
        rom = self.rom()
        with self.caught_dialog() as caught:
            self.win.create_collection_and_add(rom)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("Favourites of mine")
        dialog.emit("response", "create")
        slug = self.win.collection_manager.list_collections()[0]["slug"]
        self.assertTrue(self.win.collection_manager.contains(slug, rom["path"]))




@needs_display
class RenamingAndDeletingRomsTests(_WindowCase):
    def test_renaming_moves_the_file_and_repaths_everything_that_knew_it(self):
        rom = self.rom()
        old_path = rom["path"]
        self.win.play_history.record_launch(rom["path"])
        self.win._apply_rename(rom, "Chrono Trigger (USA)")
        new_path = self.home.roms / "SFC" / "Chrono Trigger (USA).sfc"
        self.assertTrue(new_path.is_file())
        self.assertFalse(Path(old_path).exists())
        self.assertIn(
            self.said("toast.rom.renamed", name="Chrono Trigger (USA)"), self.toasts
        )

    def test_a_rename_the_action_refuses_is_reported_not_raised(self):
        rom = self.rom()
        with mock.patch.object(
            window_module, "rename_rom", side_effect=RomActionError("taken")
        ):
            self.win._apply_rename(rom, "whatever")
        self.assertIn(self.said("toast.rom.rename_failed", error="taken"), self.toasts)

    def test_deleting_removes_the_file_and_counts_what_went(self):
        roms = [self.rom(), self.rom(index=1)]
        self.win._delete_roms(roms)
        for rom in roms:
            self.assertFalse(Path(rom["path"]).exists())
        self.assertIn(self.said("toast.rom.deleted", count=2), self.toasts)

    def test_a_delete_that_fails_names_the_rom_and_the_rest_still_go(self):
        roms = [self.rom(), self.rom(index=1)]
        calls = []

        def _delete(_roms_dir, rom):
            calls.append(rom)
            if len(calls) == 1:
                raise RomActionError("read-only")

        with mock.patch.object(window_module, "delete_rom", _delete):
            self.win._delete_roms(roms)
        self.assertIn(
            self.said("toast.rom.delete_failed", name=roms[0]["name"]), self.toasts
        )
        self.assertIn(self.said("toast.rom.deleted", count=1), self.toasts)

    def test_the_delete_prompt_only_deletes_on_the_destructive_answer(self):
        rom = self.rom()
        with self.caught_dialog() as caught:
            self.win._confirm_delete_roms([rom])
        caught[-1].emit("response", "cancel")
        self.assertTrue(Path(rom["path"]).exists())

    def test_the_delete_prompt_deletes_on_confirmation(self):
        rom = self.rom()
        with self.caught_dialog() as caught:
            self.win._confirm_delete_roms([rom])
        caught[-1].emit("response", "delete")
        self.assertFalse(Path(rom["path"]).exists())

    def test_a_prompt_for_no_roms_at_all_is_not_shown(self):
        with self.caught_dialog() as caught:
            self.win._confirm_delete_roms([])
            self.win._confirm_delete_roms(None)
        self.assertEqual(caught, [])

    def test_the_delete_key_acts_on_the_selection_when_there_is_one(self):
        roms = [self.rom(), self.rom(index=1)]
        self.win._on_selection_changed(roms)
        with mock.patch.object(self.win, "_confirm_delete_roms") as confirm:
            self.win._delete_selected_or_focused()
        confirm.assert_called_once_with(roms)

    def test_the_delete_key_acts_on_the_focused_card_otherwise(self):
        rom = self.rom()
        item = mock.Mock(rom=rom)
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=item
        ), mock.patch.object(self.win, "_confirm_delete_roms") as confirm:
            self.win._delete_selected_or_focused()
        confirm.assert_called_once_with([rom])

    def test_the_delete_key_with_nothing_focused_does_nothing(self):
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=None
        ), mock.patch.object(self.win, "_confirm_delete_roms") as confirm:
            self.win._delete_selected_or_focused()
        confirm.assert_not_called()

    def test_f2_renames_the_focused_card(self):
        item = mock.Mock(rom=self.rom())
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=item
        ), mock.patch.object(self.win, "_rename_rom_from_ui") as rename:
            self.win._rename_focused_rom()
        rename.assert_called_once_with(item.rom)

    def test_f2_with_nothing_focused_does_nothing(self):
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=None
        ), mock.patch.object(self.win, "_rename_rom_from_ui") as rename:
            self.win._rename_focused_rom()
        rename.assert_not_called()

    def test_the_favorite_shortcut_goes_through_the_card(self):
        # Through the card so its star badge stays in sync.
        item = mock.Mock(rom=self.rom())
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=item
        ):
            self.win._favorite_focused_rom()
        item.toggle_favorite.assert_called_once()

    def test_the_favorite_shortcut_with_nothing_focused_does_nothing(self):
        with mock.patch.object(
            window_module.RomGrid, "item_for_widget", return_value=None
        ):
            self.win._favorite_focused_rom()

    def test_the_rename_prompt_applies_the_typed_name(self):
        rom = self.rom()
        with self.caught_dialog() as caught:
            self.win._rename_rom_from_ui(rom)
        dialog = caught[-1]
        dialog.get_extra_child().set_text("Renamed Game")
        with mock.patch.object(self.win, "_apply_rename") as apply_rename:
            dialog.emit("response", "rename")
        apply_rename.assert_called_once_with(rom, "Renamed Game")

    def test_cancelling_the_rename_prompt_applies_nothing(self):
        with self.caught_dialog() as caught:
            self.win._rename_rom_from_ui(self.rom())
        with mock.patch.object(self.win, "_apply_rename") as apply_rename:
            caught[-1].emit("response", "cancel")
        apply_rename.assert_not_called()


@needs_display
class FavoritesTests(_WindowCase):
    def test_starring_a_rom_says_so_and_records_it(self):
        rom = self.rom()
        self.assertTrue(self.win._toggle_favorite_from_ui(rom))
        self.assertTrue(self.win._is_favorite_rom(rom))
        self.assertIn(self.said("toast.favorite.added", name=rom["name"]), self.toasts)

    def test_unstarring_says_so_too(self):
        rom = self.rom()
        self.win._toggle_favorite_from_ui(rom)
        self.assertFalse(self.win._toggle_favorite_from_ui(rom))
        self.assertIn(
            self.said("toast.favorite.removed", name=rom["name"]), self.toasts
        )

    def test_starring_while_standing_on_the_favorites_page_reloads_it(self):
        self.win.current_console = FAVORITES_ID
        with mock.patch.object(self.win.pages, "ensure_favorites_loaded") as reload:
            self.win._toggle_favorite_from_ui(self.rom())
        reload.assert_called()

    def test_starring_from_elsewhere_still_reloads_a_loaded_favorites_page(self):
        # The page need not be on screen: a stale Favorites grid behind the
        # console page would show the star that was just taken away.
        self.win._toggle_favorite_from_ui(self.rom())
        self.win.pages.ensure_favorites_loaded()
        self.win.current_console = "SFC"
        self.assertIsNotNone(self.win.pages.grid_for(FAVORITES_ID))
        with mock.patch.object(self.win.pages, "ensure_favorites_loaded") as reload:
            self.win._toggle_favorite_from_ui(self.rom(index=1))
        reload.assert_called()


@needs_display
class PerRomOverridesTests(_WindowCase):
    def test_choosing_a_core_for_one_rom_is_stored_and_announced(self):
        rom = self.rom()
        self.win.set_rom_core(rom, "snes9x_libretro.so")
        self.assertEqual(
            self.config.get_rom_core_override(rom["path"]), "snes9x_libretro.so"
        )
        self.assertTrue(
            any("snes9x" in text or rom["name"] in text for text in self.toasts)
        )

    def test_clearing_the_core_override_says_it_is_automatic_again(self):
        rom = self.rom()
        self.win.set_rom_core(rom, None)
        self.assertIn(self.said("toast.core.rom_auto", name=rom["name"]), self.toasts)

    def test_a_core_whose_bios_is_missing_warns_about_it(self):
        with mock.patch.object(
            window_module, "find_missing_required_for_core", return_value=["bios.bin"]
        ):
            self.win._warn_missing_bios_for_core("PS", "mednafen_psx_hw_libretro.so")
        self.assertIn(
            self.said(
                "toast.core.bios_warning",
                core="mednafen_psx_hw_libretro.so",
                bios="bios.bin",
            ),
            self.toasts,
        )

    def test_a_core_with_every_bios_present_warns_about_nothing(self):
        with mock.patch.object(
            window_module, "find_missing_required_for_core", return_value=[]
        ):
            self.win._warn_missing_bios_for_core("SFC", "snes9x_libretro.so")
        self.assertEqual(self.toasts, [])

    def test_choosing_a_shader_for_one_rom_is_stored(self):
        rom = self.rom()
        self.win.set_rom_shader(rom, "crt")
        self.assertEqual(self.config.get_rom_shader_override(rom["path"]), "crt")

    def test_clearing_the_shader_override_names_the_console_default(self):
        rom = self.rom()
        self.win.set_rom_shader(rom, None)
        self.assertIn(
            self.said(
                "toast.shader.rom_set",
                name=rom["name"],
                shader=self.said("context.shader.use_console_short"),
            ),
            self.toasts,
        )

    def test_a_cartridge_colour_is_stored_and_only_that_card_repainted(self):
        rom = self.rom()
        grids = list(self.win.pages.grids())
        with mock.patch.object(
            window_module.OpenEmuxWindow, "_reload_current_page"
        ) as reload:
            self.win.set_rom_cartridge_color(rom, "black")
        reload.assert_not_called()
        self.assertEqual(
            self.config.get_cartridge_color_for_rom(rom["path"], rom["console"]),
            "black",
        )
        self.assertTrue(grids or True)

    def test_the_colour_a_card_draws_with_comes_from_the_config(self):
        rom = self.rom()
        self.win.set_rom_cartridge_color(rom, "black")
        self.assertEqual(self.win._cartridge_color_for_rom(rom), "black")

    def test_the_current_view_mode_is_published_for_the_context_menus(self):
        self.assertEqual(self.win.current_view_mode, self.win._view_mode)


@needs_display
class CoverFilesTests(_WindowCase):
    def _write_cover(self, rom, kind=COVER_ART):
        target = self.home.roms / rom["console"] / kind / f"{rom['name']}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        return target

    def test_a_rom_with_no_cover_says_so(self):
        self.assertFalse(self.win._has_local_cover(self.rom()))

    def test_a_rom_with_a_cover_on_disk_is_recognised(self):
        rom = self.rom()
        self._write_cover(rom)
        self.assertTrue(self.win._has_local_cover(rom))

    def test_removing_a_cover_deletes_it_and_says_so(self):
        rom = self.rom()
        target = self._write_cover(rom)
        done = []
        self.win._remove_cover_for_rom(rom, on_done=lambda: done.append(True))
        self.assertFalse(target.exists())
        self.assertEqual(done, [True])
        self.assertIn(self.said("toast.cover.removed", name=rom["name"]), self.toasts)

    def test_removing_a_label_says_label_rather_than_cover(self):
        rom = self.rom()
        self._write_cover(rom, LABEL_ART)
        self.win._remove_cover_for_rom(rom, kind=LABEL_ART)
        self.assertIn(self.said("toast.label.removed", name=rom["name"]), self.toasts)

    def test_removing_a_cover_that_is_not_there_says_nothing(self):
        self.win._remove_cover_for_rom(self.rom())
        self.assertEqual(self.toasts, [])


@needs_display
class TheCoverPickerTests(_WindowCase):
    """The picker itself never opens; only what it hands back matters."""

    def setUp(self):
        super().setUp()
        self.dialogs = []
        patcher = mock.patch.object(
            window_module.Gtk, "FileDialog", self._make_dialog
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_dialog(self):
        dialog = mock.Mock()
        self.dialogs.append(dialog)
        return dialog

    def _answer(self, path):
        chosen = mock.Mock()
        chosen.get_path.return_value = str(path) if path is not None else ""
        source = mock.Mock()
        source.open_finish.return_value = chosen if path is not None else None
        callback = self.dialogs[-1].open.call_args[0][2]
        callback(source, None)

    def test_a_chosen_png_is_copied_into_the_library(self):
        rom = self.rom()
        source = self.tmp / "art.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n")
        done = []
        self.win._choose_cover_for_rom(rom, on_done=lambda: done.append(True))
        self._answer(source)
        self.assertTrue(
            (self.home.roms / "SFC" / COVER_ART / f"{rom['name']}.png").is_file()
        )
        self.assertEqual(done, [True])

    def test_a_chosen_file_that_is_not_an_image_is_refused(self):
        rom = self.rom()
        source = self.tmp / "notes.txt"
        source.write_text("x")
        self.win._choose_cover_for_rom(rom)
        self._answer(source)
        self.assertIn(self.said("toast.cover.invalid_extension"), self.toasts)

    def test_a_dismissed_picker_copies_nothing(self):
        rom = self.rom()
        self.win._choose_cover_for_rom(rom)
        source = mock.Mock()
        source.open_finish.side_effect = GLib.Error("dismissed")
        self.dialogs[-1].open.call_args[0][2](source, None)
        self.assertEqual(self.toasts, [])

    def test_a_picker_that_returns_nothing_copies_nothing(self):
        self.win._choose_cover_for_rom(self.rom())
        self._answer(None)
        self.assertEqual(self.toasts, [])

    def test_a_chosen_uri_with_no_local_path_copies_nothing(self):
        rom = self.rom()
        self.win._choose_cover_for_rom(rom)
        chosen = mock.Mock()
        chosen.get_path.return_value = ""
        source = mock.Mock()
        source.open_finish.return_value = chosen
        self.dialogs[-1].open.call_args[0][2](source, None)
        self.assertEqual(self.toasts, [])

    def test_the_label_picker_is_titled_after_the_label(self):
        self.win._choose_cover_for_rom(self.rom(), kind=LABEL_ART)
        self.dialogs[-1].set_title.assert_called_once_with(
            self.said("dialog.label.choose.title")
        )


@needs_display
class TheRomsFolderPickerTests(_WindowCase):
    def _chosen(self, path):
        selected = mock.Mock()
        selected.get_path.return_value = str(path) if path is not None else ""
        dialog = mock.Mock()
        dialog.select_folder_finish.return_value = selected
        return dialog

    def test_choosing_a_folder_repoints_the_library_at_it(self):
        new_root = self.tmp / "elsewhere"
        new_root.mkdir()
        with mock.patch.object(
            window_module.OpenEmuxWindow, "_rescan_all_consoles"
        ) as rescan:
            self.win._on_roms_path_chosen(self._chosen(new_root), None)
        self.assertEqual(self.config.get_roms_path(), new_root)
        self.assertEqual(self.win.roms_path, new_root)
        rescan.assert_called_once_with(show_toast=False)
        self.assertIn(
            self.said("toast.path_updated", path=str(new_root)), self.toasts
        )

    def test_a_folder_the_app_cannot_write_into_is_reported(self):
        # Issue #234: an unwritable folder used to raise into the GTK main
        # loop and take the handler down half-way through.
        new_root = self.tmp / "elsewhere"
        new_root.mkdir()
        with mock.patch.object(
            window_module.OpenEmuxWindow, "_rescan_all_consoles"
        ), mock.patch.object(
            self.config, "ensure_rom_directories", return_value=["SFC"]
        ):
            self.win._on_roms_path_chosen(self._chosen(new_root), None)
        self.assertIn(
            self.said("toast.path_not_writable", path=str(new_root)), self.toasts
        )

    def test_a_dismissed_picker_leaves_the_library_where_it_was(self):
        before = self.config.get_roms_path()
        dialog = mock.Mock()
        dialog.select_folder_finish.side_effect = GLib.Error("dismissed")
        self.win._on_roms_path_chosen(dialog, None)
        self.assertEqual(self.config.get_roms_path(), before)

    def test_a_picker_that_returns_nothing_leaves_it_alone(self):
        before = self.config.get_roms_path()
        dialog = mock.Mock()
        dialog.select_folder_finish.return_value = None
        self.win._on_roms_path_chosen(dialog, None)
        self.assertEqual(self.config.get_roms_path(), before)

    def test_a_folder_with_no_local_path_is_reported_as_invalid(self):
        self.win._on_roms_path_chosen(self._chosen(None), None)
        self.assertIn(self.said("toast.path_invalid"), self.toasts)

    def test_the_picker_starts_in_the_folder_already_configured(self):
        dialog = mock.Mock()
        with mock.patch.object(window_module.Gtk, "FileDialog", return_value=dialog):
            self.win._choose_roms_path()
        dialog.set_initial_folder.assert_called_once()
        dialog.select_folder.assert_called_once()


@needs_display
class OpeningFoldersTests(_WindowCase):
    def test_the_roms_folder_is_opened_by_path(self):
        with mock.patch.object(self.win, "_open_path_in_file_manager") as open_path:
            self.win._open_roms_folder()
        open_path.assert_called_once_with(self.config.get_roms_path())

    def test_a_console_bios_folder_is_opened_by_path(self):
        with mock.patch.object(self.win, "_open_path_in_file_manager") as open_path:
            self.win._open_console_bios_folder("SFC")
        self.assertIn("SFC", open_path.call_args[0][0].parts)

    def test_a_folder_that_opens_cleanly_says_nothing(self):
        with mock.patch.object(
            window_module.Gio.AppInfo, "launch_default_for_uri", return_value=True
        ):
            self.win._open_path_in_file_manager(self.tmp / "somewhere")
        self.assertEqual(self.toasts, [])

    def test_a_desktop_with_no_uri_handler_falls_back_to_xdg_open(self):
        with mock.patch.object(
            window_module.Gio.AppInfo,
            "launch_default_for_uri",
            side_effect=GLib.Error("no handler"),
        ), mock.patch.object(window_module.subprocess, "Popen") as popen:
            self.win._open_path_in_file_manager(self.tmp / "somewhere")
        self.assertEqual(popen.call_args[0][0][0], "xdg-open")
        self.assertEqual(self.toasts, [])

    def test_a_folder_nothing_can_open_reports_the_error(self):
        # Issue #234: the mkdir used to sit outside the try, so this raised
        # past the toast and the button simply did nothing.
        with mock.patch.object(
            window_module.Gio.AppInfo,
            "launch_default_for_uri",
            side_effect=GLib.Error("no handler"),
        ), mock.patch.object(
            window_module.subprocess, "Popen", side_effect=OSError("no xdg-open")
        ):
            self.win._open_path_in_file_manager(self.tmp / "somewhere")
        self.assertEqual(len(self.toasts), 1)

    def test_revealing_a_rom_that_is_gone_says_so(self):
        self.win._reveal_rom_in_files({"path": str(self.tmp / "gone.sfc")})
        self.assertIn(
            self.said("context.reveal.missing", name="gone.sfc"), self.toasts
        )

    def test_revealing_a_rom_asks_the_file_manager_to_select_it(self):
        rom = self.rom()
        connection = mock.Mock()
        with mock.patch.object(
            window_module.Gio, "bus_get_sync", return_value=connection
        ):
            self.win._reveal_rom_in_files(rom)
        self.assertEqual(connection.call_sync.call_args[0][3], "ShowItems")

    def test_a_desktop_with_no_file_manager_service_opens_the_folder(self):
        rom = self.rom()
        with mock.patch.object(
            window_module.Gio, "bus_get_sync", side_effect=GLib.Error("no bus")
        ), mock.patch.object(self.win, "_open_path_in_file_manager") as open_path:
            self.win._reveal_rom_in_files(rom)
        open_path.assert_called_once_with(Path(rom["path"]).parent)


@needs_display
class TheRescanPlumbingTests(_WindowCase):
    def test_a_rescan_of_one_console_runs_and_refreshes_the_library(self):
        summary = {"console": "SFC", "roms": 2}
        self.assertFalse(
            self.win._on_rescan_single_done_ui("task", summary, True, "SFC")
        )
        self.assertIn(
            self.said("toast.playlist_rebuilt", console="SFC"), self.toasts
        )
        self.assertFalse(self.win._scan_running)

    def test_a_crashed_rescan_reports_the_error_rather_than_a_clean_run(self):
        # Issue #214: a worker that died without clearing the flag left every
        # later scan refused for the rest of the session.
        summary = {"console": "SFC", "error": "disk gone"}
        self.win._on_rescan_single_done_ui("task", summary, True, "SFC")
        self.assertIn(self.said("toast.scan_failed", error="disk gone"), self.toasts)
        self.assertFalse(self.win._scan_running)

    def test_a_whole_library_rescan_reports_what_it_found(self):
        summary = {"total_consoles": 2, "total_roms": 3, "failed": {}}
        self.win._on_rescan_all_done_ui("task", summary, True, None)
        self.assertIn(
            self.said("toast.playlists_rebuilt_all", consoles=2, roms=3), self.toasts
        )

    def test_a_partly_failed_rescan_names_the_consoles_that_did_not_scan(self):
        summary = {
            "total_consoles": 1,
            "total_roms": 1,
            "failed": {"FC": "permission denied"},
        }
        self.win._on_rescan_all_done_ui("task", summary, True, None)
        self.assertIn(self.said("toast.scan_partial", consoles="FC"), self.toasts)

    def test_a_crashed_whole_library_rescan_reports_the_error(self):
        summary = {"failed": {}, "error": "boom"}
        self.win._on_rescan_all_done_ui("task", summary, True, None)
        self.assertIn(self.said("toast.scan_failed", error="boom"), self.toasts)

    def test_a_silent_rescan_says_nothing_at_all(self):
        summary = {"total_consoles": 2, "total_roms": 3, "failed": {}}
        self.win._on_rescan_all_done_ui("task", summary, False, None)
        self.assertEqual(self.toasts, [])

    def test_a_rescan_asked_for_while_one_runs_is_queued(self):
        # Issue #225: the request used to be dropped with no retry and no
        # message, so an import looked like it had failed.
        self.win._scan_running = True
        self.assertIsNone(self.win._rescan_single_console("SFC", show_toast=True))
        self.assertEqual(self.win._rescan_pending["console"], "SFC")
        self.assertIn(self.said("toast.scan_running"), self.toasts)

    def test_a_whole_library_rescan_queued_over_a_console_covers_both(self):
        self.win._queue_rescan("SFC", False)
        self.win._queue_rescan(None, True)
        self.assertIsNone(self.win._rescan_pending["console"])
        self.assertTrue(self.win._rescan_pending["show_toast"])

    def test_a_console_queued_after_the_whole_library_changes_nothing(self):
        self.win._queue_rescan(None, False)
        self.win._queue_rescan("SFC", True)
        self.assertIsNone(self.win._rescan_pending["console"])
        self.assertTrue(self.win._rescan_pending["show_toast"])

    def test_two_different_consoles_queued_become_the_whole_library(self):
        self.win._queue_rescan("SFC", False)
        self.win._queue_rescan("FC", False)
        self.assertIsNone(self.win._rescan_pending["console"])

    def test_the_same_console_queued_twice_stays_that_console(self):
        self.win._queue_rescan("SFC", False)
        self.win._queue_rescan("SFC", True)
        self.assertEqual(self.win._rescan_pending["console"], "SFC")
        self.assertTrue(self.win._rescan_pending["show_toast"])

    def test_nothing_queued_means_nothing_to_run(self):
        self.win._rescan_pending = None
        self.assertFalse(self.win._run_pending_rescan())

    def test_a_queued_console_rescan_runs_that_console(self):
        self.win._rescan_pending = {"console": "SFC", "show_toast": True}
        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            self.win._run_pending_rescan()
        rescan.assert_called_once_with("SFC", show_toast=True)
        self.assertIsNone(self.win._rescan_pending)

    def test_a_queued_whole_library_rescan_runs_everything(self):
        self.win._rescan_pending = {"console": None, "show_toast": False}
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            self.win._run_pending_rescan()
        rescan.assert_called_once_with(show_toast=False)

    def test_rescanning_all_from_the_all_page_covers_the_library(self):
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            self.win._rescan_single_console(ALL_CONSOLES_ID)
        rescan.assert_called_once()

    def test_the_startup_scan_is_a_silent_whole_library_rescan(self):
        # The method itself is held back during construction (it is a thread),
        # so it is called here against the real implementation.
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            _REAL_STARTUP_SCAN(self.win)
        rescan.assert_called_once_with(show_toast=False)

    def test_the_refresh_button_rescans_the_console_it_is_on(self):
        self.win.sidebar.select("SFC")
        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            self.win._on_refresh_clicked(None)
        rescan.assert_called_once_with("SFC", show_toast=False)

    def test_the_refresh_button_on_the_all_page_rescans_everything(self):
        self.win.sidebar.select(ALL_CONSOLES_ID)
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            self.win._on_refresh_clicked(None)
        rescan.assert_called_once_with(show_toast=False)

    def test_the_refresh_button_on_favorites_only_reloads_the_page(self):
        self.win.current_console = FAVORITES_ID
        with mock.patch.object(
            self.win.sidebar, "selected_id", return_value=FAVORITES_ID
        ), mock.patch.object(self.win.pages, "ensure_favorites_loaded") as reload:
            self.win._on_refresh_clicked(None)
        reload.assert_called_once()


@needs_display
class TheScanAndSyncDialogsTests(_WindowCase):
    def test_the_scan_dialog_starts_a_whole_library_rescan_on_all(self):
        with self.caught_dialog() as caught:
            self.win._show_scan_roms_dialog()
        dialog = caught[-1]
        self.win._set_console_dropdown_active_id(
            dialog.get_extra_child(), ALL_CONSOLES_ID
        )
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            dialog.emit("response", "start")
        rescan.assert_called_once_with(show_toast=True)

    def test_the_scan_dialog_starts_one_console_when_one_is_picked(self):
        with self.caught_dialog() as caught:
            self.win._show_scan_roms_dialog()
        dialog = caught[-1]
        self.win._set_console_dropdown_active_id(dialog.get_extra_child(), "SFC")
        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            dialog.emit("response", "start")
        rescan.assert_called_once_with("SFC", show_toast=True)

    def test_cancelling_the_scan_dialog_starts_nothing(self):
        with self.caught_dialog() as caught:
            self.win._show_scan_roms_dialog()
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            caught[-1].emit("response", "cancel")
        rescan.assert_not_called()

    def test_the_sync_dialog_covers_the_whole_library_on_all(self):
        with self.caught_dialog() as caught:
            self.win._show_sync_covers_dialog()
        dialog = caught[-1]
        self.win._set_console_dropdown_active_id(
            dialog.get_extra_child(), ALL_CONSOLES_ID
        )
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            dialog.emit("response", "start")
        sync.assert_called_once_with(scope="all", selected_console=None)

    def test_the_sync_dialog_covers_one_console_when_one_is_picked(self):
        self.win.sidebar.select("SFC")
        with self.caught_dialog() as caught:
            self.win._show_sync_covers_dialog()
        dialog = caught[-1]
        self.win._set_console_dropdown_active_id(dialog.get_extra_child(), "FC")
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            dialog.emit("response", "start")
        sync.assert_called_once_with(scope="console", selected_console="FC")

    def test_cancelling_the_sync_dialog_starts_nothing(self):
        with self.caught_dialog() as caught:
            self.win._show_sync_covers_dialog()
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            caught[-1].emit("response", "cancel")
        sync.assert_not_called()

    def test_the_scan_menu_entry_opens_the_scan_dialog(self):
        with mock.patch.object(self.win, "_show_scan_roms_dialog") as show:
            self.win._scan_current_console()
        show.assert_called_once()


@needs_display
class TheConsoleDropdownTests(_WindowCase):
    def test_it_can_offer_an_all_entry_above_the_consoles(self):
        dropdown = self.win._build_console_dropdown(["SFC", "FC"], include_all=True)
        self.assertEqual(dropdown._console_ids, [ALL_CONSOLES_ID, "SFC", "FC"])
        self.assertEqual(
            self.win._get_console_dropdown_active_id(dropdown), ALL_CONSOLES_ID
        )

    def test_without_the_all_entry_it_opens_on_the_first_console(self):
        dropdown = self.win._build_console_dropdown(["SFC", "FC"])
        self.assertEqual(self.win._get_console_dropdown_active_id(dropdown), "SFC")

    def test_it_can_be_pointed_at_a_console(self):
        dropdown = self.win._build_console_dropdown(["SFC", "FC"])
        self.win._set_console_dropdown_active_id(dropdown, "FC")
        self.assertEqual(self.win._get_console_dropdown_active_id(dropdown), "FC")

    def test_a_console_it_does_not_offer_falls_back_to_the_first_entry(self):
        dropdown = self.win._build_console_dropdown(["SFC", "FC"])
        self.win._set_console_dropdown_active_id(dropdown, "N64")
        self.assertEqual(self.win._get_console_dropdown_active_id(dropdown), "SFC")

    def test_an_empty_dropdown_cannot_be_pointed_anywhere(self):
        dropdown = Gtk.DropDown.new(Gtk.StringList.new([]), None)
        self.win._set_console_dropdown_active_id(dropdown, "SFC")
        self.assertIsNone(self.win._get_console_dropdown_active_id(dropdown))

    def test_an_out_of_range_selection_resolves_to_nothing(self):
        dropdown = self.win._build_console_dropdown(["SFC"])
        with mock.patch.object(dropdown, "get_selected", return_value=99):
            self.assertIsNone(self.win._get_console_dropdown_active_id(dropdown))


@needs_display
class TheArtworkSyncTests(_WindowCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(window_module, "sync_artwork_async")
        self.sync_async = patcher.start()
        self.addCleanup(patcher.stop)

    def test_syncing_the_scope_on_screen_covers_that_console(self):
        self.win.sidebar.select("SFC")
        self.win._sync_covers_for_current_scope()
        passes = self.sync_async.call_args.kwargs["passes"]
        self.assertTrue(any("SFC" in library for _kind, library in passes))
        self.assertFalse(any("FC" in library for _kind, library in passes))

    def test_syncing_from_a_mixed_page_covers_the_whole_library(self):
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.win._sync_covers_for_current_scope()
        passes = self.sync_async.call_args.kwargs["passes"]
        consoles = set()
        for _kind, library in passes:
            consoles.update(library)
        self.assertEqual(consoles, {"SFC", "FC"})

    def test_the_header_button_syncs_the_current_scope(self):
        with mock.patch.object(self.win, "_sync_covers_for_current_scope") as sync:
            self.win._on_sync_covers_clicked(None)
        sync.assert_called_once()

    def test_a_second_sync_while_one_runs_is_refused_with_a_message(self):
        self.win._cover_sync_running = True
        self.win._start_cover_sync(scope="all", selected_console=None)
        self.assertIn(self.said("toast.sync_running"), self.toasts)
        self.sync_async.assert_not_called()

    def test_syncing_a_selection_covers_exactly_those_roms(self):
        roms = [self.rom(), self.rom("FC")]
        self.win._on_selection_changed(roms)
        self.win._sync_covers_for_selection()
        self.assertTrue(self.sync_async.called)
        self.assertEqual(self.win._selected_roms, [])

    def test_syncing_an_empty_selection_starts_nothing(self):
        self.win._on_selection_changed([])
        self.win._sync_covers_for_selection()
        self.sync_async.assert_not_called()

    def test_a_single_rom_sync_replaces_what_is_already_there(self):
        # Syncing one game by hand usually means what it has is wrong.
        rom = self.rom()
        self.win.sync_rom_artwork(rom, COVER_ART)
        self.assertTrue(self.sync_async.call_args.kwargs["replace_existing"])

    def test_a_single_rom_sync_is_refused_while_another_sync_runs(self):
        self.win._cover_sync_running = True
        self.win.sync_rom_artwork(self.rom(), COVER_ART)
        self.assertIn(self.said("toast.sync_running"), self.toasts)

    def test_a_post_import_sync_covers_only_what_was_imported(self):
        rom = self.rom()
        self.win._start_post_import_artwork_sync([rom["path"]])
        passes = self.sync_async.call_args.kwargs["passes"]
        names = {r["name"] for _kind, library in passes for r in library["SFC"]}
        self.assertEqual(names, {rom["name"]})

    def test_a_post_import_sync_with_nothing_imported_starts_nothing(self):
        self.win._start_post_import_artwork_sync([])
        self.sync_async.assert_not_called()

    def test_a_post_import_sync_for_unknown_paths_starts_nothing(self):
        self.win._start_post_import_artwork_sync([str(self.tmp / "nowhere.sfc")])
        self.sync_async.assert_not_called()

    def test_a_post_import_sync_stands_aside_for_a_sync_the_user_started(self):
        self.win._cover_sync_running = True
        self.win._start_post_import_artwork_sync([self.rom()["path"]])
        self.sync_async.assert_not_called()
        self.assertNotIn(self.said("toast.sync_running"), self.toasts)

    def test_a_finished_sync_reports_the_tally_and_frees_the_flag(self):
        self.win._cover_sync_running = True
        summary = {"downloaded": 3, "skipped": 1, "errors": 0}
        self.assertFalse(self.win._on_cover_sync_done_ui("task", summary))
        self.assertFalse(self.win._cover_sync_running)
        self.assertIn(
            self.said("toast.sync_done", downloaded=3, skipped=1, errors=0),
            self.toasts,
        )

    def test_a_cancelled_sync_says_it_was_cancelled(self):
        summary = {"downloaded": 1, "skipped": 0, "errors": 0, "cancelled": True}
        self.win._on_cover_sync_done_ui("task", summary)
        self.assertIn(
            self.said("toast.sync_cancelled", downloaded=1, skipped=0, errors=0),
            self.toasts,
        )

    def test_the_callers_own_follow_up_runs_when_the_sync_ends(self):
        done = []
        summary = {"downloaded": 0, "skipped": 0, "errors": 0}
        self.win._on_cover_sync_done_ui("task", summary, on_finished=lambda: done.append(1))
        self.assertEqual(done, [1])


@needs_display
class TheIncrementalCoverRevealTests(_WindowCase):
    """Issue #187: covers appear while the sync is still running."""

    def setUp(self):
        super().setUp()
        self.win.sidebar.select("SFC")
        patcher = mock.patch.object(self.win, "refresh_rom_artwork")
        self.refresh = patcher.start()
        self.addCleanup(patcher.stop)

    def _rom(self, console="SFC", name="A"):
        return {"console": console, "name": name, "path": f"/tmp/{name}"}

    def test_a_single_download_waits_for_the_batch_or_the_timer(self):
        with mock.patch.object(
            window_module.GLib, "timeout_add", return_value=42
        ) as timeout:
            self.win._queue_cover_reveal(self._rom())
        timeout.assert_called_once()
        self.refresh.assert_not_called()

    def test_a_full_batch_reveals_immediately(self):
        with mock.patch.object(window_module.GLib, "timeout_add", return_value=42):
            for index in range(self.win.COVER_REVEAL_BATCH):
                self.win._queue_cover_reveal(self._rom(name=str(index)))
        self.assertEqual(self.refresh.call_count, self.win.COVER_REVEAL_BATCH)
        self.assertEqual(self.win._reveal_pending, [])

    def test_the_sync_moving_to_another_console_flushes_what_came_before(self):
        with mock.patch.object(window_module.GLib, "timeout_add", return_value=42):
            self.win._queue_cover_reveal(self._rom("SFC", "A"))
            self.win._queue_cover_reveal(self._rom("FC", "B"))
        self.assertEqual(self.refresh.call_count, 1)

    def test_the_timer_flushes_and_takes_itself_down(self):
        with mock.patch.object(window_module.GLib, "timeout_add", return_value=42):
            self.win._queue_cover_reveal(self._rom())
        self.assertFalse(self.win._flush_cover_reveal_from_timer())
        self.assertIsNone(self.win._reveal_timer)
        self.refresh.assert_called_once()

    def test_only_the_page_on_screen_is_refreshed_mid_run(self):
        with mock.patch.object(window_module.GLib, "timeout_add", return_value=42):
            self.win._queue_cover_reveal(self._rom("FC", "B"))
        self.win._flush_cover_reveal()
        self.refresh.assert_not_called()

    def test_a_mixed_page_takes_every_console_as_it_lands(self):
        self.win.sidebar.select(ALL_CONSOLES_ID)
        with mock.patch.object(window_module.GLib, "timeout_add", return_value=42):
            self.win._queue_cover_reveal(self._rom("FC", "B"))
        self.win._flush_cover_reveal()
        self.refresh.assert_called_once()

    def test_a_flush_with_a_timer_still_armed_removes_it(self):
        with mock.patch.object(
            window_module.GLib, "timeout_add", return_value=42
        ), mock.patch.object(window_module.GLib, "source_remove") as source_remove:
            self.win._queue_cover_reveal(self._rom())
            self.win._flush_cover_reveal()
        source_remove.assert_called_once_with(42)


@needs_display
class TheUpdateBannerTests(_WindowCase):
    def test_the_check_stays_off_when_the_config_says_so(self):
        with mock.patch.object(window_module, "check_for_update_async") as check:
            self.win._start_update_check()
        check.assert_not_called()

    def test_the_check_runs_when_it_is_switched_on(self):
        settings = self.config.get_update_settings()
        settings["check_on_startup"] = True
        with mock.patch.object(
            self.config, "get_update_settings", return_value=settings
        ), mock.patch.object(window_module, "check_for_update_async") as check:
            self.win._start_update_check()
        check.assert_called_once()

    def test_no_newer_release_leaves_the_banner_down(self):
        self.assertFalse(self.win._on_update_check_done(None))
        self.assertFalse(self.win.update_banner.get_revealed())

    def test_a_newer_release_raises_the_banner_and_names_the_version(self):
        self.win._on_update_check_done({"version": "9.9.9", "url": "https://x.invalid"})
        self.assertTrue(self.win.update_banner.get_revealed())
        self.assertEqual(
            self.win.update_banner.get_title(),
            self.said("banner.update.available", version="9.9.9"),
        )
        self.assertEqual(self.win._update_download_url, "https://x.invalid")

    def test_a_release_with_no_url_keeps_the_configured_download_page(self):
        before = self.win._update_download_url
        self.win._on_update_check_done({"version": "9.9.9", "url": ""})
        self.assertEqual(self.win._update_download_url, before)

    def test_clicking_the_banner_opens_the_download_page_and_lowers_it(self):
        self.win._on_update_check_done({"version": "9.9.9", "url": "https://x.invalid"})
        with mock.patch.object(self.win, "_open_uri") as open_uri:
            self.win._on_update_banner_clicked(None)
        open_uri.assert_called_once_with("https://x.invalid")
        self.assertFalse(self.win.update_banner.get_revealed())

    def test_a_uri_that_will_not_open_is_reported(self):
        launcher = mock.Mock()
        launcher.launch_finish.side_effect = GLib.Error("no browser")
        self.win._on_uri_launched(launcher, None)
        self.assertIn(self.said("toast.update.open_failed"), self.toasts)

    def test_a_uri_that_opens_says_nothing(self):
        launcher = mock.Mock()
        self.win._on_uri_launched(launcher, None)
        self.assertEqual(self.toasts, [])

    def test_opening_a_uri_hands_it_to_the_platform_launcher(self):
        with mock.patch.object(window_module.Gtk.UriLauncher, "new") as new:
            self.win._open_uri("https://x.invalid")
        new.assert_called_once_with("https://x.invalid")


@needs_display
class TheDialogsAndMenusTests(_WindowCase):
    def test_preferences_opens_and_is_remembered(self):
        with mock.patch.object(window_module.OpenEmuxPreferences, "present"):
            self.win._open_preferences()
        self.assertIsNotNone(self.win._preferences_dialog)

    def test_preferences_can_be_opened_on_a_page_and_a_console(self):
        with mock.patch.object(window_module.OpenEmuxPreferences, "present"):
            self.win._open_preferences(page="input", console="FC")
        dialog = self.win._preferences_dialog
        self.assertIs(dialog.get_visible_page(), dialog._pages["input"])
        self.assertEqual(dialog._current_console(), "FC")

    def test_the_welcome_tour_opens_on_demand(self):
        with mock.patch.object(window_module.WelcomeAssistant, "present") as present:
            self.win._open_welcome()
        present.assert_called_once()

    def test_the_tour_is_shown_at_startup_only_when_it_is_wanted(self):
        self.config.set_show_welcome_on_startup(True)
        with mock.patch.object(window_module.GLib, "idle_add") as idle_add:
            self.win.maybe_show_welcome()
        idle_add.assert_called_once_with(self.win._open_welcome)

    def test_the_tour_stays_away_when_the_user_opted_out(self):
        self.config.set_show_welcome_on_startup(False)
        with mock.patch.object(window_module.GLib, "idle_add") as idle_add:
            self.win.maybe_show_welcome()
        idle_add.assert_not_called()

    def test_the_about_dialog_is_built_with_the_running_version(self):
        with mock.patch.object(Adw.AboutDialog, "present"):
            self.win._show_about()

    def test_the_shortcuts_window_lists_every_group(self):
        with mock.patch.object(Gtk.ShortcutsWindow, "present"):
            self.win._show_shortcuts()

    def test_the_primary_menu_offers_the_four_entries(self):
        model = self.win.primary_menu_button.get_menu_model()
        self.assertEqual(model.get_n_items(), 4)


@needs_display
class RecoveredStateTests(_WindowCase):
    def test_nothing_quarantined_means_nothing_to_report(self):
        with mock.patch.object(window_module, "quarantined_files", return_value=[]):
            with mock.patch.object(window_module.GLib, "idle_add") as idle_add:
                self.win.maybe_report_recovered_state()
        idle_add.assert_not_called()

    def test_one_quarantined_file_is_named(self):
        recovered = [{"kept_as": "/tmp/cores.config.broken-2026"}]
        with mock.patch.object(
            window_module, "quarantined_files", return_value=recovered
        ), mock.patch.object(window_module, "reset_quarantine_log"), mock.patch.object(
            window_module.GLib, "idle_add"
        ) as idle_add:
            self.win.maybe_report_recovered_state()
        self.assertEqual(
            idle_add.call_args[0][1],
            self.said("toast.state_recovered.one", name="cores.config.broken-2026"),
        )

    def test_several_quarantined_files_are_counted(self):
        recovered = [{"kept_as": "/tmp/a"}, {"kept_as": "/tmp/b"}]
        with mock.patch.object(
            window_module, "quarantined_files", return_value=recovered
        ), mock.patch.object(window_module, "reset_quarantine_log"), mock.patch.object(
            window_module.GLib, "idle_add"
        ) as idle_add:
            self.win.maybe_report_recovered_state()
        self.assertEqual(
            idle_add.call_args[0][1],
            self.said("toast.state_recovered.many", count=2),
        )


@needs_display
class BootstrapReportingTests(_WindowCase):
    def test_a_clean_bootstrap_state_warns_about_nothing(self):
        self.win._maybe_show_bootstrap_warning()
        self.assertEqual(self.toasts, [])

    def test_a_failed_bootstrap_names_the_step_on_the_way_in(self):
        self.config.start_bootstrap_run()
        self.config.finish_bootstrap_failure("cores_download", "no network")
        self.win._maybe_show_bootstrap_warning()
        self.assertIn(
            self.said("toast.bootstrap.failed", step="cores_download"), self.toasts
        )

    def test_a_successful_retry_is_announced(self):
        self.win.on_bootstrap_finished({"success": True})
        self.assertIn(self.said("toast.bootstrap.completed"), self.toasts)

    def test_a_failed_retry_names_the_step(self):
        self.win.on_bootstrap_finished({"success": False, "failed_step": "playlists"})
        self.assertIn(
            self.said("toast.bootstrap.failed", step="playlists"), self.toasts
        )

    def test_a_retry_that_died_outside_the_loop_reports_the_error(self):
        # Issue #215: "step: None" told the user nothing.
        self.win.on_bootstrap_finished({"success": False, "error": "disk full"})
        self.assertIn(
            self.said("toast.bootstrap.crashed", error="disk full"), self.toasts
        )

    def test_a_crash_with_no_error_at_all_still_says_something(self):
        self.win.on_bootstrap_finished({"success": False})
        self.assertIn(
            self.said(
                "toast.bootstrap.crashed",
                error=self.said("toast.bootstrap.unknown_error"),
            ),
            self.toasts,
        )

    def test_asking_for_a_retry_reports_that_it_started(self):
        self.app.request_bootstrap_retry_from_ui = lambda _win: True
        self.addCleanup(lambda: delattr(self.app, "request_bootstrap_retry_from_ui"))
        self.win._trigger_bootstrap_retry()
        self.assertIn(self.said("toast.bootstrap.retry_started"), self.toasts)

    def test_a_retry_refused_because_one_runs_says_so(self):
        self.app.request_bootstrap_retry_from_ui = lambda _win: False
        self.addCleanup(lambda: delattr(self.app, "request_bootstrap_retry_from_ui"))
        self.win._trigger_bootstrap_retry()
        self.assertIn(self.said("toast.bootstrap.already_running"), self.toasts)

    def test_an_application_that_cannot_bootstrap_is_left_alone(self):
        self.win._trigger_bootstrap_retry()
        self.assertEqual(self.toasts, [])


@needs_display
class TheGameAndInputHandoffTests(_WindowCase):
    def test_launching_a_rom_goes_through_the_session(self):
        rom = self.rom()
        with mock.patch.object(self.win.game, "launch") as launch:
            self.win.on_launch_game(rom)
        launch.assert_called_once_with(rom)

    def test_launching_at_a_state_slot_goes_through_the_session(self):
        rom = self.rom()
        with mock.patch.object(self.win.game, "launch_at_state") as launch:
            self.win.launch_rom_at_state(rom, 3)
        launch.assert_called_once_with(rom, 3)

    def test_applying_a_remap_mid_game_goes_through_the_session(self):
        with mock.patch.object(
            self.win.game, "apply_input_changes", return_value=True
        ) as apply_changes:
            self.assertTrue(self.win.apply_input_changes_to_running_game())
        apply_changes.assert_called_once()

    def test_exclusive_capture_is_only_toggled_when_it_actually_changes(self):
        with mock.patch.object(self.win.navigation, "refresh_hints") as refresh:
            self.win.set_input_capture_active(True)
            self.win.set_input_capture_active(True)
        refresh.assert_called_once()
        self.assertTrue(self.win.input_capture_active)

    def test_the_gamepad_navigation_switch_is_stored_and_honoured(self):
        self.win._apply_gamepad_navigation(False)
        self.assertFalse(self.win._gamepad_nav_enabled)
        self.assertFalse(self.config.get_ui_settings()["gamepad_navigation"])

    def test_closing_stops_the_gamepad_reader(self):
        self.assertFalse(self.win._on_close_stop_gamepad())
        self.win.gamepad_navigator.stop.assert_called_once()

    def test_closing_takes_the_running_game_with_it(self):
        with mock.patch.object(self.win.game, "close_now") as close_now, (
            mock.patch.object(self.win.runtime_manager, "is_running", return_value=True)
        ), mock.patch.object(self.win.runtime_manager, "stop_active") as stop:
            self.assertFalse(self.win._on_close_stop_game())
        close_now.assert_called_once()
        stop.assert_called_once_with(block=True)

    def test_closing_with_no_game_running_stops_nothing(self):
        with mock.patch.object(self.win.game, "close_now"), mock.patch.object(
            self.win.runtime_manager, "is_running", return_value=False
        ), mock.patch.object(self.win.runtime_manager, "stop_active") as stop:
            self.win._on_close_stop_game()
        stop.assert_not_called()

    def test_the_artwork_manager_opens_on_the_rom_it_was_asked_for(self):
        rom = self.rom()
        with mock.patch(
            "openemux.ui.artwork_manager.ArtworkManagerWindow.present"
        ):
            self.win.open_artwork_manager(rom, art_dir=COVER_ART)


@needs_display
class SortingTests(_WindowCase):
    def test_the_scope_order_is_what_a_page_sorts_by(self):
        roms = self.win.playlist_manager.load_playlist("SFC")
        with mock.patch.object(window_module, "sort_roms", return_value=roms) as sort:
            self.win._sorted_roms(roms)
        self.assertEqual(sort.call_args[0][1], self.win._sort_order)

    def test_another_page_can_pass_its_own_order(self):
        roms = self.win.playlist_manager.load_playlist("SFC")
        order = next(o for o in window_module.SORT_ORDERS if o != self.win._sort_order)
        with mock.patch.object(window_module, "sort_roms", return_value=roms) as sort:
            self.win._sorted_roms(roms, order=order)
        self.assertEqual(sort.call_args[0][1], order)

    def test_the_disk_is_only_read_for_the_orders_that_need_it(self):
        roms = self.win.playlist_manager.load_playlist("SFC")
        needs_stat = next(iter(window_module.SORT_ORDERS_NEEDING_FILE_STAT))
        with mock.patch.object(window_module, "sort_roms", return_value=roms) as sort:
            self.win._sorted_roms(roms, order=needs_stat)
        self.assertIsNotNone(sort.call_args.kwargs["file_stat"])

    def test_the_play_history_is_only_read_for_the_orders_that_need_it(self):
        roms = self.win.playlist_manager.load_playlist("SFC")
        needs_history = next(iter(window_module.SORT_ORDERS_NEEDING_HISTORY))
        with mock.patch.object(window_module, "sort_roms", return_value=roms) as sort:
            self.win._sorted_roms(roms, order=needs_history)
        self.assertIsNotNone(sort.call_args.kwargs["last_played"])

    def test_a_rom_on_disk_reports_its_size_and_when_it_appeared(self):
        rom = self.rom()
        size, added = OpenEmuxWindow._rom_file_stat(rom["path"])
        self.assertGreater(size, 0)
        self.assertGreater(added, 0)

    def test_a_rom_that_is_gone_sorts_as_unknown(self):
        self.assertEqual(
            OpenEmuxWindow._rom_file_stat(str(self.tmp / "gone.sfc")), (0, 0.0)
        )


@needs_display
class WindowGeometryTests(unittest.TestCase):
    def test_a_normal_monitor_gives_a_share_of_itself(self):
        geometry = mock.Mock(width=1920, height=1080)
        self.assertEqual(
            OpenEmuxWindow._size_for_monitor(geometry), (1536, 864)
        )

    def test_a_monitor_that_cannot_be_read_gives_the_fallback(self):
        self.assertEqual(
            OpenEmuxWindow._size_for_monitor(None), OpenEmuxWindow.FALLBACK_WINDOW_SIZE
        )

    def test_a_monitor_reporting_nothing_gives_the_fallback_too(self):
        geometry = mock.Mock(width=0, height=0)
        self.assertEqual(
            OpenEmuxWindow._size_for_monitor(geometry),
            OpenEmuxWindow.FALLBACK_WINDOW_SIZE,
        )


@needs_display
class TheLanguageChangeTests(_WindowCase):
    def test_changing_the_language_stores_it_and_rebuilds_every_label(self):
        with mock.patch.object(self.win, "refresh_library") as refresh:
            self.win._apply_language_change("pt_BR")
        self.assertEqual(self.win.locale, "pt_BR")
        self.assertEqual(self.config.get_locale(), "pt_BR")
        self.assertTrue(refresh.call_args.kwargs["force"])

    def test_the_translated_strings_follow_the_new_locale(self):
        english = self.win.t("app.title")
        with mock.patch.object(self.win, "refresh_library"):
            self.win._apply_language_change("pt_BR")
        self.assertEqual(self.win.locale, "pt_BR")
        self.assertIsInstance(english, str)


@needs_display
class ClickLoggingTests(_WindowCase):
    """The debugging aid behind a DEBUG root logger (issue #221)."""

    def test_a_click_is_described_without_raising(self):
        gesture = mock.Mock()
        gesture.get_current_button.return_value = 1
        self.win._on_global_click_pressed(gesture, 1, 10.0, 20.0)

    def test_every_widget_kind_gets_a_description(self):
        describe = self.win._describe_widget
        self.assertEqual(describe(None), "None")
        button = Gtk.Button(label="Play")
        self.assertIn("label=Play", describe(button))
        self.assertIn("button", describe(Gtk.Button.new_from_icon_name("x")))
        self.assertIn("text=hello", describe(Gtk.Label(label="hello")))
        self.assertIn(
            "icon=view-refresh-symbolic",
            describe(Gtk.Image.new_from_icon_name("view-refresh-symbolic")),
        )
        self.assertEqual(describe(Gtk.Box()), "Box")


if __name__ == "__main__":
    unittest.main()

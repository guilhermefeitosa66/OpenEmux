"""The preferences dialog, driven the way the settings actually get changed.

`ui/preferences.py` is the largest module in the app and sat at 11%: 1225
statements, of which the suite executed the module-level `game_window_subtitle`
and little else. Everything a user changes about OpenEmux passes through here,
and every one of those changes is a signal handler that reads a widget and
writes the config -- so a stub cannot stand in for it. The dialog is built
against a real `ConfigManager` on a throwaway directory and a stand-in window
that only records what it was asked to do.

Nothing here reaches the network, the gamepad devices or a file picker: the
three collaborators that would (`retroachievements.login`, `make_capture_reader`
and `Gtk.FileDialog`) are replaced per test.
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    Adw.init()

    from openemux.core import retroachievements, rom_importer, save_backup
    from openemux.core.core_options import CoreOption
    from openemux.core.config import ConfigManager
    from openemux.core.input_actions import GLOBAL_HOTKEY_ACTIONS
    from openemux.core.shaders import ShaderCatalog
    from openemux.ui import preferences as prefs_module
    from openemux.ui.preferences import OpenEmuxPreferences, game_window_subtitle


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _CoreCatalog:
    """A catalog with one core for the SNES and nothing anywhere else.

    The empty consoles are the interesting half: the cores page has to say
    "none installed" rather than offer a picker with nothing in it.
    """

    def __init__(self, cores_by_console=None):
        self.cores_by_console = cores_by_console or {
            "SFC": [_Core("snes9x_libretro.so", "Snes9x")]
        }

    def cores_for_console(self, console_id):
        return list(self.cores_by_console.get(console_id, []))


class _RuntimeManager:
    def __init__(self, running=False, active_rom=None):
        self.running = running
        self.active_rom = active_rom

    def is_running(self):
        return self.running


class _Window:
    """Everything the dialog calls back into, recorded rather than done."""

    def __init__(self, config):
        self.config_manager = config
        self.locale = "en"
        self.current_console = "SFC"
        self.visible_consoles = ["SFC", "FC"]
        self.core_catalog = _CoreCatalog()
        self.shader_catalog = ShaderCatalog(runtime_dir=config.get_runtime_dir())
        self.runtime_manager = _RuntimeManager()
        self.calls = []
        self.capture_active = None

    def t(self, key, **kwargs):
        return key

    def set_input_capture_active(self, active):
        self.capture_active = active

    def __getattr__(self, name):
        # Every remaining collaborator is a notification the dialog sends and
        # never reads back, so one recorder covers all of them.
        if name.startswith("__"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _record


class _PreferencesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")
        self.config.set_roms_path(str(self.tmp / "roms"))
        self.win = _Window(self.config)
        self.prefs = OpenEmuxPreferences(self.win)

    def called(self, name):
        return [call for call in self.win.calls if call[0] == name]

    def toasts(self):
        """What the dialog said, in order."""
        return self.shown_toasts

    def setUpToastCapture(self):
        self.shown_toasts = []
        patcher = mock.patch.object(
            self.prefs, "_toast", lambda text, timeout=3: self.shown_toasts.append(text)
        )
        patcher.start()
        self.addCleanup(patcher.stop)


@needs_display
class TheDialogOpensOnEverythingItOwnsTests(_PreferencesCase):
    def test_all_six_pages_are_built(self):
        self.assertEqual(
            sorted(self.prefs._pages),
            ["bios", "cores", "input", "library", "system", "video"],
        )

    def test_a_named_page_can_be_opened_straight_away(self):
        self.prefs.show_page("input")
        self.assertIs(self.prefs.get_visible_page(), self.prefs._pages["input"])

    def test_an_unknown_page_name_leaves_the_dialog_where_it_was(self):
        before = self.prefs.get_visible_page()
        self.prefs.show_page("nonsense")
        self.assertIs(self.prefs.get_visible_page(), before)

    def test_closing_releases_the_gamepad_and_the_exclusive_capture(self):
        reader = mock.Mock()
        self.prefs._gamepad_reader = reader
        self.prefs._on_closed()
        reader.stop.assert_called_once()
        self.assertIsNone(self.prefs._gamepad_reader)
        self.assertFalse(self.win.capture_active)

    def test_a_toast_reaches_the_dialog(self):
        # The dialog carries its own toast overlay, so this is the one place
        # a message does not go through the window.
        self.prefs._toast("hello", timeout=1)


@needs_display
class TheLibraryPageTests(_PreferencesCase):
    def test_the_roms_row_shows_the_configured_folder(self):
        self.assertEqual(
            self.prefs._roms_path_row.get_subtitle(), str(self.config.get_roms_path())
        )

    def test_a_new_roms_folder_is_reflected_on_demand(self):
        self.config.set_roms_path(str(self.tmp / "elsewhere"))
        self.prefs.refresh_roms_path()
        self.assertEqual(
            self.prefs._roms_path_row.get_subtitle(), str(self.tmp / "elsewhere")
        )

    def test_switching_the_import_mode_to_link_is_stored(self):
        row = self.prefs._import_mode_row
        row.set_selected(self.prefs._import_modes.index(rom_importer.IMPORT_LINK))
        self.assertEqual(self.config.get_import_mode(), rom_importer.IMPORT_LINK)

    def test_an_out_of_range_import_selection_stores_nothing(self):
        before = self.config.get_import_mode()
        row = mock.Mock()
        row.get_selected.return_value = 99
        self.prefs._on_import_mode_changed(row)
        self.assertEqual(self.config.get_import_mode(), before)


@needs_display
class TheConsoleOrderRowsTests(_PreferencesCase):
    """Issue #386: the arrangement has to be reachable without dragging."""

    def rows(self):
        return [row.get_title() for row in self.prefs._console_order_rows]

    def test_the_consoles_with_games_are_listed(self):
        titles = self.rows()
        self.assertTrue(any(title.startswith("SFC") for title in titles))
        self.assertTrue(any(title.startswith("FC") for title in titles))

    def test_a_console_with_no_games_says_so_but_keeps_its_slot(self):
        self.config.set_console_order(["MD", "SFC", "FC"])
        self.prefs._rebuild_console_order_rows()
        by_console = {
            row.get_title().split(" - ")[0]: row for row in self.prefs._console_order_rows
        }
        self.assertIn("MD", by_console)
        self.assertEqual(
            by_console["MD"].get_subtitle(), "prefs.console_order.no_games"
        )
        self.assertEqual(by_console["SFC"].get_subtitle(), "")

    def test_moving_a_console_down_tells_the_window_the_new_order(self):
        before, _ = self.prefs._console_order_list()
        self.prefs._move_console(before[0], +1)
        order = self.called("reorder_consoles")[-1][1][0]
        self.assertEqual(order[:2], [before[1], before[0]])

    def test_moving_the_first_console_up_changes_nothing(self):
        first = self.prefs._console_order_list()[0][0]
        self.prefs._move_console(first, -1)
        self.assertEqual(self.called("reorder_consoles"), [])

    def test_restoring_clears_the_stored_order(self):
        self.config.set_console_order(["MD", "SFC"])
        self.prefs._restore_console_order()
        self.assertEqual(self.config.get_console_order(), [])
        self.assertEqual(self.called("reorder_consoles")[-1][1][0], [])

    def test_an_empty_library_with_no_stored_order_says_there_is_nothing(self):
        self.win.visible_consoles = []
        self.config.set_console_order([])
        self.prefs._rebuild_console_order_rows()
        self.assertEqual(len(self.prefs._console_order_rows), 1)
        self.assertEqual(
            self.prefs._console_order_rows[0].get_title(), "prefs.console_order.empty"
        )


@needs_display
class TheArtworkProviderRowsTests(_PreferencesCase):
    def test_every_configured_provider_gets_a_row(self):
        self.assertEqual(
            len(self.prefs._provider_rows), len(self.config.get_artwork_providers())
        )

    def test_moving_a_provider_up_reorders_the_stored_chain(self):
        before = [p["id"] for p in self.config.get_artwork_providers()]
        self.prefs._move_provider(1, -1)
        after = [p["id"] for p in self.config.get_artwork_providers()]
        self.assertEqual(after[:2], [before[1], before[0]])

    def test_moving_the_first_provider_up_is_a_no_op(self):
        before = [p["id"] for p in self.config.get_artwork_providers()]
        self.prefs._move_provider(0, -1)
        self.assertEqual([p["id"] for p in self.config.get_artwork_providers()], before)

    def test_moving_the_last_provider_down_is_a_no_op(self):
        providers = self.config.get_artwork_providers()
        self.prefs._move_provider(len(providers) - 1, +1)
        self.assertEqual(
            [p["id"] for p in self.config.get_artwork_providers()],
            [p["id"] for p in providers],
        )

    def test_disabling_a_provider_is_stored(self):
        provider_id = self.config.get_artwork_providers()[0]["id"]
        self.prefs._set_provider_enabled(provider_id, False)
        stored = {p["id"]: p for p in self.config.get_artwork_providers()}
        self.assertFalse(stored[provider_id]["enabled"])


@needs_display
class TheScreenScraperAccountTests(_PreferencesCase):
    def _set_screenscraper(self, enabled):
        providers = self.config.get_artwork_providers()
        for entry in providers:
            if entry["id"] == "screenscraper":
                entry["enabled"] = enabled
        self.config.set_artwork_providers(providers)
        self.prefs._update_screenscraper_rows_visibility()

    def test_typing_a_username_stores_it_as_it_is_typed(self):
        self.prefs._ss_user_row.set_text("player1")
        self.assertEqual(
            self.config.get_cover_sync_settings()["screenscraper_user"], "player1"
        )

    def test_the_password_is_stored_too(self):
        self.prefs._ss_password_row.set_text("hunter2")
        self.assertEqual(
            self.config.get_cover_sync_settings()["screenscraper_password"], "hunter2"
        )

    def test_the_developer_credential_lives_behind_the_advanced_expander(self):
        self.assertFalse(self.prefs._ss_advanced_row.get_expanded())
        self.prefs._ss_devid_row.set_text("devid")
        self.prefs._ss_devpassword_row.set_text("devpass")
        settings = self.config.get_cover_sync_settings()
        self.assertEqual(settings["screenscraper_devid"], "devid")
        self.assertEqual(settings["screenscraper_devpassword"], "devpass")

    def test_the_account_rows_go_away_when_the_provider_is_off(self):
        self._set_screenscraper(False)
        self.assertFalse(self.prefs._ss_user_row.get_visible())
        self.assertFalse(self.prefs._ss_advanced_row.get_visible())
        self.assertFalse(self.prefs._ss_hint_row.get_visible())
        self.assertFalse(self.prefs._ss_embedded_hint_row.get_visible())

    def test_a_build_with_no_embedded_credential_asks_for_one(self):
        self.prefs._ss_embedded = False
        self._set_screenscraper(True)
        self.assertTrue(self.prefs._ss_hint_row.get_visible())
        self.assertFalse(self.prefs._ss_embedded_hint_row.get_visible())

    def test_an_official_build_says_it_is_ready_to_use_instead(self):
        self.prefs._ss_embedded = True
        self._set_screenscraper(True)
        self.assertFalse(self.prefs._ss_hint_row.get_visible())
        self.assertTrue(self.prefs._ss_embedded_hint_row.get_visible())


@needs_display
class TheBiosPageTests(_PreferencesCase):
    def test_a_console_with_requirements_gets_an_expander_with_a_tally(self):
        rows = self.prefs._bios_rows
        self.assertTrue(rows)
        titles = [row.get_title() for row in rows]
        self.assertTrue(any("—" in title for title in titles))
        self.assertRegex(rows[0].get_subtitle(), r"^\d+/\d+$")

    def test_reloading_says_so_when_the_user_asked_for_it(self):
        self.setUpToastCapture()
        self.prefs._reload_bios(show_toast=True)
        self.assertEqual(self.toasts(), ["bios.reloaded"])

    def test_reloading_on_open_says_nothing(self):
        self.setUpToastCapture()
        self.prefs._reload_bios(show_toast=False)
        self.assertEqual(self.toasts(), [])

    def test_a_library_with_no_bios_requirements_says_so(self):
        with mock.patch.object(prefs_module, "scan_all_bios_status", return_value={}):
            self.prefs._reload_bios()
        self.assertEqual(len(self.prefs._bios_rows), 1)
        self.assertEqual(self.prefs._bios_rows[0].get_title(), "bios.no_requirements")


def _console_box(root):
    """The box the console factory built, wherever GTK parented it."""
    stack = [root]
    while stack:
        widget = stack.pop()
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) and " — " in child.get_label():
                return child.get_parent()
            stack.append(child)
            child = child.get_next_sibling()
    raise AssertionError("the console factory never ran")


@needs_display
class TheComboIconFactoriesTests(_PreferencesCase):
    """The list factories only run when GTK binds a real `Gtk.ListItem`.

    There is no way to build one by hand, so the factory is driven through a
    live `Gtk.ListView` -- which is what caught the closed-state factory
    resolving a device by list position in the first place.
    """

    def _bound_rows(self, combo_row, strings):
        view = Gtk.ListView(
            model=Gtk.SingleSelection(model=Gtk.StringList.new(strings)),
            factory=combo_row.get_factory(),
        )
        window = Gtk.Window()
        self.addCleanup(window.destroy)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(view)
        window.set_child(scroller)
        window.set_default_size(320, 320)
        window.present()
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        rows = []
        row = view.get_first_child()
        while row is not None:
            rows.append(row.get_first_child())
            row = row.get_next_sibling()
        return rows

    def test_a_console_row_shows_its_icon_and_its_full_name(self):
        boxes = self._bound_rows(self.prefs._console_combo, ["SFC", "FC"])
        labels = [box.get_last_child().get_label() for box in boxes]
        self.assertTrue(labels[0].startswith("SFC — "))
        self.assertTrue(labels[1].startswith("FC — "))

    def test_the_device_rows_are_resolved_by_label_not_by_position(self):
        # Issue behind the comment in _apply_device_icon_factory: the
        # closed-state factory has no valid list position to read.
        boxes = self._bound_rows(
            self.prefs._device_combo,
            ["input.device.gamepad_p1", "input.device.keyboard"],
        )
        icons = [box.get_first_child().get_icon_name() for box in boxes]
        self.assertEqual(
            icons, ["input-gaming-symbolic", "input-keyboard-symbolic"]
        )

    def _closed_state_box(self, combo_row, strings, selections):
        """The widget the closed row shows, after each of ``selections``.

        A `Gtk.DropDown` binds one list item for its closed state and rebinds
        that same widget whenever the selection changes, which is the only way
        to reach the rebind from a test.
        """
        drop = Gtk.DropDown(
            model=Gtk.StringList.new(strings), factory=combo_row.get_factory()
        )
        window = Gtk.Window()
        self.addCleanup(window.destroy)
        window.set_child(drop)
        window.present()
        context = GLib.MainContext.default()
        for index in selections:
            drop.set_selected(index)
            while context.pending():
                context.iteration(False)
        return _console_box(drop)

    def test_the_closed_row_is_rebuilt_on_every_change_not_appended_to(self):
        # GTK rebinds the same widget, so without the clear the row would grow
        # an icon and a label for every console ever selected.
        box = self._closed_state_box(
            self.prefs._console_combo, ["SFC", "FC", "MD"], [0, 1, 2]
        )
        children = []
        child = box.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        self.assertEqual(len(children), 2)
        self.assertTrue(children[-1].get_label().startswith("MD — "))

    def test_a_label_no_device_claims_falls_back_to_the_keyboard(self):
        boxes = self._bound_rows(self.prefs._device_combo, ["something else"])
        self.assertEqual(
            boxes[0].get_first_child().get_icon_name(), "input-keyboard-symbolic"
        )


@needs_display
class TheInputPageSelectorsTests(_PreferencesCase):
    def test_the_page_opens_on_the_console_the_library_is_showing(self):
        self.assertEqual(self.prefs._current_console(), "SFC")

    def test_the_page_can_be_pointed_at_another_console(self):
        self.prefs.select_input_console("FC")
        self.assertEqual(self.prefs._current_console(), "FC")

    def test_a_console_the_app_does_not_know_is_ignored(self):
        self.prefs.select_input_console("NOT-A-CONSOLE")
        self.assertEqual(self.prefs._current_console(), "SFC")

    def test_a_window_showing_no_console_falls_back_to_the_first(self):
        self.win.current_console = None
        prefs = OpenEmuxPreferences(self.win)
        self.assertEqual(prefs._current_console(), prefs._console_ids[0])

    def test_an_impossible_combo_index_falls_back_rather_than_raising(self):
        with mock.patch.object(
            self.prefs._console_combo, "get_selected", return_value=9999
        ):
            self.assertEqual(self.prefs._current_console(), self.prefs._console_ids[0])
        with mock.patch.object(
            self.prefs._device_combo, "get_selected", return_value=9999
        ):
            self.assertEqual(self.prefs._current_device(), "keyboard")

    def test_the_keyboard_is_the_device_being_edited_by_default(self):
        self.assertEqual(self.prefs._current_device(), "keyboard")

    def test_switching_console_rebuilds_the_binding_rows(self):
        self.prefs._console_combo.set_selected(self.prefs._console_ids.index("GB"))
        self.assertEqual(self.prefs._current_console(), "GB")
        self.assertTrue(self.prefs._input_rows)

    def test_the_extra_port_switch_only_appears_for_ports_two_to_four(self):
        self.assertFalse(self.prefs._port_enabled_switch.get_visible())
        self.prefs._device_combo.set_selected(
            self.prefs._device_ids.index("gamepad_p2")
        )
        self.assertTrue(self.prefs._port_enabled_switch.get_visible())

    def test_ports_two_to_four_map_no_global_hotkeys(self):
        # RetroArch treats the hotkeys as global, so offering them per port
        # would promise something the launcher cannot deliver.
        self.prefs._device_combo.set_selected(
            self.prefs._device_ids.index("gamepad_p2")
        )
        self.assertFalse(
            set(self.prefs._input_rows) & set(GLOBAL_HOTKEY_ACTIONS)
        )
        self.assertFalse(self.prefs._system_bindings_group.get_visible())

    def test_a_device_missing_from_the_profile_falls_back_to_the_keyboard(self):
        # A profile written before ports 2-4 existed has no pad entry at all,
        # and the page must not then offer to edit a device that is not there.
        stripped = self.config.get_input_profile("SFC")
        stripped["devices"].pop("gamepad_p1", None)
        with mock.patch.object(
            self.config, "get_input_profile", return_value=stripped
        ), mock.patch.object(
            self.prefs, "_current_device", return_value="gamepad_p1"
        ), mock.patch.object(
            self.prefs._device_combo, "set_selected"
        ) as set_selected:
            self.prefs._refresh_bindings()
        set_selected.assert_called_once_with(0)


@needs_display
class TheTuningAndTurboRowsTests(_PreferencesCase):
    def test_a_deadzone_change_is_stored(self):
        self.prefs._tuning_rows["analog_deadzone"].set_value(0.35)
        self.assertAlmostEqual(
            self.config.get_input_tuning_value("analog_deadzone"), 0.35, places=2
        )

    def test_the_rows_do_not_write_while_they_are_being_populated(self):
        # _tuning_guard is up during the build; without it, setting each row's
        # initial value would write the defaults straight back to disk.
        before = self.config.get_input_tuning_value("analog_deadzone")
        self.prefs._tuning_guard = True
        self.prefs._tuning_rows["analog_deadzone"].set_value(0.9)
        self.prefs._tuning_guard = False
        self.assertEqual(
            self.config.get_input_tuning_value("analog_deadzone"), before
        )

    def test_the_poll_behaviour_is_stored_by_index(self):
        other = (self.prefs._poll_row.get_selected() + 1) % 3
        self.prefs._poll_row.set_selected(other)
        self.assertEqual(
            self.config.get_input_tuning_value("poll_type_behavior"), other
        )

    def test_the_auto_focus_choice_is_stored_by_index(self):
        self.prefs._focus_row.set_selected(1)
        self.assertEqual(self.config.get_input_tuning_value("auto_game_focus"), 1)

    def test_the_descriptor_switch_is_stored(self):
        row = self.prefs._descriptor_row
        row.set_active(not row.get_active())
        self.assertEqual(
            bool(self.config.get_input_tuning_value("descriptor_label_show")),
            row.get_active(),
        )

    def test_the_guarded_rows_write_nothing_while_the_guard_is_up(self):
        self.prefs._tuning_guard = True
        before = dict(
            poll=self.config.get_input_tuning_value("poll_type_behavior"),
            focus=self.config.get_input_tuning_value("auto_game_focus"),
            descriptor=self.config.get_input_tuning_value("descriptor_label_show"),
        )
        self.prefs._on_poll_type_changed()
        self.prefs._on_auto_focus_changed()
        self.prefs._on_descriptor_changed()
        self.assertEqual(
            self.config.get_input_tuning_value("poll_type_behavior"), before["poll"]
        )
        self.assertEqual(
            self.config.get_input_tuning_value("auto_game_focus"), before["focus"]
        )

    def test_a_turbo_period_change_is_stored_for_the_shown_console(self):
        self.prefs._turbo_period_row.set_value(12)
        stored = self.config.input_profiles.get_turbo_settings("SFC")
        self.assertEqual(stored["period"], 12)

    def test_the_turbo_mode_is_stored_by_id_not_by_position(self):
        mode = self.prefs._turbo_mode_ids[-1]
        self.prefs._turbo_mode_row.set_selected(len(self.prefs._turbo_mode_ids) - 1)
        self.assertEqual(
            self.config.input_profiles.get_turbo_settings("SFC")["mode"], mode
        )

    def test_the_turbo_rows_write_nothing_while_they_are_being_synced(self):
        self.prefs._turbo_guard = True
        before = self.config.input_profiles.get_turbo_settings("SFC")
        self.prefs._turbo_period_row.set_value(30)
        self.prefs._turbo_guard = False
        self.assertEqual(
            self.config.input_profiles.get_turbo_settings("SFC"), before
        )


@needs_display
class TheAnalogRowsTests(_PreferencesCase):
    def test_the_analog_dpad_mode_is_stored_by_id(self):
        mode = self.prefs._analog_dpad_ids[-1]
        self.prefs._analog_dpad_row.set_selected(len(self.prefs._analog_dpad_ids) - 1)
        self.assertEqual(
            self.config.input_profiles.get_analog_dpad_mode("SFC"), mode
        )

    def test_the_analog_row_writes_nothing_while_it_is_being_synced(self):
        before = self.config.input_profiles.get_analog_dpad_mode("SFC")
        self.prefs._analog_dpad_guard = True
        self.prefs._analog_dpad_row.set_selected(1)
        self.prefs._analog_dpad_guard = False
        self.assertEqual(
            self.config.input_profiles.get_analog_dpad_mode("SFC"), before
        )

    def test_a_console_whose_core_reads_a_stick_offers_the_dpad_row(self):
        self.prefs.select_input_console("PS")
        self.assertTrue(self.prefs._dpad_analog_row.get_visible())

    def test_a_console_with_no_stick_hides_it(self):
        # Nothing for the D-pad to stand in for on a Famicom.
        self.prefs.select_input_console("FC")
        self.assertFalse(self.prefs._dpad_analog_row.get_visible())

    def test_turning_the_dpad_into_a_stick_is_stored(self):
        self.prefs.select_input_console("PS")
        self.prefs._dpad_analog_row.set_active(True)
        self.assertTrue(self.config.input_profiles.get_dpad_drives_analog("PS"))

    def test_the_dpad_row_writes_nothing_while_it_is_being_synced(self):
        self.prefs.select_input_console("PS")
        before = self.config.input_profiles.get_dpad_drives_analog("PS")
        self.prefs._dpad_analog_guard = True
        self.prefs._dpad_analog_row.set_active(not before)
        self.prefs._dpad_analog_guard = False
        self.assertEqual(
            self.config.input_profiles.get_dpad_drives_analog("PS"), before
        )


@needs_display
class TheControllerTypeRowTests(_PreferencesCase):
    def _console_with_types(self):
        from openemux.core.input_profiles import controller_types_for
        from openemux.core.systems import SYSTEM_IDS

        for console_id in SYSTEM_IDS:
            if controller_types_for(console_id):
                return console_id
        return None

    def test_a_console_whose_core_publishes_one_type_hides_the_row(self):
        from openemux.core.input_profiles import controller_types_for

        for console_id in self.prefs._console_ids:
            if not controller_types_for(console_id):
                self.prefs.select_input_console(console_id)
                self.assertFalse(self.prefs._controller_type_row.get_visible())
                self.assertEqual(self.prefs._controller_type_ids, [])
                return
        self.skipTest("every console publishes more than one controller type")

    def test_a_console_with_several_types_offers_core_default_first(self):
        console_id = self._console_with_types()
        if console_id is None:
            self.skipTest("no console publishes more than one controller type")
        self.prefs.select_input_console(console_id)
        self.assertTrue(self.prefs._controller_type_row.get_visible())
        self.assertIsNone(self.prefs._controller_type_ids[0])

    def test_choosing_a_type_is_stored(self):
        console_id = self._console_with_types()
        if console_id is None:
            self.skipTest("no console publishes more than one controller type")
        self.prefs.select_input_console(console_id)
        self.prefs._controller_type_row.set_selected(1)
        self.assertEqual(
            self.config.input_profiles.get_controller_type(console_id),
            self.prefs._controller_type_ids[1],
        )

    def test_the_row_writes_nothing_while_it_is_being_synced(self):
        console_id = self._console_with_types()
        if console_id is None:
            self.skipTest("no console publishes more than one controller type")
        self.prefs.select_input_console(console_id)
        before = self.config.input_profiles.get_controller_type(console_id)
        self.prefs._controller_type_guard = True
        self.prefs._on_controller_type_changed()
        self.prefs._controller_type_guard = False
        self.assertEqual(
            self.config.input_profiles.get_controller_type(console_id), before
        )

    def test_an_impossible_index_stores_nothing(self):
        console_id = self._console_with_types()
        if console_id is None:
            self.skipTest("no console publishes more than one controller type")
        self.prefs.select_input_console(console_id)
        before = self.config.input_profiles.get_controller_type(console_id)
        with mock.patch.object(
            self.prefs._controller_type_row, "get_selected", return_value=999
        ):
            self.prefs._on_controller_type_changed()
        self.assertEqual(
            self.config.input_profiles.get_controller_type(console_id), before
        )


@needs_display
class BindingLabelsTests(_PreferencesCase):
    def test_an_unbound_action_reads_as_empty(self):
        self.assertEqual(self.prefs._binding_display(""), "input.binding.empty")

    def test_a_keyboard_binding_is_shown_as_typed(self):
        self.assertEqual(self.prefs._binding_display("x"), "x")

    def test_a_gamepad_button_token_is_translated(self):
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        self.assertEqual(self.prefs._binding_display("3"), "input.binding.button")

    def test_a_gamepad_axis_token_is_translated(self):
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        self.assertEqual(self.prefs._binding_display("+2"), "input.binding.axis")

    def test_a_gamepad_hat_token_is_translated(self):
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        self.assertEqual(self.prefs._binding_display("h0up"), "input.binding.hat")

    def test_a_token_nothing_recognises_is_shown_raw(self):
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        self.assertEqual(self.prefs._binding_display("weird"), "weird")

    def test_only_the_hotkey_gate_carries_an_extra_explanation(self):
        self.assertEqual(
            self.prefs._input_action_subtitle("enable_hotkey"),
            "input.action.enable_hotkey.subtitle",
        )
        self.assertIsNone(self.prefs._input_action_subtitle("a"))

    def test_hotkeys_land_in_the_system_group_and_controls_in_the_game_one(self):
        self.assertIs(
            self.prefs._group_for_action("save_state"),
            self.prefs._system_bindings_group,
        )
        self.assertIs(self.prefs._group_for_action("a"), self.prefs._bindings_group)


@needs_display
class TheCapturePromptTests(_PreferencesCase):
    def system_default(self):
        return "prefs.group.bindings.system.description"

    def test_capturing_a_control_prompts_on_the_game_group(self):
        self.prefs._set_capture_prompt("press a key", "a")
        self.assertEqual(self.prefs._bindings_group.get_description(), "press a key")
        self.assertEqual(
            self.prefs._system_bindings_group.get_description(), self.system_default()
        )

    def test_capturing_a_hotkey_prompts_on_the_system_group(self):
        self.prefs._set_capture_prompt("press a key", "save_state")
        self.assertFalse(self.prefs._bindings_group.get_description())
        self.assertEqual(
            self.prefs._system_bindings_group.get_description(), "press a key"
        )

    def test_clearing_the_prompt_restores_the_standing_description(self):
        self.prefs._set_capture_prompt("press a key", "a")
        self.prefs._set_capture_prompt(None)
        self.assertFalse(self.prefs._bindings_group.get_description())
        self.assertEqual(
            self.prefs._system_bindings_group.get_description(), self.system_default()
        )

    def test_the_row_being_captured_is_the_only_one_marked(self):
        self.prefs._set_active_row("a")
        self.assertTrue(
            self.prefs._input_rows["a"].has_css_class("input-mapping-current")
        )
        self.assertFalse(
            self.prefs._input_rows["b"].has_css_class("input-mapping-current")
        )
        self.prefs._set_active_row(None)
        self.assertFalse(
            self.prefs._input_rows["a"].has_css_class("input-mapping-current")
        )


@needs_display
class KeyboardCaptureTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def press(self, keyval):
        return self.prefs._on_key_pressed(None, keyval, 0, 0)

    def test_a_keystroke_outside_a_capture_is_left_to_the_dialog(self):
        self.assertFalse(self.press(Gdk.KEY_x))

    def test_clicking_a_row_starts_listening_and_says_so(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertTrue(self.prefs._capture.capturing)
        self.assertEqual(
            self.prefs._input_buttons["a"].get_label(), "input.capture.waiting"
        )
        self.assertTrue(self.win.capture_active)

    def test_clicking_a_row_that_is_not_shown_starts_nothing(self):
        self.prefs._start_capture("not-an-action", sequence_mode=False)
        self.assertFalse(self.prefs._capture.capturing)

    def test_a_captured_key_is_stored_as_a_retroarch_token(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertTrue(self.press(Gdk.KEY_equal))
        self.assertEqual(self.prefs._capture.binding_for("a"), "equals")
        self.assertFalse(self.prefs._capture.capturing)

    def test_escape_clears_the_binding_being_captured(self):
        self.prefs._set_binding("a", "x")
        self.prefs._on_binding_clicked(None, "a")
        self.assertTrue(self.press(Gdk.KEY_Escape))
        self.assertEqual(self.prefs._capture.binding_for("a"), "")
        self.assertFalse(self.prefs._capture.capturing)

    def test_a_value_arriving_with_no_capture_running_is_dropped(self):
        # The gamepad reader can report a press after the capture ended; the
        # session says so by returning no outcome at all.
        before = dict(self.prefs._capture.bindings)
        self.prefs._commit_capture("q")
        self.assertEqual(self.prefs._capture.bindings, before)

    def test_a_key_with_no_name_is_swallowed_rather_than_stored(self):
        self.prefs._on_binding_clicked(None, "a")
        with mock.patch.object(Gdk, "keyval_name", return_value=None):
            self.assertTrue(self.press(0))
        self.assertTrue(self.prefs._capture.capturing)

    def test_a_key_pressed_during_a_gamepad_capture_is_swallowed(self):
        # A stray keystroke must never be stored as a controller token.
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        with mock.patch.object(self.prefs, "_start_gamepad_reader"):
            self.prefs._on_binding_clicked(None, "a")
        before = self.prefs._capture.binding_for("a")
        self.assertTrue(self.press(Gdk.KEY_x))
        self.assertEqual(self.prefs._capture.binding_for("a"), before)
        self.assertTrue(self.prefs._capture.capturing)

    def test_taking_a_key_from_another_action_says_what_it_took(self):
        self.prefs._set_binding("a", "z")
        self.prefs._on_binding_clicked(None, "b")
        self.press(Gdk.KEY_z)
        self.assertEqual(self.prefs._capture.binding_for("a"), "")
        self.assertEqual(
            self.prefs._input_buttons["a"].get_label(), "input.binding.empty"
        )
        self.assertIn("toast.input_released", self.toasts())

    def test_cancelling_puts_the_previous_label_back(self):
        self.prefs._set_binding("a", "z")
        self.prefs._on_binding_clicked(None, "a")
        self.prefs._cancel_capture()
        self.assertEqual(self.prefs._input_buttons["a"].get_label(), "z")
        self.assertFalse(self.win.capture_active)


@needs_display
class MapAllTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_map_all_starts_on_the_first_required_action(self):
        self.prefs._start_map_all()
        self.assertTrue(self.prefs._capture.sequence_mode)
        self.assertIsNotNone(self.prefs._capture.active_action)

    def test_each_press_advances_to_the_next_action(self):
        self.prefs._start_map_all()
        first = self.prefs._capture.active_action
        self.prefs._on_key_pressed(None, Gdk.KEY_q, 0, 0)
        self.assertEqual(self.prefs._capture.binding_for(first), "q")
        self.assertNotEqual(self.prefs._capture.active_action, first)

    def test_escape_abandons_the_whole_sequence_and_says_so(self):
        self.prefs._start_map_all()
        self.prefs._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
        self.assertFalse(self.prefs._capture.capturing)
        self.assertEqual(self.toasts(), ["input.capture.cancelled"])

    def test_a_sequence_that_runs_to_the_end_reports_completion(self):
        self.prefs._start_map_all()
        keys = iter(
            [Gdk.KEY_a, Gdk.KEY_b, Gdk.KEY_c, Gdk.KEY_d, Gdk.KEY_e, Gdk.KEY_f]
        )
        guard = 0
        while self.prefs._capture.capturing and guard < 200:
            guard += 1
            try:
                keyval = next(keys)
            except StopIteration:
                keys = iter(
                    [Gdk.KEY_a, Gdk.KEY_b, Gdk.KEY_c, Gdk.KEY_d, Gdk.KEY_e, Gdk.KEY_f]
                )
                keyval = next(keys)
            self.prefs._on_key_pressed(None, keyval, 0, 0)
        self.assertIn("input.capture.completed", self.toasts())

    def test_a_release_during_map_all_is_not_announced_one_toast_at_a_time(self):
        # One toast per button would be noise; the sequence says its piece at
        # the end instead.
        self.prefs._start_map_all()
        self.prefs._on_key_pressed(None, Gdk.KEY_q, 0, 0)
        self.prefs._on_key_pressed(None, Gdk.KEY_q, 0, 0)
        self.assertNotIn("toast.input_released", self.toasts())

    def test_map_all_with_nothing_to_map_starts_no_capture(self):
        with mock.patch.object(
            self.prefs._capture, "begin_sequence", return_value=None
        ):
            self.prefs._start_map_all()
        self.assertFalse(self.prefs._capture.capturing)


@needs_display
class TheGamepadReaderTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()
        self.prefs._device_combo.set_selected(self.prefs._device_ids.index("gamepad_p1"))
        self.reader = mock.Mock()
        patcher = mock.patch.object(
            prefs_module, "make_capture_reader", return_value=self.reader
        )
        self.make_reader = patcher.start()
        self.addCleanup(patcher.stop)

    def test_capturing_a_pad_binding_starts_a_reader(self):
        self.prefs._on_binding_clicked(None, "a")
        self.reader.start.assert_called_once()
        self.assertEqual(
            self.prefs._input_buttons["a"].get_label(), "input.capture.waiting_gamepad"
        )

    def test_port_one_lets_the_reader_pick_the_device(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertIsNone(self.make_reader.call_args.kwargs["device"])

    def test_a_later_port_listens_on_its_own_pad(self):
        self.prefs._device_combo.set_selected(
            self.prefs._device_ids.index("gamepad_p2")
        )
        with mock.patch.object(
            prefs_module, "list_gamepads", return_value=["pad0", "pad1"]
        ):
            self.prefs._on_binding_clicked(None, "a")
        self.assertEqual(self.make_reader.call_args.kwargs["device"], "pad1")

    def test_a_port_with_no_pad_plugged_in_says_so_and_captures_nothing(self):
        self.prefs._device_combo.set_selected(
            self.prefs._device_ids.index("gamepad_p2")
        )
        with mock.patch.object(prefs_module, "list_gamepads", return_value=["pad0"]):
            self.prefs._on_binding_clicked(None, "a")
        self.assertEqual(self.toasts(), ["input.capture.port_unavailable"])
        self.assertFalse(self.prefs._capture.capturing)

    def test_a_token_from_the_pad_is_stored(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertFalse(self.prefs._on_gamepad_token("3"))
        self.assertEqual(self.prefs._capture.binding_for("a"), "3")

    def test_a_token_arriving_after_the_capture_ended_is_dropped(self):
        before = self.prefs._capture.binding_for("a")
        self.assertFalse(self.prefs._on_gamepad_token("99"))
        self.assertEqual(self.prefs._capture.binding_for("a"), before)

    def test_a_token_arriving_after_a_switch_to_the_keyboard_is_dropped(self):
        self.prefs._on_binding_clicked(None, "a")
        self.prefs._device_combo.set_selected(0)
        self.assertFalse(self.prefs._on_gamepad_token("3"))

    def test_a_reader_that_cannot_open_the_device_says_which_problem_it_hit(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertFalse(self.prefs._on_gamepad_error("permission_denied"))
        self.assertEqual(self.toasts(), ["input.capture.permission_denied"])
        self.assertFalse(self.prefs._capture.capturing)

    def test_any_other_reader_failure_reports_no_gamepad(self):
        self.prefs._on_binding_clicked(None, "a")
        self.assertFalse(self.prefs._on_gamepad_error("gone"))
        self.assertEqual(self.toasts(), ["input.capture.no_gamepad"])

    def test_an_error_arriving_after_the_capture_ended_is_dropped(self):
        self.assertFalse(self.prefs._on_gamepad_error("gone"))
        self.assertEqual(self.toasts(), [])

    def test_stopping_the_reader_twice_is_harmless(self):
        self.prefs._on_binding_clicked(None, "a")
        self.prefs._stop_gamepad_reader()
        self.prefs._stop_gamepad_reader()
        self.reader.stop.assert_called_once()


@needs_display
class SavingAndResettingInputTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_saving_writes_the_edited_bindings_to_the_profile(self):
        self.prefs._set_binding("a", "j")
        self.prefs._save_input()
        stored = self.config.get_input_profile("SFC")
        self.assertEqual(stored["devices"]["keyboard"]["bindings"]["a"], "j")
        self.assertEqual(self.toasts(), ["toast.input_saved"])

    def test_saving_the_keyboard_makes_it_the_active_device(self):
        self.prefs._save_input()
        self.assertEqual(self.config.get_input_profile("SFC")["active_device"], "keyboard")

    def test_saving_a_later_port_records_whether_it_is_switched_on(self):
        self.prefs._device_combo.set_selected(
            self.prefs._device_ids.index("gamepad_p2")
        )
        self.prefs._port_enabled_switch.set_active(True)
        self.prefs._save_input()
        device = self.config.get_input_profile("SFC")["devices"]["gamepad_p2"]
        self.assertTrue(device["enabled"])
        self.assertNotEqual(
            self.config.get_input_profile("SFC").get("active_device"), "gamepad_p2"
        )

    def test_saving_reads_the_profile_back_rather_than_a_stale_snapshot(self):
        # Issue #126: the analog and turbo rows write straight to disk, so a
        # save from the snapshot taken at build time reverted them.
        mode = self.prefs._analog_dpad_ids[-1]
        self.config.input_profiles.set_analog_dpad_mode("SFC", mode)
        self.prefs._save_input()
        self.assertEqual(self.config.input_profiles.get_analog_dpad_mode("SFC"), mode)

    def test_resetting_restores_the_defaults_and_says_so(self):
        self.prefs._set_binding("a", "j")
        self.prefs._save_input()
        self.prefs._reset_defaults()
        stored = self.config.get_input_profile("SFC")
        self.assertNotEqual(stored["devices"]["keyboard"]["bindings"]["a"], "j")
        self.assertIn("toast.input_reset", self.toasts())

    def test_a_save_with_no_game_running_relaunches_nothing(self):
        self.prefs._save_input()
        self.assertEqual(self.called("apply_input_changes_to_running_game"), [])

    def test_a_save_for_the_running_console_reaches_the_running_game(self):
        self.win.runtime_manager = _RuntimeManager(
            running=True, active_rom={"console": "SFC"}
        )
        self.prefs._save_input()
        self.assertEqual(len(self.called("apply_input_changes_to_running_game")), 1)

    def test_a_save_for_another_console_leaves_the_running_game_alone(self):
        self.win.runtime_manager = _RuntimeManager(
            running=True, active_rom={"console": "GB"}
        )
        self.prefs._save_input()
        self.assertEqual(self.called("apply_input_changes_to_running_game"), [])

    def test_a_running_game_with_no_rom_on_record_is_left_alone(self):
        self.win.runtime_manager = _RuntimeManager(running=True, active_rom=None)
        self.prefs._save_input()
        self.assertEqual(self.called("apply_input_changes_to_running_game"), [])


@needs_display
class TheRelaunchBannerTests(_PreferencesCase):
    def test_the_banner_stays_down_while_nothing_is_running(self):
        self.assertFalse(self.prefs._relaunch_banner.get_revealed())

    def test_the_banner_comes_up_once_a_game_is_running(self):
        self.win.runtime_manager.running = True
        self.prefs._sync_relaunch_banner()
        self.assertTrue(self.prefs._relaunch_banner.get_revealed())

    def test_the_apply_button_relaunches_and_schedules_a_recheck(self):
        with mock.patch.object(prefs_module.GLib, "timeout_add_seconds") as timeout:
            self.prefs._on_relaunch_clicked(None)
        self.assertEqual(len(self.called("apply_input_changes_to_running_game")), 1)
        timeout.assert_called_once()

    def test_the_scheduled_recheck_runs_once_and_stops(self):
        self.assertFalse(self.prefs._sync_relaunch_banner_once())

    def test_a_dialog_with_no_banner_yet_is_not_asked_about_it(self):
        del self.prefs._relaunch_banner
        self.prefs._sync_relaunch_banner()


@needs_display
class TheVideoPageTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_changing_the_view_mode_tells_the_window(self):
        other = (self.prefs._view_mode_combo.get_selected() + 1) % len(
            self.prefs._view_modes
        )
        self.prefs._view_mode_combo.set_selected(other)
        applied = self.called("_apply_view_mode")[-1][1][0]
        self.assertEqual(applied, self.prefs._view_modes[other])

    def test_an_impossible_view_mode_index_tells_the_window_nothing(self):
        with mock.patch.object(
            self.prefs._view_mode_combo, "get_selected", return_value=99
        ):
            self.prefs._on_view_mode_changed()
        self.assertEqual(self.called("_apply_view_mode"), [])

    def test_changing_the_sort_order_tells_the_window(self):
        other = (self.prefs._sort_combo.get_selected() + 1) % len(
            self.prefs._sort_orders
        )
        self.prefs._sort_combo.set_selected(other)
        self.assertEqual(
            self.called("_apply_sort_order")[-1][1][0], self.prefs._sort_orders[other]
        )

    def test_an_impossible_sort_index_tells_the_window_nothing(self):
        with mock.patch.object(self.prefs._sort_combo, "get_selected", return_value=99):
            self.prefs._on_sort_order_changed()
        self.assertEqual(self.called("_apply_sort_order"), [])

    def test_showing_every_shader_is_stored_and_rebuilds_the_rows(self):
        self.prefs._show_all_switch.set_active(True)
        self.assertTrue(self.config.get_shader_settings()["show_all_shaders"])
        self.assertTrue(self.prefs._shader_rows)

    def test_every_console_gets_a_shader_row(self):
        from openemux.core.systems import SYSTEM_IDS

        self.assertEqual(len(self.prefs._shader_rows), len(SYSTEM_IDS))

    def test_choosing_a_shader_is_stored_for_that_console_only(self):
        row = self.prefs._shader_rows[0]
        console_id = row.get_title().split(" — ")[0]
        row.set_selected(1)
        self.assertEqual(
            self.config.get_shader_for_console(console_id), row._shader_ids[1]
        )

    def test_an_impossible_shader_index_stores_nothing(self):
        row = self.prefs._shader_rows[0]
        console_id = row.get_title().split(" — ")[0]
        before = self.config.get_shader_for_console(console_id)
        with mock.patch.object(row, "get_selected", return_value=99):
            self.prefs._on_shader_changed(row, None, console_id)
        self.assertEqual(self.config.get_shader_for_console(console_id), before)

    def test_a_stored_shader_the_catalog_no_longer_offers_keeps_its_row(self):
        # Otherwise the row would silently show a different shader than the
        # one the launch is going to apply.
        self.config.set_shader_for_console("SFC", "not-in-the-catalog")
        options, selected = self.prefs._shader_options_for_console("SFC")
        self.assertEqual(selected, "not-in-the-catalog")
        self.assertIn(selected, [sid for sid, _label in options])

    def test_restoring_the_shader_defaults_says_so(self):
        self.config.set_shader_for_console("SFC", "crt")
        self.prefs._restore_shader_defaults()
        self.assertEqual(self.toasts(), ["toast.shaders.defaults_restored"])


@needs_display
class TheGameWindowSwitchTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_the_subtitle_names_the_xwayland_cost_on_wayland(self):
        with mock.patch.object(
            prefs_module.game_window_support, "session_is_wayland", return_value=True
        ):
            subtitle = game_window_subtitle(lambda key, **kw: key)
        self.assertIn("prefs.game_window.subtitle.xwayland", subtitle)

    def test_the_subtitle_says_nothing_extra_on_x11(self):
        with mock.patch.object(
            prefs_module.game_window_support, "session_is_wayland", return_value=False
        ):
            subtitle = game_window_subtitle(lambda key, **kw: key)
        self.assertEqual(subtitle, "prefs.game_window.subtitle")

    def test_turning_the_game_window_on_is_stored(self):
        with mock.patch(
            "openemux.ui.game_window.display_supports_embedding", return_value=True
        ), mock.patch.object(
            prefs_module.game_window_support, "embed_unavailable_reason", return_value=None
        ):
            self.prefs._on_game_window_toggled(
                mock.Mock(get_active=lambda: True), None
            )
        self.assertTrue(self.config.get_game_window_enabled())
        self.assertEqual(self.toasts(), [])

    def test_turning_it_on_in_a_session_that_cannot_embed_asks_for_a_restart(self):
        # Issue #267: the X11 backend is chosen before GTK starts, so this run
        # cannot honour the switch however it is set.
        with mock.patch(
            "openemux.ui.game_window.display_supports_embedding", return_value=False
        ):
            self.prefs._on_game_window_toggled(
                mock.Mock(get_active=lambda: True), None
            )
        self.assertEqual(self.toasts(), ["toast.game_window.restart"])

    def test_turning_it_off_never_asks_for_a_restart(self):
        self.prefs._on_game_window_toggled(mock.Mock(get_active=lambda: False), None)
        self.assertFalse(self.config.get_game_window_enabled())
        self.assertEqual(self.toasts(), [])

    def test_a_machine_that_cannot_embed_at_all_shows_a_disabled_row_that_says_why(self):
        with mock.patch.object(
            prefs_module.game_window_support, "embedding_possible", return_value=False
        ):
            prefs = OpenEmuxPreferences(self.win)
        self.assertFalse(prefs._game_window_row.get_sensitive())
        self.assertIn("prefs.game_window.unavailable", prefs._game_window_row.get_subtitle())

    def test_on_windows_the_reason_says_there_is_no_equivalent(self):
        with mock.patch.object(
            prefs_module.game_window_support, "embedding_possible", return_value=False
        ), mock.patch.object(prefs_module, "IS_WINDOWS", True):
            prefs = OpenEmuxPreferences(self.win)
        self.assertEqual(
            prefs._game_window_row.get_subtitle(),
            "prefs.game_window.unavailable_windows",
        )


@needs_display
class TheCoresPageTests(_PreferencesCase):
    def test_a_console_with_a_core_offers_automatic_first(self):
        row = self._core_row("SFC")
        self.assertIsNotNone(row)
        self.assertIsNone(row._core_filenames[0])

    def _core_row(self, console_id):
        for page in [self.prefs._pages["cores"]]:
            for row in _walk(page):
                if getattr(row, "_core_filenames", None) is not None and row.get_title(
                ).startswith(f"{console_id} "):
                    return row
        return None

    def test_choosing_a_core_stores_the_override_and_checks_the_bios(self):
        row = self._core_row("SFC")
        row.set_selected(1)
        self.assertEqual(
            self.config.get_console_core_override("SFC"), "snes9x_libretro.so"
        )
        self.assertEqual(len(self.called("_warn_missing_bios_for_core")), 1)

    def test_going_back_to_automatic_clears_the_override_without_a_bios_check(self):
        row = self._core_row("SFC")
        row.set_selected(1)
        self.win.calls.clear()
        row.set_selected(0)
        self.assertFalse(self.config.get_console_core_override("SFC"))
        self.assertEqual(self.called("_warn_missing_bios_for_core"), [])

    def test_an_impossible_core_index_stores_nothing(self):
        row = self._core_row("SFC")
        before = self.config.get_console_core_override("SFC")
        with mock.patch.object(row, "get_selected", return_value=99):
            self.prefs._on_core_changed(row, None, "SFC")
        self.assertEqual(self.config.get_console_core_override("SFC"), before)

    def test_a_console_with_no_core_installed_resolves_to_nothing(self):
        self.assertIsNone(self.prefs._resolved_core_for("GB"))

    def test_an_override_wins_over_the_catalog_when_resolving(self):
        self.config.set_console_core_override("GB", "gambatte_libretro.so")
        self.assertEqual(self.prefs._resolved_core_for("GB"), "gambatte_libretro.so")

    def test_the_advanced_group_is_hidden_when_no_core_publishes_options(self):
        with mock.patch.object(
            prefs_module.core_options, "options_for_core", return_value=[]
        ):
            self.prefs._refresh_core_options()
        self.assertFalse(self.prefs._core_options_group.get_visible())
        self.assertEqual(self.prefs._core_options_rows, [])


def _walk(widget):
    """Every descendant of a widget, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


@needs_display
class TheCoreOptionRowsTests(_PreferencesCase):
    """Issue #296: settings the core understands, which the config cannot carry."""

    def setUp(self):
        super().setUp()
        self.option = CoreOption(
            "test_option", "core_options.test", ["a", "b"], "a"
        )
        patcher = mock.patch.object(
            prefs_module.core_options,
            "options_for_core",
            lambda filename: [self.option] if filename else [],
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        label_patch = mock.patch.object(
            prefs_module.core_options, "value_label", lambda value: f"label:{value}"
        )
        label_patch.start()
        self.addCleanup(label_patch.stop)
        self.prefs._refresh_core_options()

    def test_a_core_with_options_gets_a_row_and_the_group_appears(self):
        self.assertTrue(self.prefs._core_options_rows)
        self.assertTrue(self.prefs._core_options_group.get_visible())

    def test_changing_an_option_stores_it_against_that_console_and_core(self):
        row = self.prefs._core_options_rows[0]
        console_id, core_filename, option = row._core_option
        row.set_selected(1)
        stored = self.config.core_options.get_for_console(console_id, core_filename)
        self.assertEqual(stored[option.key], option.values[1])

    def test_an_impossible_option_index_stores_nothing(self):
        row = self.prefs._core_options_rows[0]
        console_id, core_filename, option = row._core_option
        with mock.patch.object(row, "get_selected", return_value=99):
            self.prefs._on_core_option_changed(row, None)
        self.assertEqual(
            self.config.core_options.get_for_console(console_id, core_filename), {}
        )

    def test_a_stored_value_the_core_no_longer_offers_falls_back_to_the_default(self):
        row = self.prefs._core_options_rows[0]
        console_id, core_filename, option = row._core_option
        # The store refuses a value the option does not list, so the row can
        # only ever land on something the core accepts.
        self.config.core_options.set_for_console(
            console_id, core_filename, option.key, "gone"
        )
        self.prefs._refresh_core_options()
        self.assertEqual(self.prefs._core_options_rows[0].get_selected(), 0)


@needs_display
class TheSystemPageTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_the_language_row_opens_on_the_running_locale(self):
        self.assertEqual(
            self.prefs._locale_ids[self.prefs._language_combo.get_selected()], "en"
        )

    def test_choosing_another_language_applies_it_and_reopens_the_dialog(self):
        index = self.prefs._locale_ids.index("pt_BR")
        with mock.patch.object(prefs_module.GLib, "idle_add") as idle_add:
            self.prefs._language_combo.set_selected(index)
        self.assertEqual(self.called("_apply_language_change")[-1][1][0], "pt_BR")
        idle_add.assert_called_once_with(self.prefs._reopen_after_language)

    def test_choosing_the_language_already_running_changes_nothing(self):
        self.prefs._on_language_changed()
        self.assertEqual(self.called("_apply_language_change"), [])

    def test_an_impossible_language_index_changes_nothing(self):
        with mock.patch.object(
            self.prefs._language_combo, "get_selected", return_value=999
        ):
            self.prefs._on_language_changed()
        self.assertEqual(self.called("_apply_language_change"), [])

    def test_reopening_after_a_language_change_closes_and_asks_for_a_new_dialog(self):
        self.assertFalse(self.prefs._reopen_after_language())
        self.assertEqual(len(self.called("_open_preferences")), 1)

    def test_choosing_a_theme_stores_it_and_repaints_the_header_button(self):
        with mock.patch.object(prefs_module.theming, "apply_theme") as apply_theme:
            self.prefs._theme_combo.set_selected(self.prefs._themes.index("dark"))
        apply_theme.assert_called_once()
        self.assertEqual(self.config.get_ui_settings()["theme"], "dark")
        self.assertEqual(len(self.called("_sync_theme_button")), 1)

    def test_an_impossible_theme_index_changes_nothing(self):
        before = self.config.get_ui_settings()["theme"]
        row = mock.Mock()
        row.get_selected.return_value = 99
        self.prefs._on_theme_changed(row)
        self.assertEqual(self.config.get_ui_settings()["theme"], before)

    def test_turning_the_tips_off_is_stored_and_applied(self):
        self.prefs._tips_row.set_active(False)
        self.assertFalse(self.config.get_ui_settings()["show_tips"])
        self.assertEqual(self.called("_apply_tips_visibility")[-1][1][0], False)

    def test_gamepad_navigation_is_applied_by_the_window_which_owns_it(self):
        row = self.prefs._gamepad_nav_row
        row.set_active(not row.get_active())
        self.assertEqual(len(self.called("_apply_gamepad_navigation")), 1)

    def test_the_welcome_on_startup_switch_is_stored(self):
        self.prefs._welcome_startup_row.set_active(False)
        self.assertFalse(self.config.get_show_welcome_on_startup())

    def test_opening_the_welcome_tour_closes_preferences_first(self):
        with mock.patch.object(self.prefs, "close") as close:
            self.prefs._on_open_welcome(None)
        close.assert_called_once()
        self.assertEqual(len(self.called("_open_welcome")), 1)

    def _bootstrap_subtitle(self):
        prefs = OpenEmuxPreferences(self.win)
        subtitles = [
            row.get_subtitle()
            for row in _walk(prefs._pages["system"])
            if isinstance(row, Adw.ActionRow)
            and row.get_title() == "settings.system.bootstrap.title"
        ]
        self.assertEqual(len(subtitles), 1)
        return subtitles[0]

    def test_a_library_that_never_finished_setup_says_it_is_pending(self):
        self.assertEqual(
            self._bootstrap_subtitle(), "settings.system.bootstrap.pending"
        )

    def test_a_finished_setup_says_so(self):
        self.config.start_bootstrap_run()
        self.config.finish_bootstrap_success()
        self.assertEqual(self._bootstrap_subtitle(), "settings.system.bootstrap.ok")

    def test_a_failed_setup_names_the_step_that_broke(self):
        self.config.start_bootstrap_run()
        self.config.finish_bootstrap_failure("cores_download", "no network")
        self.assertEqual(
            self._bootstrap_subtitle(), "settings.system.bootstrap.failed"
        )


@needs_display
class TheAchievementsAccountTests(_PreferencesCase):
    def setUp(self):
        super().setUp()
        self.setUpToastCapture()

    def test_a_signed_out_account_asks_for_one(self):
        self.assertIsNotNone(self.prefs._cheevos_user_row)
        self.assertIsNotNone(self.prefs._cheevos_sign_in)

    def test_a_successful_sign_in_stores_the_token_and_turns_them_on(self):
        self.assertFalse(self.prefs._on_achievements_login_ok("player1", "tok"))
        store = self.config.achievements
        self.assertTrue(store.is_signed_in())
        self.assertEqual(store.get_username(), "player1")
        self.assertTrue(store.get_enabled())
        self.assertEqual(self.toasts(), ["toast.achievements.signed_in"])

    def test_a_signed_in_account_offers_the_two_switches_and_a_way_out(self):
        self.config.achievements.set_account("player1", "tok")
        self.prefs._refresh_achievements()
        switches = [
            row for row in self.prefs._achievements_rows if isinstance(row, Adw.SwitchRow)
        ]
        self.assertEqual(len(switches), 2)

    def test_the_enable_switch_writes_straight_to_the_store(self):
        self.config.achievements.set_account("player1", "tok")
        self.prefs._refresh_achievements()
        enable, hardcore = [
            row for row in self.prefs._achievements_rows if isinstance(row, Adw.SwitchRow)
        ]
        enable.set_active(False)
        hardcore.set_active(True)
        self.assertFalse(self.config.achievements.get_enabled())
        self.assertTrue(self.config.achievements.get_hardcore())

    def test_signing_out_forgets_the_account(self):
        self.config.achievements.set_account("player1", "tok")
        self.prefs._refresh_achievements()
        self.prefs._on_achievements_sign_out(None)
        self.assertFalse(self.config.achievements.is_signed_in())
        self.assertEqual(self.toasts(), ["toast.achievements.signed_out"])

    def test_a_rejected_sign_in_reports_the_reason_and_re_arms_the_button(self):
        self.prefs._cheevos_sign_in.set_sensitive(False)
        self.assertFalse(self.prefs._on_achievements_login_failed("bad credentials"))
        self.assertTrue(self.prefs._cheevos_sign_in.get_sensitive())
        self.assertEqual(self.toasts(), ["toast.achievements.failed"])

    def test_the_sign_in_runs_off_the_main_thread_and_reports_back(self):
        self.prefs._cheevos_user_row.set_text("  player1  ")
        self.prefs._cheevos_password_row.set_text("secret")
        with mock.patch.object(
            prefs_module.retroachievements, "login", return_value="tok"
        ) as login, mock.patch.object(prefs_module.GLib, "idle_add") as idle_add:
            self.prefs._on_achievements_sign_in(None)
            _wait_for(lambda: idle_add.call_count == 1)
        login.assert_called_once_with("player1", "secret")
        self.assertEqual(
            idle_add.call_args[0], (self.prefs._on_achievements_login_ok, "player1", "tok")
        )
        self.assertFalse(self.prefs._cheevos_sign_in.get_sensitive())

    def test_a_login_the_server_refuses_comes_back_as_a_failure(self):
        with mock.patch.object(
            prefs_module.retroachievements,
            "login",
            side_effect=retroachievements.LoginError("nope"),
        ), mock.patch.object(prefs_module.GLib, "idle_add") as idle_add:
            self.prefs._on_achievements_sign_in(None)
            _wait_for(lambda: idle_add.call_count == 1)
        self.assertEqual(
            idle_add.call_args[0][0], self.prefs._on_achievements_login_failed
        )


@needs_display
class SaveBackupTests(_PreferencesCase):
    """Issue #293: export and import, without ever opening a real picker."""

    def setUp(self):
        super().setUp()
        self.setUpToastCapture()
        self.dialogs = []
        patcher = mock.patch.object(
            prefs_module.Gtk, "FileDialog", self._dialog_factory
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _dialog_factory(self):
        dialog = mock.Mock()
        self.dialogs.append(dialog)
        return dialog

    def test_the_export_picker_offers_a_default_filename(self):
        self.prefs._on_export_saves(None)
        dialog = self.dialogs[0]
        dialog.set_initial_name.assert_called_once_with(
            save_backup.default_backup_name()
        )
        dialog.save.assert_called_once()

    def test_a_chosen_export_target_starts_the_backup(self):
        target = mock.Mock()
        target.get_path.return_value = str(self.tmp / "backup.zip")
        dialog = mock.Mock()
        dialog.save_finish.return_value = target
        with mock.patch.object(save_backup, "export_saves_async") as export:
            self.prefs._on_export_target_chosen(dialog, None)
        self.assertEqual(export.call_args[0][0], str(self.tmp / "backup.zip"))

    def test_a_dismissed_export_picker_starts_nothing(self):
        dialog = mock.Mock()
        dialog.save_finish.side_effect = GLib.Error("dismissed")
        with mock.patch.object(save_backup, "export_saves_async") as export:
            self.prefs._on_export_target_chosen(dialog, None)
        export.assert_not_called()

    def test_an_export_target_with_no_local_path_starts_nothing(self):
        target = mock.Mock()
        target.get_path.return_value = ""
        dialog = mock.Mock()
        dialog.save_finish.return_value = target
        with mock.patch.object(save_backup, "export_saves_async") as export:
            self.prefs._on_export_target_chosen(dialog, None)
        export.assert_not_called()

    def test_a_finished_export_reports_what_it_wrote(self):
        self.assertFalse(self.prefs._on_export_done({"states": 3, "saves": 4}))
        self.assertEqual(self.toasts(), ["toast.saves.exported"])

    def test_a_failed_export_reports_the_error_instead(self):
        self.assertFalse(self.prefs._on_export_done({"error": "disk full"}))
        self.assertEqual(self.toasts(), ["toast.saves.failed"])

    def test_the_import_picker_opens_for_reading(self):
        self.prefs._on_import_saves(None)
        self.dialogs[0].open.assert_called_once()

    def test_a_chosen_archive_starts_the_restore(self):
        source = mock.Mock()
        source.get_path.return_value = str(self.tmp / "backup.zip")
        dialog = mock.Mock()
        dialog.open_finish.return_value = source
        with mock.patch.object(save_backup, "import_saves_async") as restore:
            self.prefs._on_import_source_chosen(dialog, None)
        self.assertEqual(restore.call_args[0][0], str(self.tmp / "backup.zip"))

    def test_a_dismissed_import_picker_starts_nothing(self):
        dialog = mock.Mock()
        dialog.open_finish.side_effect = GLib.Error("dismissed")
        with mock.patch.object(save_backup, "import_saves_async") as restore:
            self.prefs._on_import_source_chosen(dialog, None)
        restore.assert_not_called()

    def test_an_import_source_with_no_local_path_starts_nothing(self):
        source = mock.Mock()
        source.get_path.return_value = ""
        dialog = mock.Mock()
        dialog.open_finish.return_value = source
        with mock.patch.object(save_backup, "import_saves_async") as restore:
            self.prefs._on_import_source_chosen(dialog, None)
        restore.assert_not_called()

    def test_a_finished_import_reports_what_it_restored(self):
        self.assertFalse(
            self.prefs._on_import_done({"restored": 5, "skipped": 1, "errors": []})
        )
        self.assertEqual(self.toasts(), ["toast.saves.imported"])

    def test_an_import_that_restored_nothing_reports_the_first_error(self):
        self.assertFalse(
            self.prefs._on_import_done(
                {"restored": 0, "errors": [{"error": "not a backup"}]}
            )
        )
        self.assertEqual(self.toasts(), ["toast.saves.failed"])

    def test_an_import_that_hit_errors_but_still_restored_reports_the_tally(self):
        self.assertFalse(
            self.prefs._on_import_done(
                {"restored": 2, "skipped": 0, "errors": [{"error": "one bad entry"}]}
            )
        )
        self.assertEqual(self.toasts(), ["toast.saves.imported"])


def _wait_for(predicate, timeout=5.0):
    """Block until a worker thread has reported back, or give up.

    The sign-in runs on a thread the dialog starts itself; polling is what
    keeps the assertion from racing it.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError("the worker never reported back")


if __name__ == "__main__":
    unittest.main()

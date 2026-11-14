"""Big Picture's Input section: the desktop's Input page as rows a pad walks."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Gdk, GLib

    from openemux.core.input_profiles import ANALOG_DPAD_MODES, DEVICE_IDS
    from openemux.core.systems import SYSTEM_IDS
    from openemux.ui import navigation
    from openemux.ui.bigpicture import settings_input
    from openemux.ui.bigpicture.settings_input import (
        CAPTURE_TIMEOUT,
        CLEAR,
        CORE_DEFAULT,
        GUIDE_TOKEN,
        KEEP,
        REMAP,
        InputSection,
    )
    from openemux.ui.bigpicture.widgets import BigPage


class InputSectionCase(BigPictureCase):
    """A section on a stand-in Settings page, pinned to one console and device.

    The chooser is the shell's (another page), so it is mocked: ``pick``
    answers the one the section opened last.
    """

    console = "SFC"
    device = "keyboard"

    def setUp(self):
        super().setUp()
        self.page = BigPage(self.shell, "Settings")
        self.section = InputSection(self.shell, self.page)
        self.page.body.append(self.section.widget)
        self.shell.push(self.page)
        self.pump()
        # A capture left running would hold the window's exclusive flag, a
        # key controller and a countdown source into the next test.
        self.addCleanup(self.section._stop_held_reader)
        self.addCleanup(self.section._cancel_capture)
        chooser = mock.patch.object(self.shell, "open_chooser")
        self.chooser = chooser.start()
        self.addCleanup(chooser.stop)
        self.section.select_console(self.console)
        if self.device != "keyboard":
            self.section._on_device_picked(self.device)
        # Entering the mode toasted; from here on, only the section speaks.
        del self.toasts[:]

    def pick(self, choice):
        """Answer the chooser the section opened last."""
        self.chooser.call_args.args[3](choice)

    def options(self):
        return [option["id"] for option in self.chooser.call_args.args[1]]

    def current(self):
        return self.chooser.call_args.args[2]

    def remap(self, action):
        """A on the action's row, then "Remap" when the row asks."""
        self.chooser.reset_mock()
        self.section._on_binding_row(action)
        if self.chooser.called:
            self.pick(REMAP)

    def key(self, name):
        """One key, as the capture controller sees it."""
        return self.section._on_capture_key(None, Gdk.keyval_from_name(name), 0, 0)

    def stored_bindings(self, device=None):
        profile = self.config.get_input_profile(self.console)
        return profile["devices"][device or self.device]["bindings"]

    def value_of(self, row):
        return row.value_label.get_label()


@needs_display
class TheRows(InputSectionCase):
    def test_the_section_opens_on_the_console_in_front(self):
        section = InputSection(self.shell, self.page)
        current = self.win.current_console
        expected = current if current in SYSTEM_IDS else SYSTEM_IDS[0]
        self.assertEqual(section._console, expected)
        self.assertEqual(self.value_of(section.console_row), section._console_label(expected))
        self.assertEqual(self.value_of(section.device_row), self.said("input.device.keyboard"))
        self.assertFalse(section.port_row.get_visible())
        self.assertFalse(section.relaunch_row.get_visible())
        self.assertTrue(section.system_group.get_visible())
        self.assertIn("a", section._binding_rows)
        self.assertIn("menu_toggle", section._binding_rows)
        self.assertFalse(section.has_unsaved())
        self.assertFalse(section.capturing)
        self.assertEqual(
            section.save_row.subtitle_label.get_label(), self.said("big_picture.input.save.subtitle")
        )

    def test_the_console_chooser_lists_every_system_and_reloads_the_rows(self):
        section = self.section
        section.console_row.emit("clicked")
        self.assertEqual(self.options(), list(SYSTEM_IDS))
        self.assertEqual(self.current(), "SFC")
        self.assertEqual(self.chooser.call_args.kwargs["crumbs"][-1], self.said("input.console"))
        self.assertTrue(section.controller_type_row.get_visible())
        self.assertFalse(section.dpad_analog_row.get_visible())
        self.pick("N64")
        self.assertEqual(section._console, "N64")
        self.assertEqual(self.value_of(section.console_row), section._console_label("N64"))
        self.assertFalse(section.controller_type_row.get_visible())
        self.assertTrue(section.dpad_analog_row.get_visible())
        self.assertIn("l_up", section._binding_rows)
        self.assertEqual(section._drawing_console, "N64")
        # The same console again, or one that does not exist, changes nothing.
        with mock.patch.object(section, "_refresh_bindings") as refresh:
            section.select_console("N64")
            section.select_console("NOPE")
        refresh.assert_not_called()

    def test_the_device_chooser_switches_the_map_and_ports_2_to_4_have_no_hotkeys(self):
        section = self.section
        section.device_row.emit("clicked")
        self.assertEqual(self.options(), list(DEVICE_IDS))
        self.assertEqual(self.current(), "keyboard")
        self.pick("gamepad_p2")
        self.assertTrue(section.port_row.get_visible())
        self.assertFalse(section.port_row.get_active())
        self.assertFalse(section.system_group.get_visible())
        self.assertNotIn("menu_toggle", section._binding_rows)
        self.assertEqual(self.value_of(section.device_row), self.said("input.device.gamepad_p2"))
        # Pad tokens read as buttons, axes and hats; anything else as itself.
        self.assertEqual(section._binding_display("3"), self.said("input.binding.button", index="3"))
        self.assertEqual(section._binding_display("+2"), self.said("input.binding.axis", axis="+2"))
        self.assertEqual(section._binding_display("h0up"), self.said("input.binding.hat", direction="↑"))
        self.assertEqual(section._binding_display("weird"), "weird")
        self.assertEqual(section._binding_display(""), self.said("input.binding.empty"))
        # Switching the port on is a change to save.
        section.port_row.emit("clicked")
        self.assertTrue(section.has_unsaved())
        self.assertEqual(
            section.save_row.subtitle_label.get_label(), self.said("big_picture.input.save.unsaved")
        )
        with mock.patch.object(section, "_refresh_bindings") as refresh:
            section._on_device_picked("gamepad_p2")
            section._on_device_picked("nothing")
        refresh.assert_not_called()

    def test_the_controller_type_is_chosen_among_what_the_core_publishes(self):
        section = self.section
        row = section.controller_type_row
        self.assertEqual(self.value_of(row), self.said("input.controller_type.core_default"))
        row.emit("clicked")
        self.assertEqual(self.options()[0], CORE_DEFAULT)
        self.assertEqual(self.current(), CORE_DEFAULT)
        self.pick("257")
        self.assertEqual(self.config.input_profiles.get_controller_type("SFC"), 257)
        self.assertEqual(self.value_of(row), "Multitap")
        row.emit("clicked")
        self.assertEqual(self.current(), "257")
        self.pick(CORE_DEFAULT)
        self.assertIsNone(self.config.input_profiles.get_controller_type("SFC"))

    def test_the_stick_rows_write_the_profile_as_they_change(self):
        section = self.section
        section.analog_dpad_row.emit("clicked")
        self.assertEqual(self.options(), [str(mode) for mode in ANALOG_DPAD_MODES])
        self.pick("2")
        self.assertEqual(self.config.input_profiles.get_analog_dpad_mode("SFC"), 2)
        self.assertEqual(self.value_of(section.analog_dpad_row), self.said("input.analog_dpad.mode.2"))
        section.select_console("N64")
        self.assertFalse(section.dpad_analog_row.get_active())
        section.dpad_analog_row.emit("clicked")
        self.assertTrue(self.config.input_profiles.get_dpad_drives_analog("N64"))
        section.refresh()
        self.assertTrue(section.dpad_analog_row.get_active())

    def test_the_tuning_rows_step_within_their_ranges_and_save_at_once(self):
        section = self.section
        config = self.config
        deadzone = section.tuning_rows["analog_deadzone"]
        self.assertEqual(deadzone.number_label.get_label(), "0.00")
        self.assertTrue(deadzone.step(1))
        self.assertAlmostEqual(config.get_input_tuning_value("analog_deadzone"), 0.05)
        self.assertEqual(deadzone.number_label.get_label(), "0.05")
        deadzone.step(-1)
        deadzone.step(-1)
        self.assertEqual(config.get_input_tuning_value("analog_deadzone"), 0.0)
        rumble = section.tuning_rows["rumble_gain"]
        self.assertEqual(rumble.number_label.get_label(), "100")
        rumble.step(1)
        self.assertEqual(config.get_input_tuning_value("rumble_gain"), 100)
        rumble.step(-1)
        self.assertEqual(rumble.number_label.get_label(), "95")
        section.poll_row.emit("clicked")
        self.assertEqual(self.current(), "2")
        self.pick("0")
        self.assertEqual(config.get_input_tuning_value("poll_type_behavior"), 0)
        self.assertEqual(self.value_of(section.poll_row), self.said("input.tuning.poll.0"))
        section.focus_row.emit("clicked")
        self.pick("2")
        self.assertEqual(config.get_input_tuning_value("auto_game_focus"), 2)
        self.assertEqual(self.value_of(section.focus_row), self.said("input.tuning.focus.2"))
        self.assertTrue(section.descriptor_row.get_active())
        section.descriptor_row.emit("clicked")
        self.assertFalse(config.get_input_tuning_value("descriptor_label_show"))

    def test_the_turbo_rows_keep_the_duty_cycle_under_the_period(self):
        section = self.section
        turbo = self.config.input_profiles
        self.assertEqual(section.turbo_period_row.number_label.get_label(), "6")
        section.turbo_period_row.step(1)
        self.assertEqual(turbo.get_turbo_settings("SFC")["period"], 7)
        section.turbo_duty_row.step(-1)
        self.assertEqual(turbo.get_turbo_settings("SFC")["duty_cycle"], 2)
        for _ in range(10):
            section.turbo_period_row.step(-1)
        settings = turbo.get_turbo_settings("SFC")
        self.assertEqual((settings["period"], settings["duty_cycle"]), (2, 1))
        self.assertEqual(section.turbo_duty_row.number_label.get_label(), "1")
        section.turbo_mode_row.emit("clicked")
        self.assertEqual(self.current(), "0")
        self.pick("1")
        self.assertEqual(turbo.get_turbo_settings("SFC")["mode"], 1)
        self.assertEqual(self.value_of(section.turbo_mode_row), self.said("input.turbo.mode.1"))

    def test_the_relaunch_note_shows_only_while_a_game_runs(self):
        self.assertFalse(self.section.relaunch_row.get_visible())
        with mock.patch.object(self.win.runtime_manager, "is_running", return_value=True):
            self.section._sync_relaunch_row()
            self.assertTrue(self.section.relaunch_row.get_visible())

    def test_refresh_rebuilds_from_the_store_and_the_focus_lands_on_the_console_row(self):
        section = self.section
        section._set_binding("a", "j")
        self.assertTrue(section.has_unsaved())
        section.refresh()
        self.assertFalse(section.has_unsaved())
        self.assertEqual(section._capture.binding_for("a"), "z")
        self.show()
        self.assertTrue(section.focus_default())
        self.assertIs(self.focus_widget(), section.console_row)
        glyphs = self.win.navigation.glyphs()
        hints = section.hints(glyphs, self.win.t)
        self.assertEqual(hints[1], (glyphs["context"], self.said("input.map_all")))
        self.assertEqual(hints[2], (glyphs["favorite"], self.said("input.reset")))


@needs_display
class KeyboardCapture(InputSectionCase):
    def test_a_on_a_bound_row_asks_and_remap_captures_the_next_key(self):
        self.show()
        section = self.section
        row = section._binding_rows["a"]
        row.emit("clicked")
        self.assertEqual(self.options(), [REMAP, CLEAR, KEEP])
        self.assertEqual(self.current(), KEEP)
        self.assertEqual(
            self.chooser.call_args.kwargs["lead"],
            self.said("big_picture.input.binding.lead", binding="z"),
        )
        self.pick(REMAP)
        self.assertTrue(section.capturing)
        self.assertTrue(self.win.input_capture_active)
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_INPUT_CAPTURE)
        self.assertTrue(section.capture_card.get_visible())
        self.assertIsNotNone(section._key_controller)
        self.assertNotEqual(section._countdown_source, 0)
        self.assertEqual(
            section.capture_heading.get_label(),
            self.said("input.capture.waiting_for", action=self.said("input.action.a")),
        )
        self.assertEqual(
            section.capture_eyebrow.get_label(),
            self.said(
                "big_picture.input.capture.single",
                console=section._console_label("SFC"),
                device=self.said("input.device.keyboard"),
            ),
        )
        self.assertEqual(
            section.capture_countdown.get_label(),
            self.said("big_picture.input.capture.seconds", count=CAPTURE_TIMEOUT),
        )
        self.assertEqual(
            section.capture_note.get_label(), self.said("big_picture.input.capture.note_keyboard")
        )
        self.assertEqual(self.value_of(row), self.said("input.capture.waiting"))
        self.assertTrue(self.key("j"))
        self.assertFalse(section.capturing)
        self.assertFalse(self.win.input_capture_active)
        self.assertFalse(section.capture_card.get_visible())
        self.assertIsNone(section._key_controller)
        self.assertEqual(section._countdown_source, 0)
        self.assertEqual(section._capture.binding_for("a"), "j")
        self.assertEqual(self.value_of(row), "j")
        self.assertTrue(section.has_unsaved())
        self.assertIs(self.focus_widget(), row)
        # Nothing reached the disk: that is what Save is for.
        self.assertEqual(self.stored_bindings()["a"], "z")

    def test_clear_empties_the_binding_and_keep_leaves_it(self):
        section = self.section
        row = section._binding_rows["a"]
        row.emit("clicked")
        self.pick(KEEP)
        self.assertEqual(section._capture.binding_for("a"), "z")
        self.assertFalse(section.has_unsaved())
        row.emit("clicked")
        self.pick(CLEAR)
        self.assertEqual(section._capture.binding_for("a"), "")
        self.assertEqual(self.value_of(row), self.said("input.binding.empty"))
        self.assertTrue(section.has_unsaved())
        # An empty row captures at once, no question asked.
        self.chooser.reset_mock()
        row.emit("clicked")
        self.chooser.assert_not_called()
        self.assertTrue(section.capturing)
        self.key("k")
        self.assertEqual(section._capture.binding_for("a"), "k")

    def test_escape_cancels_and_keeps_the_binding(self):
        section = self.section
        self.remap("a")
        self.assertTrue(self.key("Escape"))
        self.assertFalse(section.capturing)
        self.assertEqual(section._capture.binding_for("a"), "z")
        self.assertEqual(self.value_of(section._binding_rows["a"]), "z")
        self.assertEqual(self.toasts, [])  # a single capture dies quietly
        # Outside a capture the controller claims nothing; inside one, a key
        # with no name is swallowed and the capture goes on.
        self.assertFalse(section._on_capture_key(None, Gdk.KEY_a, 0, 0))
        self.remap("a")
        self.assertTrue(section._on_capture_key(None, 0, 0, 0))
        self.assertTrue(section.capturing)
        # A capture for an action the device does not map never starts.
        section._cancel_capture()
        section._start_capture("nothing", sequence_mode=False)
        self.assertFalse(section.capturing)

    def test_a_key_another_action_holds_is_released_from_it(self):
        section = self.section
        self.remap("a")
        self.key("x")  # B's key
        self.assertEqual(section._capture.binding_for("a"), "x")
        self.assertEqual(section._capture.binding_for("b"), "")
        self.assertEqual(self.value_of(section._binding_rows["b"]), self.said("input.binding.empty"))
        self.assertIn(
            self.said("toast.input_released", binding="x", actions=self.said("input.action.b")),
            self.toasts,
        )
        # A value arriving with nothing armed is dropped.
        section._commit_capture("q")
        self.assertEqual(section._capture.binding_for("a"), "x")

    def test_the_countdown_cancels_a_capture_nobody_answers(self):
        section = self.section
        self.remap("a")
        self.assertEqual(section._on_countdown_tick(), GLib.SOURCE_CONTINUE)
        self.assertEqual(
            section.capture_countdown.get_label(),
            self.said("big_picture.input.capture.seconds", count=CAPTURE_TIMEOUT - 1),
        )
        for _ in range(CAPTURE_TIMEOUT - 2):
            self.assertEqual(section._on_countdown_tick(), GLib.SOURCE_CONTINUE)
        self.assertEqual(section._on_countdown_tick(), GLib.SOURCE_REMOVE)
        self.assertFalse(section.capturing)
        self.assertEqual(section._countdown_source, 0)
        self.assertEqual(section._capture.binding_for("a"), "z")
        self.assertEqual(self.toasts, [])


@needs_display
class MapAll(InputSectionCase):
    def test_x_walks_every_required_action_and_says_when_it_is_done(self):
        section = self.section
        sequence = list(section._capture.sequence_actions)
        self.assertTrue(section.on_pad_action("context"))
        self.assertTrue(section.capturing)
        self.assertEqual(section._capture.active_action, sequence[0])
        self.assertEqual(
            section.capture_eyebrow.get_label(),
            self.said(
                "big_picture.input.capture.sequence",
                index=1, count=len(sequence),
                console=section._console_label("SFC"),
                device=self.said("input.device.keyboard"),
            ),
        )
        keys = [f"F{index}" for index in range(1, 13)] + list("qwertyuiopasdfghjkl")
        for index, name in enumerate(keys[: len(sequence)]):
            self.assertEqual(section._capture.active_action, sequence[index])
            self.key(name)
        self.assertFalse(section.capturing)
        self.assertEqual(section._capture.binding_for(sequence[-1]), keys[len(sequence) - 1].lower())
        # One toast at the end; the releases along the way are not announced.
        self.assertEqual(self.toasts, [self.said("input.capture.completed")])
        self.assertTrue(section.has_unsaved())

    def test_escape_mid_walk_cancels_the_whole_walk_and_says_so(self):
        self.show()
        section = self.section
        section.map_all_row.emit("clicked")
        self.key("F5")
        self.assertTrue(section._capture.sequence_mode)
        self.key("Escape")
        self.assertFalse(section.capturing)
        self.assertIn(self.said("input.capture.cancelled"), self.toasts)
        # What was mapped before the Escape stays in the buffer, unsaved.
        self.assertEqual(section._capture.binding_for(section._capture.sequence_actions[0]), "f5")
        self.assertIs(self.focus_widget(), section.map_all_row)
        # The countdown running out mid-walk is the same cancel.
        section.start_map_all()
        for _ in range(CAPTURE_TIMEOUT):
            section._on_countdown_tick()
        self.assertFalse(section.capturing)
        self.assertEqual(self.toasts.count(self.said("input.capture.cancelled")), 2)
        # Nothing to walk: no capture starts.
        with mock.patch.object(section._capture, "begin_sequence", return_value=None):
            section.start_map_all()
        self.assertFalse(section.capturing)
        # Only X and Y are the section's.
        self.assertFalse(section.on_pad_action("confirm"))


@needs_display
class GamepadCapture(InputSectionCase):
    device = "gamepad_p1"

    def setUp(self):
        super().setUp()
        self.reader = mock.Mock()
        patcher = mock.patch.object(settings_input, "make_capture_reader", return_value=self.reader)
        self.make_reader = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_pad_capture_listens_on_the_pad_and_stores_its_token(self):
        section = self.section
        self.assertEqual(section._capture.binding_for("a"), "0")
        self.remap("a")
        self.reader.start.assert_called_once()
        self.assertIsNone(self.make_reader.call_args.kwargs["device"])
        self.assertEqual(
            self.value_of(section._binding_rows["a"]), self.said("input.capture.waiting_gamepad")
        )
        self.assertEqual(
            section.capture_heading.get_label(),
            self.said("input.capture.waiting_for_gamepad", action=self.said("input.action.a")),
        )
        self.assertEqual(
            section.capture_note.get_label(), self.said("big_picture.input.capture.note_gamepad")
        )
        # A stray keystroke is swallowed, not stored as a controller token.
        self.assertTrue(self.key("j"))
        self.assertTrue(section.capturing)
        self.assertEqual(section._capture.binding_for("a"), "0")
        self.assertFalse(section._on_gamepad_token("9"))
        self.assertFalse(section.capturing)
        self.assertEqual(section._capture.binding_for("a"), "9")
        self.assertEqual(
            self.value_of(section._binding_rows["a"]), self.said("input.binding.button", index="9")
        )
        # A token or an error arriving after the capture ended is dropped.
        self.assertFalse(section._on_gamepad_token("3"))
        self.assertEqual(section._capture.binding_for("a"), "9")
        self.assertFalse(section._on_gamepad_error("gone"))
        self.assertEqual(self.toasts, [])

    def test_the_guide_button_cancels_instead_of_binding(self):
        section = self.section
        self.remap("a")
        self.assertFalse(section._on_gamepad_token(GUIDE_TOKEN))
        self.assertFalse(section.capturing)
        self.assertEqual(section._capture.binding_for("a"), "0")
        self.assertFalse(self.win.input_capture_active)
        self.assertEqual(self.toasts, [])
        # Mid-walk it cancels the walk, and says so.
        section.start_map_all()
        section._on_gamepad_token(GUIDE_TOKEN)
        self.assertFalse(section.capturing)
        self.assertIn(self.said("input.capture.cancelled"), self.toasts)

    def test_switching_to_the_keyboard_ends_the_capture_and_drops_late_tokens(self):
        section = self.section
        self.remap("a")
        section._on_device_picked("keyboard")
        self.assertFalse(section.capturing)
        self.reader.stop.assert_called_once()
        self.assertFalse(section._on_gamepad_token("3"))
        self.assertEqual(section._capture.binding_for("a"), "z")
        # Stopping a reader that is already gone is harmless.
        section._stop_gamepad_reader()
        self.reader.stop.assert_called_once()

    def test_a_reader_failure_says_which_problem_it_hit(self):
        section = self.section
        self.remap("a")
        self.assertFalse(section._on_gamepad_error("permission_denied"))
        self.assertFalse(section.capturing)
        self.assertIn(self.said("input.capture.permission_denied"), self.toasts)
        self.remap("a")
        section._on_gamepad_error("gone")
        self.assertIn(self.said("input.capture.no_gamepad"), self.toasts)

    def test_a_later_port_listens_on_its_own_pad_or_says_it_is_missing(self):
        section = self.section
        section._on_device_picked("gamepad_p2")
        with mock.patch.object(settings_input, "list_gamepads", return_value=["pad0"]):
            self.remap("a")
        self.assertFalse(section.capturing)
        self.assertIn(self.said("input.capture.port_unavailable", port=2), self.toasts)
        with mock.patch.object(settings_input, "list_gamepads", return_value=["pad0", "pad1"]):
            self.remap("a")
        self.assertTrue(section.capturing)
        self.assertEqual(self.make_reader.call_args.kwargs["device"], "pad1")


@needs_display
class TheDrawing(InputSectionCase):
    def test_a_drawn_button_starts_the_capture_and_the_caption_follows(self):
        section = self.section
        drawing = section._drawing
        self.assertIsNotNone(drawing)
        self.assertTrue(section.drawing_group.get_visible())
        self.assertIn("a", drawing.buttons)
        section._on_drawing_highlight("a")
        self.assertEqual(
            section.drawing_caption.get_text(),
            self.said("input.drawing.target", action=self.said("input.action.a"), binding="z"),
        )
        section._on_drawing_highlight(None)
        self.assertEqual(section.drawing_caption.get_text(), "")
        self.show()
        drawing.buttons["a"][0].emit("clicked")
        self.assertTrue(section.capturing)
        self.assertEqual(section._capture.active_action, "a")
        self.assertEqual(
            section.drawing_caption.get_text(),
            self.said(
                "input.drawing.target",
                action=self.said("input.action.a"),
                binding=self.said("input.capture.waiting"),
            ),
        )
        self.assertTrue(section.drawing_caption.has_css_class("accent"))
        self.assertEqual(drawing.lit, frozenset({"a"}))
        self.key("j")
        self.assertIs(self.focus_widget(), drawing.buttons["a"][0])
        self.assertFalse(section.drawing_caption.has_css_class("accent"))
        self.assertEqual(drawing.lit, frozenset())
        # The focus came back to the drawn button, so the caption names it.
        focused = self.said("input.drawing.target", action=self.said("input.action.a"), binding="j")
        self.assertEqual(section.drawing_caption.get_text(), focused)
        # A hotkey the drawing has no button for leaves the caption alone.
        self.remap("save_state")
        self.assertEqual(section.drawing_caption.get_text(), focused)
        self.assertFalse(section.drawing_caption.has_css_class("accent"))

    def test_a_device_change_keeps_the_drawing_and_a_console_change_replaces_it(self):
        section = self.section
        before = section._drawing
        section._on_device_picked("gamepad_p2")
        self.assertIs(section._drawing, before)
        # Ports 2-4 map no hotkeys: the drawn menu button is not remappable there.
        menu = before.buttons["menu_toggle"][0]
        self.assertFalse(menu.get_sensitive())
        self.assertEqual(menu.get_tooltip_text(), self.said("input.drawing.not_remappable"))
        section.select_console("FC")
        self.assertIsNot(section._drawing, before)
        self.assertEqual(section._drawing_console, "FC")
        with mock.patch.object(settings_input, "layout_for", return_value=None):
            section.select_console("GB")
        self.assertIsNone(section._drawing)
        self.assertFalse(section.drawing_group.get_visible())
        self.assertEqual(section.drawing_caption.get_text(), "")
        section.select_console("SFC")
        self.assertIsNotNone(section._drawing)
        self.assertTrue(section.drawing_group.get_visible())

    def test_held_keys_light_the_buttons_they_are_bound_to(self):
        section = self.section
        drawing = section._drawing
        z_key, x_key = Gdk.keyval_from_name("z"), Gdk.keyval_from_name("x")
        self.assertFalse(section._on_key_pressed(None, z_key, 52, 0))
        self.assertEqual(drawing.lit, frozenset({"a"}))
        section._on_key_released(None, z_key, 52, 0)
        self.assertEqual(drawing.lit, frozenset())
        section._on_key_pressed(None, x_key, 53, 0)
        self.assertEqual(drawing.lit, frozenset({"b"}))
        section._forget_held_keys()
        self.assertEqual(drawing.lit, frozenset())
        # During a capture the captured button is lit and nothing else is.
        self.remap("a")
        self.assertFalse(section._on_key_pressed(None, x_key, 53, 0))
        self.assertEqual(drawing.lit, frozenset({"a"}))
        section._cancel_capture()
        # With a pad as the device the keys light nothing.
        section._on_device_picked("gamepad_p1")
        self.assertFalse(section._on_key_pressed(None, z_key, 52, 0))
        self.assertEqual(drawing.lit, frozenset())

    def test_the_pad_is_read_for_the_drawing_while_a_pad_is_being_edited(self):
        section = self.section
        readers = []

        def make(on_change, device=None, on_error=None):
            reader = mock.Mock()
            reader.on_change = on_change
            readers.append(reader)
            return reader

        with mock.patch.object(settings_input, "make_held_reader", side_effect=make), mock.patch.object(
            self.win, "is_active", return_value=True
        ):
            self.show()
            self.assertEqual(readers, [])  # the keyboard reads nothing
            section._on_device_picked("gamepad_p1")
            self.assertEqual(len(readers), 1)
            readers[0].start.assert_called_once()
            self.assertFalse(section._on_pad_held(readers[0], {"0"}))
            self.assertEqual(section._drawing.lit, frozenset({"a"}))
            # A stale reader's report is ignored.
            section._on_pad_held(mock.Mock(), {"1"})
            self.assertEqual(section._drawing.lit, frozenset({"a"}))
            # A console with no drawing has nothing to light: the reader stops
            # and what it held is forgotten.
            with mock.patch.object(settings_input, "layout_for", return_value=None):
                section.select_console("GB")
            readers[0].stop.assert_called_once()
            self.assertIsNone(section._held_reader)
            self.assertEqual(section._held_pad, frozenset())
            section.select_console("SFC")
            self.assertEqual(len(readers), 2)
            section._on_pad_held(readers[1], {"0"})
            self.assertEqual(section._drawing.lit, frozenset({"a"}))
            # A capture takes the pad away, and the end of it gives it back.
            with mock.patch.object(settings_input, "make_capture_reader", return_value=mock.Mock()):
                self.remap("a")
            readers[1].stop.assert_called_once()
            self.assertIsNone(section._held_reader)
            self.assertEqual(section._drawing.lit, frozenset({"a"}))  # lit: being captured
            section._cancel_capture()
            self.assertEqual(len(readers), 3)
            self.assertEqual(section._drawing.lit, frozenset())
            # Another port with no pad on it: nothing to read.
            with mock.patch.object(settings_input, "list_gamepads", return_value=[]):
                section._on_device_picked("gamepad_p2")
            readers[2].stop.assert_called_once()
            self.assertIsNone(section._held_reader)
            section._on_device_picked("gamepad_p1")
            self.assertEqual(len(readers), 4)
            # Leaving the screen stops it.
            section._on_unmapped()
            self.assertIsNone(section._held_reader)
            readers[3].stop.assert_called_once()
        with mock.patch.object(self.win, "is_active", return_value=False):
            self.assertFalse(section._section_is_live())


@needs_display
class SavingAndResetting(InputSectionCase):
    def test_save_writes_the_bindings_and_relaunches_the_running_game_of_this_console(self):
        section = self.section
        manager = self.win.runtime_manager
        section._set_binding("a", "j")
        with mock.patch.object(self.win, "apply_input_changes_to_running_game") as apply:
            section.save()
            apply.assert_not_called()
            self.assertEqual(self.stored_bindings()["a"], "j")
            self.assertEqual(self.config.get_input_profile("SFC")["active_device"], "keyboard")
            self.assertIn(self.said("toast.input_saved", console="SFC"), self.toasts)
            self.assertFalse(section.has_unsaved())
            self.assertEqual(self.value_of(section._binding_rows["a"]), "j")
            with mock.patch.object(manager, "is_running", return_value=True):
                manager.active_rom = {"console": "GB"}
                section.save()
                apply.assert_not_called()
                manager.active_rom = None
                section.save()
                apply.assert_not_called()
                manager.active_rom = {"console": "SNES"}
                section.save()
                apply.assert_called_once()
                self.assertTrue(section.relaunch_row.get_visible())
            manager.active_rom = None

    def test_saving_a_later_port_records_whether_it_is_on(self):
        section = self.section
        section._on_device_picked("gamepad_p2")
        section.port_row.emit("clicked")
        self.assertTrue(section.has_unsaved())
        section.save()
        profile = self.config.get_input_profile("SFC")
        self.assertTrue(profile["devices"]["gamepad_p2"]["enabled"])
        self.assertNotEqual(profile["active_device"], "gamepad_p2")
        self.assertFalse(section.has_unsaved())

    def test_reset_asks_first_and_then_restores_the_defaults(self):
        section = self.section
        section._set_binding("a", "j")
        section.save()
        self.config.input_profiles.set_turbo_settings(
            "SFC", {"period": 20, "duty_cycle": 3, "mode": 1}
        )
        section._sync_turbo_rows()
        self.assertEqual(section.turbo_period_row.number_label.get_label(), "20")
        with self.caught_dialog() as caught:
            self.assertTrue(section.on_pad_action("favorite"))
        dialog = caught[-1]
        self.assertEqual(
            dialog.get_heading(), self.said("big_picture.input.reset.heading", console="SFC")
        )
        dialog.emit("response", "cancel")
        self.assertEqual(self.stored_bindings()["a"], "j")
        with self.caught_dialog() as caught:
            section.reset_row.emit("clicked")
        with mock.patch.object(self.win, "apply_input_changes_to_running_game") as apply:
            caught[-1].emit("response", "confirm")
        self.assertEqual(self.stored_bindings()["a"], "z")
        self.assertEqual(self.value_of(section._binding_rows["a"]), "z")
        self.assertEqual(section.turbo_period_row.number_label.get_label(), "6")
        self.assertIn(self.said("toast.input_reset", console="SFC"), self.toasts)
        apply.assert_not_called()

    def test_leaving_asks_only_when_something_is_unsaved(self):
        section = self.section
        left = []
        section.confirm_leave(lambda: left.append("now"))
        self.assertEqual(left, ["now"])
        section._set_binding("a", "j")
        with self.caught_dialog() as caught:
            section.confirm_leave(lambda: left.append("later"))
        self.assertEqual(left, ["now"])
        dialog = caught[-1]
        self.assertEqual(dialog.get_heading(), self.said("big_picture.input.leave.heading"))
        dialog.emit("response", "cancel")
        self.assertEqual(left, ["now"])
        with self.caught_dialog() as caught:
            section.confirm_leave(lambda: left.append("later"))
        caught[-1].emit("response", "confirm")
        self.assertEqual(left, ["now", "later"])
        # A capture still running is ended before the question is asked.
        self.remap("b")
        with self.caught_dialog():
            section.confirm_leave(lambda: None)
        self.assertFalse(section.capturing)


if __name__ == "__main__":
    unittest.main()

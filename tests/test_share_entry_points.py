"""Where Share nearby is reached from (#589): the game menu, the selection bar,
the console menu, the Import button's menu (#611) -- and the device name in
Preferences."""

from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Gtk

    from openemux.ui import console_sidebar as sidebar_module
    from openemux.ui.icons import SHARE_ICON
    from openemux.ui.context_menu import SEPARATOR, Submenu
    from openemux.ui.preferences import OpenEmuxPreferences
    from openemux.ui.rom_context import RomContextMenuServices


def _buttons(widget):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button):
            found.append(child)
        found.extend(_buttons(child))
        child = child.get_next_sibling()
    return found


@needs_display
class EntryPointTests(WindowCase):
    def share_entry(self, rom):
        return RomContextMenuServices(self.win).build_submenus(rom)[-1]

    def test_the_game_menu_shares_one_game_or_the_selection(self):
        rom, other = self.rom("SFC", 0), self.rom("SFC", 1)
        label, callback, icon = self.share_entry(rom)
        self.assertEqual((label, icon), ("Share Nearby…", SHARE_ICON))
        with mock.patch.object(self.win, "share_roms") as share:
            callback()
        share.assert_called_once_with([rom])
        self.win._on_selection_changed([rom, other])
        label, callback, _icon = self.share_entry(rom)
        self.assertEqual(label, "Share 2 Games Nearby…")
        with mock.patch.object(self.win, "share_roms") as share:
            callback()
        share.assert_called_once_with([rom, other])

    def test_the_selection_bar_button(self):
        rom = self.rom()
        self.win._on_selection_changed([rom])
        button = self.win.selection_share_button
        self.assertIn(button, _buttons(self.win.selection_bar))
        content = button.get_child()
        self.assertEqual((content.get_icon_name(), content.get_label()), (SHARE_ICON, "Share"))
        self.assertEqual(button.get_tooltip_text(), "Share Nearby")
        self.assertTrue(button.has_css_class("raised"))
        with mock.patch.object(self.win, "share_roms") as share:
            button.emit("clicked")
        share.assert_called_once_with([rom])

    def test_share_roms_opens_the_dialog_only_for_something(self):
        coordinator = mock.Mock()
        self.win._share_coordinator = coordinator
        self.win.share_roms([])
        coordinator.open_send.assert_not_called()
        self.win.share_roms(iter([self.rom()]))
        coordinator.open_send.assert_called_once_with([self.rom()])

    def menu_actions(self, model):
        actions = []
        for i in range(model.get_n_items()):
            section = model.get_item_link(i, "section")
            if section is not None:
                actions += self.menu_actions(section)
            else:
                actions.append(model.get_item_attribute_value(i, "action").get_string())
        return actions

    def test_receive_games_left_the_primary_menu(self):
        model = self.win.primary_menu_button.get_menu_model()
        self.assertNotIn("win.receive-games", self.menu_actions(model))

    def test_the_import_button_offers_import_and_receive(self):
        model = self.win.import_btn.get_menu_model()
        self.assertEqual(self.menu_actions(model), ["win.import", "win.receive-games"])
        self.assertEqual(
            [model.get_item_attribute_value(i, "label").get_string() for i in range(2)],
            ["Import ROMs…", "Receive Games…"],
        )
        coordinator = mock.Mock()
        self.win._share_coordinator = coordinator
        self.win.activate_action("win.receive-games", None)
        coordinator.open_receive.assert_called_once_with()

    def sidebar_entries(self, console):
        caught = []
        with mock.patch.object(
            sidebar_module, "build_context_popover", lambda entries: caught.append(entries) or Gtk.Popover()
        ), mock.patch.object(sidebar_module, "present_context_popover"):
            self.win.sidebar._show_menu(self.win.sidebar.find_row(console), console, 0, 0)
        return [
            entry for entry in caught[-1]
            if entry is not SEPARATOR and not isinstance(entry, Submenu)
        ]

    def test_the_console_menu_shares_the_whole_console(self):
        entries = {label: (action, icon) for label, action, icon in self.sidebar_entries("SFC")}
        self.assertEqual(entries["Share All Games Nearby…"], ("sidebar.share", SHARE_ICON))
        with mock.patch.object(self.win, "share_roms") as share:
            self.win.sidebar._act_share(None, None)
        self.assertEqual([r["name"] for r in share.call_args.args[0]], ["Chrono Trigger", "Super Metroid"])

    def test_a_console_with_no_games_offers_no_share(self):
        with mock.patch.object(sidebar_module, "roms_for_console", return_value=[]):
            labels = [label for label, _action, _icon in self.sidebar_entries("SFC")]
        self.assertNotIn("Share All Games Nearby…", labels)

    def test_the_device_name_in_preferences(self):
        prefs = OpenEmuxPreferences(self.win)
        row = prefs._share_name_row
        self.assertEqual(row.get_text(), "")
        row.set_text("  QA Box ")
        row.emit("apply")
        self.assertEqual(self.config.get_share_device_name(), "QA Box")
        self.assertEqual(OpenEmuxPreferences(self.win)._share_name_row.get_text(), "QA Box")

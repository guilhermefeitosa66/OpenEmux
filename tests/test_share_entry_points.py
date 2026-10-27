"""Where Share nearby is reached from (#589): the game menu, the selection bar,
the console menu, the primary menu -- and the device name in Preferences."""

from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Gtk

    from openemux.ui import console_sidebar as sidebar_module
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
        self.assertEqual((label, icon), ("Share Nearby…", "network-wireless-symbolic"))
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
        button = next(b for b in _buttons(self.win.selection_bar) if b.get_icon_name() == "network-wireless-symbolic")
        self.assertEqual(button.get_tooltip_text(), "Share Nearby")
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

    def test_receive_games_is_first_in_the_primary_menu(self):
        model = self.win.primary_menu_button.get_menu_model()
        first = model.get_item_link(0, "section")
        self.assertEqual(first.get_item_attribute_value(0, "label").get_string(), "Receive Games…")
        self.assertEqual(first.get_item_attribute_value(0, "action").get_string(), "win.receive-games")
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
        entries = {label: action for label, action, _icon in self.sidebar_entries("SFC")}
        self.assertEqual(entries["Share All Games Nearby…"], "sidebar.share")
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

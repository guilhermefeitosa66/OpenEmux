"""Per-ROM save-state browser (issue #73): list, play from, delete.

Pure filesystem over the managed ``savestate_directory`` tree; the only
runtime interaction is "play from this state", which launches the ROM with
``state_slot`` seeded and asks RetroArch to load it once the game is up.
"""

import logging
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.core import save_states

logger = logging.getLogger(__name__)

_THUMB_HEIGHT = 54


class SaveStateManagerDialog(Adw.Dialog):
    """The state list for one ROM, with play-from and delete per row."""

    def __init__(self, win, rom):
        super().__init__()
        self.win = win
        self.rom = rom
        self.t = win.t
        self.set_title(self.t("states.window.title", name=rom.get("name", "")))
        self.set_content_width(460)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_top(12)
        self._list.set_margin_bottom(12)
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)

        self._empty = Adw.StatusPage(
            icon_name="media-floppy-symbolic",
            title=self.t("states.empty.title"),
            description=self.t("states.empty.body"),
        )

        scroller = Gtk.ScrolledWindow()
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(480)
        self._stack = Gtk.Stack()
        self._stack.add_named(scroller, "list")
        self._stack.add_named(self._empty, "empty")
        scroller.set_child(self._list)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(self._stack)
        self.set_child(view)

        self._reload()

    def _states(self):
        directory = self.win.config_manager.get_console_states_dir(self.rom["console"])
        return save_states.list_states(directory, self.rom["path"])

    def _reload(self):
        while (row := self._list.get_row_at_index(0)) is not None:
            self._list.remove(row)
        states = self._states()
        for state in states:
            self._list.append(self._make_row(state))
        self._stack.set_visible_child_name("list" if states else "empty")

    def _make_row(self, state):
        stamp = datetime.fromtimestamp(state.mtime).strftime("%d/%m/%Y %H:%M")
        row = Adw.ActionRow(
            title=self.t("states.slot", slot=state.slot),
            subtitle=stamp,
        )
        if state.thumbnail is not None:
            try:
                picture = Gtk.Picture.new_for_paintable(
                    Gdk.Texture.new_from_filename(str(state.thumbnail))
                )
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_size_request(96, _THUMB_HEIGHT)
                row.add_prefix(picture)
            except GLib.Error:
                pass

        play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        play.set_tooltip_text(self.t("states.play_from"))
        play.set_valign(Gtk.Align.CENTER)
        play.add_css_class("flat")
        play.connect("clicked", lambda _b, s=state: self._play_from(s))
        row.add_suffix(play)

        delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete.set_tooltip_text(self.t("states.delete"))
        delete.set_valign(Gtk.Align.CENTER)
        delete.add_css_class("flat")
        delete.connect("clicked", lambda _b, s=state: self._confirm_delete(s))
        row.add_suffix(delete)
        return row

    def _play_from(self, state):
        self.close()
        self.win.launch_rom_at_state(self.rom, state.slot)

    def _confirm_delete(self, state):
        dialog = Adw.AlertDialog(
            heading=self.t("states.delete.heading", slot=state.slot),
            body=self.t("states.delete.body"),
        )
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("delete", self.t("dialog.delete.confirm"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "delete":
                return
            if save_states.delete_state(state):
                self.win._toast(self.t("states.toast.deleted", slot=state.slot))
            self._reload()

        dialog.connect("response", _on_response)
        dialog.present(self)

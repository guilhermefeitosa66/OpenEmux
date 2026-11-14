"""The quick menu: the View button's page of everything else.

What the desktop keeps in the header bar and the main menu -- search,
import, cover sync, sharing, a rescan, Settings, the way back to the
desktop, quitting -- as tiles a D-pad walks. B closes it, as every dialog.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from openemux.ui.bigpicture.widgets import Tile, body, once

#: Tiles per row: three fits a 1000 px sheet at 1080p with room to breathe.
COLUMNS = 3


def quick_menu_entries(t, stop_label=None):
    """The tiles, in order: ``(id, name, subtitle, style)``.

    ``stop_label`` names the background task to offer stopping, when one is
    running; the tile is absent otherwise.
    """
    entries = [
        ("search", t("big_picture.tile.search"), t("big_picture.tile.search.subtitle"), None),
        ("import", t("big_picture.tile.import"), t("big_picture.tile.import.subtitle"), None),
        ("covers", t("big_picture.tile.covers"), t("big_picture.tile.covers.subtitle"), None),
        ("share", t("big_picture.tile.share"), t("big_picture.tile.share.subtitle"), None),
        ("receive", t("big_picture.tile.receive"), t("big_picture.tile.receive.subtitle"), None),
        ("rescan", t("big_picture.tile.rescan"), t("big_picture.tile.rescan.subtitle"), None),
        ("settings", t("big_picture.tile.settings"), t("big_picture.tile.settings.subtitle"), None),
        ("desktop", t("big_picture.tile.desktop"), t("big_picture.tile.desktop.subtitle"), None),
        ("quit", t("big_picture.tile.quit"), None, "bp-danger"),
    ]
    if stop_label:
        entries.insert(0, ("stop", t("big_picture.tile.stop"), stop_label, "bp-danger"))
    return entries


class QuickMenuDialog(Adw.Dialog):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.win = shell.win
        self.t = shell.win.t
        self.set_title(self.t("big_picture.quick_menu.title"))
        self.add_css_class("bp-dialog")
        self.set_content_width(1040)
        self.set_content_height(760)
        self.set_presentation_mode(Adw.DialogPresentationMode.FLOATING)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        box.set_margin_top(36)
        box.set_margin_bottom(36)
        box.set_margin_start(40)
        box.set_margin_end(40)
        heading = Gtk.Label(label=self.t("big_picture.quick_menu.title"), xalign=0.0)
        heading.add_css_class("bp-dialog-heading")
        box.append(heading)
        box.append(body(self.t("big_picture.quick_menu.body")))

        self.tiles = []
        grid = Gtk.Grid(row_spacing=16, column_spacing=16)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        stop_label = self.win.tasks.current_label() if hasattr(self.win.tasks, "current_label") else None
        for index, (entry_id, name, subtitle, style) in enumerate(
            quick_menu_entries(self.t, stop_label)
        ):
            tile = Tile(name, subtitle, style=style, wide=True, icon_name=ICONS.get(entry_id))
            tile.entry_id = entry_id
            tile.on_activate = lambda entry_id=entry_id: self._choose(entry_id)
            grid.attach(tile, index % COLUMNS, index // COLUMNS, 1, 1)
            self.tiles.append(tile)
        box.append(grid)
        self.set_child(box)
        self.connect("map", self._on_map)

    def _on_map(self, *_args):
        if self.tiles:
            GLib.idle_add(once(self.tiles[0].grab_focus))

    def _choose(self, entry_id):
        self.close()
        # After the close, so the page the action opens is not pushed under
        # a dialog that is still fading out.
        GLib.idle_add(self._run, entry_id)

    def _run(self, entry_id):
        self.shell.run_quick_action(entry_id)
        return GLib.SOURCE_REMOVE


ICONS = {
    "stop": "process-stop-symbolic",
    "search": "system-search-symbolic",
    "import": "folder-download-symbolic",
    "covers": "emblem-photos-symbolic",
    "share": "send-to-symbolic",
    "receive": "network-receive-symbolic",
    "rescan": "view-refresh-symbolic",
    "settings": "preferences-system-symbolic",
    "desktop": "video-display-symbolic",
    "quit": "application-exit-symbolic",
}

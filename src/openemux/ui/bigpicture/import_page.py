"""The Import tab: Android's, with a file browser a pad can drive (issue 957).

An intro line, then "Choose files" (the accent button), "Choose a whole
folder" and "Receive games" (Share nearby); under them, every console with
the file types it takes. GTK's file chooser cannot be driven with a pad,
so both choices open Big Picture's own browser (``file_browser``,
maintainer decision 3), and what it hands back goes to the window's import
flow with each file sent where its extension says, as Android does.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from openemux.core.big_picture_shelf import full_name
from openemux.core.systems import SYSTEMS
from openemux.ui.bigpicture.widgets import BigPage, body, caps, page_heading
from openemux.ui.console_icons import ConsolePixelArt, console_texture, console_texture_1x

MODE_FILES = "files"
MODE_FOLDER = "folder"


def _big_button(label, icon_name, css):
    button = Gtk.Button()
    button.add_css_class(css)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    box.set_halign(Gtk.Align.CENTER)
    box.append(Gtk.Image.new_from_icon_name(icon_name))
    box.append(Gtk.Label(label=label))
    button.set_child(box)
    return button


class FormatRow(Gtk.Box):
    """A console and the extensions it takes: not focusable, information only."""

    def __init__(self, system):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.add_css_class("bp-row")
        self.add_css_class("bp-list-row")
        texture = console_texture(system["id"])
        if texture is not None:
            # Crisp at a whole multiple, soft grid from 4x (issue 966).
            icon = ConsolePixelArt([texture, console_texture_1x(system["id"])])
            icon.set_size_request(40, 40)
        else:
            icon = Gtk.Image.new_from_icon_name("input-gaming-symbolic")
        icon.set_valign(Gtk.Align.CENTER)
        self.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=full_name(system["id"], system["display_name"]), xalign=0.0)
        title.add_css_class("bp-row-title")
        text.append(title)
        extensions = sorted({ext.lower().lstrip(".") for ext in system.get("extensions", ())} | {"zip"})
        self.extensions_label = Gtk.Label(label="  ".join(f".{ext}" for ext in extensions), xalign=0.0)
        self.extensions_label.add_css_class("bp-row-subtitle")
        self.extensions_label.set_wrap(True)
        text.append(self.extensions_label)
        self.append(text)


class ImportPage(BigPage):
    context = "bp-page"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.tab.import"), crumbs=[], tag="bp-import")
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        column.append(page_heading(t("big_picture.import.title")))
        column.append(body(t("big_picture.import.lead")))
        self.files_button = _big_button(t("big_picture.import.files"), "document-open-symbolic",
                                        "bp-accent-button")
        self.files_button.connect("clicked", lambda _b: self.choose(MODE_FILES))
        column.append(self.files_button)
        self.folder_button = _big_button(t("big_picture.import.folder"), "folder-open-symbolic",
                                         "bp-plain-button")
        self.folder_button.connect("clicked", lambda _b: self.choose(MODE_FOLDER))
        column.append(self.folder_button)
        self.receive_button = _big_button(t("big_picture.import.receive"), "send-to-symbolic",
                                          "bp-plain-button")
        # Looked up at the click: the window's flow is what a test patches.
        self.receive_button.connect("clicked", lambda _b: self.win.receive_games())
        column.append(self.receive_button)
        formats = caps(t("big_picture.import.formats"))
        formats.set_margin_top(12)
        column.append(formats)
        self.format_rows = []
        for system in SYSTEMS:
            row = FormatRow(system)
            column.append(row)
            self.format_rows.append(row)
        self.body.append(self.scrolled(column))

    def choose(self, mode):
        """Open the pad browser; what it picks is imported."""
        return self.shell.open_browser(mode, self.import_paths)

    def import_paths(self, paths):
        """Each file (or the folder's files) to the console its extension names."""
        paths = [str(path) for path in paths or ()]
        if not paths:
            return False
        self.win.imports.begin(paths, detect=True)
        return True

    def focus_default(self):
        return self.files_button.grab_focus()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.choose")),
            (g["back"], t("hints.back")),
            (g["consoles"], t("big_picture.hints.tabs")),
        ]


__all__ = ["ImportPage", "FormatRow", "MODE_FILES", "MODE_FOLDER"]

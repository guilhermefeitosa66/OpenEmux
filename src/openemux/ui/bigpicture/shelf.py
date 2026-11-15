"""The Shelf: Big Picture's first page, the Android gamepad layout's (issue 957).

"Shelf" in big letters, "10 consoles · 145 games" under it, a "Search all
consoles" field and an accent "Import ROMs" button on the right; the task
banners; then the console cards, three to a row. "All games" comes first,
then Favorites and the playlists, then one card per console that has games,
each in the console's own color (``core.big_picture_shelf``) with its pixel
art, its short code over its name, and how many games it holds. A on a card
opens its games; Y opens the console order; View searches every console.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Graphene, Gsk, Gtk, Pango

from openemux.core.big_picture_shelf import css_class, short_name
from openemux.ui.bigpicture.banners import TaskBanners
from openemux.ui.bigpicture.widgets import BigPage, page_heading
from openemux.ui.console_icons import console_texture
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID

#: Cards in a row, as on Android's landscape shelf.
COLUMNS = 3
# The space between the cards, both ways (unscaled).
GRID_SPACING = 24


def pixel_scale(space, size):
    """The largest whole multiple of ``size`` px that fits in ``space`` px.

    Never below 1: a box smaller than the art still shows it, at 1x.
    """
    if size <= 0 or space <= 0:
        return 1
    return max(1, int(space) // int(size))


def pixel_rect(width, height, tex_width, tex_height):
    """Where the art goes in a ``width`` x ``height`` box: ``(x, y, w, h)``.

    One whole multiple for both sides, so the pixels stay square, centred.
    """
    factor = min(pixel_scale(width, tex_width), pixel_scale(height, tex_height))
    w, h = tex_width * factor, tex_height * factor
    return (width - w) // 2, (height - h) // 2, w, h


class PixelArt(Gtk.Widget):
    """A console's pixel art at a whole multiple, nearest-neighbour (issue 964).

    ``Gtk.Picture`` scales with linear filtering, which turns 32 px pixel art
    blown up four times into a blur. This draws it at the largest whole
    multiple that fits the box the stylesheet gives it, each pixel a sharp
    square.
    """

    def __init__(self, texture):
        super().__init__()
        self.texture = texture

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            size = self.texture.get_width()
        else:
            size = self.texture.get_height()
        return size, size, -1, -1

    def do_snapshot(self, snapshot):
        x, y, w, h = pixel_rect(
            self.get_width(), self.get_height(),
            self.texture.get_width(), self.texture.get_height(),
        )
        bounds = Graphene.Rect().init(x, y, w, h)
        snapshot.append_scaled_texture(self.texture, Gsk.ScalingFilter.NEAREST, bounds)


class ShelfCard(Gtk.Button):
    """A console's card: its art, its short code, its name, its count."""

    def __init__(self, scope_id, eyebrow, name, count, texture=None, icon_name=None, style=None):
        super().__init__()
        self.scope_id = scope_id
        self.add_css_class("bp-shelf-card")
        if style:
            self.add_css_class(style)
        self.set_hexpand(True)
        # The gap between the art and the text is the stylesheet's
        # (``border-spacing``), so it scales with everything else.
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.set_valign(Gtk.Align.CENTER)
        if texture is not None:
            # The art box is the stylesheet's size, not expanding, so the
            # text column gets the rest of the card, for the name.
            art = self.art = PixelArt(texture)
        else:
            # Centred in the box without expanding it (an expanding child
            # would take width from the name).
            art = Gtk.CenterBox()
            self.art = Gtk.Image.new_from_icon_name(icon_name or "input-gaming-symbolic")
            art.set_center_widget(self.art)
        art.add_css_class("bp-shelf-art")
        art.set_valign(Gtk.Align.CENTER)
        box.append(art)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        self.eyebrow_label = Gtk.Label(label=eyebrow, xalign=0.0)
        self.eyebrow_label.add_css_class("bp-shelf-eyebrow")
        text.append(self.eyebrow_label)
        self.name_label = Gtk.Label(label=name, xalign=0.0)
        self.name_label.add_css_class("bp-shelf-name")
        self.name_label.set_wrap(True)
        self.name_label.set_wrap_mode(Pango.WrapMode.WORD)
        self.name_label.set_lines(2)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(self.name_label)
        self.count_label = Gtk.Label(label=count or "", xalign=0.0)
        self.count_label.add_css_class("bp-shelf-count")
        text.append(self.count_label)
        box.append(text)
        self.set_child(box)


class ShelfPage(BigPage):
    context = "bp-shelf"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.shelf.title"), crumbs=[], tag="bp-shelf")
        self.cards = []

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.heading = page_heading(t("big_picture.shelf.title"))
        self.heading.set_hexpand(True)
        header.append(self.heading)
        self.search_button = Gtk.Button()
        self.search_button.add_css_class("bp-search")
        self.search_button.set_valign(Gtk.Align.CENTER)
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        search_box.append(Gtk.Image.new_from_icon_name("system-search-symbolic"))
        search_box.append(Gtk.Label(label=t("big_picture.shelf.search"), xalign=0.0))
        self.search_button.set_child(search_box)
        self.search_button.connect("clicked", lambda _b: self.shell.open_search())
        header.append(self.search_button)
        self.import_button = Gtk.Button()
        self.import_button.add_css_class("bp-accent-button")
        self.import_button.set_valign(Gtk.Align.CENTER)
        import_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        import_box.append(Gtk.Image.new_from_icon_name("folder-download-symbolic"))
        import_box.append(Gtk.Label(label=t("big_picture.shelf.import")))
        self.import_button.set_child(import_box)
        self.import_button.connect("clicked", lambda _b: self.shell.open_import())
        header.append(self.import_button)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        column.append(header)
        self.banners = TaskBanners(shell)
        column.append(self.banners)
        consoles = Gtk.Label(label=t("big_picture.shelf.consoles"), xalign=0.0)
        consoles.add_css_class("bp-section-title")
        column.append(consoles)
        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(GRID_SPACING)
        self.grid.set_row_spacing(GRID_SPACING)
        self.grid.set_column_homogeneous(True)
        self.grid.set_margin_bottom(24)
        column.append(self.grid)
        self.scroller = self.scrolled(column)
        self.body.append(self.scroller)

    # -- the cards ----------------------------------------------------------------
    def refresh(self):
        """Rebuild the cards from the library as it is now."""
        t = self.win.t
        # The library can change under the pad (a scan, a sync ending): the
        # card it was on comes back focused, not dropped with the old ones.
        focus = self.win.get_focus()
        focused = next(
            (card.scope_id for card in self.cards
             if focus is not None and (focus is card or focus.is_ancestor(card))),
            None,
        )
        child = self.grid.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.grid.remove(child)
            child = following
        self.cards = []
        consoles = 0
        for scope_id in self.shell.library_scopes():
            card = self._card_for(scope_id)
            if card is None:
                continue
            if card.style_kind == "console":
                consoles += 1
            card.connect("clicked", lambda _b, scope_id=scope_id: self.shell.open_library(scope_id))
            index = len(self.cards)
            self.grid.attach(card, index % COLUMNS, index // COLUMNS, 1, 1)
            self.cards.append(card)
        total = self.shell.game_count(ALL_CONSOLES_ID)
        self.heading.subtitle_label.set_label(
            t("big_picture.shelf.summary", consoles=consoles, games=self._games_label(total))
        )
        self.heading.subtitle_label.set_visible(True)
        self.sync_banners()
        if focused is not None:
            card = next((card for card in self.cards if card.scope_id == focused), None)
            if card is not None:
                card.grab_focus()
            else:
                # Its scope is gone (the last favorite unstarred): the first card.
                self.focus_default()

    def _games_label(self, count):
        t = self.win.t
        if count == 1:
            return t("header.subtitle.one_game")
        return t("header.subtitle.games", count=count)

    def _card_for(self, scope_id):
        """The card of a scope; Recently played has a tab of its own, so none."""
        from openemux.ui.bigpicture.shell import scope_kind

        win, t = self.win, self.win.t
        kind = scope_kind(scope_id)
        if kind == "recent" or scope_id == RECENT_ID:
            return None
        count = self._games_label(self.shell.game_count(scope_id))
        name = win.sidebar.label_for(scope_id)
        if kind == "all":
            card = ShelfCard(scope_id, t("big_picture.shelf.library"), t("big_picture.shelf.all_games"),
                             count, icon_name="view-grid-symbolic", style="bp-shelf-all")
        elif kind == "favorites" or scope_id == FAVORITES_ID:
            card = ShelfCard(scope_id, t("big_picture.shelf.library"), name, count,
                             icon_name="starred-symbolic")
        elif kind == "collection":
            card = ShelfCard(scope_id, t("big_picture.shelf.playlist"), name, count,
                             icon_name="user-bookmarks-symbolic")
        else:
            card = ShelfCard(scope_id, short_name(scope_id), name, count,
                             texture=console_texture(scope_id), style=css_class(scope_id))
        card.style_kind = kind
        return card

    def sync_banners(self):
        self.banners.sync()

    # -- the pad --------------------------------------------------------------------
    def on_pad_action(self, action):
        """Y: the order of the consoles (Settings › ROM folder, where it lives)."""
        if action == "favorite":
            self.shell.open_settings("library")
            return True
        return False

    def focus_default(self):
        if self.cards:
            return self.cards[0].grab_focus()
        return self.import_button.grab_focus()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.open")),
            (g["favorite"], t("big_picture.hints.order")),
            (g["search"], t("hints.search")),
            (g["consoles"], t("big_picture.hints.tabs")),
        ]


__all__ = ["ShelfCard", "ShelfPage", "PixelArt", "COLUMNS", "GRID_SPACING", "pixel_rect", "pixel_scale"]

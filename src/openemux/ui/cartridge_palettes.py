"""Saved colors and palettes in the Custom Color dialog (issue 983).

Below the hex field the dialog offers colors to start from:

* **Saved** -- every custom color applied to a game, most recent first, so
  the same color goes on the next cartridge without typing it again. A saved
  color can be removed; the games painted with it keep it.
* **A palette** -- "Shell Colors" (the named shells), the Android skin
  editor's presets, or one of the user's own. The user's palettes are edited
  here: add the current color, move a color, remove it, rename, duplicate,
  delete. Presets are read-only; duplicating one gives an editable copy.

Every edit goes straight to the store (``CartridgeColorStore``), so a palette
made here survives a Cancel of the dialog: it is a tool, not part of the
color being picked.
"""

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from openemux.core import cartridge_colors
from openemux.ui.context_menu import _swatch_widget

#: How tall the palette list grows before it scrolls.
PALETTE_LIST_MAX_HEIGHT = 300
#: Color dots beside a palette's name in the list.
PALETTE_DOTS = 4


def _palette_menu(items):
    """A ``Gio.Menu`` of ``(label, action, target)``; a ``None`` target means none."""
    menu = Gio.Menu()
    for label, action, target in items:
        item = Gio.MenuItem.new(label, None)
        if target is None:
            item.set_action_and_target_value(action, None)
        else:
            item.set_action_and_target_value(action, GLib.Variant("s", target))
        menu.append_item(item)
    return menu


def _focus_near(buttons, index, fallback):
    """Focus the swatch now at ``index`` (or the one before it, or ``fallback``)."""
    if buttons:
        buttons[min(index, len(buttons) - 1)][1].grab_focus()
    elif fallback is not None:
        fallback.grab_focus()


class PaletteArea:
    """The "Saved" row and the palette picker, as one widget for the dialog.

    ``get_color`` returns the color being picked; ``on_pick(hex)`` makes a
    swatch's color the picked one. ``parent`` is what the small dialogs
    (name, delete) are presented over.
    """

    def __init__(self, t, store, get_color, on_pick, parent):
        self.t = t
        self.store = store
        self.get_color = get_color
        self.on_pick = on_pick
        self.parent = parent
        self.palette_id = store.selected_palette()
        self.swatch_buttons = {}
        self.palette_buttons = []
        self.saved_buttons = []
        self.list_rows = {}
        self.prompt = None
        self._menu_target = None

        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self._install_actions()

        self.saved_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        saved_label = Gtk.Label(label=t("cartridge_color.dialog.saved"), xalign=0)
        saved_label.add_css_class("dim-label")
        self.saved_box.append(saved_label)
        self.saved_flow = self._flow()
        self.saved_box.append(self.saved_flow)
        self.widget.append(self.saved_box)

        palette_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.palette_label = Gtk.Label(xalign=0)
        self.palette_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.palette_label.set_hexpand(True)
        self.palette_button = Gtk.MenuButton()
        self.palette_button.set_child(self.palette_label)
        self.palette_button.set_always_show_arrow(True)
        self.palette_button.set_hexpand(True)
        self.palette_button.set_tooltip_text(t("cartridge_color.dialog.palette"))
        self.palette_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.palette")]
        )
        self.palette_button.set_popover(self._build_palette_popover())
        header.append(self.palette_button)
        self.options_button = Gtk.MenuButton()
        self.options_button.set_icon_name("view-more-symbolic")
        self.options_button.add_css_class("flat")
        self.options_button.set_tooltip_text(t("cartridge_color.dialog.palette_options"))
        self.options_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.palette_options")]
        )
        header.append(self.options_button)
        palette_box.append(header)
        self.palette_flow = self._flow()
        palette_box.append(self.palette_flow)
        self.widget.append(palette_box)

        # One menu for every editable swatch, pointed at the one it is for.
        self.swatch_menu = Gtk.PopoverMenu()
        self.swatch_menu.set_has_arrow(True)
        self.swatch_menu.set_parent(self.widget)

        self.refresh_saved()
        self.refresh_palette()

    # -- building blocks -------------------------------------------------

    def _flow(self):
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(12)
        flow.set_min_children_per_line(6)
        flow.set_homogeneous(True)
        return flow

    def _swatch(self, color, name, menu=None, step=None, remove=None):
        """A round swatch button picking ``color``; ``menu`` makes it editable.

        ``menu`` is a callable returning the menu's items for this color; the
        same menu opens on a right click, the Menu key and Shift+F10. Delete
        runs ``remove``, and with ``step`` Alt+Left/Right moves it.
        """
        button = Gtk.Button()
        button.add_css_class("flat")
        button.add_css_class("color-swatch")
        button.set_halign(Gtk.Align.CENTER)
        button.set_child(_swatch_widget(color))
        button.set_tooltip_text(name)
        button.update_property([Gtk.AccessibleProperty.LABEL], [name])
        button.connect("clicked", lambda _b, c=color: self.on_pick(c))
        if menu is not None:
            click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            click.connect("pressed", lambda *_a, b=button, c=color: self.open_menu(b, menu(c)))
            button.add_controller(click)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_swatch_key, button, color, menu, step, remove)
            button.add_controller(keys)
        return button

    def _on_swatch_key(
        self, _controller, keyval, _keycode, state, button, color, menu, step, remove
    ):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
            remove(color)
            return True
        if keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK
        ):
            self.open_menu(button, menu(color))
            return True
        if step is not None and state & Gdk.ModifierType.ALT_MASK:
            moves = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1}
            if keyval in moves:
                step(color, moves[keyval])
                return True
        return False

    def open_menu(self, button, items):
        """Show the swatch menu at ``button``: ``items`` are ``(label, callback)``."""
        self._menu_target = items
        model = _palette_menu(
            (label, "swatch.run", str(index)) for index, (label, _cb) in enumerate(items)
        )
        self.swatch_menu.set_menu_model(model)
        if self.widget.get_native() is None:
            # Not on screen (yet): a popup needs a surface to hang from.
            return
        ok, bounds = button.compute_bounds(self.widget)
        if ok:
            rect = Gdk.Rectangle()
            rect.x, rect.y = int(bounds.get_x()), int(bounds.get_y())
            rect.width, rect.height = int(bounds.get_width()), int(bounds.get_height())
            self.swatch_menu.set_pointing_to(rect)
        self.swatch_menu.popup()

    def _install_actions(self):
        swatch = Gio.SimpleActionGroup()
        run = Gio.SimpleAction.new("run", GLib.VariantType.new("s"))
        run.connect("activate", self._on_swatch_action)
        swatch.add_action(run)
        self.widget.insert_action_group("swatch", swatch)

        palette = Gio.SimpleActionGroup()
        for name, callback in (
            ("new", self.new_palette),
            ("rename", self.rename_palette),
            ("duplicate", self.duplicate_palette),
            ("delete", self.delete_palette),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            palette.add_action(action)
        self.palette_actions = palette
        self.widget.insert_action_group("palette", palette)

    def _on_swatch_action(self, _action, param):
        items = self._menu_target or []
        index = int(param.get_string())
        if 0 <= index < len(items):
            items[index][1]()

    # -- saved colors ----------------------------------------------------

    def _saved_menu(self, color):
        return [(self.t("cartridge_color.dialog.remove"), lambda c=color: self.forget_saved(c))]

    def refresh_saved(self):
        self.saved_flow.remove_all()
        saved = self.store.saved_colors()
        self.saved_buttons = []
        for color in saved:
            button = self._swatch(
                color, color.upper(), menu=self._saved_menu, remove=self.forget_saved
            )
            self.saved_flow.append(button)
            self.saved_buttons.append((color, button))
        self.saved_box.set_visible(bool(saved))

    def forget_saved(self, color):
        colors = [value for value, _b in self.saved_buttons]
        index = colors.index(color) if color in colors else 0
        self.store.forget_saved_color(color)
        self.refresh_saved()
        _focus_near(self.saved_buttons, index, None)

    # -- the palette list ------------------------------------------------

    def _build_palette_popover(self):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(PALETTE_LIST_MAX_HEIGHT)
        scroller.set_propagate_natural_width(True)
        self.palette_list = Gtk.ListBox()
        self.palette_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.palette_list.add_css_class("navigation-sidebar")
        self.palette_list.connect("row-activated", self._on_row_activated)
        scroller.set_child(self.palette_list)
        box.append(scroller)
        box.append(Gtk.Separator())
        self.new_button = Gtk.Button(label=self.t("cartridge_color.dialog.new_palette"))
        self.new_button.add_css_class("flat")
        self.new_button.connect("clicked", lambda _b: self.new_palette())
        box.append(self.new_button)
        popover.set_child(box)
        popover.connect("show", lambda _p: self.refresh_list())
        self.palette_popover = popover
        return popover

    def _palettes(self):
        """Every palette as ``(id, name, colors, editable)``, in list order."""
        shell = cartridge_colors.SHELL_PALETTE_ID
        rows = [(shell, self.t(cartridge_colors.palette_name_key(shell)),
                 cartridge_colors.builtin_palette_colors(shell), False)]
        for palette_id, _colors in cartridge_colors.PRESET_PALETTES:
            rows.append((palette_id, self.t(cartridge_colors.palette_name_key(palette_id)),
                         cartridge_colors.builtin_palette_colors(palette_id), False))
        for palette in self.store.user_palettes():
            rows.append((palette["id"], palette["name"], palette["colors"], True))
        return rows

    def _heading_row(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        label.set_margin_top(6)
        row = Gtk.ListBoxRow(child=label)
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_focusable(False)
        return row

    def refresh_list(self):
        self.palette_list.remove_all()
        self.list_rows = {}
        palettes = self._palettes()
        presets = {palette_id for palette_id, _c in cartridge_colors.PRESET_PALETTES}
        for index, (palette_id, name, colors, editable) in enumerate(palettes):
            if palette_id in presets and palettes[index - 1][0] not in presets:
                self.palette_list.append(self._heading_row(self.t("cartridge_color.dialog.presets")))
            if editable and not palettes[index - 1][3]:
                self.palette_list.append(
                    self._heading_row(self.t("cartridge_color.dialog.your_palettes"))
                )
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=name, xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_width_chars(14)
            label.set_max_width_chars(24)
            label.set_hexpand(True)
            box.append(label)
            dots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            dots.add_css_class("palette-dots")
            for color in colors[:PALETTE_DOTS]:
                dots.append(_swatch_widget(color))
            box.append(dots)
            check = Gtk.Image.new_from_icon_name("object-select-symbolic")
            current = palette_id == self.palette_id
            check.set_opacity(1 if current else 0)
            box.append(check)
            row = Gtk.ListBoxRow(child=box)
            row.palette_id = palette_id
            row.update_property([Gtk.AccessibleProperty.LABEL], [name])
            # The check is drawn; a screen reader hears the state instead.
            row.update_state([Gtk.AccessibleState.SELECTED], [current])
            self.palette_list.append(row)
            self.list_rows[palette_id] = row

    def _on_row_activated(self, _list, row):
        self.palette_popover.popdown()
        self.select(row.palette_id)

    def select(self, palette_id):
        if self.store.palette_colors(palette_id) is None:
            return
        self.store.select_palette(palette_id)
        self.palette_id = palette_id
        self.refresh_palette()

    # -- the selected palette --------------------------------------------

    def _palette_menu_items(self, color):
        t = self.t
        return [
            (t("cartridge_color.dialog.move_left"), lambda c=color: self.move(c, -1)),
            (t("cartridge_color.dialog.move_right"), lambda c=color: self.move(c, 1)),
            (t("cartridge_color.dialog.remove"), lambda c=color: self.remove(c)),
        ]

    def refresh_palette(self):
        """The header, the options menu and the swatches of the selected palette."""
        self.palette_id = self.store.selected_palette()
        palette_id = self.palette_id
        user = self.store.user_palette(palette_id)
        if user is not None:
            name = user["name"]
        else:
            name = self.t(cartridge_colors.palette_name_key(palette_id))
        self.palette_label.set_label(name)
        self.palette_button.set_tooltip_text(name)

        t = self.t
        options = [(t("cartridge_color.dialog.duplicate_palette"), "palette.duplicate", None)]
        if user is not None:
            options = [
                (t("cartridge_color.dialog.rename_palette"), "palette.rename", None),
                options[0],
                (t("cartridge_color.dialog.delete_palette"), "palette.delete", None),
            ]
        self.options_button.set_menu_model(_palette_menu(options))
        # No room for another palette: say so by what can be pressed.
        room = len(self.store.user_palettes()) < cartridge_colors.USER_PALETTES_MAX
        for action in ("new", "duplicate"):
            self.palette_actions.lookup_action(action).set_enabled(room)
        self.new_button.set_sensitive(room)

        self.palette_flow.remove_all()
        self.swatch_buttons = {}
        self.palette_buttons = []
        self.add_button = None
        if palette_id == cartridge_colors.SHELL_PALETTE_ID:
            for entry in cartridge_colors.CARTRIDGE_COLOR_TABLE:
                color_id, key, swatch = entry
                if color_id == cartridge_colors.DEFAULT_COLOR_ID:
                    continue
                button = self._swatch(cartridge_colors.parse_hex(swatch), t(key))
                self.palette_flow.append(button)
                self.swatch_buttons[color_id] = button
                self.palette_buttons.append((cartridge_colors.parse_hex(swatch), button))
            return
        editable = user is not None
        self._colors = list(self.store.palette_colors(palette_id))
        for color in self._colors:
            button = self._swatch(
                color,
                color.upper(),
                menu=self._palette_menu_items if editable else None,
                step=self.move if editable else None,
                remove=self.remove if editable else None,
            )
            self.palette_flow.append(button)
            self.palette_buttons.append((color, button))
        if editable:
            self.add_button = Gtk.Button.new_from_icon_name("list-add-symbolic")
            self.add_button.add_css_class("flat")
            self.add_button.add_css_class("circular")
            self.add_button.add_css_class("palette-add")
            self.add_button.set_halign(Gtk.Align.CENTER)
            self.add_button.set_tooltip_text(t("cartridge_color.dialog.add_color"))
            self.add_button.update_property(
                [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.add_color")]
            )
            self.add_button.connect("clicked", lambda _b: self.add_current())
            self.palette_flow.append(self.add_button)
            self.color_changed()

    def color_changed(self):
        """The "+" only adds a color the palette does not have, while it has room."""
        if self.add_button is None:
            return
        # Asked on every drag step: the colors kept by refresh_palette, not
        # a store read per pointer event.
        colors = self._colors
        self.add_button.set_sensitive(
            self.get_color() not in colors
            and len(colors) < cartridge_colors.PALETTE_COLORS_MAX
        )

    def add_current(self):
        if self.store.add_palette_color(self.palette_id, self.get_color()):
            self.refresh_palette()

    def remove(self, color):
        colors = [value for value, _b in self.palette_buttons]
        index = colors.index(color) if color in colors else 0
        if self.store.remove_palette_color(self.palette_id, color):
            self.refresh_palette()
            # Focus stays in the row, so a second Delete removes the next.
            _focus_near(self.palette_buttons, index, self.add_button)

    def move(self, color, step):
        if self.store.move_palette_color(self.palette_id, color, step):
            self.refresh_palette()
            for value, button in self.palette_buttons:
                if value == color:
                    button.grab_focus()

    # -- palette actions -------------------------------------------------

    def _current_name(self):
        user = self.store.user_palette(self.palette_id)
        if user is not None:
            return user["name"]
        return self.t(cartridge_colors.palette_name_key(self.palette_id))

    def ask_name(self, heading, action_label, initial, on_done):
        """A small dialog asking for a palette name; ``on_done(name)`` on confirm."""
        t = self.t
        dialog = Adw.AlertDialog(heading=heading)
        dialog.add_response("cancel", t("dialog.cancel"))
        dialog.add_response("ok", action_label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")
        entry = Gtk.Entry(text=initial)
        entry.set_max_length(cartridge_colors.PALETTE_NAME_MAX)
        entry.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.palette_name")]
        )
        entry.set_placeholder_text(t("cartridge_color.dialog.palette_name"))

        def sync(_entry=None):
            dialog.set_response_enabled("ok", bool(entry.get_text().strip()))

        entry.connect("changed", sync)
        sync()
        dialog.set_extra_child(entry)

        answered = []

        def respond(_dialog, response):
            # Once: Enter answers and then closes, and the close must not
            # count as a second answer.
            if answered:
                return
            answered.append(response)
            self.prompt = None
            if response == "ok" and entry.get_text().strip():
                on_done(entry.get_text())

        def activate(_entry):
            # The default response does not follow a button that was
            # insensitive when the dialog opened, so Enter is wired here.
            if dialog.get_response_enabled("ok"):
                dialog.emit("response", "ok")
                dialog.force_close()

        dialog.connect("response", respond)
        entry.connect("activate", activate)
        dialog.entry = entry
        self.prompt = dialog
        dialog.present(self.parent)
        return dialog

    def new_palette(self):
        self.palette_popover.popdown()
        t = self.t

        def create(name):
            if self.store.create_palette(name, [self.get_color()]):
                self.refresh_palette()

        return self.ask_name(
            t("cartridge_color.dialog.new_palette_title"),
            t("cartridge_color.dialog.create"), "", create,
        )

    def rename_palette(self):
        palette_id = self.palette_id

        def rename(name):
            if self.store.rename_palette(palette_id, name):
                self.refresh_palette()

        t = self.t
        return self.ask_name(
            t("cartridge_color.dialog.rename_palette_title"),
            t("cartridge_color.dialog.rename"), self._current_name(), rename,
        )

    def duplicate_palette(self):
        base = self._current_name()
        extra = len(self.t("cartridge_color.dialog.palette_copy", name=""))
        # Shorten the name, not the suffix: a cut "(Copy)" makes a twin.
        base = base[: max(1, cartridge_colors.PALETTE_NAME_MAX - extra)].rstrip()
        name = self.t("cartridge_color.dialog.palette_copy", name=base)
        if self.store.duplicate_palette(self.palette_id, name):
            self.refresh_palette()

    def delete_palette(self):
        t = self.t
        palette_id = self.palette_id
        dialog = Adw.AlertDialog(
            heading=t("cartridge_color.dialog.delete_palette_title", name=self._current_name()),
            body=t("cartridge_color.dialog.delete_palette_body"),
        )
        dialog.add_response("cancel", t("dialog.cancel"))
        dialog.add_response("delete", t("cartridge_color.dialog.delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            self.prompt = None
            if response == "delete" and self.store.delete_palette(palette_id):
                self.refresh_palette()

        dialog.connect("response", respond)
        self.prompt = dialog
        dialog.present(self.parent)
        return dialog

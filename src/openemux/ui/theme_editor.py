"""The theme editor (issues 1011 and 1012).

One dialog for a new theme and for editing one: a list of sections, a row
per setting with its own reset-to-base, "Reset All", contrast warnings, a
drawn preview of the app and a switch that paints the whole app with the
draft while it is open. Nothing reaches the disk until Save; Cancel (or
closing the dialog any other way) puts back whatever was on screen before.

Layout follows the Claude Design projects "#1011 Theme editor" and "#1012
Theme editor: shapes, backgrounds, sharing, Big Picture": section list,
controls, preview side by side; in a narrow window the preview moves above
the controls and the section list becomes a "Section" row.

Issue 1012 added the rows that are not colors -- numbers on a slider, a few
choices, the font, the background images -- and "Start from a Palette".
A picked image goes straight into a *staging* copy of the theme's images
folder (``ThemeStore.stage``), re-encoded; Save moves that copy into the
theme, Cancel throws it away, so the person's own file is never referenced.
"""

import logging
import math
import threading

from gi.repository import Adw, GdkPixbuf, GLib, Gtk, Pango, PangoCairo

from openemux.core import cartridge_colors, theme_images
from openemux.core.contrast import WCAG_AA
from openemux.core.custom_themes import (
    DENSITY_PRESETS,
    FONT_NAME,
    IMAGE_AREAS,
    KEYS_BY_NAME,
    KIND_CHOICE,
    KIND_COLOR,
    KIND_FONT,
    KIND_IMAGE,
    SECTIONS,
    contrast_problems,
    keys_in_section,
    seed_from_palette,
    warnings_for,
)
from openemux.core.systems import get_system_display_name
from openemux.ui import theming
from openemux.ui.cartridge_palettes import PaletteArea
from openemux.ui.color_picker import ColorPicker
from openemux.ui.file_dialogs import image_filters
from openemux.ui.theme_preview import NARROW_PREVIEW_HEIGHT, PREVIEW_HEIGHT, ThemePreview

logger = logging.getLogger(__name__)

NARROW_BREAKPOINT = "max-width: 760sp"
SECTION_ICONS = {
    "colors": "applications-graphics-symbolic",
    "text": "text-x-generic-symbolic",
    "accent": "starred-symbolic",
    "borders": "view-grid-symbolic",
    "icons": "emblem-photos-symbolic",
    "typography": "document-properties-symbolic",
    "spacing": "view-list-symbolic",
    "backgrounds": "image-x-generic-symbolic",
}
SWATCH_WIDTH, SWATCH_HEIGHT = 40, 26
THUMB_WIDTH, THUMB_HEIGHT = 64, 40
SCALE_WIDTH = 160
#: The preview's copy of a background, drawn small: no need for the 2560 px.
PREVIEW_IMAGE_SIDE = 480
PREVIEW_CONSOLES = ("SFC", "GBA", "MD")
PREVIEW_CONSOLE_SHORT = "SNES"
PREVIEW_GAMES = ("Star Pilot", "Cave Run", "Puzzle Tower")
#: Palette dots beside a palette's name in "Start from a Palette".
PALETTE_DOTS = 5


def _spawn(target):
    threading.Thread(target=target, daemon=True).start()


def installed_fonts():
    """The font families on this system a theme can name, sorted."""
    families = PangoCairo.FontMap.get_default().list_families()
    names = {family.get_name() for family in families}
    return sorted((name for name in names if FONT_NAME.fullmatch(name)), key=str.casefold)


def value_text(t, spec, value):
    """"12 px", "110%": a number with its unit."""
    if spec.unit == "%":
        return t("theme_editor.unit.percent", value=value)
    return t("theme_editor.unit.px", value=value)


class Swatch(Gtk.DrawingArea):
    """The rounded color chip a row's button shows."""

    def __init__(self, color, width=SWATCH_WIDTH, height=SWATCH_HEIGHT):
        super().__init__()
        self.color = color
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_draw_func(self._draw)

    def set_color(self, color):
        self.color = color
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        r, g, b = (int(self.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        radius = min(6, height / 2)
        x0, y0, x1, y1 = 0.5, 0.5, width - 0.5, height - 0.5
        cr.new_sub_path()
        cr.arc(x1 - radius, y0 + radius, radius, -math.pi / 2, 0)
        cr.arc(x1 - radius, y1 - radius, radius, 0, math.pi / 2)
        cr.arc(x0 + radius, y1 - radius, radius, math.pi / 2, math.pi)
        cr.arc(x0 + radius, y0 + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(r, g, b)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.6)
        cr.stroke()


class SettingRow(Adw.ActionRow):
    """What every row shares: a title, a reset button, ``refresh``."""

    def __init__(self, editor, key, title=None):
        super().__init__(title=title or editor.t(f"theme_editor.key.{key}"))
        self.editor = editor
        self.key = key
        self._syncing = False
        self.set_use_markup(False)
        self.reset_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self.reset_button.set_valign(Gtk.Align.CENTER)
        self.reset_button.add_css_class("flat")
        self.reset_button.set_tooltip_text(editor.t("theme_editor.reset"))
        self.reset_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [editor.t("theme_editor.reset")]
        )
        self.reset_button.connect("clicked", lambda _b: editor.reset_value(key))

    def _pick(self, value):
        if not self._syncing:
            self.editor.set_value(self.key, value)

    def _sync(self, change):
        """Move a control to the draft's value without counting it as a pick."""
        self._syncing = True
        try:
            change()
        finally:
            self._syncing = False

    def _same_as_base(self, changed_text=""):
        changed = self.editor.draft.is_changed(self.key)
        self.set_subtitle(changed_text if changed else self.editor.t("theme_editor.same_as_base"))

    def refresh(self, problems):
        self.reset_button.set_sensitive(self.editor.draft.is_changed(self.key))


class ColorRow(SettingRow):
    """One color setting: its value or warning, reset, and the picker.

    The picker's popover also holds the saved colors and the palettes of
    the cartridge Custom Color dialog (issue 983), from the same store,
    built the first time the popover opens.
    """

    def __init__(self, editor, key):
        super().__init__(editor, key)
        color = editor.draft.effective(key)

        self.warning_icon = Gtk.Image(icon_name="dialog-warning-symbolic")
        self.warning_icon.add_css_class("warning")
        self.warning_icon.set_visible(False)
        self.add_suffix(self.warning_icon)
        self.add_suffix(self.reset_button)

        self.swatch = Swatch(color)
        self.picker = ColorPicker(editor.t, color, on_changed=self._pick)
        self.popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.popover_box, f"set_margin_{side}")(12)
        self.popover_box.set_size_request(300, -1)
        self.popover_box.append(self.picker)
        self.palettes = None
        self.popover = Gtk.Popover()
        self.popover.set_child(self.popover_box)
        self.popover.connect("show", lambda _p: self.ensure_palettes())
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_child(self.swatch)
        self.menu_button.set_popover(self.popover)
        self.menu_button.set_valign(Gtk.Align.CENTER)
        self.menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [self.get_title()]
        )
        self.add_suffix(self.menu_button)
        self.set_activatable_widget(self.menu_button)

    def ensure_palettes(self):
        """The Saved row and the palette picker, made on first use."""
        if self.palettes is None and self.editor.color_store is not None:
            self.palettes = PaletteArea(
                self.editor.t, self.editor.color_store,
                lambda: self.picker.color, self.picker.set_color, self.editor,
            )
            self.popover_box.append(self.palettes.widget)
        return self.palettes

    def refresh(self, problems):
        super().refresh(problems)
        t = self.editor.t
        draft = self.editor.draft
        color = draft.effective(self.key)
        self.swatch.set_color(color)
        if self.picker.color != color:
            # Following a reset: moving the picker must not count as a pick.
            self._sync(lambda: self.picker.set_color(color))
        if self.palettes is not None:
            self.palettes.color_changed()
        warnings = warnings_for(draft, self.key, problems)
        self.warning_icon.set_visible(bool(warnings))
        if warnings:
            other, ratio = warnings[0]
            self.set_subtitle(t(
                "theme_editor.contrast_warning",
                other=t(f"theme_editor.key.{other}"),
                # Never rounded up: 4.46 must not read as the 4.5 it misses.
                ratio=f"{math.floor(ratio * 10) / 10:.1f}",
                needed=f"{WCAG_AA:.1f}",
            ))
        else:
            self._same_as_base(color.upper())


class NumberRow(SettingRow):
    """A number on a slider (or a spin button for small exact ranges)."""

    #: Ranges this short are picked exactly with a spin button.
    SPIN_SPAN = 5

    def __init__(self, editor, key, title=None):
        super().__init__(editor, key, title=title)
        self.spec = KEYS_BY_NAME[key]
        self.add_suffix(self.reset_button)
        low, high = self.spec.minimum, self.spec.maximum
        if high - low <= self.SPIN_SPAN:
            self.control = Gtk.SpinButton.new_with_range(low, high, 1)
        else:
            self.control = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
            self.control.set_draw_value(False)
            self.control.set_size_request(SCALE_WIDTH, -1)
        self.control.set_valign(Gtk.Align.CENTER)
        self._sync(lambda: self.control.set_value(editor.draft.effective(key)))
        self.control.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        self.control.connect("value-changed", self._on_value_changed)
        self.add_suffix(self.control)

    def _on_value_changed(self, control):
        self._pick(int(round(control.get_value())))

    def refresh(self, problems):
        super().refresh(problems)
        value = self.editor.draft.effective(self.key)
        if int(round(self.control.get_value())) != value:
            self._sync(lambda: self.control.set_value(value))
        self._same_as_base(value_text(self.editor.t, self.spec, value))


class ChoiceRow(SettingRow):
    """One of a few values, as a linked group of toggle buttons."""

    def __init__(self, editor, key, labels):
        super().__init__(editor, key)
        self.spec = KEYS_BY_NAME[key]
        self.add_suffix(self.reset_button)
        box = Gtk.Box()
        box.add_css_class("linked")
        box.set_valign(Gtk.Align.CENTER)
        self.buttons = {}
        first = None
        for choice in self.spec.choices:
            button = Gtk.ToggleButton(label=labels(choice))
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._on_toggled, choice)
            box.append(button)
            self.buttons[choice] = button
        box.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        self.add_suffix(box)
        self._sync(lambda: self.buttons[editor.draft.effective(key)].set_active(True))

    def _on_toggled(self, button, choice):
        if button.get_active():
            self._pick(choice)

    def refresh(self, problems):
        super().refresh(problems)
        value = self.editor.draft.effective(self.key)
        if not self.buttons[value].get_active():
            self._sync(lambda: self.buttons[value].set_active(True))
        self._same_as_base()


class DensityRow(Adw.PreferencesRow):
    """Compact / Default / Comfortable: presets of the density setting.

    The title above, the three presets across the row under it (beside the
    title they squeezed it in a narrow column). The exact value is the
    "Fine adjustment" row below; a preset reads as active only while the
    value is exactly its own.
    """

    def __init__(self, editor):
        super().__init__(title=editor.t("theme_editor.key.density"))
        self.editor = editor
        self._syncing = False
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(column, f"set_margin_{side}")(12)
        label = Gtk.Label(label=self.get_title(), xalign=0)
        column.append(label)
        box = Gtk.Box(homogeneous=True)
        box.add_css_class("linked")
        box.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        self.buttons = {}
        for name, value in DENSITY_PRESETS:
            button = Gtk.ToggleButton(label=editor.t(f"theme_editor.density.{name}"))
            button.connect("toggled", self._on_toggled, value)
            box.append(button)
            self.buttons[value] = button
        column.append(box)
        self.set_child(column)
        self.set_activatable(False)

    def _on_toggled(self, button, value):
        if self._syncing:
            return
        if button.get_active():
            self.editor.set_value("density", value)
        else:
            # Not a radio group (none is active off the presets): a click on
            # the active one keeps it on.
            self.refresh(None)

    def refresh(self, problems):
        current = self.editor.draft.effective("density")
        self._syncing = True
        try:
            for value, button in self.buttons.items():
                button.set_active(value == current)
        finally:
            self._syncing = False


class FontRow(SettingRow):
    """The font family: "Same as base", then every installed family."""

    def __init__(self, editor, key):
        super().__init__(editor, key)
        self.add_suffix(self.reset_button)
        families = editor.fonts()
        current = editor.draft.effective(key)
        if current and current not in families:
            # A theme from another machine: keep showing what it names.
            families = sorted(families + [current], key=str.casefold)
        self.choices = [""] + families
        model = Gtk.StringList.new([editor.t("theme_editor.same_as_base")] + families)
        self.dropdown = Gtk.DropDown(model=model)
        self.dropdown.set_enable_search(True)
        self.dropdown.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        )
        self.dropdown.set_valign(Gtk.Align.CENTER)
        self.dropdown.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        self._sync(lambda: self.dropdown.set_selected(self.choices.index(current)))
        self.dropdown.connect("notify::selected", self._on_selected)
        self.add_suffix(self.dropdown)

    def _on_selected(self, dropdown, _param):
        index = dropdown.get_selected()
        if self._syncing or not 0 <= index < len(self.choices):
            return
        if index == 0:
            self.editor.reset_value(self.key)
        else:
            self._pick(self.choices[index])

    def refresh(self, problems):
        super().refresh(problems)
        current = self.editor.draft.effective(self.key)
        index = self.choices.index(current) if current in self.choices else 0
        if self.dropdown.get_selected() != index:
            self._sync(lambda: self.dropdown.set_selected(index))
        self._same_as_base()


class ImageRow(SettingRow):
    """An area's background picture: thumbnail, Choose… and Remove."""

    def __init__(self, editor, key):
        super().__init__(editor, key)
        self.area = key[: -len("_image")]
        self.error = None
        self.thumbnail = Gtk.Picture()
        self.thumbnail.set_size_request(THUMB_WIDTH, THUMB_HEIGHT)
        self.thumbnail.set_content_fit(Gtk.ContentFit.COVER)
        self.thumbnail.set_can_shrink(True)
        self.thumbnail.set_valign(Gtk.Align.CENTER)
        self.thumbnail.add_css_class("theme-image-thumbnail")
        self.thumbnail.update_property(
            [Gtk.AccessibleProperty.LABEL], [editor.t("theme_editor.image.thumbnail")]
        )
        self.add_prefix(self.thumbnail)
        self._thumb_path = None
        self.choose_button = Gtk.Button(label=editor.t("theme_editor.image.choose"))
        self.choose_button.set_valign(Gtk.Align.CENTER)
        self.choose_button.connect("clicked", lambda _b: self.choose())
        self.add_suffix(self.choose_button)
        self.remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        self.remove_button.set_valign(Gtk.Align.CENTER)
        self.remove_button.add_css_class("flat")
        self.remove_button.set_tooltip_text(editor.t("theme_editor.image.remove"))
        self.remove_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [editor.t("theme_editor.image.remove")]
        )
        self.remove_button.connect("clicked", lambda _b: self.remove())
        self.add_suffix(self.remove_button)

    def choose(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.editor.t("theme_editor.image.dialog_title"))
        dialog.set_modal(True)
        filters, default = image_filters(self.editor.t("theme_editor.image.filter"))
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        root = self.editor.get_root()
        dialog.open(root if isinstance(root, Gtk.Window) else None, None, self._on_chosen)
        return dialog

    def _on_chosen(self, dialog, result):
        try:
            chosen = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        if chosen is not None and chosen.get_path():
            self.take(chosen.get_path())

    def take(self, path):
        """Copy ``path`` into the staging folder, off the main thread."""
        self.error = None
        self.choose_button.set_sensitive(False)
        name = f"{self.area}.png"
        target = self.editor.staging / name

        def work():
            try:
                theme_images.import_image(path, target)
            except (theme_images.ThemeImageError, OSError) as exc:
                logger.info("Background image refused: %s", exc)
                GLib.idle_add(self._taken, None)
                return
            GLib.idle_add(self._taken, name)

        self.editor.spawn(work)

    def _taken(self, name):
        self.choose_button.set_sensitive(True)
        if name is None:
            self.error = self.editor.t("theme_editor.image.error")
            self.refresh(None)
            return GLib.SOURCE_REMOVE
        # Same file name, new picture: the thumbnail must reload.
        self._thumb_path = None
        self.editor.set_value(self.key, name)
        return GLib.SOURCE_REMOVE

    def remove(self):
        self.error = None
        self.editor.reset_value(self.key)

    def refresh(self, problems):
        super().refresh(problems)
        t = self.editor.t
        path = self.editor.draft.image_path(self.area)
        self.remove_button.set_sensitive(path is not None)
        if path != self._thumb_path:
            self._thumb_path = path
            self.thumbnail.set_filename(str(path) if path is not None else None)
        if self.error:
            self.set_subtitle(self.error)
            self.add_css_class("error")
            return
        self.remove_css_class("error")
        warnings = warnings_for(self.editor.draft, self.key, problems) if problems else []
        if warnings:
            other, ratio = warnings[0]
            self.set_subtitle(t(
                "theme_editor.contrast_warning",
                other=t(f"theme_editor.key.{other}"),
                ratio=f"{math.floor(ratio * 10) / 10:.1f}",
                needed=f"{WCAG_AA:.1f}",
            ))
            return
        size = theme_images.image_size(path) if path is not None else None
        if size is not None:
            self.set_subtitle(t("theme_editor.image.size", width=size[0], height=size[1]))
        else:
            self.set_subtitle(t("theme_editor.image.none"))


class ThemeEditorDialog(Adw.Dialog):
    def __init__(self, win, store, theme, is_new, on_saved=None, spawn=None):
        super().__init__()
        self.win = win
        self.t = win.t
        self.store = store
        self.is_new = is_new
        self.on_saved = on_saved
        self.spawn = spawn or _spawn
        config = getattr(win, "config_manager", None)
        self.color_store = getattr(config, "cartridge_colors", None)
        self.draft = theme.copy()
        # The images the editor changes live in a copy until Save.
        self.staging = store.stage(theme)
        self.draft.image_dir = self.staging
        self.live = False
        self.closed = False
        self._paint_source = None
        self._fonts = None
        self._preview_images = {}
        self._averages = {}
        self.saved = False
        self.narrow = False
        self.rows = {}
        self.extra_rows = []
        self.section_rows = {}
        self.section_icons = {}

        t = self.t
        self.set_title(t("theme_editor.title.new" if is_new else "theme_editor.title.edit"))
        self.set_content_width(1100)
        self.set_content_height(740)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        self.window_title = Adw.WindowTitle(
            title=self.get_title(),
            subtitle=t(f"theme_editor.subtitle.{theme.base}", name=theme.name),
        )
        header.set_title_widget(self.window_title)
        self.cancel_button = Gtk.Button(label=t("dialog.cancel"))
        self.cancel_button.connect("clicked", lambda _b: self.close())
        header.pack_start(self.cancel_button)
        self.save_button = Gtk.Button(label=t("theme_editor.save"))
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", lambda _b: self.save())
        header.pack_end(self.save_button)
        header.pack_end(self._build_palette_button())
        view.add_top_bar(header)
        view.set_content(self._build_body())
        self.set_child(view)
        self.set_default_widget(self.save_button)

        self.narrow_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(NARROW_BREAKPOINT)
        )
        self.narrow_breakpoint.connect("apply", lambda _b: self.set_narrow(True))
        self.narrow_breakpoint.connect("unapply", lambda _b: self.set_narrow(False))
        self.add_breakpoint(self.narrow_breakpoint)

        self.connect("closed", self._on_closed)
        self.show_section(SECTIONS[0])
        self.refresh()

    # -- layout ----------------------------------------------------------

    def fonts(self):
        if self._fonts is None:
            self._fonts = installed_fonts()
        return list(self._fonts)

    def _make_rows(self, spec):
        t = self.t
        if spec.kind == KIND_COLOR:
            return [ColorRow(self, spec.key)]
        if spec.kind == KIND_IMAGE:
            return [ImageRow(self, spec.key)]
        if spec.kind == KIND_FONT:
            return [FontRow(self, spec.key)]
        if spec.kind == KIND_CHOICE:
            if spec.key.endswith("_fit"):
                return [ChoiceRow(self, spec.key, lambda c: t(f"theme_editor.fit.{c}"))]
            return [ChoiceRow(self, spec.key, str)]
        if spec.key == "density":
            # The presets row, then the exact value under it.
            return [DensityRow(self),
                    NumberRow(self, spec.key, title=t("theme_editor.density_fine"))]
        return [NumberRow(self, spec.key)]

    def _build_body(self):
        t = self.t
        self.body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.sidebar.set_size_request(240, -1)
        self.sidebar.add_css_class("theme-editor-sections")
        for side in ("top", "bottom", "start", "end"):
            getattr(self.sidebar, f"set_margin_{side}")(8)
        self.section_list = Gtk.ListBox()
        self.section_list.add_css_class("navigation-sidebar")
        for section in SECTIONS:
            row = Gtk.ListBoxRow()
            row.section = section
            box = Gtk.Box(spacing=10)
            box.append(Gtk.Image(icon_name=SECTION_ICONS[section]))
            label = Gtk.Label(label=t(f"theme_editor.section.{section}"), xalign=0)
            label.set_hexpand(True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(label)
            icon = Gtk.Image(icon_name="dialog-warning-symbolic")
            icon.add_css_class("warning")
            icon.update_property(
                [Gtk.AccessibleProperty.LABEL], [t("theme_editor.has_warning")]
            )
            icon.set_visible(False)
            box.append(icon)
            row.set_child(box)
            self.section_list.append(row)
            self.section_rows[section] = row
            self.section_icons[section] = icon
        self.section_list.connect("row-selected", self._on_section_row_selected)
        sections_scroller = Gtk.ScrolledWindow()
        sections_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sections_scroller.set_vexpand(True)
        sections_scroller.set_child(self.section_list)
        self.sidebar.append(sections_scroller)
        self.reset_all_button = Gtk.Button(label=t("theme_editor.reset_all"))
        self.reset_all_button.connect("clicked", lambda _b: self.reset_all())
        self.sidebar.append(self.reset_all_button)
        self.body.append(self.sidebar)

        self.controls_scroller = Gtk.ScrolledWindow()
        self.controls_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.controls_scroller.set_hexpand(True)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.controls, f"set_margin_{side}")(18)
        self.section_combo_list = Gtk.ListBox()
        self.section_combo_list.add_css_class("boxed-list")
        self.section_combo_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.section_combo = Adw.ComboRow(title=t("theme_editor.section"))
        self.section_combo.set_model(
            Gtk.StringList.new([t(f"theme_editor.section.{s}") for s in SECTIONS])
        )
        self.section_combo.connect("notify::selected", self._on_section_combo_changed)
        self.section_combo_list.append(self.section_combo)
        self.section_combo_list.set_visible(False)
        self.controls.append(self.section_combo_list)

        self.stack = Gtk.Stack()
        for section in SECTIONS:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            groups = {}
            for spec in keys_in_section(section):
                group = groups.get(spec.group)
                if group is None:
                    group = Adw.PreferencesGroup(
                        title=t(f"theme_editor.group.{spec.group}"),
                        description=t(f"theme_editor.group.{spec.group}.description"),
                    )
                    groups[spec.group] = group
                    page.append(group)
                for row in self._make_rows(spec):
                    group.add(row)
                    if isinstance(row, SettingRow):
                        self.rows[spec.key] = row
                    else:
                        self.extra_rows.append(row)
            self.stack.add_named(page, section)
        self.controls.append(self.stack)
        self.controls_scroller.set_child(self.controls)
        self.body.append(self.controls_scroller)

        self.preview_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.preview_column.set_size_request(380, -1)
        for side in ("top", "bottom", "end"):
            getattr(self.preview_column, f"set_margin_{side}")(18)
        heading = Gtk.Label(label=t("theme_editor.preview"), xalign=0)
        heading.add_css_class("heading")
        self.preview_column.append(heading)
        self.preview = ThemePreview(self._preview_labels(), self.draft.effective_values())
        self.preview.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("theme_editor.preview")]
        )
        self.preview_column.append(self.preview)
        live_list = Gtk.ListBox()
        live_list.add_css_class("boxed-list")
        live_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.live_row = Adw.SwitchRow(title=t("theme_editor.apply_live"))
        self.live_row.connect("notify::active", lambda row, _p: self.set_live(row.get_active()))
        live_list.append(self.live_row)
        self.preview_column.append(live_list)
        self.body.append(self.preview_column)

        self.error_label = Gtk.Label(label=t("theme_editor.save_failed"), wrap=True)
        self.error_label.add_css_class("error")
        self.error_label.set_visible(False)
        self.controls.append(self.error_label)
        return self.body

    def _preview_labels(self):
        # Console names are names, the same in every language; the games
        # are made up, like the devbox's demo library.
        t = self.t
        consoles = [get_system_display_name(system) for system in PREVIEW_CONSOLES]
        return {
            "title": consoles[0],
            "consoles": consoles,
            "favorites": t("sidebar.favorites"),
            "games": list(PREVIEW_GAMES),
            "console": PREVIEW_CONSOLE_SHORT,
            "played": t("theme_editor.preview.played"),
            "play": t("details.play"),
        }

    def set_narrow(self, narrow):
        """Stack the preview above the controls; a Section row for the list."""
        if narrow == self.narrow:
            return
        self.narrow = narrow
        self.sidebar.set_visible(not narrow)
        self.section_combo_list.set_visible(narrow)
        if narrow:
            self.body.remove(self.preview_column)
            self.preview_column.set_margin_start(0)
            self.preview_column.set_margin_top(0)
            self.preview_column.set_margin_end(0)
            self.controls.prepend(self.preview_column)
            self.preview.set_content_height(NARROW_PREVIEW_HEIGHT)
            self.sidebar.remove(self.reset_all_button)
            self.controls.append(self.reset_all_button)
        else:
            self.controls.remove(self.preview_column)
            self.preview_column.set_margin_top(18)
            self.preview_column.set_margin_end(18)
            self.body.append(self.preview_column)
            self.preview.set_content_height(PREVIEW_HEIGHT)
            self.controls.remove(self.reset_all_button)
            self.sidebar.append(self.reset_all_button)

    # -- Start from a Palette ----------------------------------------------

    def _build_palette_button(self):
        t = self.t
        self.palette_list = Gtk.ListBox()
        self.palette_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.palette_list.add_css_class("navigation-sidebar")
        self.palette_list.connect("row-activated", lambda _l, row: self.apply_palette(row.colors))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hint = Gtk.Label(label=t("theme_editor.palette.hint"), xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        hint.set_max_width_chars(32)
        box.append(hint)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(420)
        scroller.set_child(self.palette_list)
        box.append(scroller)
        self.palette_popover = Gtk.Popover()
        self.palette_popover.set_child(box)
        self.palette_popover.connect("show", lambda _p: self.refresh_palettes())
        self.palette_button = Gtk.MenuButton()
        self.palette_button.set_popover(self.palette_popover)
        self.palette_button.set_child(Adw.ButtonContent(
            icon_name="color-select-symbolic", label=t("theme_editor.palette.button")
        ))
        self.palette_button.set_tooltip_text(t("theme_editor.palette.hint"))
        return self.palette_button

    def palettes(self):
        """(name, colors) of every palette to start from: presets, then theirs."""
        t = self.t
        found = [
            (t(cartridge_colors.palette_name_key(palette_id)), list(colors))
            for palette_id, colors in cartridge_colors.PRESET_PALETTES
        ]
        if self.color_store is not None:
            found.extend(
                (palette["name"], list(palette["colors"]))
                for palette in self.color_store.user_palettes()
            )
        return found

    def refresh_palettes(self):
        while (child := self.palette_list.get_first_child()) is not None:
            self.palette_list.remove(child)
        for name, colors in self.palettes():
            row = Gtk.ListBoxRow()
            row.colors = colors
            line = Gtk.Box(spacing=10)
            label = Gtk.Label(label=name, xalign=0)
            label.set_hexpand(True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            line.append(label)
            for color in colors[:PALETTE_DOTS]:
                line.append(Swatch(color, 12, 12))
            row.set_child(line)
            usable = bool(seed_from_palette(self.draft.base, colors))
            row.set_activatable(usable)
            row.set_sensitive(usable)
            self.palette_list.append(row)

    def apply_palette(self, colors):
        values = seed_from_palette(self.draft.base, colors)
        if not values:
            return
        self.draft.values.update(values)
        self.palette_popover.popdown()
        self.refresh()

    # -- sections --------------------------------------------------------

    def show_section(self, section):
        self.current_section = section
        self.stack.set_visible_child_name(section)
        row = self.section_rows[section]
        if self.section_list.get_selected_row() is not row:
            self.section_list.select_row(row)
        index = SECTIONS.index(section)
        if self.section_combo.get_selected() != index:
            self.section_combo.set_selected(index)

    def _on_section_row_selected(self, _list, row):
        if row is not None and row.section != getattr(self, "current_section", None):
            self.show_section(row.section)

    def _on_section_combo_changed(self, combo, _param):
        index = combo.get_selected()
        if 0 <= index < len(SECTIONS) and SECTIONS[index] != self.current_section:
            self.show_section(SECTIONS[index])

    # -- values ----------------------------------------------------------

    def set_value(self, key, value):
        self.draft.values[key] = value
        self.refresh()

    def reset_value(self, key):
        self.draft.values.pop(key, None)
        self.refresh()

    def reset_all(self):
        self.draft.values.clear()
        self.refresh()

    def _on_background_ready(self):
        if not self.closed:
            self.refresh()

    def _image_colors(self, backgrounds):
        colors = {}
        for area, background in backgrounds.items():
            path = background["path"]
            if path not in self._averages:
                self._averages[path] = theme_images.average_color(path)
            if self._averages[path]:
                colors[area] = self._averages[path]
        return colors

    def _preview_image(self, path):
        if path not in self._preview_images:
            try:
                self._preview_images[path] = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(path), PREVIEW_IMAGE_SIDE, PREVIEW_IMAGE_SIDE, True
                )
            except GLib.Error:
                self._preview_images[path] = None
        return self._preview_images[path]

    def refresh(self):
        backgrounds = theming.prepare_backgrounds(
            self.draft.base, self.draft.values, self.staging,
            on_ready=self._on_background_ready,
        )
        problems = contrast_problems(self.draft, self._image_colors(backgrounds))
        for row in self.rows.values():
            row.refresh(problems)
        for row in self.extra_rows:
            row.refresh(problems)
        for area in IMAGE_AREAS:
            has_image = self.draft.image_path(area) is not None
            for suffix in ("_fit", "_dim", "_blur"):
                self.rows[f"{area}_image{suffix}"].set_sensitive(has_image)
        for section in SECTIONS:
            has = any(
                warnings_for(self.draft, spec.key, problems)
                for spec in keys_in_section(section)
            )
            self.section_icons[section].set_visible(has)
        self.reset_all_button.set_sensitive(bool(self.draft.values))
        images = {}
        for area, background in backgrounds.items():
            pixbuf = self._preview_image(background["path"])
            if pixbuf is not None:
                images[area] = (pixbuf, background["fit"])
        self.preview.set_theme(self.draft.effective_values(), images)
        if self.live and self._paint_source is None:
            # A drag fires many changes a frame; restyling the whole app for
            # each would stall it. One repaint per idle, with the latest draft.
            self._paint_source = GLib.idle_add(self._paint_live)

    def _paint_live(self):
        self._paint_source = None
        if self.live:
            theming.paint(self.draft.base, self.draft.values, self.staging)
        return GLib.SOURCE_REMOVE

    def set_live(self, live):
        if live == self.live:
            return
        self.live = live
        if live:
            theming.paint(self.draft.base, self.draft.values, self.staging)
        else:
            theming.restore()

    # -- save / cancel ---------------------------------------------------

    def save(self):
        try:
            if self.is_new:
                theme = self.store.create(
                    self.draft.name, self.draft.base, self.draft.values,
                    images_from=self.staging,
                )
            else:
                theme = self.store.save(self.draft, images_from=self.staging)
        except OSError as exc:
            logger.warning("Could not save theme %s: %s", self.draft.name, exc)
            self.error_label.set_visible(True)
            return None
        self.saved = True
        self.close()
        if self.on_saved is not None:
            self.on_saved(theme)
        return theme

    def _on_closed(self, *_args):
        # Saved: the caller applies what was saved. Otherwise, whatever the
        # live switch painted goes back to what was there before.
        self.closed = True
        if self.live and not self.saved:
            theming.restore()
        self.live = False
        self.store.discard(self.staging)


def open_theme_editor(win, parent, store, theme, is_new, on_saved=None):
    dialog = ThemeEditorDialog(win, store, theme, is_new, on_saved=on_saved)
    dialog.present(parent)
    return dialog

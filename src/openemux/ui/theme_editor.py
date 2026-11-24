"""The theme editor (issue 1011).

One dialog for a new theme and for editing one: a list of sections, a row
per setting with its own reset-to-base, "Reset All", contrast warnings, a
drawn preview of the app and a switch that paints the whole app with the
draft while it is open. Nothing reaches the disk until Save; Cancel (or
closing the dialog any other way) puts back whatever was on screen before.

Layout follows the Claude Design project "#1011 Theme editor": section list,
controls, preview side by side; in a narrow window the preview moves above
the controls and the section list becomes a "Section" row.
"""

import logging
import math

from gi.repository import Adw, Gtk

from openemux.core.contrast import WCAG_AA
from openemux.core.custom_themes import (
    SECTIONS,
    contrast_problems,
    keys_in_section,
    warnings_for,
)
from openemux.core.systems import get_system_display_name
from openemux.ui import theming
from openemux.ui.color_picker import ColorPicker
from openemux.ui.theme_preview import NARROW_PREVIEW_HEIGHT, PREVIEW_HEIGHT, ThemePreview

logger = logging.getLogger(__name__)

NARROW_BREAKPOINT = "max-width: 760sp"
SECTION_ICONS = {
    "colors": "applications-graphics-symbolic",
    "text": "format-text-bold-symbolic",
    "accent": "starred-symbolic",
}
SWATCH_WIDTH, SWATCH_HEIGHT = 40, 26
PREVIEW_CONSOLES = ("SFC", "GBA", "MD")
PREVIEW_CONSOLE_SHORT = "SNES"
PREVIEW_GAMES = ("Star Pilot", "Cave Run", "Puzzle Tower")


class Swatch(Gtk.DrawingArea):
    """The rounded color chip a row's button shows."""

    def __init__(self, color):
        super().__init__()
        self.color = color
        self.set_content_width(SWATCH_WIDTH)
        self.set_content_height(SWATCH_HEIGHT)
        self.set_draw_func(self._draw)

    def set_color(self, color):
        self.color = color
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        r, g, b = (int(self.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        radius = 6
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


class ColorRow(Adw.ActionRow):
    """One color setting: its value or warning, reset, and the picker."""

    def __init__(self, editor, key):
        super().__init__(title=editor.t(f"theme_editor.key.{key}"))
        self.editor = editor
        self.key = key
        self._syncing = False
        self.set_use_markup(False)
        color = editor.draft.effective(key)

        self.warning_icon = Gtk.Image(icon_name="dialog-warning-symbolic")
        self.warning_icon.add_css_class("warning")
        self.warning_icon.set_visible(False)
        self.add_suffix(self.warning_icon)

        self.reset_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self.reset_button.set_valign(Gtk.Align.CENTER)
        self.reset_button.add_css_class("flat")
        self.reset_button.set_tooltip_text(editor.t("theme_editor.reset"))
        self.reset_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [editor.t("theme_editor.reset")]
        )
        self.reset_button.connect("clicked", lambda _b: editor.reset_value(key))
        self.add_suffix(self.reset_button)

        self.swatch = Swatch(color)
        self.picker = ColorPicker(editor.t, color, on_changed=self._on_picked)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.picker, f"set_margin_{side}")(12)
        self.picker.set_size_request(280, -1)
        popover = Gtk.Popover()
        popover.set_child(self.picker)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_child(self.swatch)
        self.menu_button.set_popover(popover)
        self.menu_button.set_valign(Gtk.Align.CENTER)
        self.menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [self.get_title()]
        )
        self.add_suffix(self.menu_button)
        self.set_activatable_widget(self.menu_button)

    def _on_picked(self, color):
        if not self._syncing:
            self.editor.set_value(self.key, color)

    def refresh(self, problems):
        t = self.editor.t
        draft = self.editor.draft
        color = draft.effective(self.key)
        changed = draft.is_changed(self.key)
        self.swatch.set_color(color)
        if self.picker.color != color:
            # Following a reset: moving the picker must not count as a pick.
            self._syncing = True
            try:
                self.picker.set_color(color)
            finally:
                self._syncing = False
        self.reset_button.set_sensitive(changed)
        warnings = warnings_for(draft, self.key, problems)
        self.warning_icon.set_visible(bool(warnings))
        if warnings:
            other, ratio = warnings[0]
            self.set_subtitle(t(
                "theme_editor.contrast_warning",
                other=t(f"theme_editor.key.{other}"),
                ratio=f"{ratio:.1f}",
                needed=f"{WCAG_AA:.1f}",
            ))
        elif changed:
            self.set_subtitle(color.upper())
        else:
            self.set_subtitle(t("theme_editor.same_as_base"))


class ThemeEditorDialog(Adw.Dialog):
    def __init__(self, win, store, theme, is_new, on_saved=None):
        super().__init__()
        self.win = win
        self.t = win.t
        self.store = store
        self.is_new = is_new
        self.on_saved = on_saved
        self.draft = theme.copy()
        self.live = False
        self.saved = False
        self.narrow = False
        self.rows = {}
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
        view.add_top_bar(header)
        view.set_content(self._build_body())
        self.set_child(view)
        self.set_default_widget(self.save_button)

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(NARROW_BREAKPOINT))
        narrow.connect("apply", lambda _b: self.set_narrow(True))
        narrow.connect("unapply", lambda _b: self.set_narrow(False))
        self.add_breakpoint(narrow)

        self.connect("closed", self._on_closed)
        self.show_section(SECTIONS[0])
        self.refresh()

    # -- layout ----------------------------------------------------------

    def _build_body(self):
        t = self.t
        self.body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.sidebar.set_size_request(210, -1)
        self.sidebar.add_css_class("theme-editor-sections")
        for side in ("top", "bottom", "start", "end"):
            getattr(self.sidebar, f"set_margin_{side}")(8)
        self.section_list = Gtk.ListBox()
        self.section_list.add_css_class("navigation-sidebar")
        self.section_list.set_vexpand(True)
        for section in SECTIONS:
            row = Gtk.ListBoxRow()
            row.section = section
            box = Gtk.Box(spacing=10)
            box.append(Gtk.Image(icon_name=SECTION_ICONS[section]))
            label = Gtk.Label(label=t(f"theme_editor.section.{section}"), xalign=0)
            label.set_hexpand(True)
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
        self.sidebar.append(self.section_list)
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
                row = ColorRow(self, spec.key)
                group.add(row)
                self.rows[spec.key] = row
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

    def set_value(self, key, color):
        self.draft.values[key] = color
        self.refresh()

    def reset_value(self, key):
        self.draft.values.pop(key, None)
        self.refresh()

    def reset_all(self):
        self.draft.values.clear()
        self.refresh()

    def refresh(self):
        problems = contrast_problems(self.draft)
        for row in self.rows.values():
            row.refresh(problems)
        for section in SECTIONS:
            has = any(
                warnings_for(self.draft, spec.key, problems)
                for spec in keys_in_section(section)
            )
            self.section_icons[section].set_visible(has)
        self.reset_all_button.set_sensitive(bool(self.draft.values))
        self.preview.set_colors(self.draft.effective_values())
        if self.live:
            theming.paint(self.draft.base, self.draft.values)

    def set_live(self, live):
        if live == self.live:
            return
        self.live = live
        if live:
            theming.paint(self.draft.base, self.draft.values)
        else:
            theming.restore()

    # -- save / cancel ---------------------------------------------------

    def save(self):
        try:
            if self.is_new:
                theme = self.store.create(self.draft.name, self.draft.base, self.draft.values)
            else:
                theme = self.store.save(self.draft)
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
        if self.live and not self.saved:
            theming.restore()
        self.live = False


def open_theme_editor(win, parent, store, theme, is_new, on_saved=None):
    dialog = ThemeEditorDialog(win, store, theme, is_new, on_saved=on_saved)
    dialog.present(parent)
    return dialog

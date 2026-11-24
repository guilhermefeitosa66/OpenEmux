"""Preferences ▸ Interface: the theme picker and the user's themes (issue 1011).

The "Theme" row lists System, Light and Dark, then the user's own themes by
name. While one of the user's themes is picked, an Edit button and a menu
(Duplicate, Rename, Delete) sit beside it; the built-ins have neither. A
"New Theme…" row under it asks for a name and a base, then opens the editor.
"""

import logging

from gi.repository import Adw, Gio, Gtk

from openemux.core.custom_themes import Theme
from openemux.core.theme import THEMES, THEME_SYSTEM
from openemux.ui import theming
from openemux.ui.theme_editor import open_theme_editor

logger = logging.getLogger(__name__)


class ThemePicker:
    def __init__(self, prefs):
        self.prefs = prefs
        self.win = prefs.win
        self.config = prefs.config
        self.store = self.config.themes
        self.t = prefs.t
        self._syncing = False
        self.ids = []
        t = self.t

        self.combo = Adw.ComboRow(
            title=t("settings.system.theme.title"),
            subtitle=t("settings.system.theme.subtitle"),
        )
        self.edit_button = Gtk.Button(icon_name="document-edit-symbolic")
        self.edit_button.set_valign(Gtk.Align.CENTER)
        self.edit_button.add_css_class("flat")
        self.edit_button.set_tooltip_text(t("theme.custom.edit"))
        self.edit_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("theme.custom.edit")]
        )
        self.edit_button.connect("clicked", lambda _b: self.edit())
        self.combo.add_suffix(self.edit_button)

        self.actions = actions = Gio.SimpleActionGroup()
        for name, handler in (("duplicate", self.duplicate), ("rename", self.ask_rename),
                              ("delete", self.ask_delete)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            actions.add_action(action)
        self.combo.insert_action_group("theme", actions)
        menu = Gio.Menu()
        menu.append(t("theme.custom.duplicate"), "theme.duplicate")
        menu.append(t("theme.custom.rename"), "theme.rename")
        menu.append(t("theme.custom.delete"), "theme.delete")
        self.menu_button = Gtk.MenuButton(icon_name="view-more-symbolic")
        self.menu_button.set_valign(Gtk.Align.CENTER)
        self.menu_button.add_css_class("flat")
        self.menu_button.set_menu_model(menu)
        self.menu_button.set_tooltip_text(t("theme.custom.more"))
        self.menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("theme.custom.more")]
        )
        self.combo.add_suffix(self.menu_button)

        self.new_row = Adw.ActionRow(title=t("theme.custom.new"))
        self.new_row.add_prefix(Gtk.Image(icon_name="list-add-symbolic"))
        self.new_row.set_activatable(True)
        self.new_row.connect("activated", lambda _r: self.ask_new())

        self.reload()
        self.combo.connect("notify::selected", self.on_selected)

    # -- the list --------------------------------------------------------

    def reload(self):
        """Rebuild the list from disk and select the stored theme.

        Never runs from inside the combo's own ``notify::selected``: setting
        a model from there re-entered the handler (and crashed GTK 4.22 on
        another combo).
        """
        themes = self.store.list()
        self.ids = list(THEMES) + [theme.id for theme in themes]
        labels = [self.t(f"theme.{name}") for name in THEMES] + [theme.name for theme in themes]
        current = self.config.get_ui_settings()["theme"]
        index = self.ids.index(current) if current in self.ids else self.ids.index(THEME_SYSTEM)
        self._syncing = True
        try:
            self.combo.set_model(Gtk.StringList.new(labels))
            self.combo.set_selected(index)
        finally:
            self._syncing = False
        self._sync_actions()

    def selected_id(self):
        index = self.combo.get_selected()
        return self.ids[index] if 0 <= index < len(self.ids) else None

    def _sync_actions(self):
        custom = self.selected_id() not in THEMES
        self.edit_button.set_visible(custom)
        self.menu_button.set_visible(custom)

    def on_selected(self, row, *_args):
        if self._syncing:
            return
        index = row.get_selected()
        if not (0 <= index < len(self.ids)):
            return
        self._use(self.ids[index])

    def _use(self, theme_id):
        theme = self.config.set_theme(theme_id)
        theming.apply_theme(theme, store=self.store)
        self._sync_actions()
        # "System" that lands on the same appearance emits no notify::dark,
        # so the header icon is refreshed here rather than left to that.
        self.win._sync_theme_button()

    def _select_and_apply(self, theme_id):
        self.config.set_theme(theme_id)
        self.reload()
        theming.apply_theme(self.config.get_ui_settings()["theme"], store=self.store)
        self.win._sync_theme_button()

    def _failed(self, exc):
        logger.warning("Theme action failed: %s", exc)
        self.prefs._toast(self.t("theme.custom.failed"))

    # -- New Theme -------------------------------------------------------

    def ask_new(self):
        t = self.t
        dialog = Adw.AlertDialog(heading=t("theme.custom.new_dialog.title"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        entry.set_placeholder_text(t("theme.custom.name"))
        entry.update_property([Gtk.AccessibleProperty.LABEL], [t("theme.custom.name")])
        box.append(entry)
        base_label = Gtk.Label(label=t("theme.custom.start_from"), xalign=0)
        base_label.add_css_class("dim-label")
        box.append(base_label)
        bases = Gtk.Box(spacing=12, homogeneous=True)
        light = Gtk.ToggleButton(label=t("theme.light"))
        dark = Gtk.ToggleButton(label=t("theme.dark"))
        dark.set_group(light)
        (dark if theming.is_dark() else light).set_active(True)
        bases.append(light)
        bases.append(dark)
        box.append(bases)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", t("dialog.cancel"))
        dialog.add_response("create", t("theme.custom.create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("create", False)
        entry.connect(
            "changed",
            lambda e: dialog.set_response_enabled("create", bool(e.get_text().strip())),
        )
        dialog.entry, dialog.light, dialog.dark = entry, light, dark
        dialog.connect("response", self._on_new_response)
        dialog.present(self.prefs)
        return dialog

    def _on_new_response(self, dialog, response):
        if response != "create":
            return
        name = dialog.entry.get_text().strip()
        if not name:
            return
        base = "dark" if dialog.dark.get_active() else "light"
        self.open_editor(Theme("", name, base), is_new=True)

    # -- Edit ------------------------------------------------------------

    def edit(self):
        theme = self.store.get(self.selected_id())
        if theme is None:
            self._failed(KeyError(self.selected_id()))
            self.reload()
            return None
        return self.open_editor(theme, is_new=False)

    def open_editor(self, theme, is_new):
        return open_theme_editor(
            self.win, self.prefs, self.store, theme, is_new,
            on_saved=lambda saved: self._on_saved(saved, is_new),
        )

    def _on_saved(self, theme, is_new):
        # A new theme is made to be used: it becomes the app's theme. An
        # edited one keeps the pick as it was, and the pick is painted again:
        # the edited theme if it is the one in use, or what was in use if the
        # editor painted the draft over it.
        if is_new:
            self._select_and_apply(theme.id)
            return
        self._select_and_apply(self.config.get_ui_settings()["theme"])

    # -- Duplicate / Rename / Delete -------------------------------------

    def duplicate(self):
        source = self.store.get(self.selected_id())
        if source is None:
            self.reload()
            return None
        try:
            copy = self.store.duplicate(
                source.id, self.t("theme.custom.copy_name", name=source.name)
            )
        except OSError as exc:
            self._failed(exc)
            return None
        self._select_and_apply(copy.id)
        return copy

    def ask_rename(self):
        theme = self.store.get(self.selected_id())
        if theme is None:
            self.reload()
            return None
        t = self.t
        dialog = Adw.AlertDialog(heading=t("theme.custom.rename_dialog.title"))
        entry = Gtk.Entry(text=theme.name)
        entry.set_activates_default(True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [t("theme.custom.name")])
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", t("dialog.cancel"))
        dialog.add_response("rename", t("theme.custom.rename_dialog.confirm"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        entry.connect(
            "changed",
            lambda e: dialog.set_response_enabled("rename", bool(e.get_text().strip())),
        )
        dialog.entry = entry
        dialog.theme_id = theme.id
        dialog.connect("response", self._on_rename_response)
        dialog.present(self.prefs)
        return dialog

    def _on_rename_response(self, dialog, response):
        if response != "rename":
            return
        try:
            self.store.rename(dialog.theme_id, dialog.entry.get_text())
        except (OSError, KeyError, ValueError) as exc:
            self._failed(exc)
        self.reload()

    def ask_delete(self):
        theme = self.store.get(self.selected_id())
        if theme is None:
            self.reload()
            return None
        t = self.t
        dialog = Adw.AlertDialog(
            heading=t("theme.custom.delete_dialog.title", name=theme.name),
            body=t("theme.custom.delete_dialog.body"),
        )
        dialog.add_response("cancel", t("dialog.cancel"))
        dialog.add_response("delete", t("theme.custom.delete_dialog.confirm"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.theme_id = theme.id
        dialog.connect("response", self._on_delete_response)
        dialog.present(self.prefs)
        return dialog

    def _on_delete_response(self, dialog, response):
        if response != "delete":
            return
        try:
            self.store.delete(dialog.theme_id)
        except OSError as exc:
            self._failed(exc)
            return
        if self.config.get_ui_settings()["theme"] == dialog.theme_id:
            self._select_and_apply(THEME_SYSTEM)
        else:
            self.reload()

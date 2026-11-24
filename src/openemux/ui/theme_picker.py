"""Preferences ▸ Interface: the theme picker and the user's themes (issue 1011).

The "Theme" row lists System, Light and Dark, then the user's own themes by
name. While one of the user's themes is picked, an Edit button and a menu
(Duplicate, Rename, Delete) sit beside it; the built-ins have neither. A
"New Theme…" row under it asks for a name and a base, then opens the editor.

Issue 1012: a theme travels as one ``.openemux-theme`` file
(``core.theme_archive``). "Export…" sits in the theme's menu; "Import
Theme…" under "New Theme…" adds the file's theme and selects it. A file the
app cannot use is refused whole, with a toast, and nothing is written.
"""

import logging

import threading

from gi.repository import Adw, GdkPixbuf, Gio, GLib, Gtk

from openemux.core import ready_themes, theme_archive
from openemux.core.custom_themes import MAX_NAME_LENGTH, Theme
from openemux.core.theme import READY_MADE, THEMES, THEME_SYSTEM
from openemux.ui import theming
from openemux.ui.theme_editor import open_theme_editor
from openemux.ui.theme_preview import ThemeCard

logger = logging.getLogger(__name__)


def theme_choices(t, store):
    """Every theme a person can pick, as (id, label).

    Built-ins, then the ready-made ones (issue 1012), then the person's own.
    """
    return (
        [(name, t(f"theme.{name}")) for name in THEMES]
        + [(theme_id, t(f"theme.ready.{theme_id}")) for theme_id in READY_MADE]
        + [(theme.id, theme.name) for theme in store.list()]
    )


def theme_label(t, store, theme_id):
    """What a stored ``ui.theme`` is called; a missing custom one is System."""
    if theme_id in THEMES:
        return t(f"theme.{theme_id}")
    if theme_id in READY_MADE:
        return t(f"theme.ready.{theme_id}")
    theme = store.get(theme_id)
    return theme.name if theme is not None else t(f"theme.{THEME_SYSTEM}")


#: The ready-made theme cards: each theme's picture, framed by its colors.
CARD_WIDTH, CARD_HEIGHT = 140, 88
CARD_IMAGE = 320


def _spawn(target):
    threading.Thread(target=target, daemon=True).start()


def export_name(name):
    """The file name an export suggests: the theme's name, made file-safe."""
    safe = "".join(c for c in name if c not in '/\\:*?"<>|').strip(" .") or "theme"
    return safe + theme_archive.EXTENSION


def copy_name(t, name):
    """"<name> (copy)", the name shortened so the suffix always fits."""
    wanted = t("theme.custom.copy_name", name=name)
    overflow = len(wanted) - MAX_NAME_LENGTH
    if overflow > 0:
        wanted = t("theme.custom.copy_name", name=name[:len(name) - overflow].rstrip())
    return wanted


class ThemePicker:
    def __init__(self, prefs, spawn=None):
        self.prefs = prefs
        self.spawn = spawn or _spawn
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
                              ("export", self.ask_export), ("delete", self.ask_delete)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            actions.add_action(action)
        self.combo.insert_action_group("theme", actions)
        menu = Gio.Menu()
        menu.append(t("theme.custom.duplicate"), "theme.duplicate")
        menu.append(t("theme.custom.rename"), "theme.rename")
        menu.append(t("theme.custom.export"), "theme.export")
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

        self.cards = self._build_cards()

        self.import_row = Adw.ActionRow(title=t("theme.custom.import"))
        self.import_row.add_prefix(Gtk.Image(icon_name="document-open-symbolic"))
        self.import_row.set_activatable(True)
        self.import_row.connect("activated", lambda _r: self.ask_import())

        self.reload()
        self.combo.connect("notify::selected", self.on_selected)

    # -- the ready-made themes' cards (issue 1012) --------------------------

    def _build_cards(self):
        """A card per ready-made theme: its drawn preview and its name."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("ready-theme-cards")
        heading = Gtk.Label(label=self.t("theme.ready.heading"), xalign=0)
        heading.add_css_class("heading")
        box.append(heading)
        self.card_flow = Gtk.FlowBox()
        self.card_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.card_flow.set_homogeneous(True)
        self.card_flow.set_min_children_per_line(3)
        self.card_flow.set_max_children_per_line(5)
        self.card_flow.set_column_spacing(8)
        self.card_flow.set_row_spacing(8)
        self.card_buttons = {}
        for theme in ready_themes.all_themes():
            self.card_flow.append(self._card(theme))
        box.append(self.card_flow)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(12)
        # A row of its own, so the cards sit in the list right under "Theme".
        row = Adw.PreferencesRow(title=self.t("theme.ready.heading"))
        row.set_activatable(False)
        row.set_child(box)
        return row

    def _card(self, theme):
        label = theme_label(self.t, self.store, theme.id)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        image = None
        path = theme.image_path("library")
        if path is not None:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), CARD_IMAGE, CARD_IMAGE, True)
                image = (pixbuf, theme.effective("library_image_fit"))
            except GLib.Error:  # pragma: no cover - a shipped asset that will not load
                pass
        column.append(ThemeCard(theme.effective_values(), image, CARD_WIDTH, CARD_HEIGHT))
        column.append(Gtk.Label(label=label))
        button = Gtk.Button()
        button.set_child(column)
        button.add_css_class("flat")
        button.add_css_class("ready-theme-card")
        button.set_tooltip_text(label)
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        button.connect("clicked", lambda _b, theme_id=theme.id: self._select_and_apply(theme_id))
        self.card_buttons[theme.id] = button
        return button

    def sync_cards(self):
        current = self.selected_id()
        for theme_id, button in self.card_buttons.items():
            if theme_id == current:
                button.add_css_class("ready-theme-current")
            else:
                button.remove_css_class("ready-theme-current")

    # -- the list --------------------------------------------------------

    def reload(self):
        """Rebuild the list from disk and select the stored theme.

        Never runs from inside the combo's own ``notify::selected``: setting
        a model from there re-entered the handler (and crashed GTK 4.22 on
        another combo).
        """
        choices = theme_choices(self.t, self.store)
        self.ids = [theme_id for theme_id, _label in choices]
        labels = [label for _theme_id, label in choices]
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
        selected = self.selected_id()
        ready = selected in READY_MADE
        custom = selected not in THEMES and not ready
        # A ready-made theme is read-only: it can be duplicated (the way to
        # change one) and exported, never edited, renamed or deleted.
        self.edit_button.set_visible(custom)
        self.menu_button.set_visible(custom or ready)
        for name in ("rename", "delete"):
            self.actions.lookup_action(name).set_enabled(custom)
        self.sync_cards()

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

    # -- Export / Import (issue 1012) -------------------------------------

    def _file_filters(self):
        file_filter = Gtk.FileFilter()
        file_filter.set_name(self.t("theme.custom.file_filter"))
        file_filter.add_pattern("*" + theme_archive.EXTENSION)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        return filters, file_filter

    def _parent_window(self):
        root = self.prefs.get_root()
        return root if isinstance(root, Gtk.Window) else None

    def ask_export(self):
        theme = self.store.get(self.selected_id())
        if theme is None:
            self.reload()
            return None
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("theme.custom.export_dialog.title"))
        dialog.set_modal(True)
        dialog.set_initial_name(export_name(theme.name))
        filters, default = self._file_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.save(self._parent_window(), None, self._on_export_chosen, theme.id)
        return dialog

    def _on_export_chosen(self, dialog, result, theme_id):
        try:
            target = dialog.save_finish(result)
        except GLib.Error:
            return  # dismissed
        if target is None or not target.get_path():
            return
        self.export_to(theme_id, target.get_path())

    def export_to(self, theme_id, path):
        try:
            theme_archive.export_theme(self.store, theme_id, path)
        except (OSError, KeyError) as exc:
            self._failed(exc)
            return False
        self.prefs._toast(self.t("theme.custom.exported"))
        return True

    def ask_import(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("theme.custom.import_dialog.title"))
        dialog.set_modal(True)
        filters, default = self._file_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.open(self._parent_window(), None, self._on_import_chosen)
        return dialog

    def _on_import_chosen(self, dialog, result):
        try:
            source = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        if source is None or not source.get_path():
            return
        self.import_from(source.get_path())

    def import_from(self, path):
        """Import ``path`` off the main thread (images are re-encoded)."""
        def work():
            try:
                theme = theme_archive.import_theme(self.store, path)
            except (theme_archive.ThemeImportError, OSError) as exc:
                logger.info("Theme import refused (%s): %s", path, exc)
                GLib.idle_add(self._imported, None)
                return
            GLib.idle_add(self._imported, theme)

        self.spawn(work)

    def _imported(self, theme):
        if theme is None:
            self.prefs._toast(self.t("theme.custom.import_failed"))
        else:
            self._select_and_apply(theme.id)
            self.prefs._toast(self.t("theme.custom.imported", name=theme.name))
        return GLib.SOURCE_REMOVE

    # -- Duplicate / Rename / Delete -------------------------------------

    def duplicate(self):
        source = self.store.get(self.selected_id())
        if source is None:
            self.reload()
            return None
        try:
            name = theme_label(self.t, self.store, source.id)
            copy = self.store.duplicate(source.id, copy_name(self.t, name))
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

"""The Settings page of Big Picture: every preference, built for a pad.

Two columns. On the left the six sections the desktop's Preferences dialog
has -- Library, BIOS, Input, Video, Cores, System -- one of them current,
LB and RB walking them. On the right the rows of that section, every one a
full-width card the D-pad walks: A flips a switch in place, opens a
full-page list for a choice, the on-screen keyboard for a text value, or
runs an action; Left and Right step a number or move a row up and down its
list; B goes back one level and never leaves the mode. Nothing has a Save
button: a change lands in the config the desktop reads the moment it is
made, and the desktop's dialog shows it on its next open.

Every row mirrors a row of ``ui/preferences.py`` and calls what that row
calls, so the two layouts never disagree about what a setting does. The one
thing added here is a question before an action that cannot be undone --
restoring an order, the shader defaults, importing saves, signing out --
because on a pad A and Y are a thumb's width apart.

The Input section is the exception to the "built here" rule: the
controller mapping has a Save of its own and a capture flow of its own, so
it lives in ``settings_input.py`` and is only placed here.
"""

from threading import Thread

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from openemux.core import bezels, core_options, retroachievements, rom_importer, save_backup
from openemux.core.bios_importer import (
    REASON_ERROR,
    REASON_OTHER_CONSOLE,
    console_bios_names,
    import_bios_files_async,
)
from openemux.core.bios_manager import scan_all_bios_status, scan_console_bios_status
from openemux.core.console_order import apply_console_order, move_console
from openemux.core.embedded_credentials import has_embedded_dev_credentials
from openemux.core.library_view import SORT_ORDERS, VIEW_MODES
from openemux.core.paths import is_running_in_flatpak
from openemux.core.shaders import normalize_shader_id
from openemux.core.share.identity import default_device_name
from openemux.core.systems import SYSTEM_IDS, get_system_display_name
from openemux.core.theme import THEMES
from openemux.i18n import LANGUAGE_META, SUPPORTED_LOCALES, normalize_locale
from openemux.ui import theming
from openemux.ui.bigpicture import theme
from openemux.ui.bigpicture.widgets import (
    ROW_ACTION,
    ROW_CHOICE,
    ROW_INFO,
    ROW_NUMBER,
    ROW_SWITCH,
    ROW_TEXT,
    BigPage,
    Row,
    eyebrow,
    note,
    once,
)
from openemux.ui.scopes import ALL_CONSOLES_ID

#: The sections, in the order the left column lists them and LB/RB walk
#: them, each with the key of its title (the desktop's page titles).
SECTIONS = (
    ("library", "prefs.page.library"),
    ("bios", "prefs.page.bios"),
    ("input", "prefs.page.input"),
    ("video", "prefs.page.video"),
    ("cores", "prefs.page.cores"),
    ("system", "prefs.page.system"),
)
SECTION_NAMES = tuple(name for name, _key in SECTIONS)
SECTION_TITLES = dict(SECTIONS)

#: What to say when a picked bezel image is refused, per
#: ``bezels.validate_png`` error key -- the desktop's table, kept in step.
BEZEL_ERROR_TOASTS = {
    "not_png": "toast.bezels.not_png",
    "too_small": "toast.bezels.too_small",
    "unreadable": "toast.bezels.unreadable",
}
BEZEL_LABELS = {
    bezels.NONE: "bezel.none",
    bezels.SIMPLE: "bezel.simple",
    bezels.CUSTOM: "bezel.custom",
}
#: The pads whose letters the hint bar can draw (issue 914), as the desktop lists them.
GLYPH_FAMILIES = ("auto", "xbox", "playstation", "nintendo", "generic")
GLYPH_FAMILY_LABELS = {
    "auto": "controller.family.auto",
    "xbox": "controller.family.xbox",
    "playstation": "controller.family.playstation",
    "nintendo": "controller.family.nintendo",
    "generic": "controller.family.generic",
}
#: How a stored password is shown on its row: that there is one, never what.
PASSWORD_MASK = "•" * 8


def console_title(console_id):
    """``SFC — Super Nintendo``: the row title every console list uses."""
    return f"{console_id} — {get_system_display_name(console_id)}"


def clear_children(box):
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def first_focusable(widget):
    """The first thing under ``widget`` the pad can land on, in reading order."""
    # ``focusable`` is the widget itself, ``can-focus`` it and its children:
    # an information row turns the second off and keeps the first.
    if (widget.get_focusable() and widget.get_can_focus() and widget.get_sensitive()
            and widget.get_visible()):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = first_focusable(child)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def scroll_to_focus(scroller):
    """Make the scroller follow the focus; GTK before 4.6.2 defaulted this off."""
    viewport = scroller.get_child()
    if isinstance(viewport, Gtk.Viewport):
        viewport.set_scroll_to_focus(True)
    return scroller


def bios_import_summary(t, summary):
    """The dialog that reports an import: what went in, what was refused and why.

    The same shape as the desktop's (issue 667), so the explanation a user
    reads on the couch is the one they read at the desk.
    """
    console_id = summary["console"]
    console = get_system_display_name(console_id)
    imported = summary["imported"]
    rejected = summary["rejected"]
    total = len(imported) + len(rejected)
    if not imported:
        heading = t("bios.import.heading_none")
    elif len(imported) == total:
        heading = (
            t("bios.import.heading_one")
            if len(imported) == 1
            else t("bios.import.heading_all", count=len(imported))
        )
    else:
        heading = t("bios.import.heading_some", imported=len(imported), total=total)
    body = ""
    if rejected:
        body = t("bios.import.body", console=console, names=", ".join(console_bios_names(console_id)))
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_css_class("bp-dialog")
    listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    for section_key, entries, icon_name, css in (
        ("bios.import.section_imported", imported, "emblem-ok-symbolic", "success"),
        ("bios.import.section_rejected", rejected, "dialog-warning-symbolic", "warning"),
    ):
        if not entries:
            continue
        header = Gtk.Label(label=t(section_key), xalign=0)
        header.add_css_class("heading")
        header.add_css_class("dim-label")
        listbox.append(Gtk.ListBoxRow(child=header, activatable=False, selectable=False))
        for entry in entries:
            row = Adw.ActionRow(title=entry["name"], use_markup=False)
            if css == "success":
                if entry["replaced"]:
                    row.set_subtitle(t("bios.import.replaced"))
            else:
                row.set_subtitle(bios_rejection_reason(t, entry, console))
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.add_css_class(css)
            row.add_prefix(icon)
            listbox.append(row)
    scroller = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=320,
    )
    scroller.set_child(listbox)
    dialog.set_extra_child(scroller)
    dialog.add_response("ok", t("bios.import.ok"))
    dialog.set_default_response("ok")
    dialog.set_close_response("ok")
    return dialog


def bios_rejection_reason(t, entry, console):
    if entry["reason"] == REASON_ERROR:
        return t("bios.import.reason_error", error=entry["error"])
    if entry["reason"] == REASON_OTHER_CONSOLE:
        owners = ", ".join(get_system_display_name(c) for c in entry["consoles"])
        return t("bios.import.reason_other_console", owners=owners, console=console)
    return t("bios.import.reason_unknown", console=console)


class OrderedRow(Row):
    """A row Left and Right move up and down its list, whatever its kind.

    The number row already spends the arrows on its value; this gives the
    same arrows to a switch row (an artwork provider) whose place in the
    list is a setting too.
    """

    def __init__(self, *args, on_move=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_move = on_move
        if self.kind != ROW_NUMBER:
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_key_pressed)
            self.add_controller(keys)

    def step(self, delta):
        self.on_move(delta)
        return True


class Section:
    """One section's view: a scroller over groups of rows, built on demand.

    ``rows`` keeps every row by a stable key, so a change can update the
    one row it concerns, the page can put the focus back on it, and a test
    can find it without walking the widget tree.
    """

    name = ""

    def __init__(self, page):
        self.page = page
        self.shell = page.shell
        self.win = page.win
        self.config = page.config
        self.t = page.t
        self.rows = {}
        self.built = False
        #: The key of the focused row while its group is being rebuilt.
        self._focus_key = None
        self.column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        self.widget = scroll_to_focus(page.scrolled(self.column))

    def build(self):
        """Throw the rows away and read every value again."""
        clear_children(self.column)
        self.rows = {}
        self._build()
        self.built = True

    def _build(self):  # pragma: no cover - every section overrides it
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------------
    def group(self, title, description=None):
        """An eyebrow, a note under it when there is one, and a box for rows."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(eyebrow(title))
        if description:
            box.append(note(description))
        self.column.append(box)
        return box

    def add(self, key, row, into):
        into.append(row)
        self.rows[key] = row
        if key == self._focus_key:
            # The row the pad was on came back under the same key: it is
            # still the place to land.
            self.page._focus_row = row
            self._focus_key = None
        return row

    def forget(self, prefix):
        """Drop the rows of a group about to be rebuilt, remembering the focused one."""
        for key, row in self.rows.items():
            if key.startswith(prefix) and row is self.page._focus_row:
                self._focus_key = key
        self.rows = {key: row for key, row in self.rows.items() if not key.startswith(prefix)}

    def shown(self, text, password=False):
        """A text value as its row shows it: masked, or "Not set" when empty."""
        if not text:
            return self.t("big_picture.settings.empty")
        return PASSWORD_MASK if password else text

    def first_row(self):
        return first_focusable(self.column)

    def focus_default(self):
        row = self.first_row()
        return row.grab_focus() if row is not None else False


class UnavailableSection(Section):
    """What stands in for a section whose module is not there."""

    name = "input"

    def _build(self):
        t = self.t
        box = self.group(t("prefs.page.input"))
        self.add(
            "unavailable",
            Row(
                t("big_picture.settings.input.unavailable.title"),
                t("big_picture.settings.input.unavailable.subtitle"),
                kind=ROW_INFO,
            ),
            box,
        )


# -- Library ---------------------------------------------------------------------
class LibrarySection(Section):
    name = "library"

    def _build(self):
        t, config, win = self.t, self.config, self.win
        folder = self.group(t("prefs.group.roms_folder"))
        self.add(
            "roms_path",
            Row(t("settings.path.title"), kind=ROW_ACTION, value=str(config.get_roms_path()),
                on_activate=lambda: win._choose_roms_path()),
            folder,
        )
        self.add("open_folder", Row(t("prefs.roms.open"), kind=ROW_ACTION, on_activate=lambda: win._open_roms_folder()), folder)
        # Copy or link (issue #298): the same two modes the desktop offers.
        self.import_modes = [rom_importer.IMPORT_COPY, rom_importer.IMPORT_LINK]
        self.add(
            "import_mode",
            Row(t("settings.library.import_mode.title"), t("settings.library.import_mode.subtitle"),
                kind=ROW_CHOICE, value=t(f"import_mode.{self._import_mode()}"),
                on_activate=self._pick_import_mode),
            folder,
        )

        maintenance = self.group(t("prefs.group.maintenance"))
        self.add("scan", Row(t("settings.scan.title"), t("settings.scan.subtitle"), kind=ROW_ACTION,
                             on_activate=self._pick_scan_scope), maintenance)
        self.add("sync", Row(t("settings.sync.title"), t("settings.sync.subtitle"), kind=ROW_ACTION,
                             on_activate=self.shell.open_covers), maintenance)

        order = self.group(t("prefs.group.console_order"), t("prefs.console_order.description"))
        order.append(note(t("big_picture.settings.reorder_hint")))
        self.order_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        order.append(self.order_box)
        self._build_order_rows()
        self.add("restore_order", Row(t("prefs.console_order.restore"), kind=ROW_ACTION, destructive=True,
                                      on_activate=self._confirm_restore_order), order)

        providers = self.group(t("prefs.group.artwork_providers"), t("prefs.artwork_providers.description"))
        providers.append(note(t("big_picture.settings.reorder_hint")))
        self.provider_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        providers.append(self.provider_box)
        self._build_provider_rows()
        self._build_screenscraper_group()

    # -- the folder and the import mode -----------------------------------------
    def _import_mode(self):
        mode = self.config.get_import_mode()
        return mode if mode in self.import_modes else self.import_modes[0]

    def _pick_import_mode(self):
        t = self.t
        options = [{"id": mode, "label": t(f"import_mode.{mode}")} for mode in self.import_modes]
        self.page.choose(
            self.rows["import_mode"], t("settings.library.import_mode.title"), options,
            self._import_mode(), self._set_import_mode, lead=t("settings.library.import_mode.subtitle"),
        )

    def _set_import_mode(self, mode):
        self.config.set_import_mode(mode)
        self.rows["import_mode"].set_value(self.t(f"import_mode.{mode}"))

    def refresh_roms_path(self):
        self.rows["roms_path"].set_value(str(self.config.get_roms_path()))

    # -- the scan ------------------------------------------------------------------
    def _pick_scan_scope(self):
        t, win = self.t, self.win
        options = [{"id": ALL_CONSOLES_ID, "label": t("sidebar.all")}]
        options += [{"id": console, "label": console_title(console)} for console in SYSTEM_IDS]
        current = win.current_console if win.current_console in SYSTEM_IDS else ALL_CONSOLES_ID
        self.page.choose(self.rows["scan"], t("dialog.scan.title"), options, current, self._start_scan,
                         lead=t("dialog.scan.scope"))

    def _start_scan(self, scope):
        if scope == ALL_CONSOLES_ID:
            self.win._rescan_all_consoles(show_toast=True)
        else:
            self.win._rescan_single_console(scope, show_toast=True)

    # -- the console order (issue #386) ----------------------------------------------
    def _console_order_list(self):
        """The arrangement: the consoles with games, plus the ones the stored order remembers."""
        stored = self.config.get_console_order()
        present = list(getattr(self.win, "visible_consoles", []) or [])
        known = list(dict.fromkeys(present + stored))
        return apply_console_order(known, stored), set(present)

    def _build_order_rows(self):
        t = self.t
        clear_children(self.order_box)
        self.forget("order:")
        consoles, present = self._console_order_list()
        if not consoles:
            self.add("order:empty", Row(t("prefs.console_order.empty"), t("prefs.console_order.empty.subtitle"),
                                        kind=ROW_INFO), self.order_box)
            return
        for index, console in enumerate(consoles):
            row = Row(
                console_title(console),
                None if console in present else t("prefs.console_order.no_games"),
                kind=ROW_NUMBER, value=index + 1,
                on_step=lambda delta, console=console: self._move_console(console, delta),
            )
            self.add(f"order:{console}", row, self.order_box)

    def _move_console(self, console, delta):
        consoles, _present = self._console_order_list()
        moved = move_console(consoles, console, delta)
        if moved == consoles:
            return
        self.win.reorder_consoles(moved)
        self._build_order_rows()
        # The rows are new widgets: the pad stays on the console it was moving.
        self.page.focus_later(self.rows[f"order:{console}"])

    def _confirm_restore_order(self):
        t = self.t
        self.page.confirm(
            t("big_picture.settings.console_order.restore.heading"),
            t("big_picture.settings.console_order.restore.body"),
            t("prefs.console_order.restore"),
            self._restore_order,
        )

    def _restore_order(self):
        self.config.clear_console_order()
        self.win.reorder_consoles([])
        self._build_order_rows()

    # -- the artwork providers (issue #76) --------------------------------------------
    def _build_provider_rows(self):
        t = self.t
        clear_children(self.provider_box)
        self.forget("provider:")
        for index, entry in enumerate(self.config.get_artwork_providers()):
            provider_id = entry["id"]
            row = OrderedRow(
                # Numbered: the number is the priority, and what Left/Right change.
                f"{index + 1}. {t(f'prefs.provider.{provider_id}')}",
                t(f"prefs.provider.{provider_id}.subtitle"),
                kind=ROW_SWITCH, active=bool(entry.get("enabled", True)),
                on_activate=lambda active, pid=provider_id: self._set_provider_enabled(pid, active),
                on_move=lambda delta, index=index: self._move_provider(index, delta),
            )
            self.add(f"provider:{provider_id}", row, self.provider_box)

    def _mutate_providers(self, mutate):
        providers = self.config.get_artwork_providers()
        mutate(providers)
        self.config.set_artwork_providers(providers)

    def _move_provider(self, index, delta):
        moved = self.config.get_artwork_providers()[index]["id"]

        def _mutate(providers):
            other = index + delta
            if 0 <= other < len(providers):
                providers[index], providers[other] = providers[other], providers[index]

        self._mutate_providers(_mutate)
        self._build_provider_rows()
        self.page.focus_later(self.rows[f"provider:{moved}"])

    def _set_provider_enabled(self, provider_id, enabled):
        def _mutate(providers):
            for entry in providers:
                if entry["id"] == provider_id:
                    entry["enabled"] = bool(enabled)

        self._mutate_providers(_mutate)
        self._sync_screenscraper_rows()

    # -- the ScreenScraper account ------------------------------------------------------
    def _build_screenscraper_group(self):
        t = self.t
        box = self.group(t("prefs.group.screenscraper"), t("prefs.screenscraper.description"))
        settings = self.config.get_cover_sync_settings()
        for key, setting, title_key, password in (
            ("ss_user", "screenscraper_user", "prefs.screenscraper.user", False),
            ("ss_password", "screenscraper_password", "prefs.screenscraper.password", True),
        ):
            self._add_screenscraper_row(box, key, setting, title_key, password, settings)
        # The developer credential is the project's own, baked into official
        # builds; it stays behind "Advanced", as on the desktop, for the one
        # user overriding it with an account of their own.
        self.ss_advanced_open = False
        self.add("ss_advanced", Row(t("prefs.screenscraper.advanced.title"), t("prefs.screenscraper.advanced.subtitle"),
                                    kind=ROW_ACTION, on_activate=self._toggle_ss_advanced), box)
        for key, setting, title_key, password in (
            ("ss_devid", "screenscraper_devid", "prefs.screenscraper.devid", False),
            ("ss_devpassword", "screenscraper_devpassword", "prefs.screenscraper.devpassword", True),
        ):
            self._add_screenscraper_row(box, key, setting, title_key, password, settings)
        self.ss_embedded = has_embedded_dev_credentials()
        self.add("ss_hint", Row(t("prefs.screenscraper.hint.title"), t("prefs.screenscraper.hint.subtitle"),
                                kind=ROW_INFO), box)
        self.add("ss_hint_embedded", Row(t("prefs.screenscraper.hint.embedded.title"),
                                         t("prefs.screenscraper.hint.embedded.subtitle"), kind=ROW_INFO), box)
        self._sync_screenscraper_rows()

    def _add_screenscraper_row(self, box, key, setting, title_key, password, settings):
        row = Row(
            self.t(title_key), kind=ROW_TEXT,
            value=self.shown(settings.get(setting, ""), password),
            on_activate=lambda: self._edit_screenscraper(key, setting, title_key, password),
        )
        self.add(key, row, box)

    def _edit_screenscraper(self, key, setting, title_key, password):
        row = self.rows[key]

        def _done(text):
            self.config.set_cover_sync_setting(setting, text)
            row.set_value(self.shown(text, password))

        self.page.edit_text(row, self.t(title_key), self.config.get_cover_sync_settings().get(setting, ""),
                            _done, password=password)

    def _toggle_ss_advanced(self):
        self.ss_advanced_open = not self.ss_advanced_open
        self._sync_screenscraper_rows()

    def _sync_screenscraper_rows(self):
        uses = any(
            entry["id"] == "screenscraper" and entry.get("enabled", True)
            for entry in self.config.get_artwork_providers()
        )
        for key in ("ss_user", "ss_password", "ss_advanced"):
            self.rows[key].set_visible(uses)
        for key in ("ss_devid", "ss_devpassword"):
            self.rows[key].set_visible(uses and self.ss_advanced_open)
        self.rows["ss_hint"].set_visible(uses and not self.ss_embedded)
        self.rows["ss_hint_embedded"].set_visible(uses and self.ss_embedded)


# -- BIOS ------------------------------------------------------------------------------
class BiosSection(Section):
    name = "bios"

    def __init__(self, page):
        super().__init__(page)
        self.console_page = None
        self.import_running = False

    def _build(self):
        t = self.t
        box = self.group(t("settings.bios.title"), t("bios.instructions"))
        # The reload stays for files copied in by hand through "Show folder";
        # an import refreshes the rows by itself (issue 667).
        self.add("reload", Row(t("bios.reload"), kind=ROW_ACTION, on_activate=lambda: self.reload(show_toast=True)), box)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self.list_box)
        self._build_console_rows()

    def _build_console_rows(self):
        t = self.t
        clear_children(self.list_box)
        self.forget("bios:")
        status_by_console = scan_all_bios_status(self.config)
        if not status_by_console:
            self.add("bios:none", Row(t("bios.no_requirements"), kind=ROW_INFO), self.list_box)
            return
        for console_id in sorted(status_by_console):
            status = status_by_console[console_id]
            entries = status["required"] + status["optional"]
            present = sum(1 for entry in entries if entry["present"])
            row = Row(console_title(console_id), f"{present}/{len(entries)}", kind=ROW_ACTION,
                      on_activate=lambda console_id=console_id: self.open_console(console_id))
            self.add(f"bios:{console_id}", row, self.list_box)

    def reload(self, show_toast=False):
        self._build_console_rows()
        if self.console_page is not None:
            self.console_page.refresh()
        if show_toast:
            self.win._toast(self.t("bios.reloaded"))

    def open_console(self, console_id):
        if self.console_page is None:
            self.console_page = BiosConsolePage(self.shell, self)
        self.console_page.load(console_id)
        self.page.push_child(self.rows[f"bios:{console_id}"], self.console_page)

    # -- the import (issue 667) ---------------------------------------------------------
    def open_import_picker(self, console_id):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("bios.import.dialog_title", console=get_system_display_name(console_id)))
        dialog.set_modal(True)
        # No file filter: BIOS extensions vary (.bin .rom .img .gg .nes ...),
        # and a filter would hide the oddly named file the summary explains.
        dialog.open_multiple(self.win, None, self._on_files_chosen, console_id)

    def _on_files_chosen(self, dialog, result, console_id):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # dismissed
        if files is None:
            return
        paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        paths = [path for path in paths if path]
        if not paths:
            return
        self._set_import_running(True)
        import_bios_files_async(
            paths, self.config, console_id,
            lambda summary: GLib.idle_add(self._on_import_done, summary),
        )

    def _set_import_running(self, running):
        self.import_running = running
        if self.console_page is not None:
            self.console_page.set_import_running(running)

    def _on_import_done(self, summary):
        self._set_import_running(False)
        # The rows read the disk again, so the imported files show as present
        # now; the sidebar icon and the console page's banner clear too (issue 911).
        self.reload()
        self.win.sync_bios_warnings([summary["console"]])
        bios_import_summary(self.t, summary).present(self.win)
        return GLib.SOURCE_REMOVE


class BiosConsolePage(BigPage):
    """One console's BIOS files: each with its mark, then Import and the folder."""

    context = "bp-page"

    def __init__(self, shell, section):
        super().__init__(shell, shell.t("prefs.page.bios"), tag="bp-bios-console")
        self.section = section
        self.console_id = None
        self.import_row = None
        self.column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.body.append(scroll_to_focus(self.scrolled(self.column)))

    def load(self, console_id):
        t = self.shell.t
        self.console_id = console_id
        title = console_title(console_id)
        self.set_title(title)
        self.set_crumbs([t("menu.preferences"), t("prefs.page.bios"), title])
        self.refresh()

    def refresh(self):
        t = self.shell.t
        clear_children(self.column)
        status = scan_console_bios_status(self.section.config, self.console_id)
        for section_key, entries in (
            ("bios.section.required", status["required"]),
            ("bios.section.optional", status["optional"]),
        ):
            for entry in entries:
                label = entry["label"]
                if entry.get("kind") == "any_of" and label:
                    label = t("bios.one_of", names=label)
                mark = "✓" if entry["present"] else "⚠"
                self.column.append(Row(f"{mark}  {label}", t(section_key), kind=ROW_INFO))
        self.import_row = Row(
            t("bios.import.button"), t("bios.import.tooltip", console=status["display_name"]),
            kind=ROW_ACTION, primary=True,
            on_activate=lambda: self.section.open_import_picker(self.console_id),
        )
        self.set_import_running(self.section.import_running)
        self.column.append(self.import_row)
        self.column.append(Row(t("bios.show_folder"), kind=ROW_ACTION,
                               on_activate=lambda: self.win._open_console_bios_folder(self.console_id)))

    def set_import_running(self, running):
        self.import_row.set_sensitive(not running)

    def focus_default(self):
        return self.import_row.grab_focus()


# -- Video --------------------------------------------------------------------------------
class VideoSection(Section):
    name = "video"

    def _build(self):
        t, config = self.t, self.config
        ui = config.get_ui_settings()
        appearance = self.group(t("prefs.group.appearance"))
        self.add("view_mode", Row(t("settings.ui.view_mode.title"), t("settings.ui.view_mode.subtitle"),
                                  kind=ROW_CHOICE, value=t(f"view_mode.{self._view_mode()}"),
                                  on_activate=self._pick_view_mode), appearance)
        self.add("sort_order", Row(t("settings.ui.sort_order.title"), t("settings.ui.sort_order.subtitle"),
                                   kind=ROW_CHOICE, value=t(f"sort_order.{self._sort_order()}"),
                                   on_activate=self._pick_sort_order), appearance)
        self.add("show_all_shaders", Row(t("settings.shaders.show_all"), kind=ROW_SWITCH,
                                         active=self._show_all_shaders(), on_activate=self._set_show_all), appearance)
        self.add("restore_shaders", Row(t("settings.shaders.restore_defaults"), kind=ROW_ACTION, destructive=True,
                                        on_activate=self._confirm_restore_shaders), appearance)

        # Windowed or fullscreen, for every game (issue #505); RetroArch's
        # automatic save state (issue 910). Both read at each launch.
        launch = self.group(t("prefs.group.launch_mode"))
        self.add("fullscreen", Row(t("settings.launch_mode.fullscreen.title"), t("settings.launch_mode.fullscreen.subtitle"),
                                   kind=ROW_SWITCH, active=ui["start_games_fullscreen"],
                                   on_activate=config.set_start_games_fullscreen), launch)
        self.add("resume", Row(t("settings.launch_mode.resume.title"), t("settings.launch_mode.resume.subtitle"),
                               kind=ROW_SWITCH, active=config.get_auto_resume(),
                               on_activate=self._set_auto_resume), launch)

        bar = self.group(t("prefs.group.game_bar"))
        self.add("translucent", Row(t("settings.game_bar.translucent.title"), t("settings.game_bar.translucent.subtitle"),
                                    kind=ROW_SWITCH, active=ui["translucent_game_bar"],
                                    on_activate=config.set_translucent_game_bar), bar)

        # One row per 4:3 console (issue #507): no bezel, the built-in one, or an image.
        bezel_box = self.group(t("prefs.group.bezels"), t("settings.bezels.description"))
        for console in SYSTEM_IDS:
            if console not in bezels.BEZEL_CONSOLES:
                continue
            self.add(f"bezel:{console}", Row(console_title(console), kind=ROW_CHOICE,
                                             on_activate=lambda console=console: self._pick_bezel(console)), bezel_box)
            self._sync_bezel_row(console)
        bezel_box.append(note(t("settings.bezels.footer")))

        shaders = self.group(t("prefs.group.shaders"))
        self.shader_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shaders.append(self.shader_box)
        self._build_shader_rows()

    # -- appearance ----------------------------------------------------------------------
    def _view_mode(self):
        mode = self.config.get_ui_settings()["view_mode"]
        return mode if mode in VIEW_MODES else VIEW_MODES[0]

    def _sort_order(self):
        order = self.config.get_ui_settings()["sort_order"]
        return order if order in SORT_ORDERS else SORT_ORDERS[0]

    def _pick_view_mode(self):
        t = self.t
        options = [{"id": mode, "label": t(f"view_mode.{mode}")} for mode in VIEW_MODES]
        self.page.choose(self.rows["view_mode"], t("settings.ui.view_mode.title"), options, self._view_mode(),
                         self._set_view_mode, lead=t("settings.ui.view_mode.subtitle"))

    def _set_view_mode(self, mode):
        self.win._apply_view_mode(mode)
        self.rows["view_mode"].set_value(self.t(f"view_mode.{mode}"))

    def _pick_sort_order(self):
        t = self.t
        options = [{"id": order, "label": t(f"sort_order.{order}")} for order in SORT_ORDERS]
        self.page.choose(self.rows["sort_order"], t("settings.ui.sort_order.title"), options, self._sort_order(),
                         self._set_sort_order, lead=t("settings.ui.sort_order.subtitle"))

    def _set_sort_order(self, order):
        self.win._apply_sort_order(order)
        self.rows["sort_order"].set_value(self.t(f"sort_order.{order}"))

    def _set_auto_resume(self, active):
        self.config.set_auto_resume(active)
        # The resume badges follow the setting, so the page on screen
        # re-reads its cards (issue 910).
        self.win._reload_current_page()

    # -- shaders ---------------------------------------------------------------------------
    def _show_all_shaders(self):
        return bool(self.config.get_shader_settings().get("show_all_shaders", False))

    def _set_show_all(self, active):
        self.config.set_show_all_shaders(active)
        self._build_shader_rows()

    def _confirm_restore_shaders(self):
        t = self.t
        self.page.confirm(
            t("big_picture.settings.shaders.restore.heading"),
            t("big_picture.settings.shaders.restore.body"),
            t("settings.shaders.restore_defaults"),
            self._restore_shaders,
        )

    def _restore_shaders(self):
        self.config.reset_shader_defaults()
        self._build_shader_rows()
        self.win._toast(self.t("toast.shaders.defaults_restored"))

    def _shader_options(self, console):
        """``(options, selected)``: the catalog's list, plus the stored id when it is not in it."""
        selected = normalize_shader_id(self.config.get_shader_for_console(console))
        catalog = self.win.shader_catalog
        options = catalog.get_options(show_all=self._show_all_shaders())
        if selected not in [shader_id for shader_id, _label in options]:
            options.append((selected, catalog.label_for_shader(selected)))
        return options, selected

    def _build_shader_rows(self):
        clear_children(self.shader_box)
        self.forget("shader:")
        for console in SYSTEM_IDS:
            options, selected = self._shader_options(console)
            row = Row(console_title(console), kind=ROW_CHOICE, value=dict(options)[selected],
                      on_activate=lambda console=console: self._pick_shader(console))
            self.add(f"shader:{console}", row, self.shader_box)

    def _pick_shader(self, console):
        options, selected = self._shader_options(console)
        self.page.choose(
            self.rows[f"shader:{console}"], console_title(console),
            [{"id": shader_id, "label": label} for shader_id, label in options], selected,
            lambda shader_id: self._set_shader(console, shader_id), lead=self.t("prefs.group.shaders"),
        )

    def _set_shader(self, console, shader_id):
        shader_id = normalize_shader_id(shader_id)
        self.config.set_shader_for_console(console, shader_id)
        self.rows[f"shader:{console}"].set_value(self.win.shader_catalog.label_for_shader(shader_id))

    # -- bezels (issue #507) ---------------------------------------------------------------
    def _sync_bezel_row(self, console):
        row = self.rows[f"bezel:{console}"]
        mode = self.config.get_bezel_for_console(console)
        row.set_value(self.t(BEZEL_LABELS[mode]))
        row.set_subtitle(self.config.get_custom_bezel_name(console) if mode == bezels.CUSTOM else None)

    def _pick_bezel(self, console):
        t = self.t
        options = [{"id": mode, "label": t(BEZEL_LABELS[mode])} for mode in bezels.BEZEL_MODES]
        self.page.choose(
            self.rows[f"bezel:{console}"], console_title(console), options,
            self.config.get_bezel_for_console(console),
            lambda mode: self._set_bezel(console, mode), lead=t("prefs.group.bezels"),
        )

    def _set_bezel(self, console, mode):
        current = self.config.get_bezel_for_console(console)
        if mode == bezels.CUSTOM:
            stored = bezels.custom_path(console, self.config.store_path("bezels"))
            if current == bezels.CUSTOM or not stored.is_file():
                # Nothing stored yet, or a new image for the one there is:
                # the picker decides, and the row follows what it stored.
                self._choose_custom_bezel(console)
                return
        if mode != current:
            self.config.set_bezel_for_console(console, mode)
        self._sync_bezel_row(console)

    def _choose_custom_bezel(self, console):
        t = self.t
        png = Gtk.FileFilter()
        png.set_name(t("bezels.dialog.filter"))
        png.add_pattern("*.png")
        png.add_mime_type("image/png")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(png)
        dialog = Gtk.FileDialog()
        dialog.set_title(t("bezels.dialog.title"))
        dialog.set_modal(True)
        dialog.set_filters(filters)
        dialog.set_default_filter(png)
        dialog.open(self.win, None, self._on_bezel_image_chosen, console)

    def _on_bezel_image_chosen(self, dialog, result, console):
        try:
            source = dialog.open_finish(result)
        except GLib.Error:
            source = None  # dismissed
        path = source.get_path() if source is not None else None
        if path:
            error = self.config.set_custom_bezel(console, path)
            if error:
                self.win._toast(self.t(BEZEL_ERROR_TOASTS[error]))
        self._sync_bezel_row(console)


# -- Cores ----------------------------------------------------------------------------------
class CoresSection(Section):
    name = "cores"

    def _build(self):
        t, config = self.t, self.config
        box = self.group(t("prefs.group.cores"), t("prefs.group.cores.description"))
        for console in SYSTEM_IDS:
            cores = self.win.core_catalog.cores_for_console(console)
            if not cores:
                # Nothing installed: say so rather than offer an empty picker.
                self.add(f"core:{console}", Row(console_title(console), t("settings.cores.none"), kind=ROW_INFO), box)
                continue
            row = Row(console_title(console), t("settings.cores.auto_resolves", core=cores[0].display_name),
                      kind=ROW_CHOICE, value=self._core_label(console),
                      on_activate=lambda console=console: self._pick_core(console))
            self.add(f"core:{console}", row, box)

        # The ~200 cores no picker lists are an opt-in (issue 908); turning it
        # on owes the sweep again, and the window starts it right away.
        downloads = self.group(t("prefs.group.core_downloads"))
        self.add("download_all", Row(t("settings.cores.download_all.title"), t("settings.cores.download_all.subtitle"),
                                     kind=ROW_SWITCH,
                                     active=config.get_retroarch_updater_settings()["download_all_cores"],
                                     on_activate=self._set_download_all), downloads)

        # Settings the core itself understands (issue #296): only for the
        # cores that have any, so this group is hidden on most libraries.
        self.options_group = self.group(t("prefs.group.core_options"), t("prefs.group.core_options.description"))
        self.options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.options_group.append(self.options_box)
        self._build_option_rows()

    def _core_options(self, console):
        cores = self.win.core_catalog.cores_for_console(console)
        options = [{"id": "", "label": self.t("settings.cores.automatic", core=cores[0].display_name)}]
        options += [{"id": core.filename, "label": core.display_name} for core in cores]
        return options

    def _current_core(self, console, options):
        override = self.config.get_console_core_override(console)
        return override if override in [option["id"] for option in options] else ""

    def _core_label(self, console):
        options = self._core_options(console)
        current = self._current_core(console, options)
        return next(option["label"] for option in options if option["id"] == current)

    def _pick_core(self, console):
        options = self._core_options(console)
        self.page.choose(
            self.rows[f"core:{console}"], console_title(console), options, self._current_core(console, options),
            lambda filename: self._set_core(console, filename), lead=self.t("prefs.group.cores"),
        )

    def _set_core(self, console, filename):
        chosen = filename or None
        self.config.set_console_core_override(console, chosen)
        if chosen:
            self.win._warn_missing_bios_for_core(console, chosen)
        self.rows[f"core:{console}"].set_value(self._core_label(console))
        # The new core has its own options, or none at all.
        self._build_option_rows()

    def _set_download_all(self, enabled):
        self.config.set_download_all_cores(enabled)
        if enabled:
            self.win._start_deferred_asset_download()

    # -- the advanced core options --------------------------------------------------------
    def _resolved_core_for(self, console):
        """The core this console would launch with right now."""
        override = self.config.get_console_core_override(console)
        if override:
            return override
        cores = self.win.core_catalog.cores_for_console(console)
        return cores[0].filename if cores else None

    def _build_option_rows(self):
        clear_children(self.options_box)
        self.forget("option:")
        store = self.config.core_options
        for console in SYSTEM_IDS:
            core_filename = self._resolved_core_for(console)
            options = core_options.options_for_core(core_filename)
            if not options:
                continue
            chosen = store.get_for_console(console, core_filename)
            for option in options:
                row = Row(
                    self.t(option.label_key), console_title(console), kind=ROW_CHOICE,
                    value=core_options.value_label(self._option_value(option, chosen)),
                    on_activate=lambda console=console, core=core_filename, option=option: self._pick_option(
                        console, core, option
                    ),
                )
                self.add(f"option:{console}:{option.key}", row, self.options_box)
        self.options_group.set_visible(self.options_box.get_first_child() is not None)

    @staticmethod
    def _option_value(option, chosen):
        current = chosen.get(option.key, option.default)
        return current if current in option.values else option.values[0]

    def _pick_option(self, console, core_filename, option):
        chosen = self.config.core_options.get_for_console(console, core_filename)
        self.page.choose(
            self.rows[f"option:{console}:{option.key}"], self.t(option.label_key),
            [{"id": value, "label": core_options.value_label(value)} for value in option.values],
            self._option_value(option, chosen),
            lambda value: self._set_option(console, core_filename, option, value), lead=console_title(console),
        )

    def _set_option(self, console, core_filename, option, value):
        self.config.core_options.set_for_console(console, core_filename, option.key, value)
        self.rows[f"option:{console}:{option.key}"].set_value(core_options.value_label(value))


# -- System ------------------------------------------------------------------------------------
class SystemSection(Section):
    name = "system"

    def __init__(self, page):
        super().__init__(page)
        # What the user typed for RetroAchievements, until Sign in sends it:
        # the desktop keeps it in its entry rows the same way.
        self.cheevos_user = ""
        self.cheevos_password = ""

    def _build(self):
        t, config, win = self.t, self.config, self.win
        ui = config.get_ui_settings()
        language = self.group(t("prefs.group.language"))
        self.add("language", Row(t("settings.system.language.title"), t("settings.system.language.subtitle"),
                                 kind=ROW_CHOICE, value=self._language_label(self._locale()),
                                 on_activate=self._pick_language), language)

        interface = self.group(t("prefs.group.interface"))
        self.add("theme", Row(t("settings.system.theme.title"), t("settings.system.theme.subtitle"), kind=ROW_CHOICE,
                              value=t(f"theme.{ui['theme']}"), on_activate=self._pick_theme), interface)
        self.add("tips", Row(t("settings.system.tips.title"), t("settings.system.tips.subtitle"), kind=ROW_SWITCH,
                             active=ui["show_tips"], on_activate=self._set_tips), interface)
        self.add("gamepad_nav", Row(t("settings.system.gamepad_nav.title"), t("settings.system.gamepad_nav.subtitle"),
                                    kind=ROW_SWITCH, active=ui["gamepad_navigation"],
                                    on_activate=win._apply_gamepad_navigation), interface)
        self.add("glyphs", Row(t("settings.system.glyphs.title"), t("settings.system.glyphs.subtitle"), kind=ROW_CHOICE,
                               value=t(GLYPH_FAMILY_LABELS[config.get_controller_glyph_family()]),
                               on_activate=self._pick_glyphs), interface)
        self.add("swap", Row(t("settings.system.swap.title"), t("settings.system.swap.subtitle"), kind=ROW_SWITCH,
                             active=config.get_swap_confirm_cancel(), on_activate=self._set_swap), interface)

        big_picture = self.group(t("prefs.group.big_picture"))
        settings = config.get_big_picture_settings()
        self.add("bp_start", Row(t("settings.system.big_picture.start.title"), t("settings.system.big_picture.start.subtitle"),
                                 kind=ROW_SWITCH, active=settings["start"],
                                 on_activate=config.set_big_picture_start), big_picture)
        self.add("bp_text_size", Row(t("settings.system.big_picture.text_size.title"),
                                     t("settings.system.big_picture.text_size.subtitle"), kind=ROW_NUMBER,
                                     value=f"{settings['text_size']}%", on_step=self._step_text_size), big_picture)

        welcome = self.group(t("prefs.group.welcome"))
        self.add("welcome_startup", Row(t("settings.system.welcome.startup.title"),
                                        t("settings.system.welcome.startup.subtitle"), kind=ROW_SWITCH,
                                        active=config.get_show_welcome_on_startup(),
                                        on_activate=config.set_show_welcome_on_startup), welcome)
        self.add("welcome_open", Row(t("settings.system.welcome.open.title"), t("settings.system.welcome.open.subtitle"),
                                     kind=ROW_ACTION, on_activate=lambda: win._open_welcome()), welcome)

        trouble = self.group(t("prefs.group.troubleshooting"), t("settings.system.troubleshooting.description"))
        self.add("log_panel", Row(t("settings.system.log_panel.title"), t("settings.system.log_panel.subtitle"),
                                  kind=ROW_SWITCH, active=ui["show_log_panel"],
                                  on_activate=win.set_log_panel_visible), trouble)
        self.add("report", Row(t("settings.system.report.title"), t("settings.system.report.subtitle"),
                               kind=ROW_ACTION, on_activate=lambda: win.show_bug_report()), trouble)

        saves = self.group(t("prefs.group.saves"))
        self.add("export_saves", Row(t("settings.system.saves.export.title"), t("settings.system.saves.export.subtitle"),
                                     kind=ROW_ACTION, on_activate=self._export_saves), saves)
        self.add("import_saves", Row(t("settings.system.saves.import.title"), t("settings.system.saves.import.subtitle"),
                                     kind=ROW_ACTION, on_activate=self._confirm_import_saves), saves)

        share = self.group(t("prefs.group.share"), t("prefs.share.description", hostname=default_device_name()))
        self.add("device_name", Row(t("prefs.share.device_name"), kind=ROW_TEXT,
                                    value=self.shown(config.get_share_device_name()),
                                    on_activate=self._edit_device_name), share)

        achievements = self.group(t("prefs.group.achievements"), t("prefs.group.achievements.description"))
        self.achievements_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        achievements.append(self.achievements_box)
        self.cheevos_user = config.achievements.get_username()
        self.cheevos_password = ""
        self._build_achievements_rows()

        setup = self.group(t("prefs.group.setup"))
        state = config.get_bootstrap_state()
        status = state.get("status", "pending")
        if status == "completed":
            subtitle = t("settings.system.bootstrap.ok")
        elif status == "failed":
            subtitle = t("settings.system.bootstrap.failed", step=state.get("failed_step") or "-")
        else:
            subtitle = t("settings.system.bootstrap.pending")
        self.add("bootstrap_status", Row(t("settings.system.bootstrap.title"), subtitle, kind=ROW_INFO), setup)
        self.add("bootstrap_retry", Row(t("settings.system.bootstrap.retry.title"),
                                        t("settings.system.bootstrap.retry.subtitle"), kind=ROW_ACTION,
                                        on_activate=lambda: win._trigger_bootstrap_retry()), setup)
        # Cores lost after the first boot (issue #512). The Flatpak's cores
        # belong to RetroArch's own, so the row is not offered there.
        running = bool(win._core_repair_running)
        verify = Row(
            t("settings.system.cores.verify.title"),
            t("settings.system.cores.verify.running" if running else "settings.system.cores.verify.subtitle"),
            kind=ROW_ACTION, on_activate=lambda: win._start_core_repair(manual=True),
        )
        verify.set_sensitive(not running)
        verify.set_visible(not is_running_in_flatpak())
        self.add("verify_cores", verify, setup)

    # -- language ------------------------------------------------------------------------------
    def _locale(self):
        current = normalize_locale(self.win.locale)
        return current if current in SUPPORTED_LOCALES else SUPPORTED_LOCALES[0]

    @staticmethod
    def _language_label(locale):
        meta = LANGUAGE_META.get(locale, LANGUAGE_META["en"])
        return f"{meta['flag']} {meta['native_name']}"

    def _pick_language(self):
        t = self.t
        options = [{"id": locale, "label": self._language_label(locale)} for locale in SUPPORTED_LOCALES]
        self.page.choose(self.rows["language"], t("settings.system.language.title"), options, self._locale(),
                         self._set_language, lead=t("settings.system.language.subtitle"))

    def _set_language(self, locale):
        selected = normalize_locale(locale)
        if selected == self.win.locale:
            return
        self.win._apply_language_change(selected)
        # Every label on this page is in the old language now: build it
        # again, once the chooser has popped.
        GLib.idle_add(self.page.retranslate)

    # -- interface -------------------------------------------------------------------------------
    def _pick_theme(self):
        t = self.t
        options = [{"id": name, "label": t(f"theme.{name}")} for name in THEMES]
        self.page.choose(self.rows["theme"], t("settings.system.theme.title"), options,
                         self.config.get_ui_settings()["theme"], self._set_theme,
                         lead=t("settings.system.theme.subtitle"))

    def _set_theme(self, name):
        applied = self.config.set_theme(name)
        theming.apply_theme(applied)
        # "System" that lands on the same appearance emits no notify::dark,
        # so the header icon is refreshed here rather than left to that.
        self.win._sync_theme_button()
        self.rows["theme"].set_value(self.t(f"theme.{applied}"))

    def _set_tips(self, enabled):
        self.config.set_show_tips(enabled)
        self.win._apply_tips_visibility(enabled)

    def _pick_glyphs(self):
        t = self.t
        options = [{"id": family, "label": t(GLYPH_FAMILY_LABELS[family])} for family in GLYPH_FAMILIES]
        self.page.choose(self.rows["glyphs"], t("settings.system.glyphs.title"), options,
                         self.config.get_controller_glyph_family(), self._set_glyphs,
                         lead=t("settings.system.glyphs.subtitle"))

    def _set_glyphs(self, family):
        self.config.set_controller_glyph_family(family)
        self.win.apply_controller_preferences()
        self.rows["glyphs"].set_value(self.t(GLYPH_FAMILY_LABELS[family]))

    def _set_swap(self, enabled):
        self.config.set_swap_confirm_cancel(enabled)
        self.win.apply_controller_preferences()

    def _step_text_size(self, delta):
        current = self.config.get_big_picture_settings()["text_size"]
        wanted = min(theme.MAX_TEXT_SIZE, max(theme.MIN_TEXT_SIZE, current + delta * theme.TEXT_SIZE_STEP))
        size = self.config.set_big_picture_text_size(wanted)
        self.rows["bp_text_size"].set_value(f"{size}%")
        # Live: the page the user is reading grows or shrinks under them.
        self.shell.apply_scale()

    # -- saves (issue #293) --------------------------------------------------------------------
    def _saves_filter(self):
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name(self.t("saves.dialog.filter"))
        zip_filter.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zip_filter)
        return filters, zip_filter

    def _export_saves(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("saves.export.dialog.title"))
        dialog.set_modal(True)
        dialog.set_initial_name(save_backup.default_backup_name())
        filters, default = self._saves_filter()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.save(self.win, None, self._on_export_target_chosen)

    def _on_export_target_chosen(self, dialog, result):
        try:
            target = dialog.save_finish(result)
        except GLib.Error:
            return  # dismissed
        if target is None or not target.get_path():
            return
        save_backup.export_saves_async(
            target.get_path(), self.config.get_states_dir(), self.config.get_roms_path(),
            on_done=lambda summary: GLib.idle_add(self._on_export_done, summary),
        )

    def _on_export_done(self, summary):
        t = self.t
        if summary.get("error"):
            self.win._toast(t("toast.saves.failed", error=summary["error"]))
        else:
            self.win._toast(t("toast.saves.exported", states=summary.get("states", 0), saves=summary.get("saves", 0)))
        return GLib.SOURCE_REMOVE

    def _confirm_import_saves(self):
        t = self.t
        self.page.confirm(
            t("big_picture.settings.saves.import.heading"),
            t("big_picture.settings.saves.import.body"),
            t("big_picture.settings.saves.import.confirm"),
            self._import_saves,
            destructive=False,
        )

    def _import_saves(self):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("saves.import.dialog.title"))
        dialog.set_modal(True)
        filters, default = self._saves_filter()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.open(self.win, None, self._on_import_source_chosen)

    def _on_import_source_chosen(self, dialog, result):
        try:
            source = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        if source is None or not source.get_path():
            return
        save_backup.import_saves_async(
            source.get_path(), self.config.get_states_dir(), self.config.get_roms_path(),
            on_done=lambda outcome: GLib.idle_add(self._on_import_done, outcome),
        )

    def _on_import_done(self, outcome):
        t = self.t
        errors = outcome.get("errors") or []
        if errors and not outcome.get("restored"):
            self.win._toast(t("toast.saves.failed", error=errors[0]["error"]))
        else:
            self.win._toast(t("toast.saves.imported", restored=outcome.get("restored", 0),
                              skipped=outcome.get("skipped", 0)))
        return GLib.SOURCE_REMOVE

    # -- Share nearby (issue #589) ------------------------------------------------------------------
    def _edit_device_name(self):
        row = self.rows["device_name"]

        def _done(text):
            self.config.set_share_device_name(text)
            row.set_value(self.shown(self.config.get_share_device_name()))

        self.page.edit_text(
            row, self.t("prefs.share.device_name"), self.config.get_share_device_name(), _done,
            subtitle=self.t("prefs.share.description", hostname=default_device_name()),
        )

    # -- RetroAchievements (issue #300) -------------------------------------------------------------
    def _build_achievements_rows(self):
        t = self.t
        store = self.config.achievements
        box = self.achievements_box
        clear_children(box)
        self.forget("cheevos:")
        if store.is_signed_in():
            self.add("cheevos:account", Row(t("settings.achievements.signed_in", user=store.get_username()),
                                            kind=ROW_INFO), box)
            self.add("cheevos:enable", Row(t("settings.achievements.enable.title"), t("settings.achievements.enable.subtitle"),
                                           kind=ROW_SWITCH, active=store.get_enabled(),
                                           on_activate=store.set_enabled), box)
            self.add("cheevos:hardcore", Row(t("settings.achievements.hardcore.title"),
                                             t("settings.achievements.hardcore.subtitle"), kind=ROW_SWITCH,
                                             active=store.get_hardcore(), on_activate=store.set_hardcore), box)
            self.add("cheevos:signout", Row(t("settings.achievements.signout"), kind=ROW_ACTION, destructive=True,
                                            on_activate=self._confirm_sign_out), box)
            return
        self.add("cheevos:user", Row(t("settings.achievements.username"), kind=ROW_TEXT,
                                     value=self.shown(self.cheevos_user), on_activate=self._edit_cheevos_user), box)
        self.add("cheevos:password", Row(t("settings.achievements.password"), kind=ROW_TEXT,
                                         value=self.shown(self.cheevos_password, password=True),
                                         on_activate=self._edit_cheevos_password), box)
        self.add("cheevos:signin", Row(t("settings.achievements.signin"), t("settings.achievements.signed_out"),
                                       kind=ROW_ACTION, primary=True, on_activate=self._sign_in), box)

    def _edit_cheevos_user(self):
        row = self.rows["cheevos:user"]

        def _done(text):
            self.cheevos_user = text.strip()
            row.set_value(self.shown(self.cheevos_user))

        self.page.edit_text(row, self.t("settings.achievements.username"), self.cheevos_user, _done)

    def _edit_cheevos_password(self):
        row = self.rows["cheevos:password"]

        def _done(text):
            self.cheevos_password = text
            row.set_value(self.shown(text, password=True))

        self.page.edit_text(row, self.t("settings.achievements.password"), self.cheevos_password, _done,
                            password=True)

    def _sign_in(self):
        username = self.cheevos_user.strip()
        password = self.cheevos_password
        self.rows["cheevos:signin"].set_sensitive(False)

        def _worker():
            try:
                token = retroachievements.login(username, password)
            except retroachievements.LoginError as exc:
                GLib.idle_add(self._on_login_failed, str(exc))
                return
            GLib.idle_add(self._on_login_ok, username, token)

        Thread(target=_worker, daemon=True).start()

    def _on_login_ok(self, username, token):
        store = self.config.achievements
        store.set_account(username, token)
        # Asking to sign in is asking for achievements; the switch is there to
        # turn them off again, not a second thing to remember.
        store.set_enabled(True)
        self._build_achievements_rows()
        self.page.focus_later(self.rows["cheevos:enable"])
        self.win._toast(self.t("toast.achievements.signed_in", user=username))
        return GLib.SOURCE_REMOVE

    def _on_login_failed(self, message):
        self.rows["cheevos:signin"].set_sensitive(True)
        # The password is left alone: retyping it after a typo in the
        # username is the annoying half.
        self.win._toast(self.t("toast.achievements.failed", error=message), timeout=5)
        return GLib.SOURCE_REMOVE

    def _confirm_sign_out(self):
        t = self.t
        self.page.confirm(
            t("big_picture.settings.achievements.signout.heading"),
            t("big_picture.settings.achievements.signout.body"),
            t("settings.achievements.signout"),
            self._sign_out,
        )

    def _sign_out(self):
        self.config.achievements.sign_out()
        self._build_achievements_rows()
        self.page.focus_later(self.rows["cheevos:user"])
        self.win._toast(self.t("toast.achievements.signed_out"))


# -- the page ----------------------------------------------------------------------------------------
class SettingsPage(BigPage):
    context = "bp-page"

    def __init__(self, shell):
        t = shell.t
        super().__init__(shell, t("menu.preferences"), tag="bp-settings")
        self.config = shell.win.config_manager
        self.t = t
        self.current = SECTION_NAMES[0]
        self.input = None
        self._pending_console = None
        #: The row the pad was on when a chooser or the keyboard opened over
        #: the page: where it lands again when they pop.
        self._focus_row = None
        #: Set while a page of this one's is on top, so coming back from it
        #: does not rebuild the rows and lose the place.
        self._returning = False
        #: The sections whose values may have changed since they were built.
        self._stale = set(SECTION_NAMES)

        self.body.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.body.set_spacing(40)
        self.section_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.section_column.set_valign(Gtk.Align.START)
        self.section_column.set_size_request(260, -1)
        self.body.append(self.section_column)
        self.buttons = {}
        for name, key in SECTIONS:
            button = Gtk.Button(label=t(key))
            button.add_css_class("bp-section")
            button.add_css_class("flat")
            button.get_child().set_xalign(0.0)
            button.connect("clicked", lambda _b, name=name: self._on_section_clicked(name))
            self.section_column.append(button)
            self.buttons[name] = button

        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.body.append(self.stack)
        self.sections = {}
        for section_class in (LibrarySection, BiosSection, VideoSection, CoresSection, SystemSection):
            section = section_class(self)
            self.sections[section.name] = section
            self.stack.add_named(section.widget, section.name)

        self.connect("showing", self._on_showing)
        shell.nav.connect("popped", self._on_nav_popped)
        self._mark_current()

    # -- sections ---------------------------------------------------------------------------
    def show_section(self, name, console=None):
        """Make ``name`` the current section; ``console`` points Input at one.

        Called before the page is pushed as well as while it is on screen:
        the rows are only built when the page is visible, so an open straight
        onto a section builds that one and nothing else.
        """
        if name not in SECTION_NAMES:
            return False
        if name != self.current:
            self._focus_row = None
        self.current = name
        if console is not None:
            self._pending_console = console
        self._mark_current()
        if self.shell.visible_page() is self:
            self._ensure(name)
        return True

    def _mark_current(self):
        for name, button in self.buttons.items():
            if name == self.current:
                button.add_css_class("bp-current")
            else:
                button.remove_css_class("bp-current")
        self.set_crumbs([self.t("menu.preferences"), self.t(SECTION_TITLES[self.current])])

    def _on_section_clicked(self, name):
        self.show_section(name)
        GLib.idle_add(once(self.focus_default))

    def step_section(self, delta):
        """LB and RB: the previous or next section, wrapping like the rail."""
        index = SECTION_NAMES.index(self.current)
        self.show_section(SECTION_NAMES[(index + delta) % len(SECTION_NAMES)])
        GLib.idle_add(once(self.focus_default))
        return True

    def _ensure(self, name):
        """Build ``name`` if it was never built or may be stale, and show it."""
        if name == "input":
            self._ensure_input()
        else:
            section = self.sections[name]
            if not section.built or name in self._stale:
                section.build()
        self._stale.discard(name)
        self.stack.set_visible_child_name(name)

    def _ensure_input(self):
        if self.stack.get_child_by_name("input") is None:
            self._build_input()
        elif self.input is not None and "input" in self._stale:
            self.input.refresh()
        if self.input is not None and self._pending_console is not None:
            self.input.select_console(self._pending_console)
        self._pending_console = None

    def _build_input(self):
        try:
            from openemux.ui.bigpicture.settings_input import InputSection
        except ImportError:
            # The mapping section is a module of its own; until it is there,
            # the page says so instead of showing an empty column.
            section = UnavailableSection(self)
            section.build()
            self.sections["input"] = section
            self.stack.add_named(section.widget, "input")
            return
        self.input = InputSection(self.shell, self)
        self.stack.add_named(self.input.widget, "input")

    def _on_showing(self, *_args):
        if self._returning:
            self._returning = False
        else:
            # Opened from home: the desktop may have changed anything since.
            self._stale = set(SECTION_NAMES)
        self._ensure(self.current)

    def _on_nav_popped(self, _nav, page):
        # Popped itself (B to home) with a child's return still pending: the
        # next open is a fresh one.
        if page is self:
            self._returning = False

    def retranslate(self):
        """The language changed: every label on the page is built again."""
        t = self.t
        self.set_title(t("menu.preferences"))
        for name, key in SECTIONS:
            self.buttons[name].set_label(t(key))
        self._stale = set(SECTION_NAMES)
        self._focus_row = None
        self.show_section(self.current)
        return GLib.SOURCE_REMOVE

    def refresh_roms_path(self):
        """The window picked a new ROMs folder: the row says so at once."""
        library = self.sections["library"]
        if library.built:
            library.refresh_roms_path()

    # -- what the rows borrow -------------------------------------------------------------
    def choose(self, row, title, options, current, on_pick, lead=None):
        """A full-page list over ``row``; the focus comes back to the row after."""
        self._leave_for_child(row)
        return self.shell.open_chooser(title, options, current, on_pick, crumbs=self._crumbs_for(title), lead=lead)

    def edit_text(self, row, title, initial, on_done, subtitle=None, password=False, max_length=64):
        """The on-screen keyboard over ``row``'s value."""
        self._leave_for_child(row)
        return self.shell.open_text_entry(
            title, initial, on_done, subtitle=subtitle, password=password, max_length=max_length,
            crumbs=self._crumbs_for(title),
        )

    def push_child(self, row, page):
        """A page of this one's (a console's BIOS files) over ``row``."""
        self._leave_for_child(row)
        self.shell.push(page)

    def confirm(self, heading, body, confirm_label, on_confirm, destructive=True):
        return self.shell.confirm(heading, body, confirm_label, on_confirm, destructive=destructive)

    def _crumbs_for(self, title):
        return [self.t("menu.preferences"), self.t(SECTION_TITLES[self.current]), title]

    def _leave_for_child(self, row):
        self._focus_row = row
        self._returning = True

    def focus_later(self, row):
        """Rows were rebuilt under the pad: land on ``row`` once they are laid out."""
        self._focus_row = row
        GLib.idle_add(once(row.grab_focus))

    # -- focus and hints ------------------------------------------------------------------
    def focus_default(self):
        row = self._focus_row
        if row is not None and row.get_root() is not None and row.is_visible() and row.get_sensitive():
            return row.grab_focus()
        if self.current == "input" and self.input is not None:
            return bool(self.input.focus_default())
        section = self.sections.get(self.current)
        if section is not None and section.focus_default():
            return True
        return self.buttons[self.current].grab_focus()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.change")),
            (g["back"], t("hints.back")),
            (g["consoles"], t("big_picture.hints.section")),
        ]


__all__ = [
    "SettingsPage", "Section", "LibrarySection", "BiosSection", "BiosConsolePage", "VideoSection",
    "CoresSection", "SystemSection", "UnavailableSection", "OrderedRow", "SECTIONS", "SECTION_NAMES",
    "console_title", "bios_import_summary", "bios_rejection_reason",
]

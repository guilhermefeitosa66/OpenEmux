"""Getting ROMs into the library: the header button, the drop target, the
questions that have to be answered first, and the background run.

Four steps that used to be nine methods on `OpenEmuxWindow`, tangled with the
rest of it only through the banner, a toast and the rescan that has to follow
(issue #237). Keeping them together is what makes the sequence readable:
ask which console when there is no context for one, resolve the extensions
that more than one console claims, import, then rescan and fetch the artwork
the new files arrived without.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio, Gtk

from openemux.core.rom_importer import (
    IMPORTABLE_EXTENSIONS,
    collect_ambiguous_extensions,
    import_roms_async,
)
from openemux.core.systems import SYSTEM_IDS, get_system_display_name
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID

logger = logging.getLogger(__name__)


class ImportFlow:
    """Drives an import from the first click to the artwork sync after it.

    Holds the window because every step of the flow needs something from it --
    a dialog parent, the banner, the current console, the library path -- but
    owns the one piece of state the flow has: whether an import is running.
    """

    def __init__(self, window):
        self.win = window
        #: One import at a time. A second one is refused with a toast rather
        #: than queued: two runs writing into the same library would race.
        self.running = False

    # ----- ways in --------------------------------------------------------
    def install_drop_target(self, widget):
        """Accept dropped files on ``widget``.

        Installed on the content stack rather than on each grid, so that every
        page -- including the empty-library status page -- accepts ROMs.
        """
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("enter", self._on_drop_enter)
        drop_target.connect("leave", self._on_drop_leave)
        drop_target.connect("drop", self._on_drop)
        widget.add_controller(drop_target)

    def open_picker(self, *_args):
        """The header button, the Ctrl+O action and the empty-library button."""
        dialog = Gtk.FileDialog()
        dialog.set_title(self.win.t("import.dialog.title"))
        dialog.set_modal(True)

        rom_filter = Gtk.FileFilter()
        rom_filter.set_name(self.win.t("import.dialog.filter"))
        for ext in IMPORTABLE_EXTENSIONS:
            suffix = ext.lstrip(".")
            rom_filter.add_pattern(f"*.{suffix}")
            rom_filter.add_pattern(f"*.{suffix.upper()}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(rom_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(rom_filter)

        dialog.open_multiple(self.win, None, self._on_files_chosen)

    def begin(self, paths):
        """Resolve ambiguous extensions, then run the import in the background."""
        if self.running:
            self.win._toast(self.win.t("import.running"))
            return

        # In "All" or "Favorites" there is no console context to import into, so
        # ask outright instead of silently guessing from the file extension.
        if self.win.current_console in (None, ALL_CONSOLES_ID, FAVORITES_ID):
            self._ask_target_console(paths)
            return

        self._continue(paths, forced_console=None)

    # ----- drag and drop --------------------------------------------------
    def _on_drop_enter(self, _target, _x, _y):
        self.win.content_stack.add_css_class("rom-drop-active")
        self.win.tasks.show_notice(self.win.t("import.drop_hint"))
        return Gdk.DragAction.COPY

    def _on_drop_leave(self, _target):
        self.win.content_stack.remove_css_class("rom-drop-active")
        self.win.tasks.refresh()

    def _on_drop(self, _target, value, _x, _y):
        self.win.content_stack.remove_css_class("rom-drop-active")
        self.win.tasks.refresh()
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        if not paths:
            return False
        logger.info("rom import: dropped %d path(s)", len(paths))
        self.begin(paths)
        return True

    def _on_files_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            # Dismissed by the user; nothing to report.
            return
        if files is None:
            return
        paths = []
        for index in range(files.get_n_items()):
            path = files.get_item(index).get_path()
            if path:
                paths.append(path)
        if paths:
            self.begin(paths)

    # ----- the questions --------------------------------------------------
    def _ask_target_console(self, paths):
        """Ask which console to import into, defaulting to auto-detection."""
        dropdown = self.win._build_console_dropdown(
            SYSTEM_IDS,
            default_id=ALL_CONSOLES_ID,
            include_all=True,
            all_label_key="import.console.auto",
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(dropdown)

        dialog = Adw.AlertDialog(
            heading=self.win.t("import.console.heading"),
            body=self.win.t("import.console.body"),
        )
        dialog.set_extra_child(box)
        dialog.add_response("cancel", self.win.t("dialog.cancel"))
        dialog.add_response("import", self.win.t("import.console.confirm"))
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "import":
                return
            chosen = self.win._get_console_dropdown_active_id(dropdown)
            # The "detect automatically" entry reuses the ALL sentinel id.
            forced = None if chosen == ALL_CONSOLES_ID else chosen
            self._continue(paths, forced_console=forced)

        dialog.connect("response", _on_response)
        dialog.present(self.win)

    def _continue(self, paths, forced_console):
        """Run the import, forcing a console or falling back to detection."""
        if forced_console:
            # One console for the whole batch: no per-extension question needed.
            self._run(paths, {}, forced_console=forced_console)
            return

        ambiguous = collect_ambiguous_extensions(paths)
        self._resolve_ambiguous_then_run(paths, list(ambiguous.items()), {})

    def _resolve_ambiguous_then_run(self, paths, pending, overrides):
        if not pending:
            self._run(paths, overrides)
            return

        extension, candidates = pending[0]
        remaining = pending[1:]

        dialog = Adw.AlertDialog(
            heading=self.win.t("import.unknown_console"),
            body=self.win.t("import.choose_console.body", extension=extension),
        )
        dialog.add_response("cancel", self.win.t("dialog.cancel"))
        for console in candidates:
            dialog.add_response(console, f"{console} — {get_system_display_name(console)}")
        dialog.set_default_response(candidates[0])
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response == "cancel":
                return
            overrides[extension] = response
            self._resolve_ambiguous_then_run(paths, remaining, overrides)

        dialog.connect("response", _on_response)
        dialog.present(self.win)

    # ----- the run --------------------------------------------------------
    def _run(self, paths, overrides, forced_console=None):
        self.running = True
        task_id = self.win.tasks.begin("import", self.win.t("import.progress.starting"))

        def _on_progress(evt):
            GLib.idle_add(
                self.win.tasks.update,
                task_id,
                evt.get("current", 0),
                evt.get("total", 0),
                # The counter is rendered by the banner; don't repeat it here.
                self.win.t("import.progress"),
            )

        def _on_done(summary):
            GLib.idle_add(self._on_done_ui, task_id, summary)

        import_roms_async(
            paths=paths,
            roms_dir=self.win.roms_path,
            on_done=_on_done,
            on_progress=_on_progress,
            console_overrides=overrides,
            forced_console=forced_console,
            mode=self.win.config_manager.get_import_mode(),
        )

    def _on_done_ui(self, task_id, summary):
        self.running = False
        self.win.tasks.finish(task_id)

        imported = len(summary["imported"])
        skipped = len(summary["skipped"])
        unknown = len(summary["unknown"])
        errors = len(summary["errors"])
        extracted = len(summary.get("extracted", []))
        logger.info(
            "rom import done: imported=%d extracted=%d skipped=%d unknown=%d errors=%d",
            imported, extracted, skipped, unknown, errors,
        )

        if imported:
            message = self.win.t("import.done", imported=imported, skipped=skipped)
            if extracted:
                # Say so explicitly: the user chose a .zip and got loose files.
                message = f"{message} — {self.win.t('import.extracted', count=extracted)}"
            self.win._toast(message, timeout=6 if extracted else 5)
            # New files on disk: rebuild the playlists so they show up.
            self.win._rescan_all_consoles(show_toast=False)
            # An import is exactly when the library gained ROMs with no artwork,
            # so fetch it now instead of leaving a shelf of blank cartridges
            # until the user remembers to sync by hand.
            self.win._start_post_import_artwork_sync(summary["imported"])
        elif unknown or errors:
            self.win._toast(self.win.t("import.failed", unknown=unknown + errors), timeout=5)
        else:
            self.win._toast(self.win.t("import.nothing_new"), timeout=4)
        return False

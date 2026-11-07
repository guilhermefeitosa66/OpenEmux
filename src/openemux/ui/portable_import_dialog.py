"""Import the profile's data into a portable folder: the dialogs (issue #768).

The copying, the path rewrite and the swap are ``core.portable_import``'s; this
module asks, shows the progress and says what went wrong. Two ways in: the
first start of an empty portable folder, over the first-boot window, and the
"Portable" group of Preferences → System.
"""

from threading import Event, Thread

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from openemux.core import portable_import
from openemux.core.paths import display_text, portable_root, profile_config_dir
from openemux.i18n import tr


def build_import_dialog(locale, source, roms_dir, roms_bytes, replace=False):
    """The question, and the "also copy the ROM folder" check (or ``None``).

    ``replace`` is the Preferences wording: that folder already has data of
    its own, and the import replaces it. Responses: ``fresh``/``copy`` on the
    first start, ``cancel``/``import`` from Preferences.
    """
    if replace:
        heading = tr(locale, "portable_import.replace.heading")
        body = tr(locale, "portable_import.replace.body", path=display_text(source))
    else:
        heading = tr(locale, "portable_import.offer.heading")
        body = tr(locale, "portable_import.offer.body", path=display_text(source))
    dialog = Adw.AlertDialog(heading=heading, body=body)
    if replace:
        dialog.add_response("cancel", tr(locale, "portable_import.replace.cancel"))
        dialog.add_response("import", tr(locale, "portable_import.replace.import"))
        dialog.set_response_appearance("import", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
    else:
        dialog.add_response("fresh", tr(locale, "portable_import.offer.fresh"))
        dialog.add_response("copy", tr(locale, "portable_import.offer.copy"))
        dialog.set_response_appearance("copy", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("copy")
        dialog.set_close_response("fresh")
    check = None
    if roms_dir is not None:
        check = Gtk.CheckButton(
            label=tr(
                locale,
                "portable_import.offer.include_roms",
                size=GLib.format_size(roms_bytes),
            )
        )
        dialog.set_extra_child(check)
    return dialog, check


def error_message(locale, exc):
    """What the user reads when an import did not happen."""
    if getattr(exc, "reason", None) == "no_space":
        return tr(
            locale,
            "portable_import.error.no_space",
            needed=GLib.format_size(exc.needed),
            free=GLib.format_size(exc.free),
        )
    return tr(locale, "portable_import.error.generic", error=str(exc))


#: Set while a copy runs. Both ways in write the same staging directory, and
#: Preferences can be closed and opened again mid-copy.
_RUNNING = Event()


def import_running():
    return _RUNNING.is_set()


def _main_loop(func, *args):
    """Run ``func(*args)`` on the main loop, at the default priority.

    Not ``GLib.idle_add``'s own idle priority: the Preferences row shows a
    spinner while it copies, and a spinner on screen keeps a redraw pending at
    a higher priority, so the progress and the restart toast never arrived
    (the same starvation as #589).
    """
    return GLib.idle_add(func, *args, priority=GLib.PRIORITY_DEFAULT)


def start_import(include_roms, on_progress, on_done, on_error):
    """Plan and copy on a worker thread; the callbacks run on the main loop.

    ``on_progress(fraction)`` comes once per whole percent, not once per file:
    a ROM folder holds thousands of them. Returns ``None``, starting nothing,
    while another copy is still running.
    """
    if _RUNNING.is_set():
        return None
    _RUNNING.set()
    last = [-1]

    def progress(copied, total):
        percent = int(copied * 100 / total) if total else 100
        if percent != last[0]:
            last[0] = percent
            _main_loop(on_progress, percent / 100)

    def worker():
        try:
            plan = portable_import.plan_import(include_roms)
            if plan is None:
                raise portable_import.PortableImportError("failed", "no data to import")
            portable_import.run_import(plan, progress)
        except Exception as exc:
            _RUNNING.clear()
            _main_loop(on_error, exc)
            return
        _RUNNING.clear()
        _main_loop(on_done)

    thread = Thread(target=worker, daemon=True)
    thread.start()
    return thread


def run_first_start_offer(window, locale, on_finished):
    """Ask over the first-boot ``window``; ``on_finished(outcome)`` ends it.

    ``outcome`` is ``"declined"``, ``"imported"`` (staged, for the caller to
    swap in) or ``"failed"`` (the user saw why and pressed Continue).
    """
    roms = portable_import.profile_roms_folder()
    roms_bytes = portable_import.folder_size(roms) if roms is not None else 0
    dialog, check = build_import_dialog(
        locale, portable_import.importable_profile(), roms, roms_bytes
    )

    def show_progress(fraction):
        window.progress.set_fraction(fraction)
        window.progress.set_text(f"{int(fraction * 100)}%")

    def show_error(exc):
        failure = Adw.AlertDialog(
            heading=tr(locale, "portable_import.error.heading"),
            body=error_message(locale, exc),
        )
        failure.add_response("continue", tr(locale, "portable_import.error.continue"))
        failure.connect("response", lambda *_args: on_finished("failed"))
        failure.present(window)

    def on_response(_dialog, response):
        if response != "copy":
            on_finished("declined")
            return
        window.subtitle_label.set_text(tr(locale, "portable_import.progress"))
        show_progress(0.0)
        start_import(
            check is not None and check.get_active(),
            show_progress,
            lambda: on_finished("imported"),
            show_error,
        )

    dialog.connect("response", on_response)
    dialog.present(window)
    return dialog


class PortableImportGroup(Adw.PreferencesGroup):
    """Preferences → System → "Portable": import the profile from here too."""

    #: The group built last. Preferences can be closed and opened again
    #: mid-copy; the copy's progress and its end go to the one on screen.
    latest = None

    def __init__(self, locale, toast):
        super().__init__(title=tr(locale, "prefs.group.portable"))
        self.locale = locale
        self._toast = toast
        self._dialog = None
        self._check = None
        self.row = Adw.ActionRow(title=tr(locale, "portable_import.row.title"))
        self.button = Gtk.Button(label=tr(locale, "portable_import.row.button"))
        self.button.add_css_class("flat")
        self.button.set_valign(Gtk.Align.CENTER)
        self.button.connect("clicked", self._on_clicked)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.row.add_suffix(self.spinner)
        self.row.add_suffix(self.button)
        self.add(self.row)
        PortableImportGroup.latest = self
        self.refresh()
        if import_running():
            # Started from an earlier Preferences window, still copying.
            self._set_busy(True)

    @classmethod
    def build(cls, locale, toast):
        """The group, or ``None`` off a portable install."""
        if portable_root() is None:
            return None
        return cls(locale, toast)

    def refresh(self):
        source = portable_import.importable_profile()
        path = display_text(profile_config_dir())
        if import_running():
            self.row.set_sensitive(False)
        elif source is None:
            self.row.set_subtitle(tr(self.locale, "portable_import.row.missing", path=path))
            self.row.set_sensitive(False)
        else:
            self.row.set_subtitle(tr(self.locale, "portable_import.row.subtitle", path=path))
            self.row.set_sensitive(True)

    def _on_clicked(self, _button):
        source = portable_import.importable_profile()
        if source is None or import_running():
            self.refresh()
            return
        roms = portable_import.profile_roms_folder()
        roms_bytes = portable_import.folder_size(roms) if roms is not None else 0
        self._dialog, self._check = build_import_dialog(
            self.locale, source, roms, roms_bytes, replace=True
        )
        self._dialog.connect("response", self._on_response)
        self._dialog.present(self)

    def _on_response(self, _dialog, response):
        if response != "import" or import_running():
            return
        self._set_busy(True)
        self._on_progress(0.0)
        start_import(
            self._check is not None and self._check.get_active(),
            lambda fraction: PortableImportGroup.latest._on_progress(fraction),
            lambda: PortableImportGroup.latest._on_done(),
            lambda exc: PortableImportGroup.latest._on_error(exc),
        )

    def _set_busy(self, busy):
        self.button.set_visible(not busy)
        self.spinner.set_visible(busy)
        self.spinner.set_spinning(busy)

    def _on_progress(self, fraction):
        self.row.set_subtitle(
            tr(self.locale, "portable_import.row.copying", percent=int(fraction * 100))
        )

    def _on_done(self):
        self._set_busy(False)
        self.refresh()
        self._toast(tr(self.locale, "portable_import.toast.ready"), 0)

    def _on_error(self, exc):
        self._set_busy(False)
        self.refresh()
        self._toast(
            tr(self.locale, "portable_import.toast.failed", error=error_message(self.locale, exc)),
            0,
        )

"""The launch splash of Big Picture, Android's (issue 957).

A game opened from Big Picture shows its art centered on black with
"Starting Snes9x" under it, from the moment it is asked for until the
game's own window takes the screen -- which is when OpenEmux's window
stops being the active one (``notify::is-active``), on X11 and Wayland
alike, with ``MAX_WAIT_S`` as the ceiling. A launch that fails, or a game
that closes straight away, says why here instead of in a toast, with the
log one button away; B, or Close, goes back.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from openemux.core import cover_cache
from openemux.core.scraper import COVER_ART, LABEL_ART, resolve_local_art
from openemux.ui.bigpicture.widgets import button, once

#: The longest the splash waits for the game's window.
MAX_WAIT_S = 15
#: The art's size at scale 1.0.
ART_SIZE = (420, 420)


def core_label(win, rom):
    """The core this game runs on: its own, the console's, else the first one."""
    config = win.config_manager
    catalog = win.core_catalog
    core = config.get_rom_core_override(rom.get("path", "")) or config.get_console_core_override(
        rom.get("console", "")
    )
    if core:
        return catalog.display_name_for(core)
    cores = catalog.cores_for_console(rom.get("console", ""))
    return cores[0].display_name if cores else ""


class LaunchSplash(Gtk.Box):
    """The splash. The window shows it in place of the shell while a game starts."""

    def __init__(self, shell):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.shell = shell
        self.win = shell.win
        t = self.t = shell.win.t
        self.rom = None
        self.shown = False
        self._timeout = 0
        self._active_handler = 0
        self._art_job = 0
        self.add_css_class("bp-splash")
        self.set_valign(Gtk.Align.FILL)
        self.set_vexpand(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_halign(Gtk.Align.CENTER)
        inner.set_vexpand(True)
        self.picture = Gtk.Picture()
        self.picture.add_css_class("bp-splash-art")
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_size_request(*ART_SIZE)
        inner.append(self.picture)
        self.caption = Gtk.Label()
        self.caption.add_css_class("bp-splash-caption")
        inner.append(self.caption)
        self.error_label = Gtk.Label()
        self.error_label.add_css_class("bp-splash-error")
        self.error_label.set_wrap(True)
        self.error_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.error_label.set_max_width_chars(60)
        self.error_label.set_justify(Gtk.Justification.CENTER)
        self.error_label.set_visible(False)
        inner.append(self.error_label)
        self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.buttons.set_halign(Gtk.Align.CENTER)
        self.log_button = button(t("toast.show_log"), self._show_log)
        self.close_button = button(t("big_picture.splash.close"), self.close, suggested=True)
        self.buttons.append(self.log_button)
        self.buttons.append(self.close_button)
        self.buttons.set_visible(False)
        inner.append(self.buttons)
        self.append(inner)

    # -- states ------------------------------------------------------------------
    def show_starting(self, rom):
        """A game was asked for: its art, "Starting <core>"."""
        self.rom = rom
        self.error_label.set_visible(False)
        self.buttons.set_visible(False)
        core = core_label(self.win, rom)
        self.caption.set_label(
            self.t("big_picture.splash.starting", core=core) if core else self.t("big_picture.splash.starting_plain")
        )
        self.caption.set_visible(True)
        self._load_art()
        self._show()

    def wait_for_game(self):
        """The game is up: the splash goes when its window takes over."""
        if not self.shown:
            return
        self._clear_wait()
        self._timeout = GLib.timeout_add_seconds(MAX_WAIT_S, self._on_timeout)
        self._active_handler = self.win.connect("notify::is-active", self._on_active_changed)
        if not self.win.is_active():
            # Already behind the game's window by the time the launch returned.
            GLib.idle_add(once(self.close))

    def show_error(self, message):
        """The launch failed or the game closed at once: why, the log, Close."""
        if self.rom is None:
            return
        self._clear_wait()
        self.caption.set_visible(False)
        self.error_label.set_label(message or "")
        self.error_label.set_visible(True)
        self.buttons.set_visible(True)
        self._show()
        GLib.idle_add(once(self.close_button.grab_focus))

    def close(self):
        """Back to Big Picture."""
        self._clear_wait()
        if not self.shown:
            return
        self.shown = False
        self.win.mode_stack.set_visible_child_name("big-picture")
        self.shell._focus_visible()

    # -- plumbing --------------------------------------------------------------------
    def _show(self):
        self.shown = True
        self.win.mode_stack.set_visible_child_name("bp-splash")
        self.win.navigation.refresh_hints(force=True)

    def _clear_wait(self):
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        if self._active_handler:
            self.win.disconnect(self._active_handler)
            self._active_handler = 0

    def _on_timeout(self):
        self._timeout = 0
        self.close()
        return GLib.SOURCE_REMOVE

    def _on_active_changed(self, *_args):
        if not self.win.is_active():
            self.close()

    def _show_log(self):
        self.close()
        self.win.set_log_panel_visible(True)

    def _load_art(self):
        rom = self.rom
        self._art_job += 1
        job = self._art_job
        self.picture.set_paintable(None)
        roms_dir = self.win.roms_path
        width, height = ART_SIZE

        def _worker():
            path = resolve_local_art(rom, roms_dir, kinds=(LABEL_ART, COVER_ART))
            pixbuf = cover_cache.load_cover(str(path), width * 2, height * 2) if path else None
            GLib.idle_add(self._apply_art, job, pixbuf)

        cover_cache.submit(_worker)

    def _apply_art(self, job, pixbuf):
        if job == self._art_job and pixbuf is not None:
            from openemux.ui.rom_card import texture_for

            self.picture.set_paintable(texture_for(pixbuf))
        return GLib.SOURCE_REMOVE

    def hints(self, g, t):
        if self.buttons.get_visible():
            return [(g["confirm"], t("big_picture.hints.choose")), (g["back"], t("big_picture.splash.close"))]
        return []


__all__ = ["LaunchSplash", "core_label", "MAX_WAIT_S"]

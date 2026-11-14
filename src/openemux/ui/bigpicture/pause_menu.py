"""Big Picture's in-game pause menu, the Android pause sheet's (issue 957).

The game is a RetroArch window of its own, full screen. The pause gesture
(Guide by default; Settings › Controllers offers the others) reaches
OpenEmux through the navigator, which keeps watching the pad during a game
for that one gesture. The game is paused over the command channel and this
window comes up over it, full screen, dark, the pad steering it again:

* the game's title, "Playing for 12 min · Snes9x", a HARDCORE tag when
  RetroAchievements hardcore is on, and ✕;
* Continue (the accent) and Restart (which asks first);
* Save and Load, with the slot and whether it holds a state;
* the slot slider and "See all" (every saved state; A loads one);
* Fast forward and Slow motion (off in hardcore), Screenshot, Audio,
  RetroArch's own menu, and Quit, last and in red.

Skins, the skin editor and the touch controls are phone things and stay on
the phone. If the window cannot get in front of the game (a compositor that
refuses to raise it), the game is unpaused and RetroArch's own menu opens
instead, so the pad is never left with nothing to steer.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from openemux.core import save_states
from openemux.core.pause_session import MAX_SLOT, MIN_SLOT, PauseSession
from openemux.ui.bigpicture.details import stamp
from openemux.ui.bigpicture.splash import core_label
from openemux.ui.bigpicture.widgets import Row, Tile, once

logger = logging.getLogger(__name__)

#: How long the window has to become the active one before the fallback.
ACTIVATION_TIMEOUT_MS = 2000
#: How long after Save the slot is read again: RetroArch writes the file
#: after the command, on its own frame.
SAVE_SETTLE_MS = 600


class SlotScale(Gtk.Scale):
    """The slot slider; Left and Right step it (the navigator's number-row hook)."""

    def __init__(self, on_change):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_range(MIN_SLOT, MAX_SLOT)
        self.set_increments(1, 1)
        self.set_digits(0)
        self.set_round_digits(0)
        self.set_draw_value(False)
        self.set_hexpand(True)
        for slot in range(MIN_SLOT, MAX_SLOT + 1):
            self.add_mark(slot, Gtk.PositionType.BOTTOM, None)
        self._on_change = on_change
        self.connect("value-changed", lambda _s: self._on_change(int(round(self.get_value()))))

    def step(self, delta):
        value = int(round(self.get_value())) + int(delta)
        if value < MIN_SLOT or value > MAX_SLOT:
            return True
        self.set_value(value)
        return True


class PauseMenuWindow(Adw.Window):
    """The menu over the paused game. One per main window, reused."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        t = self.t = win.t
        self.rom = None
        self.session = None
        self._process = None
        self._watchdog = 0
        self.add_css_class("big-picture")
        self.add_css_class("bp-pause-window")
        self.set_title(t("big_picture.pause.title"))
        self.set_decorated(False)
        self.connect("close-request", self._on_close_request)
        # The window's own keys: the main window's handler never sees them,
        # and the keyboard hints promise Esc as B.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.set_content(self.stack)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_valign(Gtk.Align.CENTER)
        page.set_halign(Gtk.Align.CENTER)
        sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        sheet.add_css_class("bp-pause-sheet")
        sheet.set_size_request(1040, -1)
        page.append(sheet)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        titles.set_hexpand(True)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-pane-title")
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_row.append(self.title_label)
        self.hardcore_tag = Gtk.Label(label=t("big_picture.pause.hardcore"))
        self.hardcore_tag.add_css_class("bp-tag")
        self.hardcore_tag.add_css_class("bp-tag-accent")
        self.hardcore_tag.set_valign(Gtk.Align.CENTER)
        title_row.append(self.hardcore_tag)
        titles.append(title_row)
        self.meta_label = Gtk.Label(xalign=0.0)
        self.meta_label.add_css_class("bp-pane-meta")
        titles.append(self.meta_label)
        header.append(titles)
        self.close_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        self.close_button.add_css_class("bp-icon-button")
        self.close_button.set_tooltip_text(t("big_picture.pause.continue"))
        self.close_button.set_valign(Gtk.Align.START)
        self.close_button.connect("clicked", lambda _b: self.resume())
        header.append(self.close_button)
        sheet.append(header)

        grid = Gtk.Grid()
        grid.set_row_spacing(14)
        grid.set_column_spacing(14)
        grid.set_column_homogeneous(True)
        self.continue_tile = Tile(t("big_picture.pause.continue"), icon_name="media-playback-start-symbolic",
                                  wide=True, fit_name=False, on_activate=self.resume, style="bp-primary")
        self.restart_tile = Tile(t("big_picture.pause.restart"), icon_name="view-refresh-symbolic",
                                 wide=True, fit_name=False, on_activate=self._ask_restart)
        self.save_tile = Tile(t("big_picture.pause.save"), icon_name="media-floppy-symbolic",
                              wide=True, fit_name=False, on_activate=self._on_save)
        self.load_tile = Tile(t("big_picture.pause.load"), icon_name="document-open-symbolic",
                              wide=True, fit_name=False, on_activate=self._on_load)
        grid.attach(self.continue_tile, 0, 0, 3, 1)
        grid.attach(self.restart_tile, 3, 0, 3, 1)
        grid.attach(self.save_tile, 0, 1, 3, 1)
        grid.attach(self.load_tile, 3, 1, 3, 1)
        sheet.append(grid)

        slots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.slot_label = Gtk.Label(xalign=0.0)
        self.slot_label.add_css_class("bp-row-title")
        self.slot_label.set_width_chars(8)
        slots.append(self.slot_label)
        self.slot_scale = SlotScale(self._on_slot_changed)
        slots.append(self.slot_scale)
        self.see_all_button = Gtk.Button(label=t("big_picture.pause.see_all"))
        self.see_all_button.add_css_class("bp-pill-button")
        self.see_all_button.connect("clicked", lambda _b: self.show_states())
        slots.append(self.see_all_button)
        sheet.append(slots)

        tiles = Gtk.Grid()
        tiles.set_row_spacing(14)
        tiles.set_column_spacing(14)
        tiles.set_column_homogeneous(True)
        self.fast_tile = Tile(t("big_picture.pause.fast_forward"), icon_name="media-seek-forward-symbolic",
                              fit_name=False, on_activate=self._on_fast_forward)
        self.slow_tile = Tile(t("big_picture.pause.slow_motion"), icon_name="media-seek-backward-symbolic",
                              fit_name=False, on_activate=self._on_slow_motion)
        self.shot_tile = Tile(t("big_picture.pause.screenshot"), icon_name="camera-photo-symbolic",
                              fit_name=False, on_activate=self._on_screenshot)
        self.audio_tile = Tile(t("big_picture.pause.audio"), icon_name="audio-volume-high-symbolic",
                               fit_name=False, on_activate=self._on_mute)
        self.menu_tile = Tile(t("big_picture.pause.retroarch_menu"), icon_name="open-menu-symbolic",
                              fit_name=False, on_activate=self._on_retroarch_menu)
        self.quit_tile = Tile(t("big_picture.pause.quit"), icon_name="system-shutdown-symbolic",
                              fit_name=False, on_activate=self._ask_quit, style="bp-danger")
        for index, tile in enumerate((self.fast_tile, self.slow_tile, self.shot_tile,
                                      self.audio_tile, self.menu_tile, self.quit_tile)):
            tiles.attach(tile, index, 0, 1, 1)
        sheet.append(tiles)
        self.note_label = Gtk.Label(xalign=0.5)
        self.note_label.add_css_class("bp-pane-meta")
        sheet.append(self.note_label)
        self.stack.add_named(page, "main")

        states_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        states_page.set_valign(Gtk.Align.CENTER)
        states_page.set_halign(Gtk.Align.CENTER)
        states_page.set_size_request(1040, -1)
        heading = Gtk.Label(label=t("big_picture.pause.states"), xalign=0.0)
        heading.add_css_class("bp-pane-title")
        states_page.append(heading)
        self.states_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        states_page.append(self.states_box)
        self.states_empty = Gtk.Label(label=t("big_picture.pane.states.empty"), xalign=0.0)
        self.states_empty.add_css_class("bp-pane-meta")
        states_page.append(self.states_empty)
        self.state_rows = []
        self.stack.add_named(states_page, "states")

    # -- opening and closing -------------------------------------------------------
    def session_for(self, rom):
        """This game's session: the same one while the same process runs."""
        runtime = self.win.runtime_manager
        process = runtime.active_process
        if self.session is None or process is not self._process:
            achievements = self.win.config_manager.achievements
            hardcore = bool(
                achievements.is_signed_in() and achievements.get_enabled() and achievements.get_hardcore()
            )
            self.session = PauseSession(runtime.send_command, hardcore=hardcore)
            launched = getattr(runtime, "_launched_at", None)
            if launched is not None:
                self.session.started_at = launched
            self._process = process
        return self.session

    def open(self, rom):
        """The gesture happened: pause the game, come up over it."""
        self.rom = rom
        session = self.session_for(rom)
        if not session.pause():
            # The game never got the command: a menu over it would leave it
            # running with nothing reading the pad.
            logger.warning("pause menu: the game did not take the pause command")
            return False
        self.win.pause_menu_open = True
        self.stack.set_visible_child_name("main")
        self.note_label.set_label("")
        self._sync()
        self.slot_scale.set_value(session.slot)
        self.present()
        self.fullscreen()
        GLib.idle_add(once(self.continue_tile.grab_focus))
        self._arm_watchdog()
        self.win.navigation.refresh_hints(force=True)
        logger.info("pause menu: open for %s", rom.get("name", ""))
        return True

    def _arm_watchdog(self):
        if self._watchdog:
            GLib.source_remove(self._watchdog)
        self._watchdog = GLib.timeout_add(ACTIVATION_TIMEOUT_MS, self._on_watchdog)

    def _on_watchdog(self):
        """Not in front after the timeout: RetroArch's own menu, so the pad has something."""
        self._watchdog = 0
        if self.win.pause_menu_open and not self.is_active():
            logger.warning("pause menu: the window did not come to the front; RetroArch's menu instead")
            self.close_menu()
            if self.session is not None:
                self.session.retroarch_menu()
        return GLib.SOURCE_REMOVE

    def close_menu(self):
        """Hide, without touching the game (it ended, or a fallback runs)."""
        if self._watchdog:
            GLib.source_remove(self._watchdog)
            self._watchdog = 0
        self.win.pause_menu_open = False
        self.set_visible(False)
        self.win.navigation.refresh_hints(force=True)

    def resume(self):
        """Continue: unpause and give the screen back to the game."""
        if self.session is not None:
            self.session.resume()
        self.close_menu()
        return True

    def _on_close_request(self, *_args):
        # Alt+F4 or the compositor: the same as Continue, the window kept.
        self.resume()
        return True

    def _on_key(self, _controller, keyval, _keycode, _state):
        """Escape is B, as on every other Big Picture page."""
        if keyval != Gdk.KEY_Escape:
            return False
        return self.handle_back()

    # -- the pad -------------------------------------------------------------------------
    def handle_back(self):
        """B: out of "See all", else back to the game."""
        if self.stack.get_visible_child_name() == "states":
            self.stack.set_visible_child_name("main")
            GLib.idle_add(once(self.see_all_button.grab_focus))
            return True
        return self.resume()

    def step_slot(self, delta):
        return self.slot_scale.step(delta)

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.choose")),
            (g["back"], t("hints.back")),
            (g["consoles"], t("big_picture.pause.slot_hint")),
            (g["guide"], t("big_picture.pause.back_to_game")),
        ]

    # -- what it shows --------------------------------------------------------------------
    def _states(self):
        rom = self.rom or {}
        states_dir = self.win.config_manager.get_console_states_dir(rom.get("console", ""))
        return save_states.list_states(states_dir, rom.get("path", ""))

    def _core_label(self):
        return core_label(self.win, self.rom or {})

    def _sync(self):
        t, session = self.t, self.session
        self.title_label.set_label((self.rom or {}).get("name", ""))
        minutes = session.played_minutes()
        parts = [t("big_picture.pause.playing_for", minutes=minutes), self._core_label()]
        self.meta_label.set_label(" · ".join(part for part in parts if part))
        self.hardcore_tag.set_visible(session.hardcore)
        self.fast_tile.set_sensitive(session.speed_allowed)
        self.slow_tile.set_sensitive(session.speed_allowed)
        for tile, on in ((self.fast_tile, session.fast_forward), (self.slow_tile, session.slow_motion),
                         (self.audio_tile, session.muted)):
            if on:
                tile.add_css_class("bp-on")
            else:
                tile.remove_css_class("bp-on")
        self._sync_slot()

    def _sync_slot(self):
        if self.session is None:
            # A settle timer outlived the session (the game ended meanwhile).
            return
        t, slot = self.t, self.session.slot
        used = any(state.slot == slot for state in self._states())
        self.slot_label.set_label(t("details.states.slot", slot=slot))
        caption = t("big_picture.pause.slot_used" if used else "big_picture.pause.slot_empty", slot=slot)
        self.save_tile.set_count(caption)
        self.load_tile.set_count(caption)
        self.load_tile.set_sensitive(used)

    def _on_slot_changed(self, slot):
        if self.session is not None:
            self.session.set_slot(slot)
            self._sync_slot()

    # -- the actions ------------------------------------------------------------------------
    def _ask_restart(self):
        self._ask(self.t("big_picture.pause.restart_question"), self.t("big_picture.pause.restart"),
                  self._restart)

    def _restart(self):
        self.session.restart()
        self.resume()

    def _ask_quit(self):
        self._ask(self.t("big_picture.pause.quit_question"), self.t("big_picture.pause.quit"), self._quit)

    def _quit(self):
        self.close_menu()
        self.session.quit()

    def _ask(self, heading, confirm_label, on_confirm):
        dialog = Adw.AlertDialog(heading=heading)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: on_confirm() if response == "confirm" else None)
        dialog.present(self)
        return dialog

    def _on_save(self):
        if self.session.save():
            self.note_label.set_label(self.t("big_picture.pause.saved", slot=self.session.slot))
            GLib.timeout_add(SAVE_SETTLE_MS, once(self._sync_slot))

    def _on_load(self):
        if self.session.load():
            self.resume()

    def _on_fast_forward(self):
        self.session.toggle_fast_forward()
        self._sync()

    def _on_slow_motion(self):
        self.session.toggle_slow_motion()
        self._sync()

    def _on_mute(self):
        self.session.toggle_mute()
        self._sync()

    def _on_screenshot(self):
        if self.session.screenshot():
            self.note_label.set_label(self.t("big_picture.pause.screenshot_taken"))

    def _on_retroarch_menu(self):
        self.close_menu()
        self.session.retroarch_menu()

    # -- every state -----------------------------------------------------------------------------
    def show_states(self):
        """See all: every saved slot, newest date shown; A loads one."""
        t = self.t
        child = self.states_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.states_box.remove(child)
            child = following
        self.state_rows = []
        for state in self._states():
            row = Row(
                t("details.states.slot", slot=state.slot), stamp(state.mtime),
                on_activate=lambda slot=state.slot: self._load_slot(slot),
            )
            self.states_box.append(row)
            self.state_rows.append(row)
        self.states_empty.set_visible(not self.state_rows)
        self.stack.set_visible_child_name("states")
        if self.state_rows:
            GLib.idle_add(once(self.state_rows[0].grab_focus))
        return True

    def _load_slot(self, slot):
        if self.session.load_slot(slot):
            self.slot_scale.set_value(slot)
            self.resume()


__all__ = ["PauseMenuWindow", "SlotScale", "ACTIVATION_TIMEOUT_MS"]

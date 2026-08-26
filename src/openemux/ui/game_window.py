"""The embedded-RetroArch game window.

An ``Adw.Window`` that adopts the running RetroArch X11 window as its own
content: libadwaita headerbar and borders outside, the game inside. With
the frame flag on, the CRT TV artwork (``assets/images/tv-frame.png``) is
drawn and the game sits inside the TV's screen cutout; without it the game
fills the content area and the headerbar carries the action buttons.

The headerbar buttons talk to RetroArch over the UDP network-command
channel the launcher already enables (``RuntimeManager.send_command``).

Whether a wrapper opens at all is ``runtime.game_window`` plus what the
session can actually do -- see ``openemux.core.game_window_support``.

Note: X keyboard focus is handed to the embedded window so RetroArch
receives the keyboard; GTK then paints the headerbar as unfocused while
playing.
"""

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from openemux.core import game_window_support, retroarch_log, screen_geometry
from openemux.i18n import tr
from openemux.core.retroarch_command import (
    MAX_VOLUME_DB,
    MIN_VOLUME_DB,
    VOLUME_SNAP_WINDOW_DB,
)
from openemux.core.x11_embed import RetroArchWindowEmbedder

logger = logging.getLogger(__name__)

FRAME_ASSET = Path(__file__).parent / "assets" / "images" / "frames" / "tv-crt.png"


def display_supports_embedding():
    """True when the app itself is an X11 client (native X11 or XWayland).

    Embedding is XReparentWindow underneath, so a native-Wayland GDK
    display can never host it -- the caller should then leave RetroArch
    in its own window instead of opening a wrapper that cannot work.
    (``main.py`` forces GDK_BACKEND=x11 while the embed flag is on, so
    this only returns False when that forcing failed or was overridden.)
    """
    display = Gdk.Display.get_default()
    return display is not None and "X11" in type(display).__name__

#: Geometry sync / process watch cadence, and how long the RetroArch
#: window gets to appear before the search is abandoned (slow first core
#: load included).
TICK_INTERVAL_MS = 200
FIND_WINDOW_TIMEOUT_TICKS = 100

#: How often the volume popover re-reads the level the game has reached
#: while a walk is still in flight (issue #284). Fast enough to read as
#: movement, slow enough to cost nothing next to a 75 ms packet cadence.
VOLUME_WATCH_INTERVAL_MS = 150

#: Ignore repeats of the grabbed fullscreen hotkey inside this window --
#: X auto-repeat turns a held key into a stream of presses.
FULLSCREEN_DEBOUNCE_US = 400_000

#: The key the wrapper falls back to when the user's own fullscreen binding
#: cannot be resolved to an X keycode. RetroArch's toggle is deliberately
#: unbound while embedded, so without this a user who rebound fullscreen to a
#: key X cannot name would have no fullscreen key at all (issue #236).
FULLSCREEN_FALLBACK_KEY = "f"

#: How often, in ticks, the wrapper asks RetroArch's log which display server
#: it took, and how often it re-checks that the embedded window is still ours.
#: Both are X/disk round-trips that nothing needs at the 200 ms tick rate.
LOG_PROBE_INTERVAL_TICKS = 5
PARENT_CHECK_INTERVAL_TICKS = 5


class _GameScreen(Gtk.Widget):
    """Draws the CRT frame (or plain black) and knows where the game goes."""

    def __init__(self, frame_texture):
        super().__init__()
        self._texture = frame_texture
        self.set_hexpand(True)
        self.set_vexpand(True)

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return (320, 900, -1, -1)
        return (240, 860, -1, -1)

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        background = Gdk.RGBA()
        background.parse("#000000")
        snapshot.append_color(
            background, Graphene.Rect().init(0, 0, width, height)
        )
        if self._texture is not None:
            fx, fy, fw, fh = screen_geometry.frame_paint_rect(width, height)
            if fw > 0 and fh > 0:
                snapshot.append_texture(
                    self._texture, Graphene.Rect().init(fx, fy, fw, fh)
                )

    def screen_rect(self):
        """The game video rect in this widget's coordinates: (x, y, w, h)."""
        return screen_geometry.screen_rect(
            self.get_width(), self.get_height(), self._texture is not None
        )


class GameWindow(Adw.Window):
    def __init__(self, application, runtime_manager, rom, frame_enabled,
                 locale="en", on_closed=None, on_open_input_settings=None,
                 on_embed_failed=None):
        super().__init__(application=application)
        # Translated once, at construction: the window lives for one game,
        # so there is no language switch to follow mid-flight.
        self._locale = locale
        self._runtime = runtime_manager
        self._proc = runtime_manager.active_process
        # Called exactly once, from whichever close path runs first. The
        # owner must not learn about the close from GTK signals: this GTK
        # defers the "destroy" emission past gtk_window_destroy(), so a
        # signal-based owner kept a stale reference for the app's lifetime.
        self._on_closed = on_closed
        self._on_open_input_settings = on_open_input_settings
        # Called at most once, when the wrapper gives up on adopting the
        # game. The owner is the one that can put the game back in a normal
        # decorated window, which is the whole point of issue #267 -- this
        # window is on its way out by the time it fires.
        self._on_embed_failed = on_embed_failed
        self._embedder = RetroArchWindowEmbedder()
        self._child_xid = None
        self._parent_xid = None
        # RetroArch's own fullscreen toggle is unbound while embedded (it
        # would recreate the window), so the wrapper takes over the user's
        # binding and fullscreens itself instead.
        profile = runtime_manager.config_manager.get_input_profile(rom.get("console"))
        keyboard = (profile.get("devices", {}) or {}).get("keyboard", {}) or {}
        self._fullscreen_key = (
            (keyboard.get("bindings", {}) or {}).get("fullscreen_toggle")
            or FULLSCREEN_FALLBACK_KEY
        )
        self._fullscreen_keycode = None
        self._fullscreen_toggled_at = 0
        # Set when embedding turns out to be impossible: the wrapper closes
        # itself and must leave the standalone RetroArch window running.
        self._standalone_fallback = False
        self._closing = False
        self._paused = False
        self._tick_id = None
        self._ticks_waited = 0
        self._last_rect = None
        # RetroArch's own answer about the display server it took, cached:
        # only a definite "not X11" is actionable, and once the log has said
        # it there is nothing left to learn from re-reading the file.
        self._log_verdict = retroarch_log.UNKNOWN
        # Ticks since the game was adopted; paces the "is it still ours?"
        # check, kept apart from _ticks_waited, which is the search budget.
        self._embedded_ticks = 0

        name = rom.get("name") or Path(rom.get("path", "Game")).stem
        self.set_title(name)

        texture = self._load_frame_texture() if frame_enabled else None
        self._screen = _GameScreen(texture)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title=name, subtitle=rom.get("console", ""))
        )
        self._pause_button = self._action_button(
            "media-playback-pause-symbolic", self._t("game_window.pause"),
            self._on_pause_clicked
        )
        header.pack_start(self._pause_button)
        header.pack_start(
            self._action_button(
                "view-refresh-symbolic", self._t("game_window.reset"),
                self._on_reset_clicked
            )
        )
        header.pack_start(
            self._action_button(
                "media-floppy-symbolic", self._t("game_window.save_state"),
                self._on_save_state_clicked
            )
        )
        header.pack_start(
            self._action_button(
                "folder-download-symbolic", self._t("game_window.load_state"),
                self._on_load_state_clicked
            )
        )
        # Right side, rightmost first: RetroArch menu, volume (mute lives
        # inside its popover, like the library's control), controller settings.
        header.pack_end(
            self._action_button(
                "open-menu-symbolic", self._t("game_window.menu"),
                self._on_menu_clicked
            )
        )
        header.pack_end(self._build_volume_button())
        header.pack_end(
            self._action_button(
                "input-gaming-symbolic",
                self._t("game_window.controller_settings"),
                self._on_input_settings_clicked,
            )
        )

        # The game screen with a "starting" overlay on top of it. Until the
        # reparent lands there is nothing to show but black, and a wrapper
        # that sits black and then vanishes is exactly what issue #267
        # describes. The overlay is dropped the moment the game is inside.
        self._overlay = Gtk.Overlay()
        self._overlay.set_child(self._screen)
        self._starting = self._build_starting_indicator(name)
        # can_target off so clicks fall through to the game area, and
        # measure off so the spinner can never influence _GameScreen's
        # allocation -- the embedded X window's rect is computed from it.
        self._overlay.add_overlay(self._starting)
        self._overlay.set_measure_overlay(self._starting, False)

        self._toolbar = Adw.ToolbarView()
        self._toolbar.add_top_bar(header)
        self._toolbar.set_content(self._overlay)
        self.set_content(self._toolbar)
        self.set_default_size(920, 930 if texture is not None else 740)

        self.connect("map", self._on_map)
        self.connect("close-request", self._on_close_request)

        self._embedder.snapshot_existing()

    def _build_starting_indicator(self, name):
        """Spinner and a line of text shown while the game is being adopted.

        ``Gtk.Spinner`` rather than ``Adw.Spinner``: the libadwaita floor is
        1.5 and the latter arrived in 1.7. It is deprecated in very recent
        GTK but not removed.
        """
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        spinner.start()

        label = Gtk.Label(label=self._t("game_window.starting").format(name=name))
        label.add_css_class("dim-label")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_can_target(False)
        box.append(spinner)
        box.append(label)
        self._starting_spinner = spinner
        return box

    def _hide_starting_indicator(self):
        """Idempotent: every path out of the wait calls it."""
        if self._starting is None:
            return
        self._starting_spinner.stop()
        self._starting.set_visible(False)
        self._starting = None

    def _build_volume_button(self):
        """A headerbar volume control mirroring the library's (issue #69):
        a MenuButton whose popover holds the mute toggle and the dB slider,
        walked over UDP by the runtime manager's pacer."""
        self._volume_btn = Gtk.MenuButton()
        self._volume_btn.set_icon_name("audio-volume-high-symbolic")
        self._volume_btn.set_tooltip_text(self._t("game_window.volume"))

        self._volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, MIN_VOLUME_DB, MAX_VOLUME_DB, 0.5
        )
        self._volume_scale.set_size_request(200, -1)
        self._volume_scale.set_draw_value(True)
        self._volume_scale.set_value_pos(Gtk.PositionType.RIGHT)
        # Same reading RetroArch's own OSD gives: amplitude percent + dB.
        self._volume_scale.set_format_value_func(
            lambda _s, v: f"{10 ** (v / 20) * 100:.0f}%  {v:+.1f} dB"
        )
        # The range continues past 100%, so unity gain gets a tick mark,
        # desktop-volume style; _on_volume_changed snaps drags onto it.
        self._volume_scale.add_mark(0.0, Gtk.PositionType.BOTTOM, None)
        self._volume_seed_guard = False
        self._volume_scale.set_value(self._runtime.volume_db)
        self._volume_scale.connect("value-changed", self._on_volume_changed)

        self._mute_button = Gtk.ToggleButton()
        self._mute_button.set_icon_name("audio-volume-muted-symbolic")
        self._mute_button.set_tooltip_text(self._t("game_window.mute"))
        self._mute_button.add_css_class("flat")
        self._mute_guard = False
        # Tracks a mute this control engaged itself at the slider floor, so
        # dragging back up releases it without touching a manual mute.
        self._auto_muted = False
        self._mute_button.connect("toggled", self._on_mute_toggled)

        # RetroArch has no absolute set-volume command, so a drag becomes a
        # walk of 0.5 dB steps -- seconds of them, for a long one. This says
        # where the game actually is while that happens, instead of leaving
        # the slider showing a level it has not reached (issue #284).
        self._volume_status = Gtk.Label()
        self._volume_status.add_css_class("dim-label")
        self._volume_status.add_css_class("caption")
        self._volume_status.set_halign(Gtk.Align.END)
        self._volume_status.set_visible(False)
        self._volume_watch_id = None

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(self._mute_button)
        row.append(self._volume_scale)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.append(row)
        box.append(self._volume_status)

        popover = Gtk.Popover()
        popover.set_child(box)
        popover.connect("show", self._on_volume_popover_shown)
        self._volume_btn.set_popover(popover)
        return self._volume_btn

    def _t(self, key):
        return tr(self._locale, key)

    @staticmethod
    def _load_frame_texture():
        try:
            return Gdk.Texture.new_from_filename(str(FRAME_ASSET))
        except GLib.Error as exc:
            logger.warning("game window: cannot load %s: %s", FRAME_ASSET, exc)
            return None

    def _action_button(self, icon_name, tooltip, handler):
        button = Gtk.Button.new_from_icon_name(icon_name)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", handler)
        return button

    # -- headerbar actions --------------------------------------------------
    def _on_pause_clicked(self, _button):
        if self._runtime.send_command("PAUSE_TOGGLE"):
            self._paused = not self._paused
            self._pause_button.set_icon_name(
                "media-playback-start-symbolic"
                if self._paused
                else "media-playback-pause-symbolic"
            )
            self._pause_button.set_tooltip_text(
                "Resume" if self._paused else "Pause"
            )

    def _on_reset_clicked(self, _button):
        self._runtime.send_command("RESET")

    def _on_save_state_clicked(self, _button):
        self._runtime.send_command("SAVE_STATE")

    def _on_load_state_clicked(self, _button):
        self._runtime.send_command("LOAD_STATE")

    def _on_menu_clicked(self, _button):
        self._runtime.send_command("MENU_TOGGLE")

    def _on_volume_changed(self, scale):
        if self._volume_seed_guard:
            level = scale.get_value()
        else:
            value = scale.get_value()
            if value != 0.0 and abs(value) <= VOLUME_SNAP_WINDOW_DB:
                # Magnetic 100%: re-enters this handler at exactly 0 dB.
                scale.set_value(0.0)
                return
            level = self._runtime.set_master_volume_db(value)
            self._watch_volume_walk()
            # The slider floor (-40 dB) is quiet but not silent; reaching
            # it should read as "off", so the control mutes there and
            # releases that mute -- only its own -- on the way back up.
            at_floor = level <= MIN_VOLUME_DB + 1e-6
            if at_floor and not self._mute_button.get_active():
                self._auto_muted = True
                self._mute_button.set_active(True)
            elif not at_floor and self._auto_muted:
                self._auto_muted = False
                if self._mute_button.get_active():
                    self._mute_button.set_active(False)
        icon = "audio-volume-high-symbolic"
        if level <= -30:
            icon = "audio-volume-low-symbolic"
        elif level <= -12:
            icon = "audio-volume-medium-symbolic"
        if not self._mute_button.get_active():
            self._volume_btn.set_icon_name(icon)

    def _on_mute_toggled(self, button):
        if self._mute_guard:
            return
        muted = self._runtime.toggle_mute()
        if muted != button.get_active():
            # The command did not go out (game gone mid-toggle): stay honest.
            self._mute_guard = True
            button.set_active(muted)
            self._mute_guard = False
        self._volume_btn.set_icon_name(
            "audio-volume-muted-symbolic" if muted else "audio-volume-high-symbolic"
        )
        if not muted:
            self._on_volume_changed(self._volume_scale)

    def _volume_reading(self, level):
        """The same format the slider's own value uses."""
        return f"{10 ** (level / 20) * 100:.0f}%  {level:+.1f} dB"

    def _watch_volume_walk(self):
        """Report the real level until it catches up with the slider."""
        if self._volume_watch_id is not None:
            return
        self._volume_watch_id = GLib.timeout_add(
            VOLUME_WATCH_INTERVAL_MS, self._on_volume_walk_tick
        )

    def _on_volume_walk_tick(self):
        if self._closing:
            self._volume_watch_id = None
            return False
        if self._runtime.volume_settling:
            self._volume_status.set_text(
                self._t("game_window.volume.settling").format(
                    level=self._volume_reading(self._runtime.volume_db)
                )
            )
            self._volume_status.set_visible(True)
            return True
        # Settled. Normally the two already agree; they do not when a step
        # never left the socket, and that is the moment to say so rather
        # than snapping the slider on some later popover open.
        self._volume_status.set_visible(False)
        self._volume_seed_guard = True
        self._volume_scale.set_value(self._runtime.volume_db)
        self._volume_seed_guard = False
        self._volume_watch_id = None
        return False

    def _on_volume_popover_shown(self, _popover):
        # Re-seed on open: the level and mute may have moved through the
        # library's own control or a RetroArch hotkey since the last look.
        self._volume_seed_guard = True
        self._volume_scale.set_value(self._runtime.volume_db)
        self._volume_seed_guard = False
        self._mute_guard = True
        self._mute_button.set_active(self._runtime.muted)
        self._mute_guard = False
        if self._runtime.volume_settling:
            self._watch_volume_walk()
        else:
            self._volume_status.set_visible(False)

    def _on_input_settings_clicked(self, _button):
        if self._on_open_input_settings is not None:
            self._on_open_input_settings(self)

    # -- embedding lifecycle ------------------------------------------------
    def _on_map(self, _widget):
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(TICK_INTERVAL_MS, self._tick)

    def _tick(self):
        if self._closing:
            self._tick_id = None
            return False
        exit_code = None if self._proc is None else self._proc.poll()
        if self._proc is None or exit_code is not None:
            # The game ended on its own (RetroArch menu quit, crash): the
            # wrapper window has nothing left to show.
            self._note_death_before_embed(exit_code)
            self._tick_id = None
            self._close_and_destroy()
            return False
        if self._child_xid is None:
            if not self._try_embed():
                # The wrapper gave up and tore this source down with it.
                self._tick_id = None
                return False
        else:
            self._sync_geometry()
            # Reclaimed every tick: the WM hands focus back to our toplevel
            # on every click/activation, and without it RetroArch drops
            # keyboard, hotkeys and (through its focus check) gamepad input.
            self._embedder.ensure_focus(self._child_xid, self._parent_xid)
            self._reassert_embed()
            if self._fullscreen_keycode in self._embedder.pressed_grabbed_keycodes():
                self._toggle_fullscreen()
        return True

    def _note_death_before_embed(self, exit_code):
        """A game that died before showing a window is an embed failure too.

        Without this the next launch repeats it identically -- same overrides,
        same wrapper, same nothing. A clean exit is left alone: quitting from
        the RetroArch menu within the search window is a normal thing to do
        and says nothing about embedding.
        """
        if self._child_xid is not None or exit_code in (None, 0):
            return
        game_window_support.mark_embed_unavailable(
            f"RetroArch exited ({exit_code}) before its window appeared"
        )
        logger.warning(
            "game window: RetroArch exited with %s before a window appeared; "
            "later launches this session run standalone",
            exit_code,
        )

    def _probe_retroarch_log(self):
        """Ask RetroArch's log whether it is an X client at all.

        The difference between failing in a second or two and sitting on a
        black screen for twenty. Cached: only a definite "not X11" changes
        anything, and re-reading the file after that answer is pure waste.
        """
        if self._log_verdict != retroarch_log.UNKNOWN:
            return self._log_verdict
        if self._ticks_waited % LOG_PROBE_INTERVAL_TICKS:
            return self._log_verdict
        self._log_verdict = retroarch_log.read_verdict(
            getattr(self._proc, "_openemux_log_path", None)
        )
        return self._log_verdict

    def _reassert_embed(self):
        """Put the game back if something re-parented it away from us.

        Only a definite answer acts. ``None`` means the question could not be
        asked -- typically the window is already gone -- and re-parenting on
        that would fight the game's own teardown. The parent is re-read
        rather than trusted from ``_parent_xid`` so a toplevel that changed
        underneath us does not read as permanent drift.
        """
        self._embedded_ticks += 1
        if self._embedded_ticks % PARENT_CHECK_INTERVAL_TICKS:
            return
        parent_xid = self._surface_xid()
        if parent_xid is None:
            return
        if self._embedder.is_child_of(self._child_xid, parent_xid) is not False:
            return
        rect = self._surface_rect()
        if rect is None:
            return
        logger.warning(
            "game window: the game window left our frame; re-adopting 0x%x",
            self._child_xid,
        )
        if self._embedder.embed(self._child_xid, parent_xid, *rect):
            self._parent_xid = parent_xid
            self._last_rect = rect
            self._embedder.focus(self._child_xid)
            if self._fullscreen_keycode is None:
                self._fullscreen_keycode = self._embedder.grab_key(
                    parent_xid, self._fullscreen_key, FULLSCREEN_FALLBACK_KEY
                )

    def _try_embed(self):
        """One attempt at adopting the game. False once the wrapper gave up."""
        if not self._embedder.available:
            self._fall_back_to_standalone("python-xlib is unavailable")
            return False
        self._ticks_waited += 1
        # RetroArch says which display server it took as soon as it has
        # video, and on Wayland no X window will *ever* appear -- waiting out
        # the full budget for that is twenty seconds of black for nothing.
        if self._probe_retroarch_log() == retroarch_log.NOT_X11:
            self._fall_back_to_standalone("RetroArch is not an X11 client")
            return False
        if retroarch_log.should_abandon(
            self._log_verdict, self._ticks_waited, FIND_WINDOW_TIMEOUT_TICKS
        ):
            self._fall_back_to_standalone("RetroArch window not found in time")
            return False
        parent_xid = self._surface_xid()
        if parent_xid is None:
            # Not fatal on its own: the surface can be missing while the
            # window is still settling, and killing the wrapper the first
            # time it is asked leaves the game borderless for a condition
            # that clears itself. The search budget above is the real limit.
            return True
        child_xid = self._embedder.find_game_window(getattr(self._proc, "pid", None))
        if child_xid is None:
            return True
        rect = self._surface_rect()
        if rect is None:
            # Not laid out yet; the window is still settling. Next tick.
            return True
        if not self._embedder.embed(child_xid, parent_xid, *rect):
            self._fall_back_to_standalone("reparenting failed")
            return False
        self._child_xid = child_xid
        self._parent_xid = parent_xid
        self._last_rect = rect
        self._hide_starting_indicator()
        self._embedder.focus(child_xid)
        # The fallback matters: RetroArch's own toggle is unbound while
        # embedded, so a binding X cannot name would mean no fullscreen key
        # at all rather than a differently-shaped one (issue #236).
        self._fullscreen_keycode = self._embedder.grab_key(
            parent_xid, self._fullscreen_key, FULLSCREEN_FALLBACK_KEY
        )
        logger.info("game window: embedded RetroArch window 0x%x", child_xid)
        return True

    def _toggle_fullscreen(self):
        now = GLib.get_monotonic_time()
        if now - self._fullscreen_toggled_at < FULLSCREEN_DEBOUNCE_US:
            return
        self._fullscreen_toggled_at = now
        if self.is_fullscreen():
            self.unfullscreen()
            self._toolbar.set_reveal_top_bars(True)
        else:
            self.fullscreen()
            self._toolbar.set_reveal_top_bars(False)

    def _fall_back_to_standalone(self, reason):
        """Close the wrapper and hand the game back to its owner.

        An embed failure (native Wayland, missing tooling, a lost race) must
        cost the chrome, never the game -- but the game was launched with
        RetroArch's decorations stripped and its fullscreen hotkey unbound,
        so simply leaving it there strands an unmovable square in the middle
        of the screen (issue #267). The owner is told, and puts it back in a
        normal window; this one is finished either way.
        """
        if self._closing or self._standalone_fallback:
            return
        logger.warning(
            "game window: embedding unavailable (%s); handing the game back",
            reason,
        )
        self._standalone_fallback = True
        self._hide_starting_indicator()
        self._close_and_destroy()
        # After the teardown on purpose: _notify_closed has already cleared
        # the owner's handle, so it is free to open a new wrapper or relaunch.
        if self._on_embed_failed is not None:
            callback, self._on_embed_failed = self._on_embed_failed, None
            callback(reason)

    def _surface_xid(self):
        surface = self.get_surface()
        if surface is None or not hasattr(surface, "get_xid"):
            logger.warning(
                "game window: surface is not X11; cannot embed (backend=%s)",
                type(surface).__name__ if surface else None,
            )
            return None
        return surface.get_xid()

    def _surface_rect(self):
        """The game rect in X pixels, relative to our toplevel X window."""
        surface = self.get_surface()
        if surface is None:
            return None
        rx, ry, rw, rh = self._screen.screen_rect()
        if rw <= 0 or rh <= 0:
            return None
        ok, point = self._screen.compute_point(
            self, Graphene.Point().init(rx, ry)
        )
        if not ok:
            return None
        # Widget coordinates live inside the surface at the CSD offset
        # (shadows/borders), and X wants device pixels.
        tx, ty = self.get_surface_transform()
        scale = surface.get_scale_factor()
        return (
            round((point.x + tx) * scale),
            round((point.y + ty) * scale),
            round(rw * scale),
            round(rh * scale),
        )

    def _sync_geometry(self):
        rect = self._surface_rect()
        if rect is None or rect == self._last_rect:
            return
        if self._embedder.move_resize(self._child_xid, *rect):
            self._last_rect = rect

    # -- shutdown -----------------------------------------------------------
    # ``Gtk.Window.close()`` only hides the window (destruction is deferred
    # to application teardown), so every programmatic close goes through
    # ``_close_and_destroy``; the user's X button goes through close-request.
    # ``_do_cleanup`` is idempotent so the two paths can overlap safely.
    def _do_cleanup(self, block=False):
        if self._closing:
            return
        self._closing = True
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        if self._volume_watch_id is not None:
            GLib.source_remove(self._volume_watch_id)
            self._volume_watch_id = None
        if self._child_xid is not None:
            # Detached before our X window dies with the GTK window: X
            # destroys children with their parent, and RetroArch aborts on
            # losing its window instead of exiting cleanly. Unconditional,
            # and above the fallback branch on purpose: a fallback can now
            # happen while a window *is* adopted, and skipping the detach
            # there would destroy the very game this is trying to save.
            self._embedder.release(self._child_xid)
            self._child_xid = None
        if self._standalone_fallback:
            # The embed failed and the owner is putting the game back in a
            # normal window; stopping it here would race that -- two stop
            # escalations against one process, each with its own QUIT and
            # SIGTERM. Detaching above is all this window still owes.
            self._embedder.close()
            self._notify_closed()
            return
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # One escalating stop, owned by the runtime manager: QUIT, then
            # SIGTERM, then SIGKILL, each only if the game is still there.
            # Closing this window is the user saying "stop playing", and it
            # has to hold even when the emulator does not cooperate.
            self._runtime.stop_active(block=block)
        self._embedder.close()
        self._notify_closed()

    def _notify_closed(self):
        if self._on_closed is not None:
            callback, self._on_closed = self._on_closed, None
            callback(self)

    def _close_and_destroy(self, block=False):
        self._do_cleanup(block=block)
        self.destroy()

    def close_now(self, block=False):
        """Close the wrapper and quit the game inside it, right now.

        For an owner that is going away itself -- the library window closing
        takes the game with it -- where ``close()`` would only hide this
        window and leave the teardown to an app exit that is already under
        way. ``block=True`` waits for the game to actually be gone.
        """
        self._close_and_destroy(block=block)

    def _on_close_request(self, _window):
        self._do_cleanup()
        return False

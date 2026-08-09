"""The embedded-RetroArch game window (POC, env-flagged).

An ``Adw.Window`` that adopts the running RetroArch X11 window as its own
content: libadwaita headerbar and borders outside, the game inside. With
the frame flag on, the CRT TV artwork (``assets/images/tv-frame.png``) is
drawn and the game sits inside the TV's screen cutout; without it the game
fills the content area and the headerbar carries the action buttons.

The headerbar buttons talk to RetroArch over the UDP network-command
channel the launcher already enables (``RuntimeManager.send_command``).

POC notes:
- Strings are English literals, not i18n keys.
- X keyboard focus is handed to the embedded window so RetroArch receives
  the keyboard; GTK then paints the headerbar as unfocused while playing.
"""

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from openemux.core import screen_geometry
from openemux.core.retroarch_command import MAX_VOLUME_DB, MIN_VOLUME_DB
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

#: Grace period between the QUIT command and a hard terminate on close.
QUIT_GRACE_MS = 1500


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
                 on_closed=None, on_open_input_settings=None):
        super().__init__(application=application)
        self._runtime = runtime_manager
        self._proc = runtime_manager.active_process
        # Called exactly once, from whichever close path runs first. The
        # owner must not learn about the close from GTK signals: this GTK
        # defers the "destroy" emission past gtk_window_destroy(), so a
        # signal-based owner kept a stale reference for the app's lifetime.
        self._on_closed = on_closed
        self._on_open_input_settings = on_open_input_settings
        self._embedder = RetroArchWindowEmbedder()
        self._child_xid = None
        self._parent_xid = None
        # Set when embedding turns out to be impossible: the wrapper closes
        # itself and must leave the standalone RetroArch window running.
        self._standalone_fallback = False
        self._closing = False
        self._paused = False
        self._tick_id = None
        self._ticks_waited = 0
        self._last_rect = None

        name = rom.get("name") or Path(rom.get("path", "Game")).stem
        self.set_title(name)

        texture = self._load_frame_texture() if frame_enabled else None
        self._screen = _GameScreen(texture)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title=name, subtitle=rom.get("console", ""))
        )
        self._pause_button = self._action_button(
            "media-playback-pause-symbolic", "Pause", self._on_pause_clicked
        )
        header.pack_start(self._pause_button)
        header.pack_start(
            self._action_button(
                "view-refresh-symbolic", "Reset game", self._on_reset_clicked
            )
        )
        header.pack_start(
            self._action_button(
                "media-floppy-symbolic", "Save state", self._on_save_state_clicked
            )
        )
        header.pack_start(
            self._action_button(
                "folder-download-symbolic", "Load state", self._on_load_state_clicked
            )
        )
        # Right side, rightmost first: RetroArch menu, volume (mute lives
        # inside its popover, like the library's control), controller settings.
        header.pack_end(
            self._action_button(
                "open-menu-symbolic", "RetroArch menu", self._on_menu_clicked
            )
        )
        header.pack_end(self._build_volume_button())
        header.pack_end(
            self._action_button(
                "input-gaming-symbolic",
                "Controller settings",
                self._on_input_settings_clicked,
            )
        )

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._screen)
        self.set_content(toolbar)
        self.set_default_size(920, 930 if texture is not None else 740)

        self.connect("map", self._on_map)
        self.connect("close-request", self._on_close_request)

        self._embedder.snapshot_existing()

    def _build_volume_button(self):
        """A headerbar volume control mirroring the library's (issue #69):
        a MenuButton whose popover holds the mute toggle and the dB slider,
        walked over UDP by the runtime manager's pacer."""
        self._volume_btn = Gtk.MenuButton()
        self._volume_btn.set_icon_name("audio-volume-high-symbolic")
        self._volume_btn.set_tooltip_text("Volume")

        self._volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, MIN_VOLUME_DB, MAX_VOLUME_DB, 0.5
        )
        self._volume_scale.set_size_request(200, -1)
        self._volume_scale.set_draw_value(True)
        self._volume_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self._volume_scale.set_format_value_func(lambda _s, v: f"{v:+.1f} dB")
        self._volume_seed_guard = False
        self._volume_scale.set_value(self._runtime.volume_db)
        self._volume_scale.connect("value-changed", self._on_volume_changed)

        self._mute_button = Gtk.ToggleButton()
        self._mute_button.set_icon_name("audio-volume-muted-symbolic")
        self._mute_button.set_tooltip_text("Mute")
        self._mute_button.add_css_class("flat")
        self._mute_guard = False
        self._mute_button.connect("toggled", self._on_mute_toggled)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.append(self._mute_button)
        box.append(self._volume_scale)

        popover = Gtk.Popover()
        popover.set_child(box)
        popover.connect("show", self._on_volume_popover_shown)
        self._volume_btn.set_popover(popover)
        return self._volume_btn

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
            level = self._runtime.set_master_volume_db(scale.get_value())
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

    def _on_volume_popover_shown(self, _popover):
        # Re-seed on open: the level and mute may have moved through the
        # library's own control or a RetroArch hotkey since the last look.
        self._volume_seed_guard = True
        self._volume_scale.set_value(self._runtime.volume_db)
        self._volume_seed_guard = False
        self._mute_guard = True
        self._mute_button.set_active(self._runtime.muted)
        self._mute_guard = False

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
        if self._proc is None or self._proc.poll() is not None:
            # The game ended on its own (RetroArch menu quit, crash): the
            # wrapper window has nothing left to show.
            self._tick_id = None
            self._close_and_destroy()
            return False
        if self._child_xid is None:
            self._try_embed()
        else:
            self._sync_geometry()
            # Reclaimed every tick: the WM hands focus back to our toplevel
            # on every click/activation, and without it RetroArch drops
            # keyboard, hotkeys and (through its focus check) gamepad input.
            self._embedder.ensure_focus(self._child_xid, self._parent_xid)
        return True

    def _try_embed(self):
        if not self._embedder.available:
            self._fall_back_to_standalone("python-xlib is unavailable")
            return
        self._ticks_waited += 1
        if self._ticks_waited > FIND_WINDOW_TIMEOUT_TICKS:
            self._fall_back_to_standalone("RetroArch window not found in time")
            return
        parent_xid = self._surface_xid()
        if parent_xid is None:
            self._fall_back_to_standalone("window surface is not X11")
            return
        child_xid = self._embedder.find_game_window(getattr(self._proc, "pid", None))
        if child_xid is None:
            return
        rect = self._surface_rect()
        if rect is None:
            # Not laid out yet; the window is still settling. Next tick.
            return
        if not self._embedder.embed(child_xid, parent_xid, *rect):
            self._fall_back_to_standalone("reparenting failed")
            return
        self._child_xid = child_xid
        self._parent_xid = parent_xid
        self._last_rect = rect
        self._embedder.focus(child_xid)
        logger.info("game window: embedded RetroArch window 0x%x", child_xid)

    def _fall_back_to_standalone(self, reason):
        """Close the wrapper and leave RetroArch running in its own window.

        The degraded mode the user asked for: an embed failure (native
        Wayland, missing tooling, a lost race) must cost the chrome, never
        the game.
        """
        logger.warning(
            "game window: embedding unavailable (%s); RetroArch stays standalone",
            reason,
        )
        self._standalone_fallback = True
        self._close_and_destroy()

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
    def _do_cleanup(self):
        if self._closing:
            return
        self._closing = True
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        if self._standalone_fallback:
            # The game was never embedded and must keep running in its own
            # window; closing the wrapper must not quit it.
            self._embedder.close()
            self._notify_closed()
            return
        if self._child_xid is not None:
            # Detached before our X window dies with the GTK window: X
            # destroys children with their parent, and RetroArch aborts on
            # losing its window instead of exiting cleanly.
            self._embedder.release(self._child_xid)
            self._child_xid = None
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._runtime.send_command("QUIT")

            def _terminate_if_alive():
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                return False

            GLib.timeout_add(QUIT_GRACE_MS, _terminate_if_alive)
        self._embedder.close()
        self._notify_closed()

    def _notify_closed(self):
        if self._on_closed is not None:
            callback, self._on_closed = self._on_closed, None
            callback(self)

    def _close_and_destroy(self):
        self._do_cleanup()
        self.destroy()

    def _on_close_request(self, _window):
        self._do_cleanup()
        return False

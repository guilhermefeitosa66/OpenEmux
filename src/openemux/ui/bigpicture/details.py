"""A game's details in Big Picture: a page of their own (issues 914, 957, 975).

The desktop keeps everything about one game in ``ui/game_details.py``, an
``Adw.Dialog``. Big Picture gives it the whole screen instead: A on a game
opens ``GameDetailsPage``, the art large on the left and, on the right, the
title, Play, the save states and the per-game settings (``GameDetail``). A
on a row changes the setting or opens a chooser for it; every action calls
the same window method the desktop dialog does, so the two never disagree
about what a change means.

``load(rom)`` rebuilds a detail for another game, which is also what the
shoulders do on the page.
"""

import logging
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Pango

from openemux.core import cartridge_colors, cartridge_render, cover_cache, save_states
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.paths import display_text
from openemux.core.scraper import COVER_ART, LABEL_ART, resolve_local_art
from openemux.ui.bigpicture.widgets import (
    ROW_ACTION,
    ROW_CHOICE,
    BigPage,
    Row,
    icon_button,
    make_badge,
    note,
    once,
)

logger = logging.getLogger(__name__)

#: The cover, at scale 1.0, in px: the pixbuf is decoded to fit twice this,
#: so it stays sharp on any screen; the ``bp-details-cover`` rule sizes it
#: (``cover_w`` and ``cover_h`` in the theme).
COVER_SIZE = (480, 600)
#: A save state's screenshot on its tile, at scale 1.0.
STATE_THUMBNAIL = 72
#: The chooser id that stands for "the console default".
CONSOLE_DEFAULT = ""
#: The chooser id of the "New playlist" option.
NEW_PLAYLIST = "__new__"
#: The ids of the artwork chooser's options.
ART_FETCH = "fetch"
ART_CHOOSE = "choose"
ART_REMOVE = "remove"


def stamp(mtime):
    """A save state's date and time, the way the desktop writes it."""
    return datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")


class CoverFrame(Gtk.Overlay):
    """The cover at the size the theme says, whatever the picture's own size.

    A ``Gtk.Picture`` asks for its paintable's natural size, and the cover
    is decoded at twice the display size to stay sharp; measured on its own
    it would push the whole column out. The spacer underneath is what gets
    measured (its size comes from the ``bp-details-cover`` rule), and the
    picture is drawn over it, fitted inside. A placeholder icon stands in
    while there is nothing on disk.
    """

    def __init__(self):
        super().__init__()
        spacer = Gtk.Box()
        spacer.add_css_class("bp-details-cover")
        self.set_child(spacer)
        self.placeholder = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
        self.placeholder.set_pixel_size(96)
        self.placeholder.add_css_class("dim-label")
        self.placeholder.set_halign(Gtk.Align.CENTER)
        self.placeholder.set_valign(Gtk.Align.CENTER)
        self.add_overlay(self.placeholder)
        self.set_measure_overlay(self.placeholder, False)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_can_shrink(True)
        self.picture.add_css_class("rom-cover")
        self.picture.set_visible(False)
        self.add_overlay(self.picture)
        self.set_measure_overlay(self.picture, False)
        self.set_clip_overlay(self.picture, True)

    def show_paintable(self, paintable):
        self.picture.set_paintable(paintable)
        self.picture.set_visible(paintable is not None)
        self.placeholder.set_visible(paintable is None)


class StateTile(Gtk.Button):
    """A save state in the pane: its screenshot or an icon, a name, a date.

    A on it launches the game into that state. The automatic one plays the
    game the ordinary way, which resumes it: that is what Play does too.
    """

    def __init__(self, title, caption, thumbnail=None, size=STATE_THUMBNAIL,
                 icon_name="media-floppy-symbolic", on_activate=None):
        super().__init__()
        self.slot = None
        self.on_activate = on_activate
        self.add_css_class("bp-state")
        self.add_css_class("flat")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        # Decoded to the badge's size and shown as an image with that pixel
        # size: a picture measured for the tile's width would ask for the
        # screenshot's height at that width and make this tile taller than
        # its neighbours. A screenshot that will not decode is an icon, not
        # an error.
        pixbuf = cover_cache.load_cover(str(thumbnail), size, size) if thumbnail else None
        if pixbuf is not None:
            from openemux.ui.rom_card import texture_for

            self.badge = Gtk.Image.new_from_paintable(texture_for(pixbuf))
            self.badge.set_pixel_size(size)
            self.badge.add_css_class("bp-badge")
        else:
            self.badge = make_badge(icon_name=icon_name)
        self.badge.set_halign(Gtk.Align.CENTER)
        self.badge.set_valign(Gtk.Align.CENTER)
        box.append(self.badge)
        self.name_label = Gtk.Label(label=title)
        self.name_label.add_css_class("bp-tile-name")
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.set_max_width_chars(14)
        box.append(self.name_label)
        self.caption = Gtk.Label(label=caption or "")
        self.caption.add_css_class("bp-tile-count")
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        self.caption.set_max_width_chars(18)
        self.caption.set_visible(bool(caption))
        box.append(self.caption)
        self.set_child(box)
        self.connect("clicked", lambda _b: self.on_activate() if self.on_activate else None)


class GameDetail(Gtk.Box):
    """One game, on its own page (issues 957, 975).

    On top, "‹ Back to the list" with the favorite and share buttons across
    from it. Below, two columns: the art with "Search artwork…" under it; and
    the title with its pencil, "Console · Core · played", Play (or Continue,
    when the game left an automatic state), the save states, the per-game
    settings rows and the file's path.
    """

    def __init__(self, shell):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.shell = shell
        self.win = shell.win
        t = self.t = shell.win.t
        self.rom = None
        self._states = []
        self._cover_job = 0
        self.state_tiles = []
        self.add_css_class("bp-detail")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.back_button = Gtk.Button(label=t("big_picture.details.back"))
        self.back_button.add_css_class("bp-back-link")
        self.back_button.set_valign(Gtk.Align.CENTER)
        self.back_button.connect("clicked", lambda _b: self.shell.pop())
        top.append(self.back_button)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        self.favorite_button = icon_button("non-starred-symbolic", t("hints.favorite"), self._toggle_favorite)
        self.share_button = icon_button("send-to-symbolic", t("share.menu.single"), self._on_share)
        for button in (self.favorite_button, self.share_button):
            top.append(button)
        self.append(top)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=48)
        columns.add_css_class("bp-details-columns")
        self.append(columns)
        art = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        art.add_css_class("bp-details-side")
        columns.append(art)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        info.set_hexpand(True)
        columns.append(info)

        self.cover = CoverFrame()
        self.cover.set_halign(Gtk.Align.CENTER)
        art.append(self.cover)
        self.artwork_button = Gtk.Button()
        self.artwork_button.add_css_class("bp-pill-button")
        self.artwork_button.set_halign(Gtk.Align.CENTER)
        art_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        art_box.append(Gtk.Image.new_from_icon_name("system-search-symbolic"))
        art_box.append(Gtk.Label(label=t("big_picture.pane.search_artwork")))
        self.artwork_button.set_child(art_box)
        self.artwork_button.connect("clicked", lambda _b: self._open_artwork_chooser())
        art.append(self.artwork_button)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_row.set_halign(Gtk.Align.START)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-pane-title")
        self.title_label.set_wrap(True)
        self.title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.title_label.set_lines(2)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_row.append(self.title_label)
        self.rename_button = icon_button("document-edit-symbolic", t("context.rename"), self._on_rename)
        self.rename_button.set_valign(Gtk.Align.CENTER)
        title_row.append(self.rename_button)
        info.append(title_row)
        self.meta_label = Gtk.Label(xalign=0.0)
        self.meta_label.add_css_class("bp-pane-meta")
        self.meta_label.set_ellipsize(Pango.EllipsizeMode.END)
        info.append(self.meta_label)

        self.play_button = Gtk.Button()
        self.play_button.add_css_class("bp-play")
        play_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        play_box.set_halign(Gtk.Align.CENTER)
        play_box.append(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
        self.play_label = Gtk.Label(label=t("details.play"))
        play_box.append(self.play_label)
        self.play_button.set_child(play_box)
        self.play_button.connect("clicked", lambda _b: self._on_play())
        self.play_button.set_margin_top(8)
        self.play_button.set_halign(Gtk.Align.START)
        info.append(self.play_button)
        self.fresh_row = Row(
            t("context.start_fresh"), t("big_picture.details.start_fresh.subtitle"),
            kind=ROW_ACTION, on_activate=self._on_start_fresh,
        )
        info.append(self.fresh_row)

        states_title = Gtk.Label(label=t("big_picture.pane.states"), xalign=0.0)
        states_title.add_css_class("bp-section-title")
        states_title.set_margin_top(14)
        info.append(states_title)
        self.states_empty = Gtk.Label(label=t("big_picture.pane.states.empty"), xalign=0.0)
        self.states_empty.add_css_class("bp-pane-meta")
        self.states_empty.set_wrap(True)
        info.append(self.states_empty)
        states_scroller = Gtk.ScrolledWindow()
        states_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        states_scroller.set_propagate_natural_height(True)
        self.states_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        states_scroller.set_child(self.states_box)
        self.states_scroller = states_scroller
        info.append(states_scroller)

        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        rows.set_margin_top(12)
        self.core_row = Row(t("context.core"), kind=ROW_CHOICE, on_activate=self._open_core_chooser)
        self.shader_row = Row(t("context.shader"), kind=ROW_CHOICE, on_activate=self._open_shader_chooser)
        self.color_row = Row(
            t("context.cartridge_color"), kind=ROW_CHOICE, on_activate=self._open_color_chooser
        )
        self.playlists_row = Row(
            t("details.group.collections"), kind=ROW_ACTION, on_activate=self._open_playlists_chooser
        )
        for row in (self.core_row, self.shader_row, self.color_row, self.playlists_row):
            rows.append(row)
        info.append(rows)
        self.path_note = note("")
        self.path_note.set_margin_top(8)
        info.append(self.path_note)

    # -- loading a game -----------------------------------------------------------
    def load(self, rom):
        """Show ``rom``: every row re-read, the cover fetched in the background."""
        self.rom = rom
        self.title_label.set_label(rom.get("name", ""))
        self.path_note.set_label(str(rom.get("path", "")))
        self._read_states()
        self._sync_meta()
        self._sync_play_rows()
        self._sync_settings()
        self._sync_playlists()
        self._build_states()
        self._load_cover()

    def refresh(self):
        """Re-read the game shown, its art kept: a game just ended (issue 957).

        Playing it leaves new save states, an automatic one (Play becomes
        Continue) and a "played" line; the page must not keep the old ones.
        A state tile that held the focus is rebuilt, so the focus goes to Play.
        """
        if self.rom is None:
            return False
        focus = self.win.get_focus()
        in_states = focus is not None and focus.is_ancestor(self.states_box)
        self._read_states()
        self._sync_meta()
        self._sync_play_rows()
        self._build_states()
        if in_states:
            self.play_button.grab_focus()
        return True

    def _read_states(self):
        rom = self.rom
        states_dir = self.win.config_manager.get_console_states_dir(rom["console"])
        self._states = save_states.list_states(states_dir, rom["path"])

    def _sync_meta(self):
        """``Nintendo (NES) · Nestopia · never played``, Android's line."""
        win, rom, t = self.win, self.rom, self.t
        parts = [
            win.sidebar.label_for(rom.get("console", "")),
            self._effective_core_label(),
            win.play_caption(rom) or t("details.never_played"),
        ]
        self.meta_label.set_label(" · ".join(part for part in parts if part))
        favorite = win._is_favorite_rom(rom)
        self.favorite_button.set_icon_name("starred-symbolic" if favorite else "non-starred-symbolic")
        if favorite:
            self.favorite_button.add_css_class("bp-on")
        else:
            self.favorite_button.remove_css_class("bp-on")

    def is_favorite(self):
        return self.favorite_button.has_css_class("bp-on")

    def _effective_core_label(self):
        core = self.win.config_manager.get_rom_core_override(self.rom["path"])
        if core:
            return self.win.core_catalog.display_name_for(core)
        return self._auto_core_label()

    def _sync_play_rows(self):
        t = self.t
        resuming = self.win.has_auto_state(self.rom)
        self.play_label.set_label(t("big_picture.details.continue") if resuming else t("details.play"))
        self.fresh_row.set_visible(resuming)

    def _sync_settings(self):
        """The three per-game settings, each saying where its value comes from."""
        rom, config = self.rom, self.win.config_manager
        console, path = rom["console"], rom["path"]
        catalog = self.win.core_catalog
        core = config.get_rom_core_override(path)
        self._show_choice(
            self.core_row,
            catalog.display_name_for(core) if core else None,
            self._auto_core_label(),
        )
        shaders = self.win.shader_catalog
        shader = config.get_rom_shader_override(path)
        self._show_choice(
            self.shader_row,
            shaders.label_for_shader(shader) if shader else None,
            shaders.label_for_shader(config.get_shader_for_console(console)),
        )
        has_shells = len(cartridge_render.frame_colors_for(console)) >= 2
        self.color_row.set_visible(has_shells)
        if has_shells:
            color = config.get_rom_cartridge_color_override(path)
            self._show_choice(
                self.color_row,
                self._color_label(color) if color else None,
                self._color_label(config.get_cartridge_color_for_console(console)),
            )

    def _show_choice(self, row, own_label, console_label):
        """A choice row's value, with Android's DEFAULT tag when the console's applies."""
        if own_label is not None:
            row.set_value(own_label)
            row.set_tag(None)
        else:
            row.set_value(console_label)
            row.set_tag(self.t("big_picture.pane.default"))

    def _auto_core_label(self):
        """What the console level would run: its override, else the first core."""
        console = self.rom["console"]
        catalog = self.win.core_catalog
        console_core = self.win.config_manager.get_console_core_override(console)
        if console_core:
            return catalog.display_name_for(console_core)
        cores = catalog.cores_for_console(console)
        if cores:
            return cores[0].display_name
        return self.t("context.core.none")

    def _color_label(self, color_id):
        key = cartridge_colors.color_name_key(color_id)
        return self.t(key) if key else str(color_id).replace("-", " ").title()

    def _sync_playlists(self):
        manager = self.win.collection_manager
        names = [
            collection["name"]
            for collection in manager.list_collections()
            if manager.contains(collection["slug"], self.rom["path"])
        ]
        self.playlists_row.set_value(", ".join(names))

    # -- the cover --------------------------------------------------------------------
    def _load_cover(self):
        rom = self.rom
        self._cover_job += 1
        job = self._cover_job
        roms_dir = self.win.roms_path
        scale = self.shell.scale()
        width, height = (int(side * 2 * scale) for side in COVER_SIZE)
        # The previous game's cover must not stand in for this one's.
        self.cover.show_paintable(None)

        def _worker():
            path = resolve_local_art(rom, roms_dir, kinds=(COVER_ART, LABEL_ART))
            pixbuf = cover_cache.load_cover(str(path), width, height) if path else None
            GLib.idle_add(self._apply_cover, job, pixbuf)

        cover_cache.submit(_worker)

    def _apply_cover(self, job, pixbuf):
        # A later load (the shoulders moved on) owns the frame now.
        if job == self._cover_job:
            if pixbuf is None:
                self.cover.show_paintable(None)
            else:
                from openemux.ui.rom_card import texture_for

                self.cover.show_paintable(texture_for(pixbuf))
        return GLib.SOURCE_REMOVE

    # -- the save states ----------------------------------------------------------------
    def _build_states(self):
        """The save states in a row: the automatic one first, then the slots.

        A on a state starts the game from it. With none, Android's note.
        """
        t = self.t
        child = self.states_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.states_box.remove(child)
            child = following
        self.state_tiles = []
        size = int(STATE_THUMBNAIL * self.shell.scale())
        if self.win.has_auto_state(self.rom):
            tile = StateTile(
                t("big_picture.details.continue"), t("big_picture.details.states.auto_short"),
                icon_name="media-playback-start-symbolic", on_activate=self._on_play,
            )
            self.states_box.append(tile)
            self.state_tiles.append(tile)
        for state in self._states:
            tile = StateTile(
                t("details.states.slot", slot=state.slot), stamp(state.mtime),
                thumbnail=state.thumbnail, size=size,
                on_activate=lambda slot=state.slot: self.win.launch_rom_at_state(self.rom, slot),
            )
            tile.slot = state.slot
            self.states_box.append(tile)
            self.state_tiles.append(tile)
        self.states_scroller.set_visible(bool(self.state_tiles))
        self.states_empty.set_visible(not self.state_tiles)

    # -- playing ---------------------------------------------------------------------------
    def _on_play(self):
        self.win.on_launch_game(self.rom)

    def _on_start_fresh(self):
        self.win.game.launch(self.rom, resume=False)

    # -- favourite ------------------------------------------------------------------------
    def _toggle_favorite(self):
        self.win._toggle_favorite_from_ui(self.rom)
        # The window is the one that knows; the star follows it, never leads.
        self._sync_meta()

    def on_pad_action(self, action):
        """X toggles the favorite, Y shares: Android's detail."""
        if action == "context":
            self._toggle_favorite()
            return True
        if action == "favorite":
            self._on_share()
            return True
        return False

    # -- the three settings ------------------------------------------------------------------
    def _crumbs(self, title):
        return [self.rom.get("name", ""), title]

    def open_options(self):
        """The Y sheet's entries, Android's options plus the desktop's per-game ones."""
        t = self.t
        options = [
            {"id": "share", "label": t("big_picture.options.share")},
            {"id": "rename", "label": t("context.rename")},
            {"id": "artwork", "label": t("details.group.artwork")},
            {"id": "core", "label": t("context.core")},
            {"id": "playlists", "label": t("details.group.collections")},
            {"id": "remove", "label": t("big_picture.options.remove")},
        ]
        self.shell.open_chooser(
            self.rom.get("name", ""), options, None, self._pick_option,
            crumbs=[self.win.sidebar.label_for(self.rom.get("console", "")), self.rom.get("name", "")],
            lead=t("big_picture.options.lead"),
        )

    def _pick_option(self, option):
        handlers = {
            "share": self._on_share,
            "rename": self._on_rename,
            "artwork": self._open_artwork_chooser,
            "core": self._open_core_chooser,
            "playlists": self._open_playlists_chooser,
            "remove": self._on_delete,
        }
        # The chooser pops itself first; the next page (or dialog) opens over
        # what was there, not under the closing chooser.
        GLib.idle_add(once(handlers[option]))

    def _open_core_chooser(self):
        t = self.t
        cores = self.win.core_catalog.cores_for_console(self.rom["console"])
        options = [{"id": CONSOLE_DEFAULT, "label": t("details.console_default", value=self._auto_core_label())}]
        options += [{"id": core.filename, "label": core.display_name} for core in cores]
        current = self.win.config_manager.get_rom_core_override(self.rom["path"]) or CONSOLE_DEFAULT
        self.shell.open_chooser(
            t("context.core"), options, current, self._pick_core, crumbs=self._crumbs(t("context.core"))
        )

    def _pick_core(self, core_id):
        chosen = core_id or None
        # The chooser hands back the current option too; a write on it would
        # toast "core set" for a change that did not happen.
        if chosen != self.win.config_manager.get_rom_core_override(self.rom["path"]):
            self.win.set_rom_core(self.rom, chosen)
        self._sync_settings()

    def _open_shader_chooser(self):
        t = self.t
        config = self.win.config_manager
        shaders = self.win.shader_catalog
        show_all = bool(config.get_shader_settings().get("show_all_shaders", False))
        console_label = shaders.label_for_shader(config.get_shader_for_console(self.rom["console"]))
        options = [{"id": CONSOLE_DEFAULT, "label": t("details.console_default", value=console_label)}]
        options += [{"id": shader_id, "label": label} for shader_id, label in shaders.get_options(show_all=show_all)]
        current = config.get_rom_shader_override(self.rom["path"]) or CONSOLE_DEFAULT
        self.shell.open_chooser(
            t("context.shader"), options, current, self._pick_shader,
            crumbs=self._crumbs(t("context.shader")),
        )

    def _pick_shader(self, shader_id):
        chosen = shader_id or None
        if chosen != self.win.config_manager.get_rom_shader_override(self.rom["path"]):
            self.win.set_rom_shader(self.rom, chosen)
        self._sync_settings()

    def _open_color_chooser(self):
        t = self.t
        config = self.win.config_manager
        console = self.rom["console"]
        ordered = [
            color_id
            for color_id in cartridge_colors.order_color_ids(cartridge_render.frame_colors_for(console))
            if color_id != cartridge_colors.DEFAULT_COLOR_ID
        ]
        console_label = self._color_label(config.get_cartridge_color_for_console(console))
        options = [{"id": CONSOLE_DEFAULT, "label": t("details.console_default", value=console_label)}]
        options += [{"id": color_id, "label": self._color_label(color_id)} for color_id in ordered]
        current = config.get_rom_cartridge_color_override(self.rom["path"]) or CONSOLE_DEFAULT
        self.shell.open_chooser(
            t("context.cartridge_color"), options, current, self._pick_color,
            crumbs=self._crumbs(t("context.cartridge_color")),
        )

    def _pick_color(self, color_id):
        chosen = color_id or None
        if chosen != self.win.config_manager.get_rom_cartridge_color_override(self.rom["path"]):
            self.win.set_rom_cartridge_color(self.rom, chosen)
        self._sync_settings()

    # -- playlists ---------------------------------------------------------------------------
    def _open_playlists_chooser(self):
        """Every playlist, saying whether the game is in it; A flips that."""
        t = self.t
        manager = self.win.collection_manager
        options = []
        for collection in manager.list_collections():
            in_it = manager.contains(collection["slug"], self.rom["path"])
            options.append({
                "id": collection["slug"],
                "label": collection["name"],
                "subtitle": t("big_picture.details.playlist.in" if in_it else "big_picture.details.playlist.out"),
            })
        options.append({"id": NEW_PLAYLIST, "label": t("collections.new")})
        self.shell.open_chooser(
            t("details.group.collections"), options, None, self._pick_playlist,
            crumbs=self._crumbs(t("details.group.collections")),
            lead=t("big_picture.details.playlists.lead"),
        )

    def _pick_playlist(self, slug):
        if slug == NEW_PLAYLIST:
            # The window's own prompt; the game is added once the name is in,
            # and the row here learns about it then, not before.
            self.win._prompt_new_collection(on_created=self._on_playlist_created)
            return
        self.win.toggle_rom_in_collection(self.rom, slug)
        self._sync_playlists()
        # The chooser pops itself after a pick; back in with the marks redrawn,
        # so several playlists can be ticked in a row.
        GLib.idle_add(once(self._open_playlists_chooser))

    def _on_playlist_created(self, slug):
        self.win.collection_manager.add(slug, [self.rom["path"]])
        self.win._after_collection_changed(slug)
        self._sync_playlists()

    # -- artwork -------------------------------------------------------------------------------
    def _open_artwork_chooser(self):
        t = self.t
        options = [
            {
                "id": ART_FETCH,
                "label": t("details.artwork.fetch"),
                "subtitle": t("big_picture.details.artwork.fetch.subtitle"),
            },
            {
                "id": ART_CHOOSE,
                "label": t("context.cover.choose"),
                "subtitle": t("big_picture.details.artwork.choose.subtitle"),
            },
        ]
        if self.win._has_local_cover(self.rom, COVER_ART):
            options.append({"id": ART_REMOVE, "label": t("context.cover.remove")})
        self.shell.open_chooser(
            t("details.group.artwork"), options, None, self._pick_artwork,
            crumbs=self._crumbs(t("details.group.artwork")),
        )

    def _pick_artwork(self, action):
        rom = self.rom
        if action == ART_FETCH:
            self._fetch_artwork()
        elif action == ART_CHOOSE:
            self.win._choose_cover_for_rom(rom, lambda: self._on_artwork_changed(rom), COVER_ART)
        elif action == ART_REMOVE:
            # The desktop removes on the click; a pad has no undo for a slip.
            self.shell.confirm(
                self.t("context.cover.remove"),
                self.t("big_picture.details.artwork.remove.body", name=rom.get("name", "")),
                self.t("context.cover.remove"),
                lambda: self.win._remove_cover_for_rom(rom, lambda: self._on_artwork_changed(rom), COVER_ART),
            )

    def _fetch_artwork(self):
        """Box art, and the cartridge label where there is a frame, in one task.

        The desktop asks the window twice, once per kind, and the second ask
        meets the first one already running. One sync with both passes is
        what a single-game fetch means.
        """
        rom, win = self.rom, self.win
        if win._cover_sync_running:
            win._toast(self.t("toast.sync_running"), timeout=3)
            return False
        kinds = [COVER_ART_TYPE_BOXART]
        if cartridge_render.has_frame(rom["console"]):
            kinds.append(COVER_ART_TYPE_CARTRIDGE_LABEL)
        passes = [(kind, {rom["console"]: [rom]}) for kind in kinds]
        win._start_artwork_sync(
            passes, replace_existing=True, on_finished=lambda: self._on_artwork_changed(rom)
        )
        return True

    def _on_artwork_changed(self, rom):
        """A cover came or went: the cards everywhere, and this page if it is still that game."""
        self.win.refresh_rom_artwork(rom)
        if self.rom is not None and self.rom.get("path") == rom.get("path"):
            self._load_cover()

    # -- the file -------------------------------------------------------------------------------
    def _on_rename(self):
        t = self.t
        self.shell.open_text_entry(
            t("dialog.rename.heading"), display_text(self.rom.get("name", "")), self._apply_rename,
            subtitle=t("dialog.rename.body"), max_length=120,
            crumbs=self._crumbs(t("context.rename")),
        )

    def _apply_rename(self, new_name):
        """Rename through the window, then follow the game to its new path.

        The window reports nothing back; the playlist does. The one entry
        that was not there before the rename is the renamed game; none means
        the rename did not happen (a refused name has had its toast) or the
        game is gone, and then the page has nothing left to show.
        """
        rom, win = self.rom, self.win
        console = rom["console"]
        before = {entry["path"] for entry in win.playlist_manager.load_playlist(console)}
        win._apply_rename(rom, new_name)
        after = win.playlist_manager.load_playlist(console)
        fresh = [entry for entry in after if entry["path"] not in before]
        if fresh:
            self.load(fresh[0])
        elif not any(entry["path"] == rom["path"] for entry in after):
            self.shell.forget_games({rom["path"]})

    def _on_share(self):
        self.win.share_roms([self.rom])

    def _on_delete(self):
        # The window asks first; the grid and this page's game go together.
        self.win._confirm_delete_roms([self.rom])

    # -- the pad -----------------------------------------------------------------------------------
    def step_game(self, delta):
        """The game before or after this one on the page the grid shows."""
        grid = self.win._visible_grid()
        if grid is None or self.rom is None:
            return False
        entries = grid.visible_entries()
        paths = [entry.rom.get("path") for entry in entries]
        current = self.rom.get("path")
        if current not in paths or len(paths) < 2:
            return False
        self.load(entries[(paths.index(current) + delta) % len(paths)].rom)
        return True

    def focus_default(self):
        return self.play_button.grab_focus()

    def hints(self, g, t):
        """Android's detail: A Play, X Favorite, Y Share, B Back."""
        play = t("big_picture.details.continue") if self.win.has_auto_state(self.rom) else t("details.play")
        return [
            (g["confirm"], play),
            (g["context"], t("hints.favorite")),
            (g["favorite"], t("big_picture.hints.share")),
            (g["back"], t("hints.back")),
        ]


class GameDetailsPage(BigPage):
    """A game's details on the whole screen: A on a game opens it, B closes it."""

    context = "bp-pane"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("details.title"), tag="bp-details")
        self.detail = GameDetail(shell)
        self.body.append(self.scrolled(self.detail))
        self._focus_play_on_show = False

    @property
    def rom(self):
        return self.detail.rom

    def load(self, rom):
        self.detail.load(rom)
        self.set_crumbs([self.win.sidebar.label_for(rom.get("console", "")), rom.get("name", "")])
        self._focus_play_on_show = True

    def on_pad_action(self, action):
        return self.detail.on_pad_action(action)

    def step_section(self, delta):
        """LB and RB: the game before or after this one."""
        moved = self.detail.step_game(delta)
        if moved:
            rom = self.detail.rom
            self.set_crumbs([self.win.sidebar.label_for(rom.get("console", "")), rom.get("name", "")])
        return moved

    def on_shown(self):
        if self._focus_play_on_show:
            self._focus_play_on_show = False
            GLib.idle_add(once(self.detail.play_button.grab_focus))
            return True
        return False

    def focus_default(self):
        return self.detail.focus_default()

    def hints(self, g, t):
        return self.detail.hints(g, t) + [(g["consoles"], t("big_picture.details.prev_next"))]


__all__ = [
    "GameDetail", "GameDetailsPage", "StateTile", "CoverFrame", "stamp",
    "CONSOLE_DEFAULT", "NEW_PLAYLIST", "ART_FETCH", "ART_CHOOSE", "ART_REMOVE",
]

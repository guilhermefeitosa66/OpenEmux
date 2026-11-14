"""A game's details in Big Picture: a page, not a dialog (issue 914).

The desktop keeps everything about one game in ``ui/game_details.py``, an
``Adw.Dialog``. A couch wants a page: the cover on the left with the save
states under it, the title and a column of rows on the right. A on a row
changes the setting or opens a chooser for it, "Continue" is the accent
row and takes the focus first, B goes back to the grid, LB and RB move to
the games beside this one. Every action calls the same window method the
desktop dialog does, so the two never disagree about what a change means.

One instance lives for the whole session: ``load(rom)`` rebuilds it for
another game, which is also what the shoulders do.
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
    ROW_SWITCH,
    BigPage,
    Row,
    eyebrow,
    make_badge,
    note,
    once,
)

logger = logging.getLogger(__name__)

#: The cover, at scale 1.0, in px: the pixbuf is decoded to fit twice this,
#: so it stays sharp on any screen; the ``bp-details-cover`` rule sizes it.
COVER_SIZE = (400, 500)
#: A save state's screenshot on its tile, at scale 1.0.
STATE_THUMBNAIL = 72
#: How many save-state tiles fit under the cover.
MAX_STATE_TILES = 3
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
    """A save state under the cover: its screenshot or an icon, a name, a date.

    A on it launches the game into that state. The automatic one plays the
    game the ordinary way, which resumes it: that is what Play does too.
    """

    def __init__(self, title, caption, thumbnail=None, size=STATE_THUMBNAIL,
                 icon_name="media-floppy-symbolic", on_activate=None):
        super().__init__()
        self.slot = None
        self.on_activate = on_activate
        self.add_css_class("bp-tile")
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


class GameDetailsPage(BigPage):
    context = "bp-page"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("details.title"), tag="bp-details")
        self.t = t
        self.rom = None
        self._states = []
        self._cover_job = 0
        self._focus_play_on_show = False
        self.state_tiles = []
        # The navigation view puts the focus on the page's first focusable
        # widget once the push transition ends -- a save-state tile, when
        # there is one -- after the shell's own idle has already landed on
        # the accent row. The first showing of a freshly loaded game ends
        # on "Continue"; coming back from a chooser keeps the view's own
        # restore, so the row that was left is the row that is found
        # (``on_shown``, which the shell calls when the slide is over).

        self.body.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.body.set_spacing(48)

        # The left column: the cover, the save states under it.
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        side.add_css_class("bp-details-side")
        side.set_valign(Gtk.Align.START)
        self.cover = CoverFrame()
        self.cover.set_halign(Gtk.Align.START)
        side.append(self.cover)
        self.states_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        side.append(self.states_box)
        left = self.scrolled(side)
        left.set_hexpand(False)
        self.body.append(left)

        # The right column: the title, the facts, the rows.
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-title")
        self.title_label.set_wrap(True)
        self.title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.title_label.set_lines(2)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        column.append(self.title_label)
        self.meta_label = Gtk.Label(xalign=0.0)
        self.meta_label.add_css_class("bp-body")
        self.meta_label.set_ellipsize(Pango.EllipsizeMode.END)
        column.append(self.meta_label)

        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        rows.set_margin_top(12)
        self.play_row = Row(t("details.play"), kind=ROW_ACTION, primary=True, on_activate=self._on_play)
        self.fresh_row = Row(
            t("context.start_fresh"), t("big_picture.details.start_fresh.subtitle"),
            kind=ROW_ACTION, on_activate=self._on_start_fresh,
        )
        self.state_row = Row(t("context.load_state"), kind=ROW_CHOICE, on_activate=self._open_state_chooser)
        self.favorite_row = Row(
            t("big_picture.details.favorite"), kind=ROW_SWITCH, on_activate=self._on_favorite_switch
        )
        self.core_row = Row(t("context.core"), kind=ROW_CHOICE, on_activate=self._open_core_chooser)
        self.shader_row = Row(t("context.shader"), kind=ROW_CHOICE, on_activate=self._open_shader_chooser)
        self.color_row = Row(
            t("context.cartridge_color"), kind=ROW_CHOICE, on_activate=self._open_color_chooser
        )
        self.playlists_row = Row(
            t("details.group.collections"), kind=ROW_ACTION, on_activate=self._open_playlists_chooser
        )
        self.artwork_row = Row(
            t("details.group.artwork"), kind=ROW_ACTION, on_activate=self._open_artwork_chooser
        )
        self.rename_row = Row(t("context.rename"), kind=ROW_ACTION, on_activate=self._on_rename)
        self.share_row = Row(t("share.menu.single"), kind=ROW_ACTION, on_activate=self._on_share)
        self.delete_row = Row(
            t("context.delete"), kind=ROW_ACTION, destructive=True, on_activate=self._on_delete
        )
        for widget in (
            self.play_row, self.fresh_row, self.state_row, self.favorite_row,
            self._eyebrow(t("details.group.settings")),
            self.core_row, self.shader_row, self.color_row,
            self._eyebrow(t("big_picture.details.file")),
            self.playlists_row, self.artwork_row, self.rename_row, self.share_row, self.delete_row,
        ):
            rows.append(widget)
        column.append(rows)
        self.path_note = note("")
        self.path_note.set_margin_top(8)
        column.append(self.path_note)
        right = self.scrolled(column)
        right.set_hexpand(True)
        self.body.append(right)

    @staticmethod
    def _eyebrow(text):
        label = eyebrow(text)
        label.set_margin_top(16)
        return label

    # -- loading a game -----------------------------------------------------------
    def load(self, rom):
        """Show ``rom``: every row re-read, the cover fetched in the background."""
        self.rom = rom
        self._focus_play_on_show = True
        win = self.win
        self.set_crumbs([win.sidebar.label_for(rom.get("console", "")), rom.get("name", "")])
        self.title_label.set_label(rom.get("name", ""))
        self.path_note.set_label(str(rom.get("path", "")))
        self._read_states()
        self._sync_meta()
        self._sync_play_rows()
        self._sync_settings()
        self._sync_playlists()
        self._build_states()
        self._load_cover()

    def _read_states(self):
        rom = self.rom
        states_dir = self.win.config_manager.get_console_states_dir(rom["console"])
        self._states = save_states.list_states(states_dir, rom["path"])

    def _sync_meta(self):
        """``Super Nintendo · 2 h ago · 1 h played · ★ Favorite``."""
        win, rom, t = self.win, self.rom, self.t
        parts = [
            win.sidebar.label_for(rom.get("console", "")),
            win.play_caption(rom) or t("details.never_played"),
        ]
        favorite = win._is_favorite_rom(rom)
        if favorite:
            parts.append(t("big_picture.details.favorite_mark"))
        self.meta_label.set_label(" · ".join(parts))
        self.favorite_row.set_active(favorite)

    def _sync_play_rows(self):
        t = self.t
        resuming = self.win.has_auto_state(self.rom)
        self.play_row.title_label.set_label(
            t("big_picture.details.continue") if resuming else t("details.play")
        )
        self.play_row.set_subtitle(t("card.resume.tooltip") if resuming else None)
        self.fresh_row.set_visible(resuming)
        if self._states:
            self.state_row.set_value(t("big_picture.details.states_count", count=len(self._states)))
        else:
            self.state_row.set_value(t("details.states.empty"))
        self.state_row.set_sensitive(bool(self._states))

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
        """A choice row's value and scope: this game's own, or the console's."""
        t = self.t
        if own_label is not None:
            row.set_value(own_label)
            row.set_subtitle(t("details.scope.game"))
        else:
            row.set_value(t("details.console_default", value=console_label))
            row.set_subtitle(None)

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
        """Up to three tiles under the cover: the automatic state, then the slots."""
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
        for state in self._states[: MAX_STATE_TILES - len(self.state_tiles)]:
            tile = StateTile(
                t("details.states.slot", slot=state.slot), stamp(state.mtime),
                thumbnail=state.thumbnail, size=size,
                on_activate=lambda slot=state.slot: self.win.launch_rom_at_state(self.rom, slot),
            )
            tile.slot = state.slot
            self.states_box.append(tile)
            self.state_tiles.append(tile)
        self.states_box.set_visible(bool(self.state_tiles))

    def _open_state_chooser(self):
        """Every saved slot with its date; the game starts from the one picked."""
        t = self.t
        if not self._states:
            return
        options = [
            {
                "id": str(state.slot),
                "label": t("details.states.slot", slot=state.slot),
                "subtitle": stamp(state.mtime),
            }
            for state in self._states
        ]
        self.shell.open_chooser(
            t("context.load_state"), options, None, self._pick_state,
            crumbs=self._crumbs(t("context.load_state")),
            lead=t("big_picture.details.load_state.lead"),
        )

    def _pick_state(self, slot_id):
        self.win.launch_rom_at_state(self.rom, int(slot_id))

    # -- playing ---------------------------------------------------------------------------
    def _on_play(self):
        self.win.on_launch_game(self.rom)

    def _on_start_fresh(self):
        self.win.game.launch(self.rom, resume=False)

    # -- favourite ------------------------------------------------------------------------
    def _on_favorite_switch(self, _active):
        self._toggle_favorite()

    def _toggle_favorite(self):
        self.win._toggle_favorite_from_ui(self.rom)
        # The window is the one that knows; the switch follows it, never leads.
        self._sync_meta()

    def on_pad_action(self, action):
        """Y toggles the favourite from anywhere on the page."""
        if action == "favorite":
            self._toggle_favorite()
            return True
        return False

    # -- the three settings ------------------------------------------------------------------
    def _crumbs(self, title):
        return [self.rom.get("name", ""), title]

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
            self.shell.pop()

    def _on_share(self):
        self.win.share_roms([self.rom])

    def _on_delete(self):
        # The window asks first; the grid and this page's game go together.
        self.win._confirm_delete_roms([self.rom])

    # -- the pad -----------------------------------------------------------------------------------
    def step_section(self, delta):
        """LB and RB: the game before or after this one on the page the grid shows."""
        grid = self.win._visible_grid()
        if grid is None or self.rom is None:
            return False
        entries = grid.visible_entries()
        paths = [entry.rom.get("path") for entry in entries]
        current = self.rom.get("path")
        if current not in paths or len(paths) < 2:
            return False
        self.load(entries[(paths.index(current) + delta) % len(paths)].rom)
        # The page is on screen already: the focus stays on the row it is on.
        self._focus_play_on_show = False
        return True

    def on_shown(self):
        if self._focus_play_on_show:
            self._focus_play_on_show = False
            GLib.idle_add(once(self.play_row.grab_focus))
            return True
        return False

    def focus_default(self):
        return self.play_row.grab_focus()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.choose")),
            (g["back"], t("hints.back")),
            (g["favorite"], t("hints.favorite")),
            (g["consoles"], t("big_picture.details.prev_next")),
        ]


__all__ = [
    "GameDetailsPage", "StateTile", "CoverFrame", "stamp",
    "CONSOLE_DEFAULT", "NEW_PLAYLIST", "ART_FETCH", "ART_CHOOSE", "ART_REMOVE",
]

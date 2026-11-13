"""The game details dialog: one place for everything about a game (issue 913).

Every per-game setting used to live in the card's context menu, fourteen rows
and five submenus deep, with nowhere to read "this game runs with core X and
shader Y, was last played Z and has three save states" at a glance. This
dialog is that place: the cover, the facts, the three overridable settings
with their scope said out loud and a one-step reset, the save states with
Load, the artwork actions and the playlists. The popover keeps the quick
actions; Alt+Return and the gamepad's X open this.
"""

import logging
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from openemux.core import cartridge_colors, cartridge_render, save_states
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.scraper import COVER_ART, LABEL_ART, resolve_local_art
from openemux.core.systems import get_system_display_name

logger = logging.getLogger(__name__)

#: The cover in the dialog's hero row.
COVER_WIDTH, COVER_HEIGHT = 120, 160
#: A save state's screenshot beside its row.
THUMBNAIL_SIZE = 64


class GameDetailsDialog(Adw.Dialog):
    def __init__(self, win, rom):
        super().__init__()
        self.win = win
        self.rom = rom
        self.t = win.t
        self.config = win.config_manager
        self._building = False
        self.set_title(self.t("details.title"))
        self.set_content_width(560)
        self.set_content_height(720)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle.new(
                self.t("details.title"), get_system_display_name(rom["console"])
            )
        )
        toolbar.add_top_bar(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        clamp = Adw.Clamp()
        clamp.set_maximum_size(560)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_top(18)
        body.set_margin_bottom(24)
        body.set_margin_start(18)
        body.set_margin_end(18)
        body.append(self._build_hero())
        self.settings_group = self._build_settings()
        body.append(self.settings_group)
        self.states_group = self._build_states()
        body.append(self.states_group)
        body.append(self._build_artwork())
        self.collections_group = self._build_collections()
        body.append(self.collections_group)
        body.append(self._build_file_actions())
        clamp.set_child(body)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

    # ----- the hero: cover, name, facts, Play -------------------------------
    def _build_hero(self):
        rom = self.rom
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.cover = Gtk.Picture()
        self.cover.set_size_request(COVER_WIDTH, COVER_HEIGHT)
        self.cover.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.cover.set_valign(Gtk.Align.START)
        art = resolve_local_art(rom, self.win.roms_path, kinds=(COVER_ART, LABEL_ART))
        if art:
            self.cover.set_filename(str(art))
        else:
            # Nothing on disk: the artwork rows below are the way to one.
            placeholder = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
            placeholder.set_pixel_size(48)
            placeholder.set_size_request(COVER_WIDTH, COVER_HEIGHT)
            placeholder.add_css_class("dim-label")
            self.cover = placeholder
        row.append(self.cover)

        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        facts.set_hexpand(True)
        facts.set_valign(Gtk.Align.CENTER)
        self.name_label = Gtk.Label(label=rom.get("name", ""))
        self.name_label.add_css_class("title-2")
        self.name_label.set_halign(Gtk.Align.START)
        self.name_label.set_wrap(True)
        self.name_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.name_label.set_xalign(0.0)
        facts.append(self.name_label)
        console_label = Gtk.Label(label=get_system_display_name(rom["console"]))
        console_label.add_css_class("dim-label")
        console_label.set_halign(Gtk.Align.START)
        facts.append(console_label)
        # When and for how long (issue 910), or that it was never played.
        self.played_label = Gtk.Label(
            label=self.win.play_caption(rom) or self.t("details.never_played")
        )
        self.played_label.add_css_class("caption")
        self.played_label.add_css_class("dim-label")
        self.played_label.set_halign(Gtk.Align.START)
        facts.append(self.played_label)
        self.file_label = Gtk.Label(label=str(rom.get("path", "")))
        self.file_label.add_css_class("caption")
        self.file_label.add_css_class("dim-label")
        self.file_label.set_halign(Gtk.Align.START)
        self.file_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.file_label.set_selectable(True)
        self.file_label.set_tooltip_text(str(rom.get("path", "")))
        facts.append(self.file_label)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_margin_top(6)
        self.play_button = Gtk.Button(label=self.t("details.play"))
        self.play_button.add_css_class("suggested-action")
        self.play_button.add_css_class("pill")
        self.play_button.connect("clicked", self._on_play)
        buttons.append(self.play_button)
        self.favorite_button = Gtk.Button()
        self.favorite_button.add_css_class("pill")
        self.favorite_button.connect("clicked", self._on_favorite)
        buttons.append(self.favorite_button)
        self._sync_favorite()
        facts.append(buttons)
        row.append(facts)
        return row

    def _sync_favorite(self):
        is_favorite = self.win._is_favorite_rom(self.rom)
        key = "context.favorite.remove" if is_favorite else "context.favorite.add"
        self.favorite_button.set_label(self.t(key))

    def _on_play(self, _button):
        self.win.on_launch_game(self.rom)
        self.close()

    def _on_favorite(self, _button):
        self.win._toggle_favorite_from_ui(self.rom)
        self._sync_favorite()

    # ----- the three per-game settings --------------------------------------
    def _build_settings(self):
        group = Adw.PreferencesGroup(title=self.t("details.group.settings"))
        self.core_row = self._combo_row(group, "context.core", self._on_core_selected)
        self.shader_row = self._combo_row(group, "context.shader", self._on_shader_selected)
        self.color_row = None
        if len(cartridge_render.frame_colors_for(self.rom["console"])) >= 2:
            self.color_row = self._combo_row(
                group, "context.cartridge_color", self._on_color_selected
            )
        self._sync_settings()
        return group

    def _combo_row(self, group, title_key, on_selected):
        row = Adw.ComboRow(title=self.t(title_key))
        reset = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        reset.add_css_class("flat")
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_tooltip_text(self.t("details.reset"))
        reset.set_visible(False)
        reset.connect("clicked", lambda _b, r=row: self._reset_row(r))
        row.add_suffix(reset)
        row.reset_button = reset
        row.connect("notify::selected", on_selected)
        group.add(row)
        return row

    def _fill_row(self, row, console_label, options, override):
        """Rebuild a combo row: "Console default (X)" first, then the options.

        ``options`` is ``[(value, label)]``; ``override`` the per-game value
        in effect or ``None``. The subtitle says which scope the value comes
        from, and the reset arrow shows only while this game has its own.
        """
        self._building = True
        try:
            model = Gtk.StringList()
            model.append(self.t("details.console_default", value=console_label))
            for _value, label in options:
                model.append(label)
            row.set_model(model)
            row.options = [value for value, _label in options]
            row.console_label = console_label
            selected = 0
            if override is not None and override in row.options:
                selected = row.options.index(override) + 1
            row.set_selected(selected)
            self._mark_scope(row, bool(selected))
        finally:
            self._building = False

    def _mark_scope(self, row, overridden):
        """The subtitle and the reset arrow say where the value in effect comes from."""
        if overridden:
            row.set_subtitle(self.t("details.scope.game"))
        else:
            row.set_subtitle(self.t("details.scope.console", value=row.console_label))
        row.reset_button.set_visible(overridden)

    def _sync_settings(self):
        rom = self.rom
        console, path = rom["console"], rom["path"]
        catalog = self.win.core_catalog
        cores = catalog.cores_for_console(console)
        console_core = self.config.get_console_core_override(console)
        if console_core:
            auto_label = catalog.display_name_for(console_core)
        elif cores:
            auto_label = cores[0].display_name
        else:
            auto_label = self.t("context.core.none")
        self._fill_row(
            self.core_row,
            auto_label,
            [(core.filename, core.display_name) for core in cores],
            self.config.get_rom_core_override(path),
        )
        shaders = self.win.shader_catalog
        show_all = bool(self.config.get_shader_settings().get("show_all_shaders", False))
        self._fill_row(
            self.shader_row,
            shaders.label_for_shader(self.config.get_shader_for_console(console)),
            shaders.get_options(show_all=show_all),
            self.config.get_rom_shader_override(path),
        )
        if self.color_row is not None:
            available = cartridge_render.frame_colors_for(console)
            ordered = [
                color_id
                for color_id in cartridge_colors.order_color_ids(available)
                if color_id != cartridge_colors.DEFAULT_COLOR_ID
            ]
            console_color = self.config.get_cartridge_color_for_console(console)
            self._fill_row(
                self.color_row,
                self._color_label(console_color),
                [(color_id, self._color_label(color_id)) for color_id in ordered],
                self.config.get_rom_cartridge_color_override(path),
            )

    def _color_label(self, color_id):
        key = cartridge_colors.color_name_key(color_id)
        return self.t(key) if key else str(color_id).replace("-", " ").title()

    def _chosen(self, row):
        """The value a combo row's selection stands for; None for the console default."""
        index = row.get_selected()
        if index <= 0 or index > len(row.options):
            return None
        return row.options[index - 1]

    # Each handler writes only when the selection differs from what is stored,
    # and never rebuilds the row from inside its own notify::selected: a
    # set_model there corrupted the combo row (and a write on every echoed
    # notification was a loop of saves that never ended). The scope line and
    # the reset arrow are updated in place; the console default's label does
    # not change with a per-game choice.
    def _on_core_selected(self, row, _pspec):
        if self._building:
            return
        chosen = self._chosen(row)
        if chosen == self.config.get_rom_core_override(self.rom["path"]):
            return
        self.win.set_rom_core(self.rom, chosen)
        self._mark_scope(row, chosen is not None)

    def _on_shader_selected(self, row, _pspec):
        if self._building:
            return
        chosen = self._chosen(row)
        if chosen == self.config.get_rom_shader_override(self.rom["path"]):
            return
        self.win.set_rom_shader(self.rom, chosen)
        self._mark_scope(row, chosen is not None)

    def _on_color_selected(self, row, _pspec):
        if self._building:
            return
        chosen = self._chosen(row)
        if chosen == self.config.get_rom_cartridge_color_override(self.rom["path"]):
            return
        self.win.set_rom_cartridge_color(self.rom, chosen)
        self._mark_scope(row, chosen is not None)

    def _reset_row(self, row):
        """Back to the console default in one step: the first item is that."""
        row.set_selected(0)

    # ----- save states ------------------------------------------------------
    def _build_states(self):
        group = Adw.PreferencesGroup(title=self.t("details.group.states"))
        rom = self.rom
        states_dir = self.config.get_console_states_dir(rom["console"])
        found = save_states.list_states(states_dir, rom["path"])
        self.state_rows = []
        if self.win.has_auto_state(rom):
            auto = Adw.ActionRow(
                title=self.t("details.states.auto"),
                subtitle=self.t("card.resume.tooltip"),
            )
            auto.add_prefix(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
            group.add(auto)
        for state in found:
            row = Adw.ActionRow(
                title=self.t("details.states.slot", slot=state.slot),
                subtitle=datetime.fromtimestamp(state.mtime).strftime("%d/%m/%Y %H:%M"),
            )
            if state.thumbnail is not None and Path(state.thumbnail).is_file():
                shot = Gtk.Picture.new_for_filename(str(state.thumbnail))
                shot.set_size_request(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
                shot.set_content_fit(Gtk.ContentFit.COVER)
                row.add_prefix(shot)
            load = Gtk.Button(label=self.t("details.states.load"))
            load.add_css_class("flat")
            load.set_valign(Gtk.Align.CENTER)
            load.connect("clicked", lambda _b, slot=state.slot: self._on_load_state(slot))
            row.add_suffix(load)
            row.set_activatable_widget(load)
            row.slot = state.slot
            group.add(row)
            self.state_rows.append(row)
        if not found and not self.win.has_auto_state(rom):
            group.add(Adw.ActionRow(title=self.t("details.states.empty")))
        return group

    def _on_load_state(self, slot):
        self.win.launch_rom_at_state(self.rom, slot)
        self.close()

    # ----- artwork ----------------------------------------------------------
    def _build_artwork(self):
        group = Adw.PreferencesGroup(title=self.t("details.group.artwork"))
        self.fetch_row = self._action_row(
            group, "details.artwork.fetch", "folder-download-symbolic", self._on_fetch_artwork
        )
        self.manage_row = self._action_row(
            group,
            "context.cover.manage",
            "document-properties-symbolic",
            lambda: self.win.open_artwork_manager(self.rom, COVER_ART),
        )
        self.choose_row = self._action_row(
            group,
            "context.cover.choose",
            "image-x-generic-symbolic",
            lambda: self.win._choose_cover_for_rom(self.rom, self._on_artwork_changed, COVER_ART),
        )
        self.remove_row = self._action_row(
            group,
            "context.cover.remove",
            "user-trash-symbolic",
            lambda: self.win._remove_cover_for_rom(self.rom, self._on_artwork_changed, COVER_ART),
        )
        self.remove_row.set_visible(self.win._has_local_cover(self.rom, COVER_ART))
        return group

    def _action_row(self, group, title_key, icon, on_activate):
        row = Adw.ActionRow(title=self.t(title_key), activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        row.connect("activated", lambda _r: on_activate())
        group.add(row)
        return row

    def _on_fetch_artwork(self):
        self.win.sync_rom_artwork(self.rom, COVER_ART_TYPE_BOXART)
        if cartridge_render.has_frame(self.rom["console"]):
            self.win.sync_rom_artwork(self.rom, COVER_ART_TYPE_CARTRIDGE_LABEL)

    def _on_artwork_changed(self, *_args):
        self.remove_row.set_visible(self.win._has_local_cover(self.rom, COVER_ART))
        for grid in self.win.pages.grids():
            grid.refresh_rom_artwork(self.rom)

    # ----- playlists --------------------------------------------------------
    def _build_collections(self):
        group = Adw.PreferencesGroup(title=self.t("details.group.collections"))
        manager = self.win.collection_manager
        self.collection_rows = []
        for collection in manager.list_collections():
            row = Adw.SwitchRow(title=collection["name"])
            row.set_active(manager.contains(collection["slug"], self.rom["path"]))
            row.slug = collection["slug"]
            row.connect("notify::active", self._on_collection_toggled)
            group.add(row)
            self.collection_rows.append(row)
        self.new_collection_row = self._action_row(
            group,
            "collections.new",
            "list-add-symbolic",
            lambda: (self.win.create_collection_and_add(self.rom), self.close()),
        )
        return group

    def _on_collection_toggled(self, row, _pspec):
        if self._building:
            return
        manager = self.win.collection_manager
        if row.get_active() == manager.contains(row.slug, self.rom["path"]):
            return
        self.win.toggle_rom_in_collection(self.rom, row.slug)

    # ----- the file ---------------------------------------------------------
    def _build_file_actions(self):
        group = Adw.PreferencesGroup()
        self._action_row(
            group, "context.reveal", "folder-open-symbolic",
            lambda: self.win._reveal_rom_in_files(self.rom),
        )
        self._action_row(
            group, "context.rename", "document-edit-symbolic",
            lambda: (self.close(), self.win._rename_rom_from_ui(self.rom)),
        )
        delete = self._action_row(
            group, "context.delete", "user-trash-symbolic",
            lambda: (self.close(), self.win._confirm_delete_roms([self.rom])),
        )
        delete.add_css_class("error")
        return group

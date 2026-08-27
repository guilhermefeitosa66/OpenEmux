"""Extra ROM context-menu entries that need more than a flat action row.

The grid builds the basic rows (favorite, cover, rename, delete) itself. The
richer, data-driven submenus -- picking a shader for a single game today, and a
core or a collection later -- are assembled here so the grid does not have to
know about every subsystem. One service, one place for the ``if`` that decides
whether an entry applies.
"""

from openemux.core import cartridge_colors, cartridge_render
from openemux.core.library_view import renders_cartridge
from openemux.ui.context_menu import SEPARATOR, Submenu
from openemux.ui.scopes import is_collection_scope


class RomContextMenuServices:
    def __init__(self, window):
        self.win = window

    def build_submenus(self, rom):
        """Return the extra entries to splice into ``rom``'s context menu."""
        # Load state comes first and the collection entries last: picking up
        # where you left off is what people reach this menu for during play,
        # while filing a game away is housekeeping. The add/remove collection
        # pair stays adjacent -- they are two halves of the same thing.
        entries = []
        load_state = self._load_state_submenu(rom)
        if load_state is not None:
            entries.append(load_state)
        core = self._core_submenu(rom)
        if core is not None:
            entries.append(core)
        shader = self._shader_submenu(rom)
        if shader is not None:
            entries.append(shader)
        color = self._cartridge_color_submenu(rom)
        if color is not None:
            entries.append(color)
        entries.append(self._add_to_collection_submenu(rom))
        remove = self._remove_from_collection_entry(rom)
        if remove is not None:
            entries.append(remove)
        return entries

    def _add_to_collection_submenu(self, rom):
        cm = self.win.collection_manager
        t = self.win.t
        collections = cm.list_collections()
        entries = []
        for collection in collections:
            in_it = cm.contains(collection["slug"], rom.get("path", ""))
            entries.append(
                (
                    collection["name"],
                    (lambda r=rom, s=collection["slug"]: self.win.toggle_rom_in_collection(r, s)),
                    "emblem-ok-symbolic" if in_it else None,
                )
            )
        if collections:
            entries.append(SEPARATOR)
        # Creating a collection and adding the game in one step -- the common
        # case when the first game of a new grouping shows up.
        entries.append(
            (t("collections.new"), (lambda r=rom: self.win.create_collection_and_add(r)), "list-add-symbolic")
        )
        return Submenu(t("context.add_to_collection"), entries, "list-add-symbolic")

    def _remove_from_collection_entry(self, rom):
        # Only while viewing a collection: removing here never touches the file.
        if not is_collection_scope(self.win.current_console):
            return None
        return (
            self.win.t("context.remove_from_collection"),
            (lambda r=rom: self.win.remove_rom_from_current_collection(r)),
            "list-remove-symbolic",
        )

    def _core_submenu(self, rom):
        console = rom.get("console")
        path = rom.get("path")
        if not console or not path:
            return None

        config = self.win.config_manager
        catalog = self.win.core_catalog
        t = self.win.t

        cores = catalog.cores_for_console(console)
        if not cores:
            # Nothing installed for this system -- no choice to offer.
            return None

        override = config.get_rom_core_override(path)
        auto_label = self._auto_core_label(console)

        entries = [
            (
                t("context.core.automatic", core=auto_label),
                (lambda r=rom: self.win.set_rom_core(r, None)),
                "emblem-ok-symbolic" if not override else None,
            ),
            SEPARATOR,
        ]
        for core in cores:
            checked = override == core.filename
            entries.append(
                (
                    core.display_name,
                    (lambda r=rom, f=core.filename: self.win.set_rom_core(r, f)),
                    "emblem-ok-symbolic" if checked else None,
                )
            )
        return Submenu(t("context.core"), entries, "application-x-executable-symbolic")

    def _auto_core_label(self, console):
        """What the console/automatic level would run, for the Automatic row."""
        config = self.win.config_manager
        catalog = self.win.core_catalog
        console_override = config.get_console_core_override(console)
        if console_override:
            return catalog.display_name_for(console_override)
        for core in catalog.cores_for_console(console):
            return core.display_name
        return self.win.t("context.core.none")

    def _cartridge_color_submenu(self, rom):
        """Pick this ROM's shell color -- only where a shell is being drawn.

        Absent (returns ``None``) outside cartridge view, for consoles with no
        frame, and for consoles whose only shell is the default: a menu with
        one choice is noise.
        """
        console = rom.get("console")
        path = rom.get("path")
        if not console or not path:
            return None
        if not renders_cartridge(self.win.current_view_mode):
            return None
        available = cartridge_render.frame_colors_for(console)
        if len(available) < 2:
            return None

        config = self.win.config_manager
        t = self.win.t
        override = config.get_rom_cartridge_color_override(path)

        def _label(color_id):
            key = cartridge_colors.color_name_key(color_id)
            # An id on disk but not in the table still shows up, title-cased.
            return t(key) if key else color_id.replace("-", " ").title()

        entries = []
        for color_id in cartridge_colors.order_color_ids(available):
            if color_id == cartridge_colors.DEFAULT_COLOR_ID:
                # Clearing the override; "" keeps the labels aligned with the
                # swatch column of the color rows below.
                entries.append(
                    (
                        _label(color_id),
                        (lambda r=rom: self.win.set_rom_cartridge_color(r, None)),
                        "emblem-ok-symbolic" if not override else None,
                        "",
                    )
                )
                entries.append(SEPARATOR)
                continue
            entries.append(
                (
                    _label(color_id),
                    (lambda r=rom, c=color_id: self.win.set_rom_cartridge_color(r, c)),
                    "emblem-ok-symbolic" if override == color_id else None,
                    cartridge_colors.color_swatch(color_id),
                )
            )
        return Submenu(t("context.cartridge_color"), entries, "color-select-symbolic")

    def _load_state_submenu(self, rom):
        """Pick a save-state slot to launch this ROM from (issue #73 redo).

        One row per slot, stamped with the save's date/time; empty slots stay
        visible but insensitive, so the numbering never shifts around. In-game
        saving and loading is RetroArch-hotkey territory -- this menu only
        covers "start the game from that save".
        """
        from datetime import datetime

        from openemux.core import save_states

        console = rom.get("console")
        path = rom.get("path")
        # Guarded like every sibling submenu: both are keys into per-console
        # and per-ROM state, and this one used to index them directly, so a
        # ROM dict missing either raised KeyError straight out of the
        # right-click (issue #245).
        if not console or not path:
            return None

        t = self.win.t
        states_dir = self.win.config_manager.get_console_states_dir(console)
        entries = []
        for slot, mtime in save_states.slot_entries(states_dir, path):
            if mtime is None:
                label = t("states.slot_empty", slot=slot)
                entries.append((label, None, None))
                continue
            stamp = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            label = t("states.slot_stamped", slot=slot, stamp=stamp)
            entries.append(
                (label, (lambda r=rom, s=slot: self.win.launch_rom_at_state(r, s)), None)
            )
        return Submenu(t("context.load_state"), entries, "media-floppy-symbolic")

    def _shader_submenu(self, rom):
        console = rom.get("console")
        path = rom.get("path")
        if not console or not path:
            return None

        config = self.win.config_manager
        catalog = self.win.shader_catalog
        t = self.win.t

        show_all = bool(config.get_shader_settings().get("show_all_shaders", False))
        options = catalog.get_options(show_all=show_all)
        override = config.get_rom_shader_override(path)
        console_shader = config.get_shader_for_console(console)
        console_label = catalog.label_for_shader(console_shader)

        entries = [
            (
                t("context.shader.use_console", shader=console_label),
                (lambda r=rom: self.win.set_rom_shader(r, None)),
                "emblem-ok-symbolic" if override is None else None,
            ),
            SEPARATOR,
        ]
        for shader_id, label in options:
            checked = override is not None and shader_id == override
            entries.append(
                (
                    label,
                    (lambda r=rom, s=shader_id: self.win.set_rom_shader(r, s)),
                    "emblem-ok-symbolic" if checked else None,
                )
            )
        return Submenu(t("context.shader"), entries, "applications-graphics-symbolic")

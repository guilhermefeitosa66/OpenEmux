"""Extra ROM context-menu entries that need more than a flat action row.

The grid builds the basic rows (favorite, cover, rename, delete) itself. The
richer, data-driven submenus -- picking a shader for a single game today, and a
core or a collection later -- are assembled here so the grid does not have to
know about every subsystem. One service, one place for the ``if`` that decides
whether an entry applies.
"""

from openemux.ui.context_menu import SEPARATOR, Submenu


class RomContextMenuServices:
    def __init__(self, window):
        self.win = window

    def build_submenus(self, rom):
        """Return the extra entries to splice into ``rom``'s context menu."""
        entries = []
        entries.append(self._add_to_collection_submenu(rom))
        remove = self._remove_from_collection_entry(rom)
        if remove is not None:
            entries.append(remove)
        core = self._core_submenu(rom)
        if core is not None:
            entries.append(core)
        shader = self._shader_submenu(rom)
        if shader is not None:
            entries.append(shader)
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
        from openemux.ui.window import is_collection_scope

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

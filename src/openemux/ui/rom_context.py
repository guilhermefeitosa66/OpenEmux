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
        shader = self._shader_submenu(rom)
        if shader is not None:
            entries.append(shader)
        return entries

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

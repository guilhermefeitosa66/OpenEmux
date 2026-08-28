"""The data-driven half of a ROM's context menu (issue #245).

`ui/rom_context.py` had no test file and sat at 10% coverage, while it decides
what a right-click actually offers: which submenus appear at all, and which row
in each carries the check mark. Every one of those decisions is an `if` over
config and catalog state -- no widgets involved -- so a fake window is enough,
and getting one wrong shows up as a menu that quietly lies about what is
selected.
"""

import tempfile
import unittest
from pathlib import Path

from openemux.ui.context_menu import SEPARATOR, Submenu
from openemux.ui.rom_context import RomContextMenuServices

CHECK = "emblem-ok-symbolic"


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _CoreCatalog:
    def __init__(self, cores=()):
        self._cores = list(cores)

    def cores_for_console(self, _console):
        return list(self._cores)

    def display_name_for(self, filename):
        for core in self._cores:
            if core.filename == filename:
                return core.display_name
        return filename


class _ShaderCatalog:
    def __init__(self, options=()):
        self.options = list(options)
        self.show_all_asked = None

    def get_options(self, show_all=False):
        self.show_all_asked = show_all
        return list(self.options)

    def label_for_shader(self, shader_id):
        return f"label:{shader_id}"


class _CollectionManager:
    def __init__(self, collections=(), members=()):
        self._collections = list(collections)
        self._members = set(members)

    def list_collections(self):
        return list(self._collections)

    def contains(self, slug, path):
        return (slug, path) in self._members


class _Config:
    def __init__(self, **overrides):
        self._rom_core = overrides.get("rom_core", {})
        self._console_core = overrides.get("console_core", {})
        self._rom_shader = overrides.get("rom_shader", {})
        self._console_shader = overrides.get("console_shader", {})
        self._rom_color = overrides.get("rom_color", {})
        self._shader_settings = overrides.get("shader_settings", {})
        # A directory that does not exist is a console with no saves, which is
        # what most of these tests want; list_states() answers [] for it.
        self.states_dir = overrides.get("states_dir", Path("/nonexistent/states"))

    def get_rom_core_override(self, path):
        return self._rom_core.get(path)

    def get_console_core_override(self, console):
        return self._console_core.get(console)

    def get_rom_shader_override(self, path):
        return self._rom_shader.get(path)

    def get_shader_for_console(self, console):
        return self._console_shader.get(console, "none")

    def get_rom_cartridge_color_override(self, path):
        return self._rom_color.get(path)

    def get_shader_settings(self):
        return dict(self._shader_settings)

    def get_console_states_dir(self, _console):
        return self.states_dir


class _Window:
    """Exactly the surface RomContextMenuServices reads off the window."""

    def __init__(self, **kwargs):
        self.config_manager = kwargs.get("config", _Config())
        self.core_catalog = kwargs.get("core_catalog", _CoreCatalog())
        self.shader_catalog = kwargs.get("shader_catalog", _ShaderCatalog())
        self.collection_manager = kwargs.get("collections", _CollectionManager())
        self.current_console = kwargs.get("current_console", "SFC")
        self.current_view_mode = kwargs.get("view_mode", "cover")
        self.calls = []

    def t(self, key, **params):
        return key if not params else f"{key}({','.join(sorted(params))})"

    def __getattr__(self, name):
        # Every win.<action>(...) the menu wires up: recorded, never executed
        # for real.
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _record


ROM = {"console": "SFC", "path": "/roms/SFC/Game.sfc", "name": "Game"}


def _labels(submenu):
    return [entry[0] for entry in submenu.entries if entry is not SEPARATOR]


def _checked(submenu):
    return [
        entry[0]
        for entry in submenu.entries
        if entry is not SEPARATOR and len(entry) > 2 and entry[2] == CHECK
    ]


def _by_title(entries, title):
    for entry in entries:
        if isinstance(entry, Submenu) and entry.label == title:
            return entry
    return None


class WhichSubmenusAppearTests(unittest.TestCase):
    def test_the_bare_case_offers_load_state_shader_and_collections(self):
        # No cores installed, not a cartridge view, not inside a collection.
        # The shader submenu stays: even with no presets it carries the "use
        # the console's choice" row, which is a real thing to pick.
        services = RomContextMenuServices(_Window(view_mode="cover"))
        entries = services.build_submenus(ROM)
        self.assertEqual(
            [entry.label for entry in entries if isinstance(entry, Submenu)],
            ["context.load_state", "context.shader", "context.add_to_collection"],
        )

    def test_a_cover_view_is_not_a_cartridge_view(self):
        # normalize_view_mode() defaults an unknown value to "cartridge", so
        # the absence has to be checked against a real mode, not a typo.
        services = RomContextMenuServices(_Window(view_mode="cover"))
        self.assertIsNone(
            _by_title(services.build_submenus(ROM), "context.cartridge_color")
        )

    def test_load_state_comes_first_and_collections_last(self):
        # Deliberate ordering: resuming is what the menu is reached for during
        # play; filing a game away is housekeeping.
        services = RomContextMenuServices(
            _Window(core_catalog=_CoreCatalog([_Core("snes9x_libretro.so", "Snes9x")]))
        )
        entries = services.build_submenus(ROM)
        self.assertEqual(entries[0].label, "context.load_state")
        self.assertEqual(entries[-1].label, "context.add_to_collection")

    def test_a_rom_with_no_console_or_path_gets_no_per_rom_submenu(self):
        # Both are keys into config overrides; without them there is nothing
        # to store a choice against.
        window = _Window(
            core_catalog=_CoreCatalog([_Core("snes9x_libretro.so", "Snes9x")]),
            shader_catalog=_ShaderCatalog([("crt", "CRT")]),
        )
        services = RomContextMenuServices(window)
        for broken in ({"console": "SFC"}, {"path": "/x.sfc"}, {}):
            with self.subTest(rom=broken):
                titles = [
                    entry.label
                    for entry in services.build_submenus({**broken, "name": "x"})
                    if isinstance(entry, Submenu)
                ]
                self.assertNotIn("context.core", titles)
                self.assertNotIn("context.shader", titles)
                # This one used to index rom["console"] directly and raise
                # KeyError out of the right-click.
                self.assertNotIn("context.load_state", titles)


class CoreSubmenuTests(unittest.TestCase):
    def _services(self, **kwargs):
        cores = [_Core("snes9x_libretro.so", "Snes9x"), _Core("bsnes_libretro.so", "bsnes")]
        kwargs.setdefault("core_catalog", _CoreCatalog(cores))
        return RomContextMenuServices(_Window(**kwargs))

    def test_no_installed_core_means_no_submenu_rather_than_an_empty_one(self):
        services = RomContextMenuServices(_Window(core_catalog=_CoreCatalog([])))
        self.assertIsNone(_by_title(services.build_submenus(ROM), "context.core"))

    def test_automatic_is_checked_while_the_rom_has_no_override(self):
        submenu = _by_title(self._services().build_submenus(ROM), "context.core")
        self.assertEqual(_checked(submenu), ["context.core.automatic(core)"])

    def test_the_overridden_core_is_the_one_checked(self):
        services = self._services(
            config=_Config(rom_core={ROM["path"]: "bsnes_libretro.so"})
        )
        submenu = _by_title(services.build_submenus(ROM), "context.core")
        self.assertEqual(_checked(submenu), ["bsnes"])

    def test_every_installed_core_is_listed_by_display_name(self):
        submenu = _by_title(self._services().build_submenus(ROM), "context.core")
        self.assertEqual(_labels(submenu)[1:], ["Snes9x", "bsnes"])

    def test_picking_automatic_clears_the_override(self):
        window = _Window(core_catalog=_CoreCatalog([_Core("snes9x_libretro.so", "S")]))
        submenu = _by_title(
            RomContextMenuServices(window).build_submenus(ROM), "context.core"
        )
        submenu.entries[0][1]()
        self.assertEqual(window.calls, [("set_rom_core", (ROM, None), {})])

    def test_picking_a_core_stores_that_filename(self):
        window = _Window(core_catalog=_CoreCatalog([_Core("snes9x_libretro.so", "S")]))
        submenu = _by_title(
            RomContextMenuServices(window).build_submenus(ROM), "context.core"
        )
        submenu.entries[-1][1]()
        self.assertEqual(
            window.calls, [("set_rom_core", (ROM, "snes9x_libretro.so"), {})]
        )

    def test_the_automatic_row_names_the_console_override_when_there_is_one(self):
        # The row has to say what "automatic" would actually run, or the user
        # cannot tell what they are choosing between.
        services = self._services(
            config=_Config(console_core={"SFC": "bsnes_libretro.so"})
        )
        self.assertEqual(services._auto_core_label("SFC"), "bsnes")

    def test_otherwise_it_names_the_first_resolvable_core(self):
        self.assertEqual(self._services()._auto_core_label("SFC"), "Snes9x")

    def test_and_says_so_when_nothing_would_run(self):
        services = RomContextMenuServices(_Window(core_catalog=_CoreCatalog([])))
        self.assertEqual(services._auto_core_label("SFC"), "context.core.none")


class ShaderSubmenuTests(unittest.TestCase):
    def _services(self, **kwargs):
        kwargs.setdefault(
            "shader_catalog", _ShaderCatalog([("crt", "CRT"), ("lcd", "LCD")])
        )
        return RomContextMenuServices(_Window(**kwargs))

    def test_the_console_default_is_checked_while_the_rom_has_no_override(self):
        submenu = _by_title(self._services().build_submenus(ROM), "context.shader")
        self.assertEqual(_checked(submenu), ["context.shader.use_console(shader)"])

    def test_an_override_moves_the_check_to_that_shader(self):
        services = self._services(config=_Config(rom_shader={ROM["path"]: "lcd"}))
        submenu = _by_title(services.build_submenus(ROM), "context.shader")
        self.assertEqual(_checked(submenu), ["LCD"])

    def test_the_full_list_is_asked_for_only_when_the_setting_says_so(self):
        catalog = _ShaderCatalog([("crt", "CRT")])
        services = self._services(
            shader_catalog=catalog,
            config=_Config(shader_settings={"show_all_shaders": True}),
        )
        services.build_submenus(ROM)
        self.assertTrue(catalog.show_all_asked)

    def test_and_the_curated_list_otherwise(self):
        catalog = _ShaderCatalog([("crt", "CRT")])
        services = self._services(shader_catalog=catalog)
        services.build_submenus(ROM)
        self.assertFalse(catalog.show_all_asked)


class CartridgeColorSubmenuTests(unittest.TestCase):
    def test_it_is_absent_outside_cartridge_view(self):
        services = RomContextMenuServices(_Window(view_mode="cover"))
        self.assertIsNone(
            _by_title(services.build_submenus(ROM), "context.cartridge_color")
        )

    def test_it_is_absent_when_the_console_has_fewer_than_two_shells(self):
        # A menu with one choice is noise.
        from unittest.mock import patch

        from openemux.core import cartridge_render

        services = RomContextMenuServices(_Window(view_mode="cartridge"))
        with patch.object(cartridge_render, "frame_colors_for", return_value=["default"]):
            self.assertIsNone(
                _by_title(services.build_submenus(ROM), "context.cartridge_color")
            )

    def test_the_default_shell_is_checked_while_there_is_no_override(self):
        from unittest.mock import patch

        from openemux.core import cartridge_colors, cartridge_render

        services = RomContextMenuServices(_Window(view_mode="cartridge"))
        with patch.object(
            cartridge_render,
            "frame_colors_for",
            return_value=[cartridge_colors.DEFAULT_COLOR_ID, "black"],
        ):
            submenu = _by_title(
                services.build_submenus(ROM), "context.cartridge_color"
            )
        self.assertIsNotNone(submenu)
        self.assertEqual(len(_checked(submenu)), 1)


class CollectionEntriesTests(unittest.TestCase):
    def test_every_collection_is_listed_with_membership_marked(self):
        collections = [
            {"name": "Fighting", "slug": "fighting"},
            {"name": "To Finish", "slug": "to-finish"},
        ]
        window = _Window(
            collections=_CollectionManager(
                collections, members={("fighting", ROM["path"])}
            )
        )
        submenu = _by_title(
            RomContextMenuServices(window).build_submenus(ROM),
            "context.add_to_collection",
        )
        self.assertEqual(_checked(submenu), ["Fighting"])
        self.assertIn("To Finish", _labels(submenu))

    def test_creating_a_new_collection_is_always_offered(self):
        window = _Window(collections=_CollectionManager([]))
        submenu = _by_title(
            RomContextMenuServices(window).build_submenus(ROM),
            "context.add_to_collection",
        )
        self.assertEqual(_labels(submenu), ["collections.new"])

    def test_remove_appears_only_while_viewing_a_collection(self):
        outside = RomContextMenuServices(_Window(current_console="SFC"))
        self.assertNotIn(
            "context.remove_from_collection",
            [e[0] for e in outside.build_submenus(ROM) if isinstance(e, tuple)],
        )

        inside = RomContextMenuServices(_Window(current_console="col:fighting"))
        self.assertIn(
            "context.remove_from_collection",
            [e[0] for e in inside.build_submenus(ROM) if isinstance(e, tuple)],
        )


class LoadStateSubmenuTests(unittest.TestCase):
    def test_empty_slots_stay_visible_and_insensitive(self):
        # The numbering must not shift around as saves come and go.
        with tempfile.TemporaryDirectory() as tmp:
            window = _Window(config=_Config(states_dir=Path(tmp)))
            submenu = _by_title(
                RomContextMenuServices(window).build_submenus(ROM),
                "context.load_state",
            )
            self.assertEqual(len(submenu.entries), 10)
            for entry in submenu.entries:
                self.assertIsNone(entry[1], "an empty slot must not be clickable")
                self.assertIn("states.slot_empty", entry[0])

    def test_a_saved_slot_is_stamped_and_launches_from_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            states = Path(tmp)
            (states / "Game.state3").write_bytes(b"save")
            window = _Window(config=_Config(states_dir=states))
            submenu = _by_title(
                RomContextMenuServices(window).build_submenus(ROM),
                "context.load_state",
            )
            slot3 = submenu.entries[3]
            self.assertIn("states.slot_stamped", slot3[0])
            self.assertIsNotNone(slot3[1])
            slot3[1]()
            self.assertEqual(window.calls, [("launch_rom_at_state", (ROM, 3), {})])


if __name__ == "__main__":
    unittest.main()

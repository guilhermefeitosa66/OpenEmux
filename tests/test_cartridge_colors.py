"""Per-ROM cartridge shell colors: palette table and persistence (issue #79)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import cartridge_colors
from openemux.core.cartridge_colors import (
    CARTRIDGE_COLOR_TABLE,
    DEFAULT_COLOR_ID,
    CartridgeColorStore,
)

ROM = "/roms/SFC/Chrono Trigger.sfc"
OTHER = "/roms/SFC/Terranigma.sfc"


class PaletteTableTests(unittest.TestCase):
    def test_table_matches_the_issue_palette(self):
        ids = [entry[0] for entry in CARTRIDGE_COLOR_TABLE]
        self.assertEqual(ids[0], DEFAULT_COLOR_ID)
        for color in ("black", "white", "red", "orange", "yellow", "green",
                      "teal", "blue", "purple", "pink", "gold", "clear"):
            self.assertIn(color, ids)

    def test_order_follows_the_table_with_unknown_ids_last(self):
        ordered = cartridge_colors.order_color_ids(
            ["red", "zebra", "default", "black", "aqua"]
        )
        self.assertEqual(ordered, ["default", "black", "red", "aqua", "zebra"])

    def test_unknown_id_still_gets_a_swatch_and_no_name_key(self):
        self.assertIsNone(cartridge_colors.color_name_key("zebra"))
        self.assertEqual(cartridge_colors.color_swatch("zebra"),
                         cartridge_colors.UNKNOWN_SWATCH)
        self.assertEqual(cartridge_colors.color_name_key("red"),
                         "cartridge_color.red")
        self.assertEqual(cartridge_colors.color_swatch("red"), "#B23A34")


class CartridgeColorStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = CartridgeColorStore(Path(self._tmp.name) / "cartridge_colors.config")

    def test_unset_rom_uses_the_default_shell(self):
        self.assertIsNone(self.store.get_rom_color(ROM))
        self.assertEqual(self.store.get_effective_color(ROM, "SFC"), DEFAULT_COLOR_ID)

    def test_set_and_clear_a_rom_color(self):
        self.store.set_rom_color(ROM, "SFC", "red")
        self.assertEqual(self.store.get_rom_color(ROM), "red")
        self.assertEqual(self.store.get_effective_color(ROM, "SFC"), "red")
        self.store.set_rom_color(ROM, "SFC", None)
        self.assertIsNone(self.store.get_rom_color(ROM))

    def test_color_survives_a_reload(self):
        self.store.set_rom_color(ROM, "SFC", "gold")
        again = CartridgeColorStore(self.store.config_file)
        self.assertEqual(again.get_rom_color(ROM), "gold")

    def test_console_default_backs_every_rom_without_an_override(self):
        self.store.set_console_color("SFC", "red")
        self.assertEqual(self.store.get_effective_color(ROM, "SFC"), "red")
        self.assertIsNone(self.store.get_rom_color(ROM))
        # The per-ROM override still wins over the console default.
        self.store.set_rom_color(OTHER, "SFC", "blue")
        self.assertEqual(self.store.get_effective_color(OTHER, "SFC"), "blue")

    def test_repeating_the_console_default_stores_no_override(self):
        self.store.set_console_color("SFC", "red")
        self.store.set_rom_color(ROM, "SFC", "red")
        self.assertIsNone(self.store.get_rom_color(ROM))

    def test_console_aliases_resolve_to_the_canonical_id(self):
        self.store.set_console_color("SNES", "green")
        self.assertEqual(self.store.get_console_color("SFC"), "green")

    def test_rename_follows_the_rom(self):
        self.store.set_rom_color(ROM, "SFC", "teal")
        self.store.repath_rom(ROM, OTHER)
        self.assertIsNone(self.store.get_rom_color(ROM))
        self.assertEqual(self.store.get_rom_color(OTHER), "teal")

    def test_delete_forgets_the_rom(self):
        self.store.set_rom_color(ROM, "SFC", "pink")
        self.store.forget_rom(ROM)
        self.assertIsNone(self.store.get_rom_color(ROM))
        self.assertNotIn(ROM, self.store.load()["rom_overrides"])

    def test_garbage_config_file_falls_back_to_defaults(self):
        self.store.config_file.write_text("{not yaml: [")
        self.assertEqual(self.store.get_effective_color(ROM, "SFC"), DEFAULT_COLOR_ID)


if __name__ == "__main__":
    unittest.main()

"""Per-ROM cartridge shell colors: palette table and persistence (issue #79)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

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


class ColorStoreCachingTests(unittest.TestCase):
    """The file is parsed once per write, not once per card (issue #231)."""

    def _store(self, tmp_dir):
        return CartridgeColorStore(Path(tmp_dir) / "cartridges.yaml")

    def test_repeated_lookups_read_the_file_once(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")

            reads = []
            real_read_text = Path.read_text

            def spy(self, *args, **kwargs):
                if self.name == "cartridges.yaml":
                    reads.append(self.name)
                return real_read_text(self, *args, **kwargs)

            Path.read_text = spy
            try:
                for _ in range(100):  # a page of cards, two lookups each
                    store.get_effective_color("/roms/SFC/Game.sfc", "SFC")
            finally:
                Path.read_text = real_read_text
            self.assertEqual(len(reads), 1, reads)

    def test_a_write_is_seen_by_the_next_lookup(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            self.assertEqual(store.get_console_color("SFC"), "red")
            store.set_console_color("SFC", "blue")
            self.assertEqual(store.get_console_color("SFC"), "blue")

    def test_a_page_of_lookups_stats_the_file_once_not_per_card(self):
        # Issue 907: every card bind stat-ed the file twice and deep-copied
        # the mapping twice. Readers now share the parse, and the stamp is
        # compared at most every STAMP_TTL_S.
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            store.get_effective_color("/roms/SFC/Game.sfc", "SFC")
            with mock.patch.object(store, "_stamp", wraps=store._stamp) as stamp, mock.patch.object(
                cartridge_colors.copy, "deepcopy", side_effect=AssertionError("copied")
            ):
                for _ in range(200):
                    self.assertEqual(
                        store.get_effective_color("/roms/SFC/Game.sfc", "SFC"), "red"
                    )
            self.assertEqual(stamp.call_count, 0)

    def test_an_edit_made_outside_the_app_is_seen_after_the_grace_period(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            self.assertEqual(store.get_console_color("SFC"), "red")
            other = CartridgeColorStore(store.config_file)
            other.set_console_color("SFC", "blue")
            # Inside the grace period the parse is trusted.
            self.assertEqual(store.get_console_color("SFC"), "red")
            store._checked_at -= cartridge_colors.STAMP_TTL_S
            self.assertEqual(store.get_console_color("SFC"), "blue")

    def test_after_the_grace_period_an_unchanged_file_is_not_parsed_again(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            self.assertEqual(store.get_console_color("SFC"), "red")
            store._checked_at -= cartridge_colors.STAMP_TTL_S
            with mock.patch.object(store, "_load_uncached", side_effect=AssertionError("parsed")):
                self.assertEqual(store.get_console_color("SFC"), "red")

    def test_a_caller_cannot_edit_the_cache(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            data = store.load()
            data["console_defaults"]["SFC"] = "blue"
            self.assertEqual(store.get_console_color("SFC"), "red")


class WhatTheStoreRefusesToKeepTests(unittest.TestCase):
    """The file is the user's; anything unusable in it is dropped, not obeyed."""

    def _store(self, tmp_dir):
        return CartridgeColorStore(Path(tmp_dir) / "cartridge_colors.yaml")

    def test_a_file_that_is_not_a_mapping_is_set_aside(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.config_file.write_text("- red\n", encoding="utf-8")
            self.assertEqual(store.get_console_color("SFC"), DEFAULT_COLOR_ID)
            self.assertEqual(
                len(list(Path(tmp_dir).glob("cartridge_colors.yaml.broken-*"))), 1
            )

    def test_a_default_for_a_console_that_does_not_exist_is_dropped(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.config_file.write_text(
                "console_defaults:\n  DREAMCAST: red\n  SFC: red\n", encoding="utf-8"
            )
            self.assertEqual(
                store.load()["console_defaults"], {"SFC": "red"}
            )

    def test_an_override_with_no_rom_path_is_dropped(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.config_file.write_text(
                "rom_overrides:\n  \"\": red\n", encoding="utf-8"
            )
            self.assertEqual(store.load()["rom_overrides"], {})

    def test_a_colour_for_a_console_that_does_not_exist_is_not_stored(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("DREAMCAST", "red")
            self.assertEqual(store.load()["console_defaults"], {})

    def test_setting_a_console_back_to_the_default_forgets_it(self):
        # Stating the default would pin it against a later change of default.
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_console_color("SFC", "red")
            store.set_console_color("SFC", DEFAULT_COLOR_ID)
            self.assertEqual(store.load()["console_defaults"], {})


if __name__ == "__main__":
    unittest.main()



class PresetPaletteTests(unittest.TestCase):
    """The presets are the Android skin editor's, value for value (issue 983)."""

    ANDROID = {
        "basic": "#F472B6 #EF4444 #F97316 #FACC15 #22C55E #3B82F6 #8B5CF6",
        "dracula": "#282A36 #44475A #BD93F9 #FF79C6 #8BE9FD #50FA7B #FFB86C",
        "pastel": "#FBCFE8 #FECACA #FED7AA #FEF08A #BBF7D0 #BFDBFE #DDD6FE",
        "nord": "#2E3440 #4C566A #88C0D0 #81A1C1 #A3BE8C #EBCB8B #BF616A",
        "gruvbox": "#282828 #504945 #CC241D #D79921 #98971A #458588 #B16286",
        "neon": "#0D0221 #FF2A6D #05D9E8 #D1F7FF #F9C80E #7B2FF7 #01FF89",
        "earth": "#3E2C23 #6B4F3A #A47148 #D4A373 #E9EDC9 #CCD5AE #606C38",
        "green-screen": "#0F380F #306230 #8BAC0F #9BBC0F",
    }

    def test_presets_match_android(self):
        self.assertEqual([pid for pid, _ in cartridge_colors.PRESET_PALETTES], list(self.ANDROID))
        for palette_id, colors in self.ANDROID.items():
            self.assertEqual(
                cartridge_colors.builtin_palette_colors(palette_id),
                [color.lower() for color in colors.split()],
            )

    def test_shell_palette_is_the_named_swatches(self):
        colors = cartridge_colors.builtin_palette_colors(cartridge_colors.SHELL_PALETTE_ID)
        self.assertEqual(len(colors), 12)
        self.assertEqual(colors[0], "#26262a")

    def test_custom_color_choices(self):
        choices = cartridge_colors.custom_color_choices
        self.assertEqual(choices(["#111111"], "#222222"), ["#222222", "#111111"])
        self.assertEqual(choices(["#111111", "#222222"], "#222222"), ["#111111", "#222222"])
        self.assertEqual(choices(None, "red"), [])

    def test_unknown_builtin_and_name_keys(self):
        self.assertIsNone(cartridge_colors.builtin_palette_colors("nope"))
        self.assertEqual(cartridge_colors.palette_name_key("green-screen"),
                         "cartridge_color.palette.green_screen")
        self.assertTrue(cartridge_colors.is_user_palette("user-0123abcd"))
        self.assertFalse(cartridge_colors.is_user_palette("basic"))
        self.assertFalse(cartridge_colors.is_user_palette(None))


class SavedColorsAndPalettesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "cartridge_colors.config"
        self.store = CartridgeColorStore(self.path)

    def reload(self):
        return CartridgeColorStore(self.path)

    def test_remember_puts_the_color_first_without_repeats_and_caps(self):
        self.store.remember_color("#AA0000")
        self.store.remember_color("#00aa00")
        self.store.remember_color("#aa0000")
        self.assertEqual(self.store.saved_colors(), ["#aa0000", "#00aa00"])
        for index in range(12):
            self.store.remember_color(f"#0000{index:02x}")
        saved = self.reload().saved_colors()
        self.assertEqual(len(saved), cartridge_colors.SAVED_COLORS_MAX)
        self.assertEqual(saved[0], "#00000b")

    def test_remember_ignores_named_ids_and_repeats_at_the_front(self):
        self.store.remember_color("red")
        self.assertEqual(self.store.saved_colors(), [])
        self.store.remember_color("#123456")
        with mock.patch.object(self.store, "save") as save:
            self.store.remember_color("#123456")
        save.assert_not_called()

    def test_forget_saved_color_keeps_the_games(self):
        self.store.set_rom_color(ROM, "SFC", "#123456")
        self.store.remember_color("#123456")
        self.store.forget_saved_color("#123456")
        self.store.forget_saved_color("#654321")
        self.assertEqual(self.reload().saved_colors(), [])
        self.assertEqual(self.reload().get_rom_color(ROM), "#123456")

    def test_saved_colors_survive_other_writes(self):
        self.store.remember_color("#123456")
        self.store.set_rom_color(ROM, "SFC", "red")
        self.store.set_console_color("SFC", "blue")
        self.assertEqual(self.reload().saved_colors(), ["#123456"])

    def test_palette_lifecycle(self):
        self.assertEqual(self.store.selected_palette(), "shell")
        palette_id = self.store.create_palette("  Pokémon   carts ", ["#AA0000", "red", "#aa0000"])
        self.assertTrue(cartridge_colors.is_user_palette(palette_id))
        store = self.reload()
        self.assertEqual(store.selected_palette(), palette_id)
        self.assertEqual(store.user_palettes(),
                         [{"id": palette_id, "name": "Pokémon carts", "colors": ["#aa0000"]}])
        self.assertTrue(store.add_palette_color(palette_id, "#00AA00"))
        self.assertTrue(store.add_palette_color(palette_id, "#0000aa"))
        self.assertFalse(store.add_palette_color(palette_id, "#00aa00"))
        self.assertFalse(store.add_palette_color(palette_id, "blue"))
        self.assertTrue(store.move_palette_color(palette_id, "#0000aa", -1))
        self.assertEqual(store.palette_colors(palette_id), ["#aa0000", "#0000aa", "#00aa00"])
        self.assertFalse(store.move_palette_color(palette_id, "#aa0000", -1))
        self.assertFalse(store.move_palette_color(palette_id, "#00aa00", 1))
        self.assertFalse(store.move_palette_color(palette_id, "#999999", 1))
        self.assertTrue(store.remove_palette_color(palette_id, "#aa0000"))
        self.assertFalse(store.remove_palette_color(palette_id, "#aa0000"))
        self.assertTrue(store.rename_palette(palette_id, "Mine"))
        self.assertFalse(store.rename_palette(palette_id, "Mine"))
        self.assertFalse(store.rename_palette(palette_id, "   "))
        self.assertFalse(store.rename_palette("user-ffffffff", "Other"))
        self.assertEqual(self.reload().user_palette(palette_id)["name"], "Mine")
        self.assertIsNone(store.user_palette("user-ffffffff"))
        self.assertTrue(store.delete_palette(palette_id))
        self.assertFalse(store.delete_palette(palette_id))
        self.assertEqual(self.reload().selected_palette(), "shell")

    def test_full_palette_refuses_a_color(self):
        palette_id = self.store.create_palette(
            "Full", [f"#0000{i:02x}" for i in range(cartridge_colors.PALETTE_COLORS_MAX + 3)]
        )
        self.assertEqual(len(self.store.palette_colors(palette_id)),
                         cartridge_colors.PALETTE_COLORS_MAX)
        self.assertFalse(self.store.add_palette_color(palette_id, "#ffffff"))

    def test_create_refuses_blank_names_and_too_many(self):
        self.assertIsNone(self.store.create_palette("  "))
        with mock.patch.object(cartridge_colors, "USER_PALETTES_MAX", 1):
            self.assertIsNotNone(self.store.create_palette("One"))
            self.assertIsNone(self.store.create_palette("Two"))

    def test_duplicate_builtin_and_user_palettes(self):
        copy_id = self.store.duplicate_palette("nord", "Nord copy")
        self.assertEqual(self.store.palette_colors(copy_id),
                         cartridge_colors.builtin_palette_colors("nord"))
        again = self.store.duplicate_palette(copy_id, "Again")
        self.assertEqual(self.store.palette_colors(again), self.store.palette_colors(copy_id))
        self.assertIsNone(self.store.duplicate_palette("nope", "x"))

    def test_select_palette(self):
        self.store.select_palette("dracula")
        self.assertEqual(self.reload().selected_palette(), "dracula")
        with mock.patch.object(self.store, "save") as save:
            self.store.select_palette("dracula")
            self.store.select_palette("nope")
        save.assert_not_called()

    def test_a_remembered_palette_that_is_gone_falls_back_to_shell(self):
        self.path.write_text("palette: user-00000000\n", encoding="utf-8")
        self.assertEqual(self.reload().selected_palette(), "shell")

    def test_loader_filters_junk(self):
        self.path.write_text(
            "saved_colors: ['#ABCDEF', 'red', '#zzz', 5, '#abcdef']\n"
            "palette: 7\n"
            "palettes:\n"
            "  - {id: user-0000000a, name: '  A  ', colors: ['#111111', bad, '#111111']}\n"
            "  - {id: user-0000000a, name: dup, colors: []}\n"
            "  - {id: basic, name: preset id, colors: []}\n"
            "  - {id: user-0000000b, name: '', colors: []}\n"
            "  - {id: user-0000000c, name: no colors, colors: oops}\n"
            "  - just a string\n",
            encoding="utf-8",
        )
        store = self.reload()
        self.assertEqual(store.saved_colors(), ["#abcdef"])
        self.assertEqual(store.selected_palette(), "shell")
        self.assertEqual(store.user_palettes(), [
            {"id": "user-0000000a", "name": "A", "colors": ["#111111"]},
            {"id": "user-0000000c", "name": "no colors", "colors": []},
        ])

    def test_loader_ignores_non_list_values(self):
        self.path.write_text("saved_colors: '#123456'\npalettes: {a: 1}\n", encoding="utf-8")
        store = self.reload()
        self.assertEqual(store.saved_colors(), [])
        self.assertEqual(store.user_palettes(), [])
        self.assertTrue(self.path.exists())

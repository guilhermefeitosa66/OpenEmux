"""The game details dialog (issue 913), built against the real window."""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from openemux.core import save_states
    from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
    from openemux.core.scraper import COVER_ART
    from openemux.ui import game_details as details_module
    from openemux.ui.game_details import GameDetailsDialog


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _DetailsCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.rom = self.rom()
        self.cores = [_Core("snes9x_libretro.so", "Snes9x"), _Core("bsnes_libretro.so", "bsnes")]
        catalog = self.win.core_catalog
        for name, value in (
            ("cores_for_console", lambda _console: list(self.cores)),
            ("display_name_for", lambda filename: {c.filename: c.display_name for c in self.cores}.get(filename, filename)),
        ):
            patcher = mock.patch.object(catalog, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def dialog(self):
        dialog = GameDetailsDialog(self.win, self.rom)
        self.addCleanup(dialog.force_close)
        return dialog


@needs_display
class TheHeroRowTests(_DetailsCase):
    def test_it_names_the_game_its_console_and_its_file(self):
        dialog = self.dialog()
        self.assertEqual(dialog.name_label.get_label(), self.rom["name"])
        self.assertEqual(dialog.file_label.get_label(), self.rom["path"])
        self.assertEqual(dialog.played_label.get_label(), self.said("details.never_played"))

    def test_a_played_game_says_when_and_for_how_long(self):
        self.win.play_history.record_launch(self.rom["path"])
        self.win.play_history.record_play_time(self.rom["path"], 600)
        dialog = self.dialog()
        self.assertEqual(dialog.played_label.get_label(), self.win.play_caption(self.rom))

    def test_without_a_cover_a_placeholder_stands_in(self):
        dialog = self.dialog()
        self.assertEqual(type(dialog.cover).__name__, "Image")

    def test_with_a_cover_the_picture_shows_it(self):
        covers = self.home.console_dir(self.rom["console"]) / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        from gi.repository import GdkPixbuf

        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
        pixbuf.savev(str(covers / f"{self.rom['name']}.png"), "png", [], [])
        dialog = self.dialog()
        self.assertEqual(type(dialog.cover).__name__, "Picture")

    def test_play_launches_and_closes(self):
        dialog = self.dialog()
        with mock.patch.object(self.win, "on_launch_game") as launch, mock.patch.object(dialog, "close") as close:
            dialog.play_button.emit("clicked")
        launch.assert_called_once_with(self.rom)
        close.assert_called_once()

    def test_the_favorite_button_toggles_and_relabels(self):
        dialog = self.dialog()
        self.assertEqual(dialog.favorite_button.get_label(), self.said("context.favorite.add"))
        dialog.favorite_button.emit("clicked")
        self.assertTrue(self.win.playlist_manager.is_favorite(self.rom["path"]))
        self.assertEqual(dialog.favorite_button.get_label(), self.said("context.favorite.remove"))


@needs_display
class ThePerGameSettingsTests(_DetailsCase):
    def test_the_rows_show_the_console_default_and_its_source(self):
        dialog = self.dialog()
        self.assertEqual(dialog.core_row.get_selected(), 0)
        self.assertEqual(
            dialog.core_row.get_subtitle(), self.said("details.scope.console", value="Snes9x")
        )
        self.assertFalse(dialog.core_row.reset_button.get_visible())
        self.assertEqual(dialog.core_row.get_model().get_string(0), self.said("details.console_default", value="Snes9x"))
        self.assertEqual(dialog.core_row.get_model().get_string(2), "bsnes")

    def test_a_console_override_is_the_default_the_row_names(self):
        self.config.set_console_core_override("SFC", "bsnes_libretro.so")
        dialog = self.dialog()
        self.assertEqual(dialog.core_row.get_subtitle(), self.said("details.scope.console", value="bsnes"))

    def test_picking_a_core_sets_the_override_and_reset_clears_it(self):
        dialog = self.dialog()
        dialog.core_row.set_selected(2)
        self.assertEqual(self.config.get_rom_core_override(self.rom["path"]), "bsnes_libretro.so")
        self.assertEqual(dialog.core_row.get_subtitle(), self.said("details.scope.game"))
        self.assertTrue(dialog.core_row.reset_button.get_visible())
        dialog.core_row.reset_button.emit("clicked")
        self.assertIsNone(self.config.get_rom_core_override(self.rom["path"]))
        self.assertEqual(dialog.core_row.get_selected(), 0)
        self.assertFalse(dialog.core_row.reset_button.get_visible())

    def test_a_notification_that_changes_nothing_writes_nothing(self):
        # GTK may echo notify::selected after the row was rebuilt; the
        # handlers compare with what is stored before writing.
        self.config.set_rom_core(self.rom["path"], "bsnes_libretro.so")
        self.config.set_rom_shader(self.rom["path"], "SFC", "disabled")
        with mock.patch.object(
            details_module.cartridge_render, "frame_colors_for", return_value=["default", "black"]
        ), mock.patch.object(details_module.cartridge_colors, "order_color_ids", side_effect=lambda ids: list(ids)):
            self.config.set_rom_cartridge_color(self.rom["path"], "SFC", "black")
            dialog = self.dialog()
        with mock.patch.object(self.win, "set_rom_core") as core, mock.patch.object(
            self.win, "set_rom_shader"
        ) as shader, mock.patch.object(self.win, "set_rom_cartridge_color") as color:
            dialog._on_core_selected(dialog.core_row, None)
            dialog._on_shader_selected(dialog.shader_row, None)
            dialog._on_color_selected(dialog.color_row, None)
        core.assert_not_called()
        shader.assert_not_called()
        color.assert_not_called()

    def test_an_existing_override_opens_selected(self):
        self.config.set_rom_core(self.rom["path"], "bsnes_libretro.so")
        dialog = self.dialog()
        self.assertEqual(dialog.core_row.get_selected(), 2)
        self.assertTrue(dialog.core_row.reset_button.get_visible())

    def test_the_shader_row_writes_the_per_game_shader(self):
        dialog = self.dialog()
        options = dialog.shader_row.options
        self.assertTrue(options)
        dialog.shader_row.set_selected(1)
        self.assertEqual(self.config.get_rom_shader_override(self.rom["path"]), options[0])
        dialog.shader_row.reset_button.emit("clicked")
        self.assertIsNone(self.config.get_rom_shader_override(self.rom["path"]))

    def test_the_color_row_exists_only_where_the_console_has_shells(self):
        with mock.patch.object(details_module.cartridge_render, "frame_colors_for", return_value=["default"]):
            self.assertIsNone(self.dialog().color_row)
        with mock.patch.object(
            details_module.cartridge_render, "frame_colors_for", return_value=["default", "black"]
        ), mock.patch.object(details_module.cartridge_colors, "order_color_ids", side_effect=lambda ids: list(ids)):
            dialog = self.dialog()
        self.assertIsNotNone(dialog.color_row)
        self.assertEqual(dialog.color_row.options, ["black"])
        with mock.patch.object(self.win, "set_rom_cartridge_color") as set_color:
            dialog.color_row.set_selected(1)
        set_color.assert_called_once_with(self.rom, "black")

    def test_an_unknown_colour_is_titled_from_its_id(self):
        dialog = self.dialog()
        self.assertEqual(dialog._color_label("deep-blue"), "Deep Blue")

    def test_a_selection_outside_the_options_means_the_default(self):
        dialog = self.dialog()
        dialog.core_row.options = []
        self.assertIsNone(dialog._chosen(dialog.core_row))

    def test_no_core_installed_names_none(self):
        self.cores.clear()
        dialog = self.dialog()
        self.assertEqual(
            dialog.core_row.get_subtitle(),
            self.said("details.scope.console", value=self.said("context.core.none")),
        )


@needs_display
class TheSaveStatesTests(_DetailsCase):
    def _state(self, slot, thumbnail=False):
        states_dir = self.config.get_console_states_dir(self.rom["console"])
        states_dir.mkdir(parents=True, exist_ok=True)
        stem = save_states.rom_state_stem(self.rom["path"])
        suffix = f".state{slot}" if slot else ".state"
        (states_dir / f"{stem}{suffix}").write_bytes(b"state")
        if thumbnail:
            from gi.repository import GdkPixbuf

            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
            pixbuf.savev(str(states_dir / f"{stem}{suffix}.png"), "png", [], [])

    def test_no_state_says_so(self):
        dialog = self.dialog()
        self.assertEqual(dialog.state_rows, [])
        self.assertIsNotNone(dialog.states_group.get_first_child())

    def test_each_state_gets_a_row_and_load_launches_into_it(self):
        self._state(3, thumbnail=True)
        self._state(0)
        dialog = self.dialog()
        self.assertEqual([row.slot for row in dialog.state_rows], [0, 3])
        with mock.patch.object(self.win, "launch_rom_at_state") as launch, mock.patch.object(dialog, "close") as close:
            dialog.state_rows[1].get_activatable_widget().emit("clicked")
        launch.assert_called_once_with(self.rom, 3)
        close.assert_called_once()

    def test_the_automatic_state_is_listed_when_play_would_resume_it(self):
        with mock.patch.object(self.win, "has_auto_state", return_value=True):
            dialog = self.dialog()
        first = dialog.states_group.get_first_child()
        self.assertIsNotNone(first)
        self.assertEqual(dialog.state_rows, [])


@needs_display
class TheArtworkAndPlaylistRowsTests(_DetailsCase):
    def test_fetch_asks_for_the_box_art_and_the_label_where_there_is_a_frame(self):
        dialog = self.dialog()
        with mock.patch.object(self.win, "sync_rom_artwork") as sync, mock.patch.object(
            details_module.cartridge_render, "has_frame", return_value=True
        ):
            dialog.fetch_row.emit("activated")
        self.assertEqual(
            [call.args[1] for call in sync.call_args_list],
            [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL],
        )
        with mock.patch.object(self.win, "sync_rom_artwork") as sync, mock.patch.object(
            details_module.cartridge_render, "has_frame", return_value=False
        ):
            dialog.fetch_row.emit("activated")
        self.assertEqual(sync.call_count, 1)

    def test_manage_choose_and_remove_go_through_the_window(self):
        dialog = self.dialog()
        self.assertFalse(dialog.remove_row.get_visible())
        with mock.patch.object(self.win, "open_artwork_manager") as manage:
            dialog.manage_row.emit("activated")
        manage.assert_called_once_with(self.rom, COVER_ART)
        with mock.patch.object(self.win, "_choose_cover_for_rom") as choose:
            dialog.choose_row.emit("activated")
        choose.assert_called_once()
        with mock.patch.object(self.win, "_remove_cover_for_rom") as remove:
            dialog.remove_row.emit("activated")
        remove.assert_called_once()

    def test_a_changed_cover_re_reads_the_remove_row_and_the_cards(self):
        dialog = self.dialog()
        with mock.patch.object(self.win, "_has_local_cover", return_value=True):
            dialog._on_artwork_changed()
        self.assertTrue(dialog.remove_row.get_visible())

    def test_the_playlist_switches_follow_membership(self):
        slug = self.win.collection_manager.create("RPGs")
        dialog = self.dialog()
        row = dialog.collection_rows[0]
        self.assertFalse(row.get_active())
        row.set_active(True)
        self.assertTrue(self.win.collection_manager.contains(slug, self.rom["path"]))
        row.set_active(False)
        self.assertFalse(self.win.collection_manager.contains(slug, self.rom["path"]))

    def test_a_switch_notified_while_building_is_ignored(self):
        self.win.collection_manager.create("RPGs")
        dialog = self.dialog()
        dialog._building = True
        with mock.patch.object(self.win, "toggle_rom_in_collection") as toggle:
            dialog.collection_rows[0].set_active(True)
        toggle.assert_not_called()
        dialog._building = False

    def test_a_switch_already_in_step_changes_nothing(self):
        slug = self.win.collection_manager.create("RPGs")
        self.win.collection_manager.add(slug, [self.rom["path"]])
        dialog = self.dialog()
        with mock.patch.object(self.win, "toggle_rom_in_collection") as toggle:
            dialog._on_collection_toggled(dialog.collection_rows[0], None)
        toggle.assert_not_called()

    def test_a_new_playlist_takes_the_game_and_closes(self):
        dialog = self.dialog()
        with mock.patch.object(self.win, "create_collection_and_add") as create, mock.patch.object(dialog, "close") as close:
            dialog.new_collection_row.emit("activated")
        create.assert_called_once_with(self.rom)
        close.assert_called_once()

    def test_the_file_rows_reach_the_windows_actions(self):
        dialog = self.dialog()
        body = dialog.get_child().get_content().get_child().get_child().get_child()
        rows = []
        section = body.get_last_child()
        with mock.patch.object(self.win, "_reveal_rom_in_files") as reveal, mock.patch.object(
            self.win, "_rename_rom_from_ui"
        ) as rename, mock.patch.object(self.win, "_confirm_delete_roms") as delete:
            for row in self._action_rows(section):
                row.emit("activated")
                rows.append(row.get_title())
        reveal.assert_called_once_with(self.rom)
        rename.assert_called_once_with(self.rom)
        delete.assert_called_once_with([self.rom])
        self.assertEqual(len(rows), 3)

    @staticmethod
    def _action_rows(group):
        from gi.repository import Adw

        found = []

        def walk(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Adw.ActionRow):
                    found.append(child)
                else:
                    walk(child)
                child = child.get_next_sibling()

        walk(group)
        return found


if __name__ == "__main__":
    unittest.main()

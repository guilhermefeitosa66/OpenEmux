"""Big Picture's game details page (issue 914): the cover, the rows, the choosers.

Built against the real window with the mode on, like the desktop dialog's
tests: every row calls the window method the dialog calls, so what is
checked here is the page's own half -- which rows show, what they say, and
what each one asks the window for. The choosers and the keyboard page are
captured at the shell, which keeps the tests about this page alone.
"""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import GdkPixbuf

    from openemux.core import save_states
    from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
    from openemux.core.scraper import COVER_ART
    from openemux.ui.bigpicture import details as details_module
    from openemux.ui.bigpicture.details import (
        ART_CHOOSE,
        ART_FETCH,
        ART_REMOVE,
        CONSOLE_DEFAULT,
        MAX_STATE_TILES,
        NEW_PLAYLIST,
        GameDetailsPage,
        StateTile,
    )


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _DetailsCase(BigPictureCase):
    def setUp(self):
        super().setUp()
        self.game = self.rom("SFC")
        self.cores = [_Core("snes9x_libretro.so", "Snes9x"), _Core("bsnes_libretro.so", "bsnes")]
        catalog = self.win.core_catalog
        for name, value in (
            ("cores_for_console", lambda _console: list(self.cores)),
            ("display_name_for", lambda filename: {c.filename: c.display_name for c in self.cores}.get(filename, filename)),
        ):
            patcher = mock.patch.object(catalog, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The shell's pages for a pick and for typing are other pages' tests;
        # here what matters is what the page asks them for and does with the answer.
        self.choosers = []
        chooser = mock.patch.object(self.shell, "open_chooser", side_effect=self._capture_chooser)
        chooser.start()
        self.addCleanup(chooser.stop)
        self.entries = []
        entry = mock.patch.object(self.shell, "open_text_entry", side_effect=self._capture_entry)
        entry.start()
        self.addCleanup(entry.stop)
        # Covers decode on the calling thread: a worker finishing inside the
        # next test, against a home that is gone, is a crash and not a test.
        submit = mock.patch.object(details_module.cover_cache, "submit", side_effect=lambda fn, *a, **k: fn())
        submit.start()
        self.addCleanup(submit.stop)

    def _capture_chooser(self, title, options, current, on_pick, crumbs=None, lead=None):
        self.choosers.append(
            {"title": title, "options": options, "current": current, "on_pick": on_pick,
             "crumbs": crumbs, "lead": lead}
        )

    def _capture_entry(self, title, initial, on_done, **kwargs):
        self.entries.append({"title": title, "initial": initial, "on_done": on_done, **kwargs})

    def open(self, rom=None):
        page = self.shell.open_details(rom or self.game)
        self.pump()
        return page

    def ids(self):
        return [option["id"] for option in self.choosers[-1]["options"]]

    def pick(self, option_id):
        self.choosers[-1]["on_pick"](option_id)
        self.pump()

    def state(self, slot, thumbnail=False, rom=None):
        rom = rom or self.game
        states_dir = self.config.get_console_states_dir(rom["console"])
        states_dir.mkdir(parents=True, exist_ok=True)
        stem = save_states.rom_state_stem(rom["path"])
        suffix = f".state{slot}" if slot else ".state"
        (states_dir / f"{stem}{suffix}").write_bytes(b"state")
        if thumbnail:
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
            pixbuf.savev(str(states_dir / f"{stem}{suffix}.png"), "png", [], [])
        return states_dir / f"{stem}{suffix}"

    def cover(self, rom):
        covers = self.home.console_dir(rom["console"]) / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
        path = covers / f"{rom['name']}.png"
        pixbuf.savev(str(path), "png", [], [])
        return path


@needs_display
class ThePage(_DetailsCase):
    def test_one_page_shows_the_games_facts_and_is_reused(self):
        page = self.open()
        self.assertIsInstance(page, GameDetailsPage)
        self.assertIs(self.visible_page(), page)
        self.assertEqual(page.get_tag(), "bp-details")
        self.assertEqual(page.title_label.get_label(), self.game["name"])
        meta = page.meta_label.get_label()
        self.assertIn(self.win.sidebar.label_for("SFC"), meta)
        self.assertIn(self.said("details.never_played"), meta)
        self.assertNotIn(self.said("big_picture.details.favorite_mark"), meta)
        self.assertEqual(page.path_note.get_label(), self.game["path"])
        self.assertEqual(page.play_row.title_label.get_label(), self.said("details.play"))
        self.assertFalse(page.fresh_row.get_visible())
        self.assertFalse(page.states_box.get_visible())
        # Played: the caption takes the place of "never played".
        other = self.rom("FC")
        self.win.play_history.record_launch(other["path"])
        self.win.play_history.record_play_time(other["path"], 600)
        again = self.shell.open_details(other)
        self.pump()
        self.assertIs(again, page)
        self.assertEqual(page.title_label.get_label(), other["name"])
        self.assertIn(self.win.play_caption(other), page.meta_label.get_label())

    def test_play_continue_and_start_fresh_follow_the_automatic_state(self):
        with mock.patch.object(self.win, "has_auto_state", return_value=True):
            page = self.open()
        self.assertEqual(page.play_row.title_label.get_label(), self.said("big_picture.details.continue"))
        self.assertEqual(page.play_row.subtitle_label.get_label(), self.said("card.resume.tooltip"))
        self.assertTrue(page.fresh_row.get_visible())
        self.assertTrue(page.states_box.get_visible())
        self.assertEqual(len(page.state_tiles), 1)
        self.assertIsNone(page.state_tiles[0].slot)
        with mock.patch.object(self.win, "on_launch_game") as launch:
            page.play_row.emit("clicked")
            page.state_tiles[0].emit("clicked")
        self.assertEqual(launch.call_count, 2)
        launch.assert_called_with(self.game)
        with mock.patch.object(self.win.game, "launch") as launch:
            page.fresh_row.emit("clicked")
        launch.assert_called_once_with(self.game, resume=False)

    def test_the_cover_loads_in_the_background_or_a_placeholder_stands_in(self):
        page = self.open(self.rom("FC"))
        self.assertTrue(page.cover.placeholder.get_visible())
        self.assertFalse(page.cover.picture.get_visible())
        self.assertIsNone(page.cover.picture.get_paintable())
        self.cover(self.game)
        page.load(self.game)
        self.pump()
        self.assertTrue(page.cover.picture.get_visible())
        self.assertIsNotNone(page.cover.picture.get_paintable())
        self.assertFalse(page.cover.placeholder.get_visible())
        # A load the shoulders have already moved past changes nothing.
        page._apply_cover(page._cover_job - 1, None)
        self.assertTrue(page.cover.picture.get_visible())

    def test_save_states_become_tiles_and_a_chooser(self):
        for slot, thumbnail in ((0, False), (3, True), (5, False), (7, False)):
            self.state(slot, thumbnail=thumbnail)
        page = self.open()
        self.assertEqual([tile.slot for tile in page.state_tiles], [0, 3, 5])
        self.assertEqual(len(page.state_tiles), MAX_STATE_TILES)
        self.assertTrue(page.state_row.get_sensitive())
        self.assertEqual(page.state_row.value_label.get_label(), self.said("big_picture.details.states_count", count=4))
        with mock.patch.object(self.win, "launch_rom_at_state") as launch:
            page.state_tiles[1].emit("clicked")
        launch.assert_called_once_with(self.game, 3)
        page.state_row.emit("clicked")
        self.assertEqual(self.ids(), ["0", "3", "5", "7"])
        self.assertEqual(self.choosers[-1]["options"][1]["label"], self.said("details.states.slot", slot=3))
        self.assertTrue(self.choosers[-1]["options"][1]["subtitle"])
        with mock.patch.object(self.win, "launch_rom_at_state") as launch:
            self.pick("7")
        launch.assert_called_once_with(self.game, 7)
        # Nothing saved: the row says so and opens nothing.
        page.load(self.rom("FC"))
        self.pump()
        self.assertFalse(page.state_row.get_sensitive())
        self.assertEqual(page.state_row.value_label.get_label(), self.said("details.states.empty"))
        page._open_state_chooser()
        self.assertEqual(len(self.choosers), 1)

    def test_a_tile_screenshot_that_will_not_decode_is_an_icon(self):
        path = self.state(2)
        broken = path.with_name(path.name + ".png")
        broken.write_bytes(b"not a png")
        tile = StateTile("Slot 2", "today", thumbnail=broken)
        self.assertEqual(tile.badge.get_icon_name(), "media-floppy-symbolic")
        good = self.state(3, thumbnail=True)
        tile = StateTile("Slot 3", None, thumbnail=good.with_name(good.name + ".png"), size=40)
        self.assertIsNone(tile.badge.get_icon_name())
        self.assertIsNotNone(tile.badge.get_paintable())
        self.assertEqual(tile.badge.get_pixel_size(), 40)
        self.assertFalse(tile.caption.get_visible())
        tile.emit("clicked")  # no handler: nothing happens

    def test_the_favorite_switch_the_pad_and_the_meta_line(self):
        page = self.open()
        self.assertFalse(page.favorite_row.get_active())
        page.favorite_row.emit("clicked")
        self.assertTrue(self.win.playlist_manager.is_favorite(self.game["path"]))
        self.assertTrue(page.favorite_row.get_active())
        self.assertIn(self.said("big_picture.details.favorite_mark"), page.meta_label.get_label())
        self.assertTrue(page.on_pad_action("favorite"))
        self.assertFalse(self.win.playlist_manager.is_favorite(self.game["path"]))
        self.assertFalse(page.favorite_row.get_active())
        self.assertFalse(page.on_pad_action("context"))


@needs_display
class TheSettingsRows(_DetailsCase):
    def test_the_core_chooser_writes_the_per_game_core(self):
        page = self.open()
        self.assertEqual(page.core_row.value_label.get_label(), self.said("details.console_default", value="Snes9x"))
        self.assertFalse(page.core_row.subtitle_label.get_visible())
        page.core_row.emit("clicked")
        self.assertEqual(self.ids(), [CONSOLE_DEFAULT, "snes9x_libretro.so", "bsnes_libretro.so"])
        self.assertEqual(self.choosers[-1]["current"], CONSOLE_DEFAULT)
        self.assertEqual(self.choosers[-1]["crumbs"], [self.game["name"], self.said("context.core")])
        self.pick("bsnes_libretro.so")
        self.assertEqual(self.config.get_rom_core_override(self.game["path"]), "bsnes_libretro.so")
        self.assertEqual(page.core_row.value_label.get_label(), "bsnes")
        self.assertEqual(page.core_row.subtitle_label.get_label(), self.said("details.scope.game"))
        # The current option handed back is not a change.
        with mock.patch.object(self.win, "set_rom_core") as set_core:
            self.pick("bsnes_libretro.so")
        set_core.assert_not_called()
        page.core_row.emit("clicked")
        self.assertEqual(self.choosers[-1]["current"], "bsnes_libretro.so")
        self.pick(CONSOLE_DEFAULT)
        self.assertIsNone(self.config.get_rom_core_override(self.game["path"]))
        # The console's own override is the default the row names; none installed names none.
        self.config.set_console_core_override("SFC", "bsnes_libretro.so")
        page.load(self.game)
        self.assertEqual(page.core_row.value_label.get_label(), self.said("details.console_default", value="bsnes"))
        self.config.set_console_core_override("SFC", None)
        self.cores.clear()
        page.load(self.game)
        self.assertEqual(
            page.core_row.value_label.get_label(),
            self.said("details.console_default", value=self.said("context.core.none")),
        )

    def test_the_shader_chooser_writes_the_per_game_shader(self):
        page = self.open()
        shaders = self.win.shader_catalog
        console_label = shaders.label_for_shader(self.config.get_shader_for_console("SFC"))
        self.assertEqual(page.shader_row.value_label.get_label(), self.said("details.console_default", value=console_label))
        page.shader_row.emit("clicked")
        options = shaders.get_options(show_all=False)
        self.assertEqual(self.ids(), [CONSOLE_DEFAULT] + [shader_id for shader_id, _label in options])
        self.pick(options[0][0])
        self.assertEqual(self.config.get_rom_shader_override(self.game["path"]), options[0][0])
        self.assertEqual(page.shader_row.value_label.get_label(), options[0][1])
        with mock.patch.object(self.win, "set_rom_shader") as set_shader:
            self.pick(options[0][0])
        set_shader.assert_not_called()
        self.pick(CONSOLE_DEFAULT)
        self.assertIsNone(self.config.get_rom_shader_override(self.game["path"]))

    def test_the_color_row_exists_only_where_the_console_has_shells(self):
        with mock.patch.object(details_module.cartridge_render, "frame_colors_for", return_value=["default"]):
            page = self.open()
        self.assertFalse(page.color_row.get_visible())
        with mock.patch.object(
            details_module.cartridge_render, "frame_colors_for", return_value=["default", "black"]
        ), mock.patch.object(details_module.cartridge_colors, "order_color_ids", side_effect=lambda ids: list(ids)):
            page.load(self.game)
            self.assertTrue(page.color_row.get_visible())
            page.color_row.emit("clicked")
            self.assertEqual(self.ids(), [CONSOLE_DEFAULT, "black"])
            self.pick("black")
            self.assertEqual(self.config.get_rom_cartridge_color_override(self.game["path"]), "black")
            self.assertEqual(page.color_row.value_label.get_label(), page._color_label("black"))
            with mock.patch.object(self.win, "set_rom_cartridge_color") as set_color:
                self.pick("black")
            set_color.assert_not_called()
            self.pick(CONSOLE_DEFAULT)
            self.assertIsNone(self.config.get_rom_cartridge_color_override(self.game["path"]))
        self.assertEqual(page._color_label("deep-blue"), "Deep Blue")


@needs_display
class ThePlaylistsArtworkAndFileRows(_DetailsCase):
    def test_the_playlists_chooser_toggles_membership_and_comes_back(self):
        manager = self.win.collection_manager
        slug = manager.create("RPGs")
        page = self.open()
        self.assertEqual(page.playlists_row.value_label.get_label(), "")
        page.playlists_row.emit("clicked")
        self.assertEqual(self.ids(), [slug, NEW_PLAYLIST])
        self.assertEqual(self.choosers[-1]["options"][0]["subtitle"], self.said("big_picture.details.playlist.out"))
        self.pick(slug)
        self.assertTrue(manager.contains(slug, self.game["path"]))
        self.assertEqual(page.playlists_row.value_label.get_label(), "RPGs")
        # Back in the chooser, the mark redrawn, for the next playlist.
        self.assertEqual(len(self.choosers), 2)
        self.assertEqual(self.choosers[-1]["options"][0]["subtitle"], self.said("big_picture.details.playlist.in"))
        self.pick(slug)
        self.assertFalse(manager.contains(slug, self.game["path"]))
        self.assertEqual(page.playlists_row.value_label.get_label(), "")
        # A new playlist: the window's prompt, then the game goes in.
        with mock.patch.object(self.win, "_prompt_new_collection") as prompt:
            self.pick(NEW_PLAYLIST)
        on_created = prompt.call_args.kwargs["on_created"]
        other = manager.create("Shmups")
        on_created(other)
        self.assertTrue(manager.contains(other, self.game["path"]))
        self.assertEqual(page.playlists_row.value_label.get_label(), "Shmups")

    def test_the_artwork_chooser_fetches_chooses_and_removes(self):
        page = self.open()
        page.artwork_row.emit("clicked")
        self.assertEqual(self.ids(), [ART_FETCH, ART_CHOOSE])
        # Fetch: one task with both kinds where there is a frame, one without.
        with mock.patch.object(self.win, "_start_artwork_sync") as start, mock.patch.object(
            details_module.cartridge_render, "has_frame", return_value=True
        ):
            self.pick(ART_FETCH)
        passes = start.call_args.args[0]
        self.assertEqual([kind for kind, _library in passes], [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL])
        self.assertEqual(passes[0][1], {"SFC": [self.game]})
        self.assertTrue(start.call_args.kwargs["replace_existing"])
        with mock.patch.object(page, "_load_cover") as reload, mock.patch.object(self.win, "refresh_rom_artwork") as refresh:
            start.call_args.kwargs["on_finished"]()
        reload.assert_called_once()
        refresh.assert_called_once_with(self.game)
        with mock.patch.object(self.win, "_start_artwork_sync") as start, mock.patch.object(
            details_module.cartridge_render, "has_frame", return_value=False
        ):
            self.assertTrue(page._fetch_artwork())
        self.assertEqual(len(start.call_args.args[0]), 1)
        self.win._cover_sync_running = True
        try:
            self.assertFalse(page._fetch_artwork())
        finally:
            self.win._cover_sync_running = False
        self.assertIn(self.said("toast.sync_running"), self.toasts)
        # Choose: the window's picker, with a callback that reloads this page.
        page.artwork_row.emit("clicked")
        with mock.patch.object(self.win, "_choose_cover_for_rom") as choose:
            self.pick(ART_CHOOSE)
        rom, on_done, kind = choose.call_args.args
        self.assertEqual((rom, kind), (self.game, COVER_ART))
        # Another game's artwork changing does not touch this page's cover.
        with mock.patch.object(page, "_load_cover") as reload:
            page._on_artwork_changed(self.rom("FC"))
        reload.assert_not_called()
        # Remove: offered only with a cover on disk, and asked about first.
        self.cover(self.game)
        page.artwork_row.emit("clicked")
        self.assertEqual(self.ids(), [ART_FETCH, ART_CHOOSE, ART_REMOVE])
        with self.caught_dialog() as caught:
            self.pick(ART_REMOVE)
        self.assertEqual(len(caught), 1)
        self.assertEqual(caught[0].get_heading(), self.said("context.cover.remove"))
        caught[0].emit("response", "cancel")
        self.assertTrue(self.win._has_local_cover(self.game, COVER_ART))
        caught[0].emit("response", "confirm")
        self.pump()
        self.assertFalse(self.win._has_local_cover(self.game, COVER_ART))
        self.assertIn(self.said("toast.cover.removed", name=self.game["name"]), self.toasts)
        self.assertTrue(page.cover.placeholder.get_visible())

    def test_rename_goes_through_the_keyboard_and_follows_the_game(self):
        page = self.open()
        page.rename_row.emit("clicked")
        self.assertEqual(self.entries[-1]["initial"], self.game["name"])
        self.assertEqual(self.entries[-1]["title"], self.said("dialog.rename.heading"))
        self.entries[-1]["on_done"]("Chrono Trigger DX")
        self.pump()
        self.assertEqual(page.rom["name"], "Chrono Trigger DX")
        self.assertEqual(page.title_label.get_label(), "Chrono Trigger DX")
        self.assertTrue(page.rom["path"].endswith("Chrono Trigger DX.sfc"))
        self.assertIs(self.visible_page(), page)
        # A refused name: the window toasts, the page keeps the game.
        page.rename_row.emit("clicked")
        self.entries[-1]["on_done"]("Super Metroid")
        self.assertIn(self.said("toast.rom.rename_failed", error="Super Metroid.sfc already exists"), self.toasts)
        self.assertEqual(page.rom["name"], "Chrono Trigger DX")
        self.assertIs(self.visible_page(), page)
        # The game gone from the playlist altogether: nothing left to show.
        gone = page.rom

        def _vanish(rom, _name):
            self.win.playlist_manager.forget_rom(rom["console"], rom["path"])

        with mock.patch.object(self.win, "_apply_rename", side_effect=_vanish):
            page._apply_rename("whatever")
        self.pump()
        self.assertIsNot(self.visible_page(), page)
        self.assertEqual(page.rom, gone)

    def test_share_delete_focus_and_the_hints(self):
        page = self.open()
        with mock.patch.object(self.win, "share_roms") as share:
            page.share_row.emit("clicked")
        share.assert_called_once_with([self.game])
        with mock.patch.object(self.win, "_confirm_delete_roms") as delete:
            page.delete_row.emit("clicked")
        delete.assert_called_once_with([self.game])
        self.assertTrue(page.delete_row.has_css_class("bp-danger"))
        self.assertTrue(page.play_row.has_css_class("bp-primary"))
        glyphs = self.win.navigation.glyphs()
        hints = page.hints(glyphs, self.win.t)
        self.assertEqual([label for _glyph, label in hints], [
            self.said("big_picture.hints.choose"), self.said("hints.back"),
            self.said("hints.favorite"), self.said("big_picture.details.prev_next"),
        ])
        self.show()
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.play_row)

    def test_the_first_showing_lands_on_continue_and_a_return_does_not(self):
        self.state(0)
        page = self.open()
        self.show()
        # A fresh load, then what the navigation view does at the end of
        # the push: the page's first focusable widget is a tile, and the
        # page takes the focus back to "Continue".
        page.load(self.game)
        page.state_tiles[0].grab_focus()
        self.assertIs(self.focus_widget(), page.state_tiles[0])
        page.emit("shown")
        self.pump()
        self.assertIs(self.focus_widget(), page.play_row)
        # Back from a chooser: the row that was left is the row that is found.
        page.core_row.grab_focus()
        page.emit("shown")
        self.pump()
        self.assertIs(self.focus_widget(), page.core_row)
        # The shoulders load in place; the focus stays where it is then too.
        self.shell.open_library("SFC")
        self.pump()
        self.shell.open_details(self.game)
        self.pump()
        self.assertTrue(page.step_section(1))
        page.core_row.grab_focus()
        page.emit("shown")
        self.pump()
        self.assertIs(self.focus_widget(), page.core_row)


@needs_display
class TheShoulders(_DetailsCase):
    def test_the_shoulders_walk_the_games_of_the_page(self):
        self.shell.open_library("SFC")
        self.pump()
        grid = self.win.pages.grid_for("SFC")
        roms = [entry.rom for entry in grid.visible_entries()]
        self.assertEqual(len(roms), 2)
        page = self.open(roms[0])
        self.assertTrue(self.shell.step_console(1))
        self.assertEqual(page.rom["path"], roms[1]["path"])
        self.assertTrue(page.step_section(1))
        self.assertEqual(page.rom["path"], roms[0]["path"])
        self.assertTrue(page.step_section(-1))
        self.assertEqual(page.rom["path"], roms[1]["path"])
        # A game that is not on the page, a page of one, no page at all.
        page.load(self.rom("FC"))
        self.assertFalse(page.step_section(1))
        self.win.sidebar.select("FC")
        self.pump()
        self.assertFalse(page.step_section(1))
        with mock.patch.object(self.win, "_visible_grid", return_value=None):
            self.assertFalse(page.step_section(1))
        page.rom = None
        self.assertFalse(page.step_section(1))


if __name__ == "__main__":
    unittest.main()

"""The registry behind the content stack's pages (issue #237).

Four dictionaries keyed by the same scope id -- the page, its grid, whether it
has been loaded, and the signature of what it was last built from -- used to be
updated from a dozen places in `OpenEmuxWindow`. One of them forgot the grid
when deleting a collection, so an orphaned grid went on receiving artwork
refreshes for a page nobody could reach.

Only the registry is tested here: rendering needs a display and a real window.
That is the half where the bug lived.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from openemux.core.library_view import VIEW_MODE_LIST
    from openemux.ui.scopes import (
        ALL_CONSOLES_ID,
        FAVORITES_ID,
        collection_scope,
    )


class FakeStack:
    def __init__(self):
        self.children = []

    def add_titled(self, page, name, title):
        self.children.append((name, title, page))


class FakeSidebar:
    def label_for(self, scope):
        return f"label:{scope}"


class FakeWindow:
    def __init__(self):
        self.content_stack = FakeStack()
        self.sidebar = FakeSidebar()
        self.current_console = None

    def t(self, key, **kwargs):
        return key


def _pages():
    from openemux.ui.library_pages import LibraryPages

    win = FakeWindow()
    return LibraryPages(win), win


@needs_display
class TheRegistryMovesAsOneTests(unittest.TestCase):
    def setUp(self):
        self.pages, self.win = _pages()

    def test_a_new_page_is_registered_unloaded_and_put_in_the_stack(self):
        page = self.pages.add("SFC", "Super Nintendo")
        self.assertTrue(self.pages.has("SFC"))
        self.assertIs(self.pages.page_for("SFC"), page)
        self.assertFalse(self.pages.is_loaded("SFC"))
        self.assertEqual(
            self.win.content_stack.children, [("SFC", "Super Nintendo", page)]
        )

    def test_forgetting_a_scope_drops_its_grid_too(self):
        # The collection-delete bug: three dictionaries were popped and
        # _grids was not, so the orphaned grid kept receiving artwork
        # refreshes for a page that had left the stack.
        page = self.pages.add("col:best", "Best")
        self.pages._grids["col:best"] = object()
        self.pages.mark_loaded("col:best")

        self.assertIs(self.pages.forget("col:best"), page)
        self.assertFalse(self.pages.has("col:best"))
        self.assertIsNone(self.pages.grid_for("col:best"))
        self.assertFalse(self.pages.is_loaded("col:best"))
        self.assertEqual(self.pages.grids(), [])

    def test_forgetting_a_scope_that_was_never_added_is_harmless(self):
        self.assertIsNone(self.pages.forget("nope"))

    def test_a_deleted_collections_grid_is_not_refreshed_any_more(self):
        # grids() is what the artwork refreshes walk.
        self.pages.add("SFC", "Super Nintendo")
        self.pages.add("col:best", "Best")
        keep, orphan = object(), object()
        self.pages._grids["SFC"] = keep
        self.pages._grids["col:best"] = orphan

        self.pages.forget("col:best")
        self.assertEqual(self.pages.grids(), [keep])

    def test_reset_empties_everything(self):
        self.pages.add("SFC", "Super Nintendo")
        self.pages._grids["SFC"] = object()
        self.pages.reset()
        self.assertFalse(self.pages.any_page())
        self.assertEqual(self.pages.grids(), [])
        self.assertIsNone(self.pages.page_for("SFC"))

    def test_invalidating_contents_keeps_the_pages(self):
        # A rescan that finds the same consoles has the right pages already;
        # only what is on them may have moved.
        page = self.pages.add("SFC", "Super Nintendo")
        self.pages.mark_loaded("SFC")
        self.pages.invalidate_contents()
        self.assertIs(self.pages.page_for("SFC"), page)
        self.assertFalse(self.pages.is_loaded("SFC"))

    def test_an_unknown_scope_has_no_page_and_no_grid(self):
        self.assertFalse(self.pages.has("GBA"))
        self.assertIsNone(self.pages.page_for("GBA"))
        self.assertIsNone(self.pages.grid_for("GBA"))
        self.assertFalse(self.pages.is_loaded("GBA"))


@needs_display
class CollectionPagesTests(unittest.TestCase):
    def setUp(self):
        self.pages, self.win = _pages()

    def test_a_collection_page_is_titled_from_the_sidebar_label(self):
        self.pages.ensure_collection_page("best")
        name, title, _page = self.win.content_stack.children[0]
        self.assertEqual(name, "col:best")
        self.assertEqual(title, "label:col:best")

    def test_asking_twice_adds_it_once(self):
        self.pages.ensure_collection_page("best")
        self.pages.ensure_collection_page("best")
        self.assertEqual(len(self.win.content_stack.children), 1)


if __name__ == "__main__":
    unittest.main()


@needs_display
class TheMasterCheckboxTests(WindowCase):
    """The list layout's "select everything visible" box (issue #78)."""

    library = {"SFC": [f"Game {index}.sfc" for index in range(4)]}

    def setUp(self):
        super().setUp()
        self.win._apply_view_mode(VIEW_MODE_LIST)
        self.win.sidebar.select("SFC")
        self.show()
        self.pages = self.win.pages
        self.page = self.pages.page_for("SFC")
        self.grid = self.pages.grid_for("SFC")
        if not hasattr(self.page, "master_check"):
            self.skipTest("this page is not drawn as a list")

    def test_ticking_it_selects_every_visible_rom(self):
        self.page.master_check.set_active(True)
        self.assertEqual(len(self.grid.selected_roms()), len(self.grid.entries()))

    def test_unticking_it_clears_the_selection(self):
        self.page.master_check.set_active(True)
        self.page.master_check.set_active(False)
        self.assertEqual(self.grid.selected_roms(), [])

    def test_the_guard_stops_it_re_entering_its_own_handler(self):
        self.page.master_guard[0] = True
        self.pages._on_master_check_toggled(self.page)
        self.page.master_guard[0] = False
        self.assertEqual(self.grid.selected_roms(), [])

    def test_a_page_with_no_grid_is_left_alone(self):
        self.win.current_console = "not-a-page"
        self.pages._on_master_check_toggled(self.page)

    def test_selecting_some_of_them_leaves_the_box_indeterminate(self):
        self.grid.select_item(self.grid.entries()[0])
        self.pages.update_master_check()
        self.assertTrue(self.page.master_check.get_inconsistent())

    def test_selecting_all_of_them_ticks_it(self):
        self.grid.select_all()
        self.pages.update_master_check()
        self.assertTrue(self.page.master_check.get_active())
        self.assertFalse(self.page.master_check.get_inconsistent())

    def test_selecting_none_of_them_unticks_it(self):
        self.grid.clear_selection()
        self.pages.update_master_check()
        self.assertFalse(self.page.master_check.get_active())

    def test_a_scope_with_no_page_at_all_is_left_alone(self):
        self.win.current_console = "not-a-page"
        self.pages.update_master_check()


@needs_display
class LoadingAPageTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.pages = self.win.pages

    def test_a_console_page_that_does_not_exist_loads_nothing(self):
        with mock.patch.object(self.pages, "render") as render:
            self.pages.ensure_loaded("N64")
        render.assert_not_called()

    def test_the_all_page_is_reached_through_the_same_call(self):
        with mock.patch.object(self.pages, "ensure_all_loaded") as load:
            self.pages.ensure_loaded(ALL_CONSOLES_ID)
        load.assert_called_once_with(force_rescan=False)

    def test_the_favorites_page_is_reached_through_it_too(self):
        with mock.patch.object(self.pages, "ensure_favorites_loaded") as load:
            self.pages.ensure_loaded(FAVORITES_ID)
        load.assert_called_once()

    def test_a_collection_page_is_reached_by_its_scope(self):
        slug = self.win.collection_manager.create("RPGs")
        with mock.patch.object(self.pages, "ensure_collection_loaded") as load:
            self.pages.ensure_loaded(collection_scope(slug))
        load.assert_called_once_with(slug)

    def test_a_collection_page_is_rendered_from_its_own_entries(self):
        slug = self.win.collection_manager.create("RPGs")
        rom = self.win.playlist_manager.load_playlist("SFC")[0]
        self.win.collection_manager.add(slug, [rom["path"]])
        self.pages.ensure_collection_loaded(slug)
        scope = collection_scope(slug)
        self.assertTrue(self.pages.is_loaded(scope))
        self.assertEqual(self.pages.grid_for(scope).count(), 1)

    def test_a_collection_page_is_only_added_once(self):
        slug = self.win.collection_manager.create("RPGs")
        self.pages.ensure_collection_page(slug)
        page = self.pages.page_for(collection_scope(slug))
        self.pages.ensure_collection_page(slug)
        self.assertIs(self.pages.page_for(collection_scope(slug)), page)

    def test_a_forced_rescan_rebuilds_the_playlist_and_fetches_the_artwork(self):
        # A playlist built for the first time is exactly when the library has
        # ROMs with no covers.
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            self.pages.ensure_loaded("SFC", force_rescan=True)
        sync.assert_called_once_with(scope="console", selected_console="SFC")

    def test_a_page_visited_again_re_reads_its_playlist(self):
        self.pages.ensure_loaded("SFC")
        self.win._initial_roms.pop("SFC", None)
        with mock.patch.object(
            self.win.playlist_manager, "load_playlist", return_value=[]
        ) as load:
            self.pages.ensure_loaded("SFC")
        load.assert_called_once_with("SFC")

    def test_a_console_with_no_playlist_yet_is_scanned_on_first_open(self):
        self.win._initial_roms.pop("SFC", None)
        self.pages.mark_loaded("SFC", False)
        with mock.patch.object(
            self.win.playlist_manager, "playlist_exists", return_value=False
        ), mock.patch.object(
            self.win.playlist_manager, "scan_and_rebuild_playlist", return_value=[]
        ) as scan:
            self.pages.ensure_loaded("SFC")
        scan.assert_called_once_with("SFC")

    def test_a_user_who_turned_the_first_open_scan_off_gets_an_empty_page(self):
        self.win._initial_roms.pop("SFC", None)
        self.pages.mark_loaded("SFC", False)
        with mock.patch.object(
            self.win.playlist_manager, "playlist_exists", return_value=False
        ), mock.patch.object(
            self.config, "auto_scan_on_first_open", return_value=False
        ), mock.patch.object(
            self.win.playlist_manager, "scan_and_rebuild_playlist"
        ) as scan:
            self.pages.ensure_loaded("SFC")
        scan.assert_not_called()

    def test_a_favorites_page_that_does_not_exist_loads_nothing(self):
        self.pages.forget(FAVORITES_ID)
        with mock.patch.object(self.pages, "render") as render:
            self.pages.ensure_favorites_loaded()
        render.assert_not_called()

    def test_pruning_a_missing_favorite_re_syncs_the_sidebar_row(self):
        # Pruning can empty the list, and an empty list has no row (#382).
        with mock.patch.object(
            self.win.playlist_manager, "remove_missing_favorites", return_value=True
        ), mock.patch.object(self.win.sidebar, "sync_favorites_row") as sync:
            self.pages.ensure_favorites_loaded()
        sync.assert_called_once()

    def test_an_all_page_that_does_not_exist_loads_nothing(self):
        self.pages.forget(ALL_CONSOLES_ID)
        with mock.patch.object(self.pages, "render") as render:
            self.pages.ensure_all_loaded()
        render.assert_not_called()

    def test_the_all_page_re_reads_a_console_it_has_already_shown(self):
        self.pages.ensure_all_loaded()
        self.win._initial_roms.clear()
        with mock.patch.object(
            self.win.playlist_manager, "load_playlist", return_value=[]
        ) as load:
            self.pages.ensure_all_loaded()
        self.assertEqual(load.call_count, len(self.win.visible_consoles))

    def test_a_forced_rescan_of_the_all_page_rebuilds_every_console(self):
        with mock.patch.object(
            self.win.playlist_manager, "scan_and_rebuild_playlist", return_value=[]
        ) as scan:
            self.pages.ensure_all_loaded(force_rescan=True)
        self.assertEqual(scan.call_count, len(self.win.visible_consoles))


@needs_display
class TheEmptyStatesTests(WindowCase):
    def _title_of(self, scope):
        page = self.win.pages._empty_page_for(scope)
        return page.get_title()

    def test_an_empty_favorites_page_says_how_to_star_a_game(self):
        self.assertEqual(self._title_of(FAVORITES_ID), self.said("favorites.empty.title"))

    def test_an_empty_all_page_says_the_library_is_indexed(self):
        self.assertEqual(self._title_of(ALL_CONSOLES_ID), self.said("console.empty.title"))

    def test_an_empty_collection_says_what_a_collection_is_for(self):
        self.assertEqual(
            self._title_of(collection_scope("rpgs")),
            self.said("collections.empty.title"),
        )

    def test_an_empty_console_page_names_the_playlist_it_read(self):
        page = self.win.pages._empty_page_for("SFC")
        self.assertIn("SFC", page.get_description())


@needs_display
class TheGroupHeadingsTests(WindowCase):
    def test_a_group_is_headed_by_its_console_id_and_name(self):
        from openemux.ui.library_pages import LibraryPages

        self.assertTrue(LibraryPages._group_title("SFC").startswith("SFC - "))

    def test_a_group_with_no_console_at_all_is_headed_with_a_question_mark(self):
        from openemux.ui.library_pages import LibraryPages

        self.assertEqual(LibraryPages._group_title(""), "?")

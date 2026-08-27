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

from tests.gtk_display import needs_display


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

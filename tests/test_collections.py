import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.collections import CollectionManager, slugify


class SlugifyTests(unittest.TestCase):
    def test_slugify_makes_filesystem_safe(self):
        self.assertEqual(slugify("Fighting Games!"), "fighting-games")
        self.assertEqual(slugify("  To Finish  "), "to-finish")
        self.assertEqual(slugify("***"), "")


class CollectionManagerTests(unittest.TestCase):
    def _manager(self, tmp_dir, loader=None):
        return CollectionManager(Path(tmp_dir) / "collections", entries_loader=loader)

    def test_create_lists_and_rejects_duplicates(self):
        with TemporaryDirectory() as tmp_dir:
            m = self._manager(tmp_dir)
            m.create("Fighting")
            self.assertEqual([c["name"] for c in m.list_collections()], ["Fighting"])
            with self.assertRaises(ValueError):
                m.create("fighting")  # case-insensitive duplicate
            with self.assertRaises(ValueError):
                m.create("   ")  # empty

    def test_distinct_names_that_slug_the_same_coexist(self):
        with TemporaryDirectory() as tmp_dir:
            m = self._manager(tmp_dir)
            a = m.create("Co-op")
            b = m.create("Co op")
            self.assertNotEqual(a, b)
            self.assertEqual(len(m.list_collections()), 2)

    def test_add_remove_and_contains(self):
        with TemporaryDirectory() as tmp_dir:
            m = self._manager(tmp_dir)
            slug = m.create("Racing")
            self.assertEqual(m.add(slug, ["/g/MD/a.md", "/g/PS/b.cue"]), 2)
            self.assertEqual(m.add(slug, ["/g/MD/a.md"]), 0)  # already there
            self.assertTrue(m.contains(slug, "/g/MD/a.md"))
            self.assertEqual(m.remove(slug, ["/g/MD/a.md"]), 1)
            self.assertFalse(m.contains(slug, "/g/MD/a.md"))

    def test_rename_persists_and_survives_reload(self):
        with TemporaryDirectory() as tmp_dir:
            cdir = Path(tmp_dir) / "collections"
            m = CollectionManager(cdir)
            slug = m.create("Platformers")
            m.add(slug, ["/g/SFC/x.sfc"])
            m.rename(slug, "Platform Games")
            reloaded = CollectionManager(cdir)
            self.assertEqual(reloaded.get_name(slug), "Platform Games")
            # The games survive the rename (same slug/file).
            self.assertTrue(reloaded.contains(slug, "/g/SFC/x.sfc"))

    def test_delete_removes_index_entry_and_file(self):
        with TemporaryDirectory() as tmp_dir:
            m = self._manager(tmp_dir)
            slug = m.create("Kids")
            m.add(slug, ["/g/GBA/x.gba"])
            m.delete(slug)
            self.assertEqual(m.list_collections(), [])
            self.assertFalse((Path(tmp_dir) / "collections" / f"{slug}.list").exists())

    def test_repath_and_forget_across_collections(self):
        with TemporaryDirectory() as tmp_dir:
            m = self._manager(tmp_dir)
            a = m.create("A")
            b = m.create("B")
            m.add(a, ["/g/MD/s.md"])
            m.add(b, ["/g/MD/s.md"])
            m.repath_rom("/g/MD/s.md", "/g/MD/sonic.md")
            self.assertTrue(m.contains(a, "/g/MD/sonic.md"))
            self.assertTrue(m.contains(b, "/g/MD/sonic.md"))
            m.forget_rom("/g/MD/sonic.md")
            self.assertFalse(m.contains(a, "/g/MD/sonic.md"))
            self.assertFalse(m.contains(b, "/g/MD/sonic.md"))

    def test_load_entries_uses_injected_loader(self):
        with TemporaryDirectory() as tmp_dir:
            captured = {}

            def loader(paths):
                captured["paths"] = list(paths)
                return [{"path": p} for p in paths]

            m = self._manager(tmp_dir, loader=loader)
            slug = m.create("Fav")
            m.add(slug, ["/g/MD/a.md"])
            entries = m.load_entries(slug)
            self.assertEqual(captured["paths"], ["/g/MD/a.md"])
            self.assertEqual(entries, [{"path": "/g/MD/a.md"}])


class AnIndexThatCannotBeTrustedTests(unittest.TestCase):
    """The .list files are the data; the index is only the display names."""

    def _manager(self, tmp_dir, loader=None):
        return CollectionManager(Path(tmp_dir) / "collections", entries_loader=loader)

    def test_an_index_that_is_not_a_mapping_is_rebuilt_from_the_lists(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            slug = manager.create("Best of SNES")
            manager.index_path.write_text("- oops\n", encoding="utf-8")

            self.assertEqual(
                [entry["slug"] for entry in manager.list_collections()], [slug]
            )

    def test_a_directory_that_cannot_be_listed_rebuilds_to_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.create("Best of SNES")
            manager.index_path.write_text("- oops\n", encoding="utf-8")
            with mock.patch.object(
                Path, "glob", side_effect=OSError("permission denied")
            ):
                self.assertEqual(manager.list_collections(), [])

    def test_entries_that_are_not_collections_are_skipped(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.collections_dir.mkdir(parents=True, exist_ok=True)
            manager.index_path.write_text(
                "collections:\n"
                "  - just a string\n"
                "  - slug: \"\"\n"
                "    name: No slug\n"
                "  - slug: rpgs\n"
                "    name: RPGs\n"
                "  - slug: rpgs\n"
                "    name: RPGs again\n",
                encoding="utf-8",
            )

            self.assertEqual(
                manager.list_collections(), [{"slug": "rpgs", "name": "RPGs"}]
            )


class WhatACollectionAnswersWhenItHasNothingTests(unittest.TestCase):
    def _manager(self, tmp_dir, loader=None):
        return CollectionManager(Path(tmp_dir) / "collections", entries_loader=loader)

    def test_a_collection_with_no_list_file_holds_no_paths(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(self._manager(tmp_dir).paths("never-created"), [])

    def test_without_a_loader_there_are_no_entries_to_show(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            slug = manager.create("RPGs")
            manager.add(slug, ["/g/SFC/a.sfc"])
            self.assertEqual(manager.load_entries(slug), [])


class NamesThatCollideTests(unittest.TestCase):
    def _manager(self, tmp_dir):
        return CollectionManager(Path(tmp_dir) / "collections")

    def test_three_names_that_slugify_alike_all_coexist(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            slugs = [
                manager.create("RPGs"),
                manager.create("RPGs!"),
                manager.create("RPGs?"),
            ]
            self.assertEqual(slugs, ["rpgs", "rpgs-2", "rpgs-3"])

    def test_renaming_onto_another_collections_name_is_refused(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.create("RPGs")
            other = manager.create("Shooters")
            with self.assertRaises(ValueError):
                manager.rename(other, "rpgs")

    def test_renaming_a_collection_that_is_not_there_is_refused(self):
        with TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                self._manager(tmp_dir).rename("never-created", "RPGs")

    def test_a_rename_of_a_game_no_collection_holds_changes_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            slug = manager.create("RPGs")
            manager.add(slug, ["/g/SFC/a.sfc"])
            manager.repath_rom("/g/SFC/b.sfc", "/g/SFC/c.sfc")
            self.assertEqual(manager.paths(slug), ["/g/SFC/a.sfc"])


if __name__ == "__main__":
    unittest.main()

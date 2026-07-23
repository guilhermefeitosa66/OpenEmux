import unittest
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
            slug = m.create("Fighting")
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


if __name__ == "__main__":
    unittest.main()

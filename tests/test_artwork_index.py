import sqlite3
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.artwork_index import (
    ArtworkNameIndex,
    _numeral_swapped,
    _strip_tag_groups,
    _subtitle_head,
)

SNES = "Nintendo - Super Nintendo Entertainment System"
MD = "Sega - Mega Drive - Genesis"


def _build_db(path, rows, crc_rows=None):
    """A fixture database with the shipped games.db schema (#188)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL, system TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE games_fts USING fts5("
        "name, system, content='games', content_rowid='id')"
    )
    for name, system in rows:
        cursor = conn.execute(
            "INSERT INTO games (name, system) VALUES (?, ?)", (name, system)
        )
        conn.execute(
            "INSERT INTO games_fts (rowid, name, system) VALUES (?, ?, ?)",
            (cursor.lastrowid, name, system),
        )
    if crc_rows is not None:
        conn.execute(
            "CREATE TABLE crc_index (crc32 TEXT NOT NULL, system TEXT NOT NULL,"
            " name TEXT NOT NULL, PRIMARY KEY (crc32, system))"
        )
        conn.executemany(
            "INSERT INTO crc_index (crc32, system, name) VALUES (?, ?, ?)", crc_rows
        )
    conn.commit()
    conn.close()


_LADDER_ROWS = [
    ("Adventures of Batman _ Robin, The (USA)", SNES),
    ("Adventures of Batman _ Robin, The (Europe)", SNES),
    ("Adventures of Batman _ Robin, The (USA)", MD),
    ("Final Fantasy II (USA)", SNES),
    ("Final Fantasy II (USA) (Rev 1)", SNES),
    ("Final Fantasy III (USA)", SNES),
    ("Maui Mallard in Cold Shadow (USA)", SNES),
    ("Donald Duck no Maui Mallard (Japan)", SNES),
    ("Donald Duck no Mahou no Boushi (Japan)", SNES),
    ("Chrono Trigger (USA)", SNES),
    ("Chrono Trigger (Japan)", SNES),
]


class HelperTests(unittest.TestCase):
    def test_tag_groups_are_stripped(self):
        self.assertEqual(
            _strip_tag_groups("Final Fantasy 2 (V1.1) (U) [!]"), "Final Fantasy 2"
        )

    def test_numeral_swap_goes_both_ways(self):
        self.assertEqual(_numeral_swapped(["final", "fantasy", "2"]),
                         ["final", "fantasy", "ii"])
        self.assertEqual(_numeral_swapped(["final", "fantasy", "iv"]),
                         ["final", "fantasy", "4"])
        self.assertIsNone(_numeral_swapped(["chrono", "trigger"]))

    def test_subtitle_head_drops_the_subtitle_and_version_tail(self):
        self.assertEqual(
            _subtitle_head("Donald Duck - Maui Mallard in Cold Shadow (E) [!]"),
            "Donald Duck",
        )
        self.assertEqual(_subtitle_head("Mega Man 7"), "Mega Man")


class ResolutionLadderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "games.db"
        _build_db(self.db_path, _LADDER_ROWS)
        self.index = ArtworkNameIndex(db_path=self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sanitized_special_characters_resolve(self):
        # The reported bug (#175): "&" in the display title, "_" in the stem.
        resolved = self.index.resolve_name(
            SNES, "Adventures of Batman & Robin, The (USA)"
        )
        self.assertIsNotNone(resolved)
        stem, _round = resolved
        self.assertEqual(stem, "Adventures of Batman _ Robin, The (USA)")

    def test_numeral_swap_resolves_arabic_to_roman(self):
        resolved = self.index.resolve_name(SNES, "Final Fantasy 2 (V1.1) (U)")
        self.assertIsNotNone(resolved)
        stem, round_label = resolved
        self.assertEqual(stem, "Final Fantasy II (USA)")
        self.assertEqual(round_label, "untagged")

    def test_broad_round_resolves_the_subtitle_case(self):
        # Both POCs needed a manual second query here; the OR round with the
        # strict coverage winner automates it.
        resolved = self.index.resolve_name(
            SNES, "Donald Duck - Maui Mallard in Cold Shadow (E) [!]"
        )
        self.assertIsNotNone(resolved)
        stem, round_label = resolved
        self.assertEqual(stem, "Maui Mallard in Cold Shadow (USA)")
        self.assertEqual(round_label, "broad")

    def test_ambiguity_is_never_guessed(self):
        # "Final Fantasy" alone matches II and III equally: no answer.
        self.assertIsNone(self.index.resolve_name(SNES, "Final Fantasy"))

    def test_region_priority_picks_the_stem(self):
        resolved = self.index.resolve_name(
            SNES, "Chrono Trigger", region_priority=("Japan", "USA")
        )
        self.assertEqual(resolved[0], "Chrono Trigger (Japan)")
        resolved = self.index.resolve_name(SNES, "Chrono Trigger")
        self.assertEqual(resolved[0], "Chrono Trigger (USA)")

    def test_resolution_is_scoped_to_the_system(self):
        resolved = self.index.resolve_name(MD, "Adventures of Batman & Robin, The")
        self.assertEqual(resolved[0], "Adventures of Batman _ Robin, The (USA)")
        self.assertIsNone(self.index.resolve_name(MD, "Chrono Trigger"))

    def test_plain_release_beats_revision_variants(self):
        resolved = self.index.resolve_name(SNES, "Final Fantasy II")
        self.assertEqual(resolved[0], "Final Fantasy II (USA)")


class CrcResolutionTests(unittest.TestCase):
    def test_crc_hit_and_miss(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "games.db"
            _build_db(
                db_path,
                [("Chrono Trigger (USA)", SNES)],
                crc_rows=[("2D206BF7", SNES, "Chrono Trigger (USA)")],
            )
            index = ArtworkNameIndex(db_path=db_path)
            self.assertTrue(index.has_crc_index())
            self.assertEqual(
                index.resolve_by_crc(SNES, "2d206bf7"), "Chrono Trigger (USA)"
            )
            self.assertIsNone(index.resolve_by_crc(SNES, "00000000"))
            self.assertIsNone(index.resolve_by_crc(MD, "2D206BF7"))

    def test_a_database_without_the_table_reports_no_crc_support(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "games.db"
            _build_db(db_path, [("Chrono Trigger (USA)", SNES)])
            index = ArtworkNameIndex(db_path=db_path)
            self.assertFalse(index.has_crc_index())
            self.assertIsNone(index.resolve_by_crc(SNES, "2D206BF7"))


class DegradationTests(unittest.TestCase):
    def test_a_missing_database_is_silent(self):
        index = ArtworkNameIndex(db_path="/nonexistent/dir/games.db")
        self.assertFalse(index.available)
        self.assertIsNone(index.resolve_name(SNES, "Chrono Trigger"))
        self.assertIsNone(index.resolve_by_crc(SNES, "AABBCCDD"))
        self.assertFalse(index.has_crc_index())

    def test_a_corrupt_database_is_silent(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "games.db"
            db_path.write_bytes(b"this is not sqlite at all")
            index = ArtworkNameIndex(db_path=db_path)
            self.assertIsNone(index.resolve_name(SNES, "Chrono Trigger"))
            self.assertFalse(index.available)

    def test_a_database_without_fts_still_serves_crc(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "games.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, system TEXT)"
            )
            conn.execute(
                "CREATE TABLE crc_index (crc32 TEXT, system TEXT, name TEXT)"
            )
            conn.execute(
                "INSERT INTO crc_index VALUES ('AABBCCDD', ?, 'Chrono Trigger (USA)')",
                (SNES,),
            )
            conn.commit()
            conn.close()
            index = ArtworkNameIndex(db_path=db_path)
            # Name resolution degrades (no FTS table), the hash path works.
            self.assertIsNone(index.resolve_name(SNES, "Chrono Trigger"))
            self.assertEqual(
                index.resolve_by_crc(SNES, "AABBCCDD"), "Chrono Trigger (USA)"
            )


class ShippedZipTests(unittest.TestCase):
    def test_the_database_is_extracted_from_the_shipped_zip_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            (root / "tools").mkdir(parents=True)
            inner = Path(tmp) / "games.db"
            _build_db(inner, [("Chrono Trigger (USA)", SNES)])
            with zipfile.ZipFile(root / "tools" / "games.db.zip", "w") as archive:
                archive.write(inner, "games.db")

            db_path = Path(tmp) / "cache" / "games.db"
            index = ArtworkNameIndex(db_path=db_path, project_root=root)
            resolved = index.resolve_name(SNES, "Chrono Trigger (USA)")
            self.assertEqual(resolved[0], "Chrono Trigger (USA)")
            self.assertTrue(db_path.exists())

    def test_no_zip_and_no_database_degrades_silently(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            index = ArtworkNameIndex(
                db_path=Path(tmp) / "cache" / "games.db", project_root=root
            )
            self.assertFalse(index.available)
            self.assertIsNone(index.resolve_name(SNES, "Chrono Trigger"))


if __name__ == "__main__":
    unittest.main()

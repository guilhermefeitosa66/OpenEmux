"""The name-database generator (issue #184): tools/generate_name_db.py.

Loaded by file path -- tools/ is not a package -- and exercised against a
miniature fake mirror, so the pipeline stays testable without the real
60k-file checkout.
"""

import importlib.util
import sqlite3
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

_TOOL = Path(__file__).parent.parent / "tools" / "generate_name_db.py"
_spec = importlib.util.spec_from_file_location("generate_name_db", _TOOL)
generate_name_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_name_db)

SNES_DIR = "Nintendo_-_Super_Nintendo_Entertainment_System"
SNES = "Nintendo - Super Nintendo Entertainment System"

_DAT = """<?xml version="1.0"?>
<datafile>
  <game name="Adventures of Batman &amp; Robin, The (USA)">
    <rom name="rom.sfc" crc="aabbccdd"/>
  </game>
  <game name="Not In The Mirror (USA)">
    <rom name="other.sfc" crc="11223344"/>
  </game>
</datafile>
"""


def _make_mirror(root):
    system = Path(root) / SNES_DIR
    system.mkdir(parents=True)
    (system / "Chrono Trigger (USA).webp").write_bytes(b"w")
    (system / "Adventures of Batman _ Robin, The (USA).webp").write_bytes(b"w")
    # The mirror's own tooling folder must not become a "system".
    scripts = Path(root) / "scripts"
    scripts.mkdir()
    (scripts / "sync.py").write_text("pass")


class GeneratorTests(unittest.TestCase):
    def test_rows_come_from_the_mirror_files(self):
        with TemporaryDirectory() as tmp:
            _make_mirror(tmp)
            rows = generate_name_db.collect_rows(tmp)
        self.assertEqual(
            rows,
            [
                ("Adventures of Batman _ Robin, The (USA)", SNES),
                ("Chrono Trigger (USA)", SNES),
            ],
        )

    def test_generated_database_matches_the_shipped_schema(self):
        with TemporaryDirectory() as tmp:
            _make_mirror(tmp)
            out = Path(tmp) / "games.db.zip"
            generate_name_db.generate(tmp, out)
            with zipfile.ZipFile(out) as archive:
                archive.extract("games.db", Path(tmp) / "x")
            conn = sqlite3.connect(Path(tmp) / "x" / "games.db")
            names = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master").fetchall()
            }
            self.assertIn("games", names)
            self.assertIn("games_fts", names)
            self.assertNotIn("crc_index", names)
            hit = conn.execute(
                "SELECT g.name FROM games_fts f JOIN games g ON g.id = f.rowid "
                "WHERE games_fts MATCH '\"batman\" \"robin\"'"
            ).fetchall()
            conn.close()
        self.assertEqual(hit, [("Adventures of Batman _ Robin, The (USA)",)])

    def test_dats_add_only_crc_rows_with_artwork(self):
        with TemporaryDirectory() as tmp:
            _make_mirror(tmp)
            dats = Path(tmp) / "dats"
            dats.mkdir()
            (dats / f"{SNES}.dat").write_text(_DAT)
            (dats / "Unknown System.dat").write_text(_DAT)
            out = Path(tmp) / "games.db.zip"
            generate_name_db.generate(tmp, out, dats=dats)
            with zipfile.ZipFile(out) as archive:
                archive.extract("games.db", Path(tmp) / "x")
            conn = sqlite3.connect(Path(tmp) / "x" / "games.db")
            crc_rows = conn.execute(
                "SELECT crc32, system, name FROM crc_index"
            ).fetchall()
            conn.close()
        # The sanitized DAT name with artwork is kept, uppercased CRC; the
        # game absent from the mirror is dropped.
        self.assertEqual(
            crc_rows,
            [("AABBCCDD", SNES, "Adventures of Batman _ Robin, The (USA)")],
        )

    def test_an_empty_mirror_refuses_to_generate(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                generate_name_db.generate(tmp, Path(tmp) / "out.zip")


if __name__ == "__main__":
    unittest.main()

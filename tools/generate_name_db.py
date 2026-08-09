#!/usr/bin/env python3
"""Generate the game-name database from the artwork mirror (issue #184).

Rebuilds ``games.db`` -- the SQLite + FTS5 name base the staged cover
lookup (#175) and the manual cover picker (#185) consume -- from a local
checkout of ``openemux-artwork``. The mirror is the source of truth on
purpose: every row then corresponds to an artwork file that actually
exists, the stems already carry the libretro filename convention, and a
regeneration needs nothing beyond ``git pull`` in the mirror.

Optionally, a directory of No-Intro/Redump DAT files (logiqx XML, one per
system, named ``<Thumbnail System Name>.dat``) adds the ``crc_index``
table: stage 1 of the lookup ladder resolves a renamed ROM by CRC32
through it. Only entries whose sanitized name has artwork in the mirror
are kept.

Usage:
    python3 tools/generate_name_db.py --mirror ../openemux-artwork \\
        [--dats <dir>] [--output src/openemux/data/games.db.zip]

Standalone by design -- no imports from the app -- so it runs against a
bare checkout with any Python 3.8+.
"""

import argparse
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

DEFAULT_OUTPUT = Path("src") / "openemux" / "data" / "games.db.zip"

# Mirror layout: <System_Name_With_Underscores>/<stem>.webp
ART_SUFFIX = ".webp"

# The libretro thumbnail filename convention (kept in sync with
# cover_sync._sanitize_thumbnail_name): these characters become "_".
_SANITIZE = str.maketrans({ch: "_" for ch in '&*/:`<>?\\|"'})


def sanitize_stem(name):
    return name.translate(_SANITIZE)


def system_name_from_dir(dirname):
    """``Nintendo_-_Super_Nintendo_Entertainment_System`` -> the real name."""
    return dirname.replace("_", " ")


def collect_rows(mirror_root):
    """Sorted ``(name, system)`` rows for every artwork file in the mirror."""
    mirror_root = Path(mirror_root)
    rows = []
    for system_dir in sorted(p for p in mirror_root.iterdir() if p.is_dir()):
        if system_dir.name.startswith("."):
            continue
        system = system_name_from_dir(system_dir.name)
        stems = sorted(
            f.name[: -len(ART_SUFFIX)]
            for f in system_dir.iterdir()
            if f.is_file() and f.name.endswith(ART_SUFFIX)
        )
        rows.extend((stem, system) for stem in stems)
    return rows


def collect_crc_rows(dats_dir, stems_by_system):
    """``(crc32, system, name)`` rows from logiqx DAT files.

    Only games whose sanitized name has artwork in the mirror are kept,
    so the CRC table can never point at a stem that would 404.
    """
    crc_rows = []
    skipped_files = []
    for dat_file in sorted(Path(dats_dir).glob("*.dat")):
        system = dat_file.stem
        known_stems = stems_by_system.get(system)
        if known_stems is None:
            skipped_files.append(dat_file.name)
            continue
        try:
            root = ElementTree.parse(dat_file).getroot()
        except ElementTree.ParseError as exc:
            print(f"warning: unparseable DAT skipped: {dat_file.name}: {exc}",
                  file=sys.stderr)
            continue
        for game in root.iter("game"):
            stem = sanitize_stem(game.get("name") or "")
            if stem not in known_stems:
                continue
            for rom in game.iter("rom"):
                crc = (rom.get("crc") or "").strip().upper()
                if len(crc) == 8:
                    crc_rows.append((crc, system, stem))
    if skipped_files:
        print(
            "warning: DATs skipped (no matching mirror system): "
            + ", ".join(skipped_files),
            file=sys.stderr,
        )
    return crc_rows


def build_database(db_path, rows, crc_rows=None):
    """The shipped schema (#188), plus ``crc_index`` when DATs were given."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                system TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE games_fts USING fts5(
                name,
                system,
                content='games',
                content_rowid='id'
            );
            """
        )
        for name, system in rows:
            cursor = conn.execute(
                "INSERT INTO games (name, system) VALUES (?, ?)", (name, system)
            )
            conn.execute(
                "INSERT INTO games_fts (rowid, name, system) VALUES (?, ?, ?)",
                (cursor.lastrowid, name, system),
            )
        if crc_rows:
            conn.execute(
                "CREATE TABLE crc_index ("
                " crc32 TEXT NOT NULL, system TEXT NOT NULL, name TEXT NOT NULL,"
                " PRIMARY KEY (crc32, system))"
            )
            conn.executemany(
                "INSERT OR REPLACE INTO crc_index (crc32, system, name)"
                " VALUES (?, ?, ?)",
                crc_rows,
            )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def generate(mirror, output, dats=None):
    rows = collect_rows(mirror)
    if not rows:
        raise SystemExit(f"no artwork found under {mirror} -- is it a mirror checkout?")
    crc_rows = None
    if dats:
        stems_by_system = {}
        for stem, system in rows:
            stems_by_system.setdefault(system, set()).add(stem)
        crc_rows = collect_crc_rows(dats, stems_by_system)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "games.db"
        build_database(db_path, rows, crc_rows)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_path, "games.db")
    systems = len({system for _stem, system in rows})
    print(
        f"games.db.zip written: {output} "
        f"({len(rows)} names, {systems} systems"
        + (f", {len(crc_rows)} crc entries" if crc_rows else "")
        + ")"
    )
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mirror",
        default="../openemux-artwork",
        help="local checkout of openemux-artwork (default: ../openemux-artwork)",
    )
    parser.add_argument(
        "--dats",
        default=None,
        help="directory of '<Thumbnail System Name>.dat' logiqx files for crc_index",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"where the zipped database goes (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    generate(args.mirror, args.output, dats=args.dats)


if __name__ == "__main__":
    main()

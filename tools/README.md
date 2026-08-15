# Tools

Developer tooling that is not part of the shipped application code.

## `generate_name_db.py` — the game-name database (issue #184)

Regenerates `src/openemux/data/games.db.zip`: the SQLite + FTS5 game-name
base consumed by the staged cover lookup (issue #175, stage 1 and stage 4)
and the manual cover-picker suggestions (issue #185).

```bash
make name-db                       # uses ../openemux-artwork
make name-db MIRROR=/path/mirror DATS=/path/dats
```

### Source of truth

A local checkout of [`openemux-artwork`](https://github.com/guilhermefeitosa66/openemux-artwork)
— the project's own mirror. Every row in the database corresponds to an
artwork file that actually exists there, the stored stems already carry the
libretro filename convention (`&*/:` etc. replaced with `_`), and a
regeneration needs nothing beyond `git pull` in the mirror — zero load on
libretro's infrastructure. The upstream thumbnail set changes rarely
(once in 2025), so regenerating 1–2× a year after a mirror sync is enough.

The first version of this base was built end-to-end by
[@mozertdev](https://github.com/mozertdev) (#188), who prototyped the whole
pipeline and settled the FTS5 approach; this generator reproduces it from
the mirror.

### Delivery

The zip ships **inside the package tree** (`src/openemux/data/`), so every
packaging path that ships `src/openemux` — AppImage, .deb/.rpm, Flatpak,
source checkout — carries it automatically (~2 MB). The app extracts it on
first use to `~/.openemux/artwork-index/games.db`
(`openemux.core.artwork_index`). This full cross-system shape supersedes
the per-system `index/<System>.db` delivery sketched in #175.

### Optional: CRC index (stage 1)

Passing `DATS=<dir>` — a directory of logiqx-XML DAT files named
`<Thumbnail System Name>.dat` (from
[libretro-database](https://github.com/libretro/libretro-database),
No-Intro/Redump) — adds the `crc_index` table, which lets stage 1 of the
lookup ladder resolve a renamed ROM by CRC32. Only entries whose name has
artwork in the mirror are kept. Without DATs the table is absent and the
app silently skips the hash stage.

## `games.db` schema

```sql
games(id INTEGER PRIMARY KEY, name TEXT, system TEXT)
games_fts    -- FTS5 over (name, system), content='games'
crc_index(crc32 TEXT, system TEXT, name TEXT)   -- optional
```

`name` is the artwork filename stem; `system` the libretro thumbnail
system name (e.g. `Nintendo - Super Nintendo Entertainment System`).

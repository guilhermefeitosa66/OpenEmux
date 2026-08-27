"""Local game-name index for artwork lookups (issues #175 / #184).

The index is the SQLite database mozertdev generated from the artwork
mirror (#188): ``games(id, name, system)`` plus the ``games_fts`` FTS5
table, where ``name`` is the artwork filename stem exactly as the mirror
files it (libretro naming convention, ``&*/:`<>?\\|"`` already replaced
with ``_``) and ``system`` is the libretro thumbnail system name. It ships
zipped as ``tools/games.db.zip`` and is extracted on first use to
``~/.openemux/artwork-index/games.db``.

An optional ``crc_index(crc32, system, name)`` table -- absent from the
current build, emitted by the #184 generator when DAT files are available
-- resolves a ROM by content hash (stage 1 of the #175 ladder).

Name resolution (stage 4 of the ladder) automates the query broadening
both of mozertdev's POCs needed by hand, as a bounded relaxation ladder:

1. ``full``     -- every token of the stem, ANDed;
2. ``untagged`` -- tokens with the ``(...)``/``[...]`` tag groups stripped;
3. ``head``     -- the segment before a ``" - "`` subtitle separator,
                   trailing version/number tokens dropped;
4. ``broad``    -- the untagged tokens ORed, accepted only on a strict
                   token-coverage winner.

AND rounds also try an arabic<->roman numeral swap (``2`` <-> ``ii``): the
index stores no normalized shadow column, so ``Final Fantasy 2`` must
become ``final fantasy ii`` on the query side. An AND round is accepted
only when every row it returns is the same title once tags are stripped --
regional variants of one game are one answer, two different games are
ambiguity, and ambiguity takes the next round instead of guessing.

Everything degrades silently: a missing, corrupt or FTS5-less database
answers ``None``, never raises -- the index must never fail a sync.
"""

import difflib
import logging
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from openemux.core.paths import store_path

logger = logging.getLogger(__name__)

#: Where the extracted database lives, under the user config dir.
INDEX_DIRNAME = "artwork-index"
DB_FILENAME = "games.db"
#: The shipped artifact (#184 delivery shape): inside the package tree, so
#: every packaging path (AppImage, deb/rpm, Flatpak, source checkout) that
#: ships ``src/openemux`` ships the database with it.
DEFAULT_SHIPPED_ZIP = Path(__file__).resolve().parent.parent / "data" / "games.db.zip"

#: Rows fetched per FTS round; the ladder only needs enough to detect
#: ambiguity and pick a region, not the full match list.
_AND_ROUND_LIMIT = 16
_OR_ROUND_LIMIT = 24

#: Region tag preference when one title exists as several regional stems.
DEFAULT_REGION_PRIORITY = ("USA", "World", "Europe", "Japan")

#: Words too weak to distinguish titles; dropped from OR-round queries.
_CONNECTOR_TOKENS = {
    "of", "the", "and", "in", "no", "de", "a", "to", "for", "vs", "or", "on", "at",
}

_ARABIC_TO_ROMAN = {
    "1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi",
    "7": "vii", "8": "viii", "9": "ix", "10": "x", "11": "xi", "12": "xii",
    "13": "xiii", "14": "xiv", "15": "xv", "16": "xvi",
}
_ROMAN_TO_ARABIC = {roman: arabic for arabic, roman in _ARABIC_TO_ROMAN.items()}

_TAG_GROUP_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _strip_tag_groups(name):
    return re.sub(r"\s+", " ", _TAG_GROUP_RE.sub(" ", name)).strip()


def _tokens(text):
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _numeral_swapped(tokens):
    """The token list with arabic and roman numerals exchanged, or ``None``
    when no token is a numeral (no point re-running the same query)."""
    swapped = []
    changed = False
    for token in tokens:
        if token in _ARABIC_TO_ROMAN:
            swapped.append(_ARABIC_TO_ROMAN[token])
            changed = True
        elif token in _ROMAN_TO_ARABIC:
            swapped.append(_ROMAN_TO_ARABIC[token])
            changed = True
        else:
            swapped.append(token)
    return swapped if changed else None


def _subtitle_head(name):
    """The title before a `` - `` subtitle, minus trailing version tokens."""
    head = _strip_tag_groups(name).split(" - ")[0]
    head = re.sub(r"\s+(?:v[\d][\w.]*|\d{1,2})\s*$", "", head, flags=re.IGNORECASE)
    return head.strip()


def _fts_query(tokens, joiner=" "):
    return joiner.join('"%s"' % token.replace('"', '""') for token in tokens)


class ArtworkNameIndex:
    """Read-only access to the local name index. Never raises to callers."""

    def __init__(self, db_path=None, shipped_zip=None):
        if db_path is None:
            db_path = store_path("artwork_index") / DB_FILENAME
        self._db_path = Path(db_path)
        self._shipped_zip = Path(shipped_zip) if shipped_zip else DEFAULT_SHIPPED_ZIP
        #: Latched only for a database that is there and cannot be read: a
        #: corrupt file will not heal, so retrying it once per missed ROM is
        #: pure cost. An extraction that failed -- a full disk during the
        #: first one -- is *not* latched: it may well work on the next
        #: attempt, and latching it lost the index for the rest of the
        #: process over a transient (issue #239).
        self._corrupt = False
        self._fts_ok = None
        self._has_crc_table = None

    # -- plumbing -----------------------------------------------------------
    def _needs_extraction(self):
        """Whether the shipped zip has something the extracted copy has not.

        Not just "is it missing": a release with a regenerated index shipped a
        newer zip, and the extracted database from the previous version stayed
        forever -- CRC lookups and FTS results never improved unless the user
        deleted the file by hand (issue #239).
        """
        if not self._db_path.exists():
            return True
        try:
            return self._shipped_zip.stat().st_mtime > self._db_path.stat().st_mtime
        except OSError:
            # No shipped zip, or an unreadable one: what is extracted is what
            # there is.
            return False

    def _ensure_db_file(self):
        if not self._needs_extraction():
            return True
        shipped = self._shipped_zip
        if not shipped.exists():
            return False
        tmp_path = None
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(shipped) as archive:
                with archive.open(DB_FILENAME) as member, tempfile.NamedTemporaryFile(
                    dir=self._db_path.parent, delete=False
                ) as tmp:
                    tmp_path = Path(tmp.name)
                    shutil.copyfileobj(member, tmp)
            tmp_path.replace(self._db_path)
            tmp_path = None
            logger.info("artwork index extracted: %s -> %s", shipped, self._db_path)
            return True
        except Exception as exc:
            logger.warning("artwork index extraction failed: %s", exc)
            return False
        finally:
            # A copyfileobj that raised half way -- a full disk is the likely
            # one -- used to leave its NamedTemporaryFile behind in
            # artwork-index/, once per attempt (issue #239).
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _connect(self):
        """A fresh read-only connection, or ``None``.

        Per call on purpose: lookups are rare (one per missed ROM), and the
        sync may fan out across worker threads (#186) -- sharing one sqlite
        connection across threads is exactly the bug this avoids.
        """
        if self._corrupt:
            return None
        if not self._ensure_db_file():
            # Nothing to open, and nothing that says it will stay that way.
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True, timeout=1.0
            )
            conn.execute("SELECT 1 FROM games LIMIT 1")
            return conn
        except Exception as exc:
            logger.warning("artwork index unusable: path=%s error=%s", self._db_path, exc)
            self._corrupt = True
            return None

    def _fts_available(self, conn):
        if self._fts_ok is None:
            try:
                conn.execute("SELECT rowid FROM games_fts WHERE games_fts MATCH '\"a\"' LIMIT 1")
                self._fts_ok = True
            except sqlite3.Error as exc:
                logger.warning("artwork index has no usable FTS5: %s", exc)
                self._fts_ok = False
        return self._fts_ok

    def _crc_table_present(self, conn):
        if self._has_crc_table is None:
            try:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='crc_index'"
                ).fetchone()
                self._has_crc_table = bool(row)
            except sqlite3.Error:
                self._has_crc_table = False
        return self._has_crc_table

    @property
    def available(self):
        conn = self._connect()
        if conn is None:
            return False
        conn.close()
        return True

    def has_crc_index(self):
        """Whether stage 1 can work at all -- callers gate the (costly) ROM
        hashing on this, so a database without the table costs nothing.

        Asked once per ROM of a sync run and answered by opening a fresh
        sqlite connection every time, which is the whole cost of a question
        whose answer is fixed for the life of the database file (#231).
        """
        # _crc_table_present already remembers the answer; what was paid per
        # ROM is the connection opened to ask it again.
        if self._has_crc_table is not None:
            return self._has_crc_table
        conn = self._connect()
        if conn is None:
            # Not remembered: the database may still be downloading.
            return False
        try:
            return self._crc_table_present(conn)
        finally:
            conn.close()

    # -- stage 1: content hash ---------------------------------------------
    def resolve_by_crc(self, thumb_system, crc32):
        if not thumb_system or not crc32:
            return None
        conn = self._connect()
        if conn is None:
            return None
        try:
            if not self._crc_table_present(conn):
                return None
            row = conn.execute(
                "SELECT name FROM crc_index WHERE crc32 = ? AND system = ?",
                (str(crc32).upper(), thumb_system),
            ).fetchone()
            return row[0] if row else None
        except sqlite3.Error as exc:
            logger.warning("artwork index crc lookup failed: %s", exc)
            return None
        finally:
            conn.close()

    # -- stage 4: full-text resolution -------------------------------------
    def resolve_name(self, thumb_system, rom_name, region_priority=None):
        """Resolve ``rom_name`` to a canonical stem: ``(stem, round)`` or ``None``."""
        if not thumb_system or not (rom_name or "").strip():
            return None
        conn = self._connect()
        if conn is None:
            return None
        try:
            if not self._fts_available(conn):
                return None
            priority = tuple(region_priority or DEFAULT_REGION_PRIORITY)

            full = _tokens(rom_name)
            untagged = _tokens(_strip_tag_groups(rom_name))
            head = _tokens(_subtitle_head(rom_name))
            seen_queries = set()
            for label, tokens in (("full", full), ("untagged", untagged), ("head", head)):
                for variant in (tokens, _numeral_swapped(tokens)):
                    if not variant:
                        continue
                    key = tuple(variant)
                    if key in seen_queries:
                        continue
                    seen_queries.add(key)
                    stem = self._and_round(conn, thumb_system, variant, priority)
                    if stem:
                        return stem, label

            broad = [t for t in untagged if t not in _CONNECTOR_TOKENS] or untagged
            stem = self._or_round(conn, thumb_system, untagged, broad, priority)
            if stem:
                return stem, "broad"
            return None
        except sqlite3.Error as exc:
            logger.warning("artwork index name resolution failed: %s", exc)
            return None
        finally:
            conn.close()

    def _rows_matching(self, conn, thumb_system, match, limit):
        return conn.execute(
            "SELECT g.name FROM games_fts f JOIN games g ON g.id = f.rowid "
            "WHERE games_fts MATCH ? AND g.system = ? "
            "ORDER BY bm25(games_fts) LIMIT ?",
            (match, thumb_system, limit),
        ).fetchall()

    def _and_round(self, conn, thumb_system, tokens, priority):
        if not tokens:
            return None
        rows = self._rows_matching(
            conn, thumb_system, _fts_query(tokens), _AND_ROUND_LIMIT
        )
        stems = [row[0] for row in rows]
        if not stems:
            return None
        titles = {_strip_tag_groups(stem).lower() for stem in stems}
        if len(titles) != 1:
            # Two different games both match every token: guessing here is
            # how a plausible wrong cover would beat a correct miss.
            return None
        return _pick_region(stems, priority)

    def _or_round(self, conn, thumb_system, coverage_tokens, query_tokens, priority):
        if not query_tokens:
            return None
        rows = self._rows_matching(
            conn, thumb_system, _fts_query(query_tokens, joiner=" OR "), _OR_ROUND_LIMIT
        )
        if not rows:
            return None
        wanted = set(coverage_tokens)
        groups = {}
        for (stem,) in rows:
            title = _strip_tag_groups(stem).lower()
            coverage = len(wanted & set(_tokens(_strip_tag_groups(stem))))
            entry = groups.setdefault(title, {"coverage": 0, "stems": []})
            entry["coverage"] = max(entry["coverage"], coverage)
            entry["stems"].append(stem)
        ranked = sorted(groups.values(), key=lambda entry: -entry["coverage"])
        best = ranked[0]
        # Strict winner only, covering at least half the queried tokens: a
        # tie between two titles is ambiguity, same rule as the AND rounds.
        if best["coverage"] * 2 < len(wanted):
            return None
        if len(ranked) > 1 and ranked[1]["coverage"] >= best["coverage"]:
            return None
        return _pick_region(best["stems"], priority)


    # -- manual suggestions (#185) ------------------------------------------
    def suggest(self, thumb_system, query, limit=12, approximate=False):
        """Ranked candidate stems for the manual cover picker (#185).

        Standard mode is FTS5 -- every token required, the last one as a
        prefix, ranked by bm25. Approximate mode is similarity-ranked
        (stdlib ``difflib``) for typos and heavily tagged stems: seeded by
        an ORed FTS pass, falling back to a scan of the system's whole name
        list when even that finds nothing. Only stems present in the index
        (and therefore in the mirror) are ever returned; any degradation
        answers an empty list.
        """
        if not thumb_system or not (query or "").strip():
            return []
        conn = self._connect()
        if conn is None:
            return []
        try:
            tokens = _tokens(query)
            if not tokens:
                return []
            if not self._fts_available(conn):
                if approximate:
                    return self._similarity_scan(conn, thumb_system, query, limit)
                return []
            if not approximate:
                # The numeral swap ("2" <-> "ii") applies here too, so
                # "Final Fantasy 2" answers on the first query -- the same
                # broadening the automatic ladder does.
                for variant in (tokens, _numeral_swapped(tokens)):
                    if not variant:
                        continue
                    match = _fts_query(variant[:-1])
                    prefix = '"%s"*' % variant[-1].replace('"', '""')
                    match = f"{match} {prefix}".strip()
                    rows = self._rows_matching(conn, thumb_system, match, limit)
                    if rows:
                        return [row[0] for row in rows]
                return []
            rows = self._rows_matching(
                conn, thumb_system, _fts_query(tokens, joiner=" OR "),
                max(limit * 4, 32),
            )
            stems = [row[0] for row in rows]
            if not stems:
                return self._similarity_scan(conn, thumb_system, query, limit)
            return _rank_by_similarity(stems, query)[:limit]
        except sqlite3.Error as exc:
            logger.warning("artwork index suggestions failed: %s", exc)
            return []
        finally:
            conn.close()

    def _similarity_scan(self, conn, thumb_system, query, limit):
        """Last resort for a fully misspelled query: rank the whole system.

        A system's name list tops out around 13k rows (NES); the quick-ratio
        prefilter inside the ranking keeps a one-shot manual query cheap.
        """
        rows = conn.execute(
            "SELECT name FROM games WHERE system = ?", (thumb_system,)
        ).fetchall()
        return _rank_by_similarity(
            [row[0] for row in rows], query, floor=0.5
        )[:limit]


def _rank_by_similarity(stems, query, floor=0.0):
    reference = _strip_tag_groups(query).lower()
    scored = []
    for stem in stems:
        matcher = difflib.SequenceMatcher(
            None, reference, _strip_tag_groups(stem).lower()
        )
        if matcher.real_quick_ratio() < floor:
            continue
        ratio = matcher.ratio()
        if ratio >= floor:
            scored.append((ratio, stem))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [stem for _ratio, stem in scored]


def _pick_region(stems, priority):
    """The stem to use among regional variants of one title.

    Region priority first; within a region -- and when no region matches --
    the shortest stem wins, which prefers the plain release over ``(Rev 1)``
    / ``(Virtual Console)`` variants.
    """
    for region in priority:
        marked = [stem for stem in stems if f"({region}" in stem]
        if marked:
            return min(marked, key=len)
    return min(stems, key=len)

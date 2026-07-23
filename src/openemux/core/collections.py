"""User-defined collections: named lists of games that span consoles.

Favorites already proved the mechanic -- a flat file of absolute ROM paths,
console resolved from the path, missing files skipped on load. This generalises
it from one hard-coded bucket to as many named ones as the user wants.

Each collection is a ``<slug>.list`` file under ``playlists/collections/``; an
``collections.yaml`` index maps slug -> display name and keeps the sidebar
order stable, so a rename never has to move a file and names are free to hold
characters a filename could not.
"""

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

INDEX_FILENAME = "collections.yaml"


def slugify(name):
    """A filesystem-safe slug for a collection name (may be empty)."""
    text = (name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


class CollectionManager:
    def __init__(self, collections_dir, entries_loader=None):
        """``entries_loader(paths)`` turns a list of ROM paths into rom entries.

        Injected so this module stays free of the playlist/scanner machinery and
        stays testable; the window wires in ``PlaylistManager.entries_for_paths``.
        """
        self.collections_dir = Path(collections_dir)
        self._entries_loader = entries_loader

    # -- index -------------------------------------------------------------
    @property
    def index_path(self):
        return self.collections_dir / INDEX_FILENAME

    def _load_index(self):
        if not self.index_path.exists():
            return []
        try:
            raw = yaml.safe_load(self.index_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return []
        result = []
        seen = set()
        for entry in raw.get("collections", []) or []:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "").strip()
            name = str(entry.get("name") or "").strip()
            if not slug or not name or slug in seen:
                continue
            seen.add(slug)
            result.append({"slug": slug, "name": name})
        return result

    def _save_index(self, collections):
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "collections": collections}
        self.index_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # -- queries -----------------------------------------------------------
    def list_collections(self):
        """Collections in sidebar order: ``[{"slug", "name"}, ...]``."""
        return self._load_index()

    def get_name(self, slug):
        for entry in self._load_index():
            if entry["slug"] == slug:
                return entry["name"]
        return None

    def exists_name(self, name):
        target = (name or "").strip().casefold()
        return any(entry["name"].casefold() == target for entry in self._load_index())

    def _list_file(self, slug):
        return self.collections_dir / f"{slug}.list"

    def paths(self, slug):
        list_file = self._list_file(slug)
        if not list_file.exists():
            return []
        with open(list_file, "r", encoding="utf-8") as handle:
            out = []
            seen = set()
            for line in handle:
                value = line.strip()
                if value and value not in seen:
                    seen.add(value)
                    out.append(value)
            return out

    def contains(self, slug, rom_path):
        return str(Path(rom_path)) in set(self.paths(slug))

    def load_entries(self, slug):
        if self._entries_loader is None:
            return []
        return self._entries_loader(self.paths(slug))

    # -- mutations ---------------------------------------------------------
    def create(self, name):
        """Create a collection, returning its slug. Raises ``ValueError``.

        Names must be non-empty and unique case-insensitively; the slug is made
        unique by suffixing so two names that slugify the same still coexist.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("empty name")
        if self.exists_name(name):
            raise ValueError("duplicate name")
        collections = self._load_index()
        slug = self._unique_slug(slugify(name) or "collection", {c["slug"] for c in collections})
        collections.append({"slug": slug, "name": name})
        self._save_index(collections)
        # Touch the list file so the collection exists even while empty.
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self._list_file(slug).touch(exist_ok=True)
        return slug

    def _unique_slug(self, base, taken):
        if base not in taken:
            return base
        index = 2
        while f"{base}-{index}" in taken:
            index += 1
        return f"{base}-{index}"

    def rename(self, slug, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("empty name")
        collections = self._load_index()
        for entry in collections:
            if entry["slug"] != slug and entry["name"].casefold() == name.casefold():
                raise ValueError("duplicate name")
        found = False
        for entry in collections:
            if entry["slug"] == slug:
                entry["name"] = name
                found = True
        if not found:
            raise ValueError("unknown collection")
        self._save_index(collections)

    def delete(self, slug):
        collections = [c for c in self._load_index() if c["slug"] != slug]
        self._save_index(collections)
        list_file = self._list_file(slug)
        if list_file.exists():
            list_file.unlink()

    def _write_paths(self, slug, paths):
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        with open(self._list_file(slug), "w", encoding="utf-8") as handle:
            for path in paths:
                handle.write(f"{path}\n")

    def add(self, slug, rom_paths):
        """Add ROM paths, skipping duplicates. Returns how many were new."""
        existing = self.paths(slug)
        seen = set(existing)
        added = 0
        for rom_path in rom_paths:
            value = str(Path(rom_path))
            if value not in seen:
                seen.add(value)
                existing.append(value)
                added += 1
        if added:
            self._write_paths(slug, existing)
        return added

    def remove(self, slug, rom_paths):
        targets = {str(Path(p)) for p in rom_paths}
        existing = self.paths(slug)
        kept = [p for p in existing if p not in targets]
        removed = len(existing) - len(kept)
        if removed:
            self._write_paths(slug, kept)
        return removed

    def repath_rom(self, old_path, new_path):
        """Follow a renamed ROM across every collection."""
        old_line = str(Path(old_path))
        new_line = str(Path(new_path))
        for entry in self._load_index():
            paths = self.paths(entry["slug"])
            if old_line not in paths:
                continue
            self._write_paths(entry["slug"], [new_line if p == old_line else p for p in paths])

    def forget_rom(self, rom_path):
        """Drop a deleted ROM from every collection."""
        line = str(Path(rom_path))
        for entry in self._load_index():
            paths = self.paths(entry["slug"])
            if line in paths:
                self._write_paths(entry["slug"], [p for p in paths if p != line])

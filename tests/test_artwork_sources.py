"""Where each artwork file came from (issue #510)."""

import json
import os
import threading
import unittest
from datetime import timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core import artwork_sources
from openemux.core.artwork_sources import (
    SOURCE_LOCAL,
    SOURCE_MANUAL,
    SOURCE_SYNCED,
    SOURCES_FILE,
    batch,
    describe,
    forget,
    record,
    rename,
    sources_path,
)
from openemux.core.scraper import COVER_ART, LABEL_ART


def _art(roms, console, name, kind=COVER_ART, ext="png", data=b"\x89PNG"):
    path = Path(roms) / console / kind / f"{name}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _entries(roms, console, kind=COVER_ART):
    return json.loads(sources_path(roms, console, kind).read_text())["entries"]


class _Case(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roms = Path(tmp.name)


class RecordAndDescribeTests(_Case):
    def test_a_recorded_cover_reads_back_with_its_source(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_SYNCED, provider="libretro")
        state = describe(self.roms, "GB", "Kirby", COVER_ART)
        self.assertEqual(state.path, art)
        self.assertEqual(state.source, SOURCE_SYNCED)
        self.assertEqual(state.provider, "libretro")
        self.assertEqual(state.updated.tzinfo, timezone.utc)

    def test_the_record_lives_beside_the_art_as_a_hidden_file(self):
        art = _art(self.roms, "GB", "Kirby", LABEL_ART)
        record(self.roms, "GB", LABEL_ART, "Kirby", art, SOURCE_MANUAL, origin="file")
        path = self.roms / "GB" / LABEL_ART / SOURCES_FILE
        data = json.loads(path.read_text())
        self.assertEqual(data["version"], 1)
        entry = data["entries"]["Kirby"]
        self.assertEqual(entry["file"], "Kirby.png")
        self.assertEqual(entry["origin"], "file")
        self.assertEqual(entry["mtime_ns"], art.stat().st_mtime_ns)

    def test_meta_left_empty_is_not_written(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_SYNCED, provider=None)
        self.assertNotIn("provider", _entries(self.roms, "GB")["Kirby"])

    def test_no_art_at_all_describes_as_nothing(self):
        self.assertIsNone(describe(self.roms, "GB", "Kirby", COVER_ART))

    def test_art_with_no_record_is_a_local_file(self):
        art = _art(self.roms, "GB", "Kirby")
        state = describe(self.roms, "GB", "Kirby", COVER_ART)
        self.assertEqual((state.path, state.source), (art, SOURCE_LOCAL))
        self.assertIsNone(state.updated)

    def test_art_replaced_by_hand_falls_back_to_local(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_MANUAL)
        stat = art.stat()
        os.utime(art, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(describe(self.roms, "GB", "Kirby", COVER_ART).source, SOURCE_LOCAL)

    def test_a_record_naming_another_file_falls_back_to_local(self):
        png = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", png, SOURCE_MANUAL)
        png.unlink()
        _art(self.roms, "GB", "Kirby", ext="jpg")
        self.assertEqual(describe(self.roms, "GB", "Kirby", COVER_ART).source, SOURCE_LOCAL)

    def test_an_unknown_source_falls_back_to_local(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, "mystery")
        self.assertEqual(describe(self.roms, "GB", "Kirby", COVER_ART).source, SOURCE_LOCAL)

    def test_art_that_cannot_be_stat_ed_reads_as_local(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_MANUAL)
        vanished = mock.Mock(spec=Path)
        vanished.name = art.name
        vanished.stat.side_effect = OSError("gone")
        with mock.patch.object(artwork_sources, "find_local_art", return_value=vanished):
            state = describe(self.roms, "GB", "Kirby", COVER_ART)
        self.assertEqual(state.source, SOURCE_LOCAL)

    def test_a_damaged_date_or_provider_is_left_out(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_SYNCED)
        path = sources_path(self.roms, "GB", COVER_ART)
        data = json.loads(path.read_text())
        data["entries"]["Kirby"]["updated"] = "yesterday"
        data["entries"]["Kirby"]["provider"] = 7
        path.write_text(json.dumps(data))
        state = describe(self.roms, "GB", "Kirby", COVER_ART)
        self.assertEqual(state.source, SOURCE_SYNCED)
        self.assertIsNone(state.updated)
        self.assertIsNone(state.provider)

    def test_a_date_that_is_not_text_is_left_out(self):
        art = _art(self.roms, "GB", "Kirby")
        record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_SYNCED)
        path = sources_path(self.roms, "GB", COVER_ART)
        data = json.loads(path.read_text())
        data["entries"]["Kirby"]["updated"] = 12
        path.write_text(json.dumps(data))
        self.assertIsNone(describe(self.roms, "GB", "Kirby", COVER_ART).updated)

    def test_recording_art_that_is_gone_writes_nothing(self):
        with self.assertLogs(artwork_sources.logger, "WARNING"):
            record(self.roms, "GB", COVER_ART, "Kirby", self.roms / "nope.png", SOURCE_SYNCED)
        self.assertFalse(sources_path(self.roms, "GB", COVER_ART).exists())

    def test_a_second_record_keeps_the_first(self):
        a = _art(self.roms, "GB", "A")
        b = _art(self.roms, "GB", "B")
        record(self.roms, "GB", COVER_ART, "A", a, SOURCE_SYNCED)
        record(self.roms, "GB", COVER_ART, "B", b, SOURCE_MANUAL)
        self.assertEqual(sorted(_entries(self.roms, "GB")), ["A", "B"])


class DamagedFileTests(_Case):
    def _write(self, text):
        path = sources_path(self.roms, "GB", COVER_ART)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def _assert_reads_empty_and_is_replaced(self, text):
        self._write(text)
        art = _art(self.roms, "GB", "Kirby")
        with self.assertLogs(artwork_sources.logger, "WARNING"):
            self.assertEqual(describe(self.roms, "GB", "Kirby", COVER_ART).source, SOURCE_LOCAL)
        with self.assertLogs(artwork_sources.logger, "WARNING"):
            record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_MANUAL)
        self.assertEqual(list(_entries(self.roms, "GB")), ["Kirby"])

    def test_bad_json_reads_as_empty_and_is_replaced(self):
        self._assert_reads_empty_and_is_replaced("{not json")

    def test_a_newer_layout_reads_as_empty(self):
        self._assert_reads_empty_and_is_replaced('{"version": 99, "entries": {}}')

    def test_entries_that_are_not_a_mapping_read_as_empty(self):
        self._assert_reads_empty_and_is_replaced('{"version": 1, "entries": []}')

    def test_a_top_level_that_is_not_an_object_reads_as_empty(self):
        self._assert_reads_empty_and_is_replaced("[1, 2]")

    def test_an_entry_that_is_not_an_object_is_dropped(self):
        self._write('{"version": 1, "entries": {"Kirby": "synced", "Other": {}}}')
        self.assertEqual(
            artwork_sources._load(sources_path(self.roms, "GB", COVER_ART)), {"Other": {}}
        )

    def test_an_unreadable_file_reads_as_empty(self):
        self._write("{}")
        with (
            mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            self.assertLogs(artwork_sources.logger, "WARNING"),
        ):
            self.assertEqual(artwork_sources._load(sources_path(self.roms, "GB", COVER_ART)), {})

    def test_a_failed_write_is_logged_not_raised(self):
        art = _art(self.roms, "GB", "Kirby")
        with (
            mock.patch.object(
                artwork_sources, "atomic_write_text", side_effect=OSError("read-only")
            ),
            self.assertLogs(artwork_sources.logger, "WARNING"),
        ):
            record(self.roms, "GB", COVER_ART, "Kirby", art, SOURCE_MANUAL)
        self.assertFalse(sources_path(self.roms, "GB", COVER_ART).exists())


class ForgetAndRenameTests(_Case):
    def test_forget_drops_only_that_rom(self):
        for name in ("A", "B"):
            record(self.roms, "GB", COVER_ART, name, _art(self.roms, "GB", name), SOURCE_SYNCED)
        forget(self.roms, "GB", COVER_ART, "A")
        self.assertEqual(list(_entries(self.roms, "GB")), ["B"])

    def test_forget_with_no_file_creates_none(self):
        forget(self.roms, "GB", COVER_ART, "A")
        self.assertFalse(sources_path(self.roms, "GB", COVER_ART).exists())

    def test_forget_of_an_unknown_rom_does_not_rewrite(self):
        record(self.roms, "GB", COVER_ART, "A", _art(self.roms, "GB", "A"), SOURCE_SYNCED)
        with mock.patch.object(artwork_sources, "_store") as store:
            forget(self.roms, "GB", COVER_ART, "Z")
        store.assert_not_called()

    def test_rename_carries_every_kind_and_follows_the_file_name(self):
        record(self.roms, "GB", COVER_ART, "Old", _art(self.roms, "GB", "Old"), SOURCE_SYNCED)
        record(
            self.roms, "GB", LABEL_ART, "Old",
            _art(self.roms, "GB", "Old", LABEL_ART, ext="jpg"), SOURCE_MANUAL,
        )
        # What scraper.rename_local_art does to the files themselves.
        for kind, ext in ((COVER_ART, "png"), (LABEL_ART, "jpg")):
            folder = self.roms / "GB" / kind
            (folder / f"Old.{ext}").replace(folder / f"New.{ext}")

        rename(self.roms, "GB", "Old", "New")

        self.assertEqual(describe(self.roms, "GB", "New", COVER_ART).source, SOURCE_SYNCED)
        self.assertEqual(describe(self.roms, "GB", "New", LABEL_ART).source, SOURCE_MANUAL)
        self.assertNotIn("Old", _entries(self.roms, "GB", LABEL_ART))
        self.assertEqual(_entries(self.roms, "GB", LABEL_ART)["New"]["file"], "New.jpg")

    def test_rename_of_a_rom_with_no_record_changes_nothing(self):
        record(self.roms, "GB", COVER_ART, "A", _art(self.roms, "GB", "A"), SOURCE_SYNCED)
        with mock.patch.object(artwork_sources, "_store") as store:
            rename(self.roms, "GB", "Missing", "New")
        store.assert_not_called()

    def test_rename_replaces_a_record_already_under_the_new_name(self):
        record(self.roms, "GB", COVER_ART, "Old", _art(self.roms, "GB", "Old"), SOURCE_MANUAL)
        record(self.roms, "GB", COVER_ART, "New", _art(self.roms, "GB", "New"), SOURCE_SYNCED)
        rename(self.roms, "GB", "Old", "New")
        entries = _entries(self.roms, "GB")
        self.assertEqual(list(entries), ["New"])
        self.assertEqual(entries["New"]["source"], SOURCE_MANUAL)


class BatchTests(_Case):
    def test_a_batch_writes_each_console_and_kind_once(self):
        arts = [_art(self.roms, "GB", f"G{i}") for i in range(5)]
        label = _art(self.roms, "GB", "G0", LABEL_ART)
        with mock.patch.object(
            artwork_sources, "_store", wraps=artwork_sources._store
        ) as store:
            with batch(self.roms) as sources:
                for index, art in enumerate(arts):
                    sources.record("GB", COVER_ART, f"G{index}", art, SOURCE_SYNCED)
                sources.record("GB", LABEL_ART, "G0", label, SOURCE_SYNCED)
                store.assert_not_called()
        self.assertEqual(store.call_count, 2)
        self.assertEqual(len(_entries(self.roms, "GB")), 5)

    def test_a_batch_flushes_even_when_the_run_raises(self):
        art = _art(self.roms, "GB", "Kirby")
        with self.assertRaises(RuntimeError):
            with batch(self.roms) as sources:
                sources.record("GB", COVER_ART, "Kirby", art, SOURCE_SYNCED)
                raise RuntimeError("cancelled")
        self.assertIn("Kirby", _entries(self.roms, "GB"))

    def test_a_batch_keeps_records_already_on_disk(self):
        record(self.roms, "GB", COVER_ART, "A", _art(self.roms, "GB", "A"), SOURCE_MANUAL)
        with batch(self.roms) as sources:
            sources.record("GB", COVER_ART, "B", _art(self.roms, "GB", "B"), SOURCE_SYNCED)
        self.assertEqual(sorted(_entries(self.roms, "GB")), ["A", "B"])

    def test_a_batch_skips_art_that_is_gone(self):
        with self.assertLogs(artwork_sources.logger, "WARNING"):
            with batch(self.roms) as sources:
                sources.record("GB", COVER_ART, "A", self.roms / "nope.png", SOURCE_SYNCED)
        self.assertFalse(sources_path(self.roms, "GB", COVER_ART).exists())

    def test_concurrent_records_keep_every_entry(self):
        names = [f"Game {i}" for i in range(40)]
        arts = {name: _art(self.roms, "GB", name) for name in names}
        threads = [
            threading.Thread(
                target=record,
                args=(self.roms, "GB", COVER_ART, name, arts[name], SOURCE_SYNCED),
            )
            for name in names
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(_entries(self.roms, "GB")), sorted(names))


if __name__ == "__main__":
    unittest.main()

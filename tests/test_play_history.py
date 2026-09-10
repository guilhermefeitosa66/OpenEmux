import json
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.play_history import PlayHistory


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        self.now += 10
        return self.now


class PlayHistoryTests(unittest.TestCase):
    def _history(self, tmp_dir, clock=None):
        return PlayHistory(
            history_file=Path(tmp_dir) / "play_history.json", clock=clock or FakeClock()
        )

    def test_a_game_never_played_has_no_timestamp(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            self.assertEqual(history.last_played("/roms/x.sfc"), 0.0)
            self.assertEqual(history.play_count("/roms/x.sfc"), 0)
            self.assertFalse(history.has_history())

    def test_a_launch_is_stamped_and_counted(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            first = history.record_launch("/roms/x.sfc")
            second = history.record_launch("/roms/x.sfc")
            self.assertEqual(history.last_played("/roms/x.sfc"), second)
            self.assertGreater(second, first)
            self.assertEqual(history.play_count("/roms/x.sfc"), 2)

    def test_history_survives_a_restart(self):
        with TemporaryDirectory() as tmp_dir:
            self._history(tmp_dir).record_launch("/roms/x.sfc")
            reopened = self._history(tmp_dir)
            self.assertEqual(reopened.play_count("/roms/x.sfc"), 1)
            self.assertGreater(reopened.last_played("/roms/x.sfc"), 0)

    def test_a_corrupt_file_starts_empty_instead_of_raising(self):
        """Losing the history is a nuisance; failing to open the library is not."""
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "play_history.json"
            path.write_text("{not json", encoding="utf-8")
            history = PlayHistory(history_file=path)
            self.assertEqual(history.last_played("/roms/x.sfc"), 0.0)

    def test_junk_entries_are_coerced_rather_than_trusted(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "play_history.json"
            path.write_text(
                json.dumps({
                    "/roms/x.sfc": {"last_played": "yesterday", "play_count": None},
                    "/roms/y.sfc": "nonsense",
                }),
                encoding="utf-8",
            )
            history = PlayHistory(history_file=path)
            self.assertEqual(history.last_played("/roms/x.sfc"), 0.0)
            self.assertEqual(history.play_count("/roms/x.sfc"), 0)
            self.assertEqual(history.last_played("/roms/y.sfc"), 0.0)

    def test_deleting_a_rom_forgets_it(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_launch("/roms/x.sfc")
            history.forget("/roms/x.sfc")
            self.assertEqual(history.play_count("/roms/x.sfc"), 0)

    def test_renaming_a_rom_carries_its_history_over(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_launch("/roms/old.sfc")
            history.repath("/roms/old.sfc", "/roms/new.sfc")
            self.assertEqual(history.play_count("/roms/new.sfc"), 1)
            self.assertEqual(history.play_count("/roms/old.sfc"), 0)


class WhenTheHistoryFileCannotBeUsedTests(unittest.TestCase):
    def test_a_file_that_is_not_an_object_is_set_aside(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "play_history.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            history = PlayHistory(path)
            self.assertFalse(history.has_history())
            self.assertEqual(
                len(list(Path(tmp_dir).glob("play_history.json.broken-*"))), 1
            )

    def test_a_history_that_cannot_be_written_is_not_a_failed_launch(self):
        # Recording a launch must never be what stops a game from starting.
        with TemporaryDirectory() as tmp_dir:
            history = PlayHistory(Path(tmp_dir) / "play_history.json")
            with mock.patch(
                "openemux.core.play_history.atomic_write_text",
                side_effect=OSError("read-only"),
            ):
                with self.assertLogs("openemux.core.play_history", level="INFO"):
                    history.record_launch("/roms/SFC/Game.sfc")

    def test_repathing_a_game_with_no_history_changes_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            history = PlayHistory(Path(tmp_dir) / "play_history.json")
            history.repath("/roms/SFC/Never Played.sfc", "/roms/SFC/Renamed.sfc")
            self.assertFalse(history.has_history())


if __name__ == "__main__":
    unittest.main()

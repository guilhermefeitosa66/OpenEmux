import json
import unittest
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


if __name__ == "__main__":
    unittest.main()

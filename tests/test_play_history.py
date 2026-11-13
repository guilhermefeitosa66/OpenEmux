import json
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.play_history import PlayHistory, format_play_time


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


class ThePlayTimeTests(unittest.TestCase):
    """How long a game was played, and which were played last (issue 910)."""

    def _history(self, tmp_dir):
        return PlayHistory(history_file=Path(tmp_dir) / "play_history.json", clock=FakeClock())

    def test_a_game_never_timed_has_no_play_time(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(self._history(tmp_dir).play_seconds("/roms/x.sfc"), 0.0)

    def test_sessions_add_up_and_survive_a_restart(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_launch("/roms/x.sfc")
            self.assertEqual(history.record_play_time("/roms/x.sfc", 90), 90.0)
            self.assertEqual(history.record_play_time("/roms/x.sfc", 30.5), 120.5)
            self.assertEqual(self._history(tmp_dir).play_seconds("/roms/x.sfc"), 120.5)

    def test_a_session_that_died_at_once_adds_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_launch("/roms/x.sfc")
            self.assertEqual(history.record_play_time("/roms/x.sfc", 0.4), 0.0)
            self.assertEqual(history.record_play_time("/roms/x.sfc", None), 0.0)
            self.assertEqual(history.record_play_time("/roms/x.sfc", -5), 0.0)
            self.assertEqual(self._history(tmp_dir).play_seconds("/roms/x.sfc"), 0.0)

    def test_an_old_history_file_reads_as_never_timed(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "play_history.json"
            path.write_text(
                json.dumps({"/roms/x.sfc": {"last_played": 5.0, "play_count": 1}}),
                encoding="utf-8",
            )
            history = PlayHistory(history_file=path)
            self.assertEqual(history.play_seconds("/roms/x.sfc"), 0.0)
            # ...and gets its first session like any other game.
            self.assertEqual(history.record_play_time("/roms/x.sfc", 60), 60.0)

    def test_the_recent_games_come_last_played_first(self):
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_launch("/roms/a.sfc")
            history.record_launch("/roms/b.sfc")
            history.record_launch("/roms/c.sfc")
            history.record_launch("/roms/a.sfc")
            self.assertEqual(history.recent(), ["/roms/a.sfc", "/roms/c.sfc", "/roms/b.sfc"])
            self.assertEqual(history.recent(limit=2), ["/roms/a.sfc", "/roms/c.sfc"])

    def test_a_game_only_timed_but_never_launched_is_not_recent(self):
        # A play time recorded for a game with no launch stamp (a hand-edited
        # file) has no place in the order.
        with TemporaryDirectory() as tmp_dir:
            history = self._history(tmp_dir)
            history.record_play_time("/roms/x.sfc", 60)
            self.assertEqual(history.recent(), [])
            self.assertTrue(history.has_history())


class FormattingPlayTimeTests(unittest.TestCase):
    def test_hours_and_minutes_are_split_for_the_caller_to_word(self):
        self.assertEqual(format_play_time(80 * 60), (1, 20))
        self.assertEqual(format_play_time(12 * 60 + 59), (0, 12))

    def test_under_a_minute_is_nothing_yet(self):
        self.assertEqual(format_play_time(59), (0, 0))
        self.assertEqual(format_play_time(None), (0, 0))
        self.assertEqual(format_play_time(-10), (0, 0))


if __name__ == "__main__":
    unittest.main()

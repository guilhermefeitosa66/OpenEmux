"""Save-state browsing over the managed states directory (issue #73)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import save_states

ROM = "/roms/SFC/Chrono Trigger (USA).sfc"


class ListStatesTests(unittest.TestCase):
    def _touch(self, directory, name):
        path = Path(directory) / name
        path.write_bytes(b"state")
        return path

    def test_slots_are_parsed_and_sorted(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state3")
            self._touch(tmp_dir, "Chrono Trigger (USA).state")
            self._touch(tmp_dir, "Chrono Trigger (USA).state1")
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual([s.slot for s in states], [0, 1, 3])

    def test_other_roms_and_junk_are_ignored(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state")
            self._touch(tmp_dir, "Terranigma.state")           # another ROM
            self._touch(tmp_dir, "Chrono Trigger (USA).state.auto")  # auto state
            self._touch(tmp_dir, "Chrono Trigger (USA).state.png")   # screenshot
            self._touch(tmp_dir, "notes.txt")
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual([s.slot for s in states], [0])

    def test_companion_thumbnail_is_attached_when_present(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state2")
            thumb = self._touch(tmp_dir, "Chrono Trigger (USA).state2.png")
            no_thumb = save_states.list_states(tmp_dir, ROM)
            self.assertEqual(no_thumb[0].thumbnail, thumb)
            thumb.unlink()
            self.assertIsNone(save_states.list_states(tmp_dir, ROM)[0].thumbnail)

    def test_missing_directory_is_empty(self):
        self.assertEqual(save_states.list_states("/nope/nothing", ROM), [])


class SlotEntriesTests(unittest.TestCase):
    """The context menu's slot list: full range, empties visible (issue #73)."""

    def test_full_range_with_empties_as_none(self):
        with TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "Chrono Trigger (USA).state").write_bytes(b"s")
            (Path(tmp_dir) / "Chrono Trigger (USA).state4").write_bytes(b"s")
            entries = save_states.slot_entries(tmp_dir, ROM)
        self.assertEqual(len(entries), 10)
        self.assertEqual([slot for slot, _ in entries], list(range(10)))
        filled = {slot for slot, mtime in entries if mtime is not None}
        self.assertEqual(filled, {0, 4})

    def test_missing_directory_is_all_empty(self):
        entries = save_states.slot_entries("/nope/nothing", ROM)
        self.assertTrue(all(mtime is None for _slot, mtime in entries))
        self.assertEqual(len(entries), 10)


class DeleteStateTests(unittest.TestCase):
    def test_delete_removes_state_and_screenshot(self):
        with TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "Chrono Trigger (USA).state1"
            state_file.write_bytes(b"s")
            thumb = Path(tmp_dir) / "Chrono Trigger (USA).state1.png"
            thumb.write_bytes(b"p")
            state = save_states.list_states(tmp_dir, ROM)[0]
            self.assertTrue(save_states.delete_state(state))
            self.assertFalse(state_file.exists())
            self.assertFalse(thumb.exists())

    def test_delete_of_a_gone_file_reports_failure(self):
        state = save_states.SaveState("/nope/x.state", 0, 0)
        self.assertFalse(save_states.delete_state(state))


if __name__ == "__main__":
    unittest.main()

"""Setting changes reach the disk once they stop, not once per keystroke (issue 905).

Every zoom step, sort change, theme toggle and log-panel switch used to dump
the whole YAML and fsync it twice, on the main thread, while the user was
still performing the gesture. The setters that run on a gesture now mark the
config dirty and write on a worker thread once the changes pause; the file is
still written atomically, so a crash inside the window loses at most those
last settings and never the file.
"""

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml

from openemux.core import atomic_write, config as config_module
from openemux.core.config import ConfigManager


class _DebounceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.yaml"
        self.manager = ConfigManager(config_file=self.path)
        self.manager.save_config()
        self.addCleanup(self.manager.flush)

    def _writes(self):
        """A counter on the atomic write, started empty."""
        counter = mock.patch.object(
            config_module, "atomic_write_text", wraps=config_module.atomic_write_text
        )
        self.addCleanup(counter.stop)
        return counter.start()

    def _zoom_on_disk(self):
        return yaml.safe_load(self.path.read_text(encoding="utf-8"))["ui"]["zoom"]


class TenZoomStepsAreOneWriteTests(_DebounceCase):
    def test_rapid_zoom_steps_write_nothing_until_flushed(self):
        writes = self._writes()
        for zoom in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 1.5, 1.25, 1.0, 0.75):
            self.manager.set_zoom(zoom)
        self.assertEqual(writes.call_count, 0)
        self.assertTrue(self.manager.has_pending_save())
        self.assertTrue(self.manager.flush())
        self.assertEqual(writes.call_count, 1)
        self.assertEqual(self._zoom_on_disk(), 0.75)
        self.assertFalse(self.manager.has_pending_save())

    def test_the_timer_writes_by_itself_once_the_changes_stop(self):
        writes = self._writes()
        with mock.patch.object(ConfigManager, "SAVE_DEBOUNCE_S", 0.05):
            self.manager.set_zoom(1.5)
            deadline = time.monotonic() + 5
            while writes.call_count < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
        self.manager.flush()  # joins a write still in flight, writes nothing itself
        self.assertFalse(self.manager.has_pending_save())
        self.assertEqual(writes.call_count, 1)
        self.assertEqual(self._zoom_on_disk(), 1.5)

    def test_the_write_runs_off_the_calling_thread(self):
        threads = []
        real = config_module.atomic_write_text

        def spy(*args, **kwargs):
            threads.append(threading.current_thread().name)
            return real(*args, **kwargs)

        with mock.patch.object(config_module, "atomic_write_text", spy), mock.patch.object(
            ConfigManager, "SAVE_DEBOUNCE_S", 0.05
        ):
            self.manager.set_zoom(1.25)
            deadline = time.monotonic() + 5
            while not threads and time.monotonic() < deadline:
                time.sleep(0.01)
        self.manager.flush()
        self.assertEqual(threads, ["openemux-config-save"])

    def test_a_flush_with_nothing_pending_writes_nothing(self):
        writes = self._writes()
        self.assertFalse(self.manager.flush())
        writes.assert_not_called()

    def test_an_immediate_save_takes_the_pending_change_with_it(self):
        writes = self._writes()
        self.manager.set_zoom(2.0)
        self.manager.set_roms_path(Path(self._tmp.name) / "roms")  # saves at once
        self.assertEqual(writes.call_count, 1)
        self.assertFalse(self.manager.has_pending_save())
        self.assertEqual(self._zoom_on_disk(), 2.0)

    def test_a_timer_that_fires_after_a_flush_writes_nothing_more(self):
        writes = self._writes()
        self.manager.set_zoom(1.5)
        self.manager.flush()
        self.manager._save_from_timer()
        self.assertEqual(writes.call_count, 1)

    def test_every_gesture_setter_is_debounced(self):
        writes = self._writes()
        self.manager.set_view_mode("list")
        self.manager.set_sort_order("name_desc")
        self.manager.set_theme("dark")
        self.manager.set_show_log_panel(True)
        self.manager.enable_scope_override("SFC")
        self.manager.set_scope_display("SFC", "zoom", 1.5)
        self.manager.clear_scope_override("SFC")
        self.assertEqual(writes.call_count, 0)
        self.assertTrue(self.manager.flush())
        self.assertEqual(writes.call_count, 1)
        on_disk = yaml.safe_load(self.path.read_text(encoding="utf-8"))["ui"]
        self.assertEqual(on_disk["view_mode"], "list")
        self.assertEqual(on_disk["sort_order"], "name_desc")
        self.assertEqual(on_disk["theme"], "dark")
        self.assertTrue(on_disk["show_log_panel"])
        self.assertNotIn("SFC", on_disk.get("scope_overrides", {}))

    def test_the_file_is_still_written_atomically(self):
        self.manager.set_zoom(1.5)
        with mock.patch.object(
            atomic_write, "_replace_atomically", wraps=atomic_write._replace_atomically
        ) as replace:
            self.manager.flush()
        self.assertEqual(replace.call_count, 1)
        self.assertTrue(replace.call_args[1].get("durable", True))


class NonDurableWritesTests(unittest.TestCase):
    """The session file keeps the atomic rename and drops the two fsyncs."""

    def test_a_non_durable_write_syncs_nothing(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            with mock.patch.object(atomic_write.os, "fsync") as fsync, mock.patch.object(
                atomic_write, "_fsync_directory"
            ) as sync_dir:
                atomic_write.atomic_write_text(path, "{}", durable=False)
            fsync.assert_not_called()
            sync_dir.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "{}")

    def test_a_durable_write_syncs_the_file_and_the_directory(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            with mock.patch.object(atomic_write.os, "fsync", wraps=atomic_write.os.fsync) as fsync, mock.patch.object(
                atomic_write, "_fsync_directory", wraps=atomic_write._fsync_directory
            ) as sync_dir:
                atomic_write.atomic_write_text(path, "a: 1\n")
            # The content, and then the directory entry through _fsync_directory.
            self.assertEqual(fsync.call_count, 2)
            sync_dir.assert_called_once()

    def test_the_session_store_writes_without_a_sync(self):
        from openemux.core.session_store import SessionStore

        with TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp) / "session.json")
            with mock.patch.object(
                config_module, "atomic_write_text"
            ), mock.patch(
                "openemux.core.session_store.atomic_write_text",
                wraps=atomic_write.atomic_write_text,
            ) as write:
                store.set_last_view("SFC")
            self.assertFalse(write.call_args[1]["durable"])


if __name__ == "__main__":
    unittest.main()

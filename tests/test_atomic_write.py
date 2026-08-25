import os
import stat
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from openemux.core.atomic_write import (
    DEFAULT_FILE_MODE,
    atomic_write_lines,
    atomic_write_text,
)
from openemux.core.config import ConfigManager
from openemux.core.playlist_manager import PlaylistManager


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _leftovers(directory):
    """Anything the helper created and did not clean up."""
    return sorted(p.name for p in Path(directory).iterdir() if p.name.endswith(".tmp"))


class AtomicWriteTextTests(unittest.TestCase):
    def test_writes_the_content(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "state.yaml"
            atomic_write_text(target, "roms_path: /games\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "roms_path: /games\n")

    def test_creates_the_parent_directory(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "playlists" / "collections" / "rpg.list"
            atomic_write_text(target, "x\n")
            self.assertTrue(target.is_file())

    def test_leaves_no_temporary_file_behind(self):
        with TemporaryDirectory() as tmp_dir:
            atomic_write_text(Path(tmp_dir) / "state.yaml", "a: 1\n")
            self.assertEqual(_leftovers(tmp_dir), [])

    def test_a_new_file_is_readable_by_the_user_tooling(self):
        # mkstemp opens 0600; a config only root-and-owner can read would be a
        # regression against the plain open() this replaced.
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            atomic_write_text(target, "a: 1\n")
            self.assertEqual(_mode_of(target), DEFAULT_FILE_MODE)

    def test_an_existing_file_keeps_its_permissions(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            target.write_text("a: 1\n", encoding="utf-8")
            os.chmod(target, 0o600)
            atomic_write_text(target, "a: 2\n")
            self.assertEqual(_mode_of(target), 0o600)

    def test_an_explicit_mode_wins(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "cheevos.config"
            atomic_write_text(target, "{}", mode=0o600)
            self.assertEqual(_mode_of(target), 0o600)

    def test_a_failed_write_leaves_the_previous_file_untouched(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            target.write_text("roms_path: /games\n", encoding="utf-8")

            with patch("openemux.core.atomic_write.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "roms_path: /elsewhere\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "roms_path: /games\n")
            self.assertEqual(_leftovers(tmp_dir), [])

    def test_a_crash_mid_write_never_exposes_a_partial_file(self):
        # The point of the whole helper: a reader that opens the target at the
        # worst possible moment sees the old content, not half the new one.
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            target.write_text("roms_path: /games\n", encoding="utf-8")
            seen = []

            real_replace = os.replace

            def _peek_then_replace(src, dst):
                seen.append(Path(dst).read_text(encoding="utf-8"))
                return real_replace(src, dst)

            with patch("openemux.core.atomic_write.os.replace", _peek_then_replace):
                atomic_write_text(target, "roms_path: /elsewhere\n")

            self.assertEqual(seen, ["roms_path: /games\n"])
            self.assertEqual(target.read_text(encoding="utf-8"), "roms_path: /elsewhere\n")


class AtomicWriteLinesTests(unittest.TestCase):
    def test_writes_one_newline_terminated_line_each(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "FAVORITES.list"
            atomic_write_lines(target, ["/roms/a.sfc", "/roms/b.sfc"])
            self.assertEqual(
                target.read_text(encoding="utf-8"), "/roms/a.sfc\n/roms/b.sfc\n"
            )

    def test_an_empty_list_writes_an_empty_file(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "FAVORITES.list"
            atomic_write_lines(target, [])
            self.assertEqual(target.read_text(encoding="utf-8"), "")


class ConfigAtomicSaveTests(unittest.TestCase):
    def test_a_failed_save_keeps_the_previous_config(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=config_file)
            manager.set_roms_path("/games/roms")
            before = config_file.read_text(encoding="utf-8")

            with patch("openemux.core.atomic_write.os.replace", side_effect=OSError("disk full")):
                # save_config swallows write errors -- the app carries on with
                # the in-memory config -- but the file must not be damaged.
                manager.set_roms_path("/somewhere/else")

            self.assertEqual(config_file.read_text(encoding="utf-8"), before)
            self.assertEqual(_leftovers(tmp_dir), [])

    def test_concurrent_saves_never_expose_a_truncated_config(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=config_file)
            stop = threading.Event()
            failures = []

            def _reader():
                while not stop.is_set():
                    try:
                        loaded = yaml.safe_load(config_file.read_text(encoding="utf-8"))
                    except Exception as exc:  # pragma: no cover - the bug
                        failures.append(repr(exc))
                        return
                    if not isinstance(loaded, dict) or "roms_path" not in loaded:
                        failures.append(f"partial config: {loaded!r}")
                        return

            def _writer(index):
                for step in range(10):
                    manager.set_roms_path(f"/games/{index}/{step}")

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()
            writers = [threading.Thread(target=_writer, args=(i,)) for i in range(3)]
            for writer in writers:
                writer.start()
            for writer in writers:
                writer.join()
            stop.set()
            reader.join(timeout=5)

            self.assertEqual(failures, [])
            self.assertEqual(_leftovers(tmp_dir), [])


class _StubScanner:
    def __init__(self, roms):
        self.roms = roms

    def scan_console(self, console):
        return self.roms


class _StubConfigManager:
    def __init__(self, playlists_dir):
        self._playlists_dir = Path(playlists_dir)

    def get_playlists_dir(self):
        return self._playlists_dir


class PlaylistAtomicWriteTests(unittest.TestCase):
    def _manager(self, tmp_dir, roms=()):
        return PlaylistManager(_StubConfigManager(tmp_dir), _StubScanner(list(roms)))

    def test_a_rebuild_never_exposes_a_half_written_playlist(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(
                tmp_dir, [{"name": "A", "path": "/roms/a.sfc"}, {"name": "B", "path": "/roms/b.sfc"}]
            )
            manager.scan_and_rebuild_playlist("SFC")
            playlist = Path(tmp_dir) / "SFC.list"
            self.assertEqual(
                playlist.read_text(encoding="utf-8"), "/roms/a.sfc\n/roms/b.sfc\n"
            )

            manager.scanner.roms = [{"name": "C", "path": "/roms/c.sfc"}]
            seen = []
            real_replace = os.replace

            def _peek_then_replace(src, dst):
                seen.append(Path(dst).read_text(encoding="utf-8"))
                return real_replace(src, dst)

            with patch("openemux.core.atomic_write.os.replace", _peek_then_replace):
                manager.scan_and_rebuild_playlist("SFC")

            self.assertEqual(seen, ["/roms/a.sfc\n/roms/b.sfc\n"])
            self.assertEqual(playlist.read_text(encoding="utf-8"), "/roms/c.sfc\n")

    def test_a_failed_favorite_toggle_keeps_the_favorites_file(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.toggle_favorite({"path": "/roms/a.sfc"})
            favorites = Path(tmp_dir) / "FAVORITES.list"
            before = favorites.read_text(encoding="utf-8")

            with patch("openemux.core.atomic_write.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    manager.toggle_favorite({"path": "/roms/b.sfc"})

            self.assertEqual(favorites.read_text(encoding="utf-8"), before)
            self.assertEqual(_leftovers(tmp_dir), [])

    def test_concurrent_favorite_toggles_do_not_lose_edits(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            roms = [{"path": f"/roms/{index}.sfc"} for index in range(24)]
            threads = [
                threading.Thread(target=manager.toggle_favorite, args=(rom,))
                for rom in roms
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(manager.list_favorite_paths()), len(roms))


if __name__ == "__main__":
    unittest.main()

import errno
import hashlib
import io
import os
import time
import unittest
from unittest import mock

from openemux.core.save_backup import is_battery_save
from openemux.core.scanner import RomScanner
from openemux.core.share import receive
from openemux.core.share.placement import plan_receive
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.receive import IncomingTransfer, LibraryHooks
from tests.share_fixtures import PNG_BYTES, core_file, make_catalog, temp_library
from tests.test_share_placement import SNES9X, game, item, manifest


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RecordingHooks(LibraryHooks):
    def __init__(self):
        self.calls = []

    def set_favorite(self, rom_path):
        self.calls.append(("favorite", rom_path.name))

    def set_cartridge_color(self, rom_path, console, color_id):
        self.calls.append(("color", rom_path.name, console, color_id))

    def set_core(self, rom_path, core_filename):
        self.calls.append(("core", rom_path.name, core_filename))

    def set_shader(self, rom_path, console, shader_id):
        self.calls.append(("shader", rom_path.name, console, shader_id))


class Body:
    """An upload body; ``at_end`` runs when the last byte has been read."""

    def __init__(self, data, at_end=None, during=None):
        self.stream = io.BytesIO(data)
        self.at_end = at_end
        self.during = during

    def read(self, size=-1):
        chunk = self.stream.read(size)
        if chunk and self.during is not None:
            self.during()
            self.during = None
        if not chunk and self.at_end is not None:
            self.at_end()
            self.at_end = None
        return chunk


DATA = {"r": b"rom bytes", "s": b"battery", "t": b"state", "c": PNG_BYTES}


class ReceiveTestCase(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})
        self.clock = Clock()
        self.hooks = RecordingHooks()
        self.done = []
        self.aborted = []
        self.progress = []

    def full_game(self, metadata=None, **extra):
        items = [
            item("r", "rom", "Game.sfc", DATA["r"], mtime=1500),
            item("s", "battery_save", "Game.srm", DATA["s"], mtime=1600),
            item("t", "state", "Game.state1", DATA["t"], mtime=1700, state={**SNES9X, "slot": 1}),
            item("c", "cover", "Game.png", DATA["c"], mtime=1800),
        ]
        g = game(items, **({"metadata": metadata} if metadata else {}), **extra)
        return manifest(g)

    def transfer(self, m, **kwargs):
        plan = plan_receive(m, roms_dir=self.lib.roms, states_dir=self.lib.states, catalog=self.catalog,
                            **kwargs.pop("plan_kwargs", {}))
        kwargs.setdefault("shader_ids", {"crt-easymode"})
        return IncomingTransfer(
            "offer1", plan, catalog=self.catalog, hooks=self.hooks, on_done=self.done.append,
            on_abort=self.aborted.append, on_progress=self.progress.append, clock=self.clock, **kwargs,
        )

    def put(self, transfer, item_id, data=None, length=None, **body):
        data = DATA[item_id] if data is None else data
        transfer.handle_put(item_id, Body(data, **body), len(data) if length is None else length)

    def assertShareError(self, code, call, *args, **kwargs):
        with self.assertRaises(ShareError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def visible(self):
        """What a scan of the library would see: no cores, no dotfiles."""
        return [p for p in self.lib.tree()
                if not p.startswith("cores/") and not any(part.startswith(".") for part in p.split("/"))]

    def assertClean(self):
        """Nothing placed, no temporary file, no directory left behind."""
        self.assertEqual(self.lib.tree(), [p for p in self.lib.tree() if p.startswith("cores/")])
        leftovers = [p for p in self.lib.root.rglob("*") if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertFalse(self.lib.roms.exists() and any(self.lib.roms.iterdir()))


class SuccessTests(ReceiveTestCase):
    def test_everything_appears_at_once_with_the_sent_mtimes(self):
        transfer = self.transfer(self.full_game())
        for item_id in "rst":
            self.put(transfer, item_id)
            self.assertEqual(self.visible(), [])
        self.put(transfer, "c")
        self.assertEqual(self.visible(), [
            "roms/SFC/Game.sfc", "roms/SFC/Game.srm", "roms/SFC/covers/Game.png", "states/SFC/Game.state1",
        ])
        self.assertEqual((self.lib.roms / "SFC" / "Game.sfc").read_bytes(), DATA["r"])
        self.assertEqual(os.stat(self.lib.roms / "SFC" / "Game.srm").st_mtime, 1600)
        [result] = self.done
        self.assertEqual((result["status"], len(result["placed"]), result["replaced"], result["skipped"]),
                         ("done", 4, [], []))
        self.assertEqual(transfer.status, receive.STATUS_DONE)
        self.assertEqual(self.aborted, [])

    def test_a_replaced_save_is_reported_and_the_old_one_removed(self):
        self.lib.file("roms/SFC/Game.sfc", DATA["r"])
        self.lib.file("roms/SFC/Game.srm", b"old save", mtime=1000)
        transfer = self.transfer(self.full_game())
        for item_id in "stc":
            self.put(transfer, item_id)
        result = self.done[0]
        self.assertEqual(result["replaced"], [str(self.lib.roms / "SFC" / "Game.srm")])
        self.assertEqual(result["skipped"], [{"item_id": "r", "reason": "exists_skip"}])
        self.assertEqual((self.lib.roms / "SFC" / "Game.srm").read_bytes(), DATA["s"])
        self.assertEqual(list((self.lib.roms / "SFC").glob(".*")), [])

    def test_a_replaced_file_that_cannot_be_removed_is_kept_aside(self):
        self.lib.file("roms/SFC/Game.sfc", DATA["r"])
        self.lib.file("roms/SFC/Game.srm", b"old save", mtime=1000)
        transfer = self.transfer(self.full_game(), plan_kwargs={"unchecked": {"t", "c"}})
        real_unlink = receive.Path.unlink

        def unlink(path, *args, **kwargs):
            if ".share-old-" in path.name:
                raise OSError("busy")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(receive.Path, "unlink", unlink), self.assertLogs(receive.logger, "WARNING"):
            self.put(transfer, "s")
        self.assertEqual(self.done[0]["status"], "done")

    def test_nothing_to_send_finishes_at_start(self):
        transfer = self.transfer(self.full_game(), plan_kwargs={"unchecked": {"g1"}})
        transfer.start()
        self.assertEqual(self.done[0]["status"], "done")
        transfer.start()
        self.assertEqual(len(self.done), 1)


class MetadataTests(ReceiveTestCase):
    METADATA = {"favorite": True, "cartridge_color": "black", "core": "Snes9x", "shader": "crt-easymode"}

    def receive_all(self, transfer, ids="rstc"):
        for item_id in ids:
            self.put(transfer, item_id)

    def test_a_new_rom_gets_all_of_it(self):
        self.receive_all(self.transfer(self.full_game(self.METADATA)))
        self.assertEqual(self.hooks.calls, [
            ("favorite", "Game.sfc"), ("color", "Game.sfc", "SFC", "black"),
            ("core", "Game.sfc", core_file("snes9x")), ("shader", "Game.sfc", "SFC", "crt-easymode"),
        ])

    def test_unknown_values_are_ignored(self):
        metadata = {"favorite": "yes", "cartridge_color": "onyx", "core": "Nope", "shader": "unknown"}
        self.receive_all(self.transfer(self.full_game(metadata)))
        self.assertEqual(self.hooks.calls, [])
        self.hooks.calls.clear()
        self.lib = temp_library(self)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})
        self.receive_all(self.transfer(self.full_game(self.METADATA), shader_ids=None))
        self.assertNotIn("shader", [call[0] for call in self.hooks.calls])

    def test_an_existing_rom_only_becomes_a_favorite(self):
        self.lib.file("roms/SFC/Game.sfc", DATA["r"])
        self.receive_all(self.transfer(self.full_game(self.METADATA)), "stc")
        self.assertEqual(self.hooks.calls, [("favorite", "Game.sfc")])

    def test_a_replaced_rom_gets_none(self):
        self.lib.file("roms/SFC/Game.sfc", b"older", mtime=1)
        transfer = self.transfer(self.full_game(self.METADATA), plan_kwargs={"overrides": {"r": "newest"}})
        self.receive_all(transfer)
        self.assertEqual(self.hooks.calls, [])

    def test_a_failing_hook_is_logged_not_fatal(self):
        self.hooks.set_favorite = mock.Mock(side_effect=RuntimeError("bug"))
        with self.assertLogs(receive.logger, "ERROR"):
            self.receive_all(self.transfer(self.full_game(self.METADATA)))
        self.assertEqual(self.done[0]["status"], "done")

    def test_the_default_hooks_do_nothing(self):
        hooks = LibraryHooks()
        self.assertIsNone(hooks.set_favorite("x"))
        self.assertIsNone(hooks.set_cartridge_color("x", "SFC", "black"))
        self.assertIsNone(hooks.set_core("x", "core"))
        self.assertIsNone(hooks.set_shader("x", "SFC", "crt"))
        plan = plan_receive(manifest(game([])), roms_dir=self.lib.roms, states_dir=self.lib.states,
                            catalog=self.catalog)
        self.assertIsInstance(IncomingTransfer("o", plan, catalog=self.catalog).hooks, LibraryHooks)


class RefusedUploadTests(ReceiveTestCase):
    def test_uploads_the_plan_does_not_expect(self):
        self.lib.file("roms/SFC/Game.png", PNG_BYTES)
        transfer = self.transfer(self.full_game(), plan_kwargs={"unchecked": {"c"}})
        self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "nope", b"x")
        self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "c")
        self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "r", length=3)
        self.put(transfer, "r")
        self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "r")
        self.assertEqual(transfer.status, receive.STATUS_RECEIVING)
        self.put(transfer, "s")
        self.put(transfer, "t")
        self.assertEqual(self.done[0]["status"], "done")

    def test_an_upload_already_in_progress(self):
        transfer = self.transfer(self.full_game())
        self.assertShareError(
            ErrorCode.BAD_REQUEST, self.put, transfer, "r",
            during=lambda: self.put(transfer, "r"),
        )


class AbortTests(ReceiveTestCase):
    def assertAborted(self, transfer, error):
        self.assertEqual(transfer.status, receive.STATUS_FAILED)
        self.assertEqual((self.done[0]["status"], self.done[0]["error"]), ("failed", error))
        self.assertEqual(self.aborted, ["offer1"])
        self.assertClean()

    def test_short_upload(self):
        transfer = self.transfer(self.full_game())
        self.put(transfer, "r")
        with self.assertLogs(receive.logger, "WARNING"):
            self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "s", b"bat", length=7)
        self.assertAborted(transfer, ErrorCode.BAD_REQUEST)
        self.assertShareError(ErrorCode.CANCELLED, self.put, transfer, "t")

    def test_sha256_mismatch(self):
        transfer = self.transfer(self.full_game())
        with self.assertLogs(receive.logger, "WARNING"):
            self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "r", b"ROM BYTES")
        self.assertAborted(transfer, ErrorCode.BAD_REQUEST)

    def test_art_that_is_not_an_image(self):
        m = manifest(game([item("r", "rom", "Game.sfc", DATA["r"]),
                           item("c", "cover", "Game.png", b"<html>" * 20, hashed=False)]))
        transfer = self.transfer(m)
        self.put(transfer, "r")
        with self.assertLogs(receive.logger, "WARNING"):
            self.assertShareError(ErrorCode.BAD_REQUEST, self.put, transfer, "c", b"<html>" * 20)
        self.assertAborted(transfer, ErrorCode.BAD_REQUEST)

    def test_disk_full_and_other_write_failures(self):
        for exc, code in (
            (OSError(errno.ENOSPC, "No space left on device"), ErrorCode.NO_SPACE),
            (ConnectionResetError("reset"), ErrorCode.UNREACHABLE),
            (TimeoutError("timed out"), ErrorCode.UNREACHABLE),
            (OSError(errno.EIO, "I/O error"), ErrorCode.INTERNAL),
        ):
            self.done.clear()
            self.aborted.clear()
            transfer = self.transfer(self.full_game())
            with mock.patch.object(receive, "stage_stream", side_effect=exc), \
                    self.assertLogs(receive.logger, "WARNING"):
                self.assertShareError(code, self.put, transfer, "r")
            self.assertAborted(transfer, code)

    def test_cancel_by_the_receiver_mid_file(self):
        transfer = self.transfer(self.full_game())
        self.put(transfer, "r")
        self.assertShareError(ErrorCode.CANCELLED, self.put, transfer, "s", during=transfer.cancel)
        self.assertEqual((transfer.status, self.aborted), (receive.STATUS_CANCELLED, ["offer1"]))
        self.assertEqual(self.done[0]["error"], ErrorCode.CANCELLED)
        self.assertClean()
        transfer.cancel()
        transfer.on_remote_cancel()
        self.assertEqual(len(self.done), 1)

    def test_cancel_by_the_sender_between_files(self):
        transfer = self.transfer(self.full_game())
        self.put(transfer, "r")
        transfer.on_remote_cancel()
        self.assertEqual((self.done[0]["status"], self.aborted), ("cancelled", []))
        self.assertClean()

    def test_cancel_landing_as_an_upload_finishes(self):
        transfer = self.transfer(self.full_game())
        self.assertShareError(ErrorCode.CANCELLED, self.put, transfer, "r", at_end=transfer.on_remote_cancel)
        self.assertClean()

    def test_a_unit_folder_created_for_the_transfer_is_removed(self):
        unit = {"unit": "g1"}
        m = manifest(game([
            item("c", "rom", "Game.cue", b"cue", part={**unit, "role": "cue"}),
            item("b", "rom", "Track 1.bin", b"bin", part={**unit, "role": "bin"}),
        ], console="PS"))
        transfer = self.transfer(m)
        self.put(transfer, "c", b"cue")
        self.assertTrue((self.lib.roms / "PS" / "Game").is_dir())
        transfer.cancel()
        self.assertFalse(self.lib.roms.exists())

    def test_idle_timeout(self):
        transfer = self.transfer(self.full_game())
        self.put(transfer, "r")
        self.assertFalse(transfer.sweep(self.clock.now + 30))
        self.assertTrue(transfer.sweep(self.clock.now + 31))
        self.assertAborted(transfer, ErrorCode.IDLE_TIMEOUT)
        self.assertTrue(transfer.sweep(self.clock.now + 100))

    def test_the_watchdog(self):
        transfer = self.transfer(self.full_game())
        transfer.start_watchdog(interval=0.01)
        self.clock.now += 60
        deadline = time.monotonic() + 5
        while not self.done and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.done[0]["error"], ErrorCode.IDLE_TIMEOUT)


class CommitFailureTests(ReceiveTestCase):
    def test_a_target_taken_after_the_plan_rolls_everything_back(self):
        original = b"local save, older"
        self.lib.file("roms/SFC/Game.srm", original, mtime=1000)
        transfer = self.transfer(self.full_game())
        for item_id in "rst":
            self.put(transfer, item_id)
        # Someone saved a cover in the meantime: the last commit step fails.
        self.lib.file("roms/SFC/covers/Game.png", PNG_BYTES)
        with self.assertLogs(receive.logger, "WARNING"):
            self.assertShareError(ErrorCode.INTERNAL, self.put, transfer, "c")
        self.assertEqual(self.done[0]["status"], "failed")
        self.assertEqual(self.aborted, ["offer1"])
        self.assertEqual((self.lib.roms / "SFC" / "Game.srm").read_bytes(), original)
        self.assertEqual(os.stat(self.lib.roms / "SFC" / "Game.srm").st_mtime, 1000)
        self.assertEqual([p for p in self.lib.tree() if not p.startswith("cores/")],
                         ["roms/SFC/Game.srm", "roms/SFC/covers/Game.png"])
        self.assertEqual([p for p in self.lib.root.rglob("*") if p.name.endswith(".tmp")], [])

    def test_a_rollback_that_cannot_undo_is_logged(self):
        self.lib.file("roms/SFC/Game.srm", b"old", mtime=1000)
        transfer = self.transfer(self.full_game())
        for item_id in "rst":
            self.put(transfer, item_id)
        self.lib.file("roms/SFC/covers/Game.png", PNG_BYTES)
        real_replace = os.replace

        def replace(src, dst):
            if ".share-old-" in str(src):
                raise OSError("stuck")
            return real_replace(src, dst)

        real_unlink = receive.Path.unlink

        def unlink(path, *args, **kwargs):
            if not path.name.startswith("."):
                raise OSError("stuck")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(receive.Path, "unlink", unlink), \
                mock.patch.object(receive.os, "replace", replace), \
                self.assertLogs(receive.logger, "ERROR") as logs:
            self.assertShareError(ErrorCode.INTERNAL, self.put, transfer, "c")
        self.assertTrue(any("on rollback" in line for line in logs.output))


class ProgressTests(ReceiveTestCase):
    def test_throttled_with_a_final_call_per_file(self):
        m = manifest(game([item("r", "rom", "Game.sfc", b"x" * (3 * receive.READ_CHUNK))]))
        transfer = self.transfer(m)
        self.put(transfer, "r", b"x" * (3 * receive.READ_CHUNK))
        self.assertEqual(len(self.progress), 2)
        self.assertEqual(self.progress[-1], {
            "item_id": "r", "name": "Game.sfc", "kind": "rom", "bytes": 3 * receive.READ_CHUNK,
            "size": 3 * receive.READ_CHUNK, "done_bytes": 3 * receive.READ_CHUNK,
            "total_bytes": 3 * receive.READ_CHUNK, "files_done": 1, "file_count": 1,
        })
        clock_steps = iter(range(100))
        self.progress.clear()
        transfer = self.transfer(manifest(game([item("r", "rom", "Other.sfc", b"x" * (3 * receive.READ_CHUNK))])))
        transfer.clock = lambda: next(clock_steps)
        self.put(transfer, "r", b"x" * (3 * receive.READ_CHUNK))
        self.assertEqual(len(self.progress), 4)

    def test_without_a_listener(self):
        transfer = self.transfer(self.full_game())
        transfer.on_progress = None
        transfer.on_done = None
        transfer.on_abort = None
        for item_id in "rstc":
            self.put(transfer, item_id)
        self.assertEqual(transfer.status, receive.STATUS_DONE)
        transfer = self.transfer(self.full_game())
        transfer.on_abort = None
        transfer.cancel()


class HousekeepingTests(ReceiveTestCase):
    def test_stale_temp_files_are_removed_from_the_target_dirs(self):
        old = self.lib.file("roms/SFC/.Game.sfc.abc.tmp")
        fresh = self.lib.file("roms/SFC/.Other.sfc.def.tmp")
        kept = self.lib.file("roms/SFC/notes.tmp")
        os.utime(old, (1, 1))
        self.lib.file("roms/SFC/.dir.tmp/x")
        os.utime(self.lib.roms / "SFC" / ".dir.tmp", (1, 1))
        self.transfer(self.full_game())
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists() and kept.exists())
        self.assertTrue((self.lib.roms / "SFC" / ".dir.tmp").is_dir())

    def test_a_stale_temp_that_cannot_be_read(self):
        temp = self.lib.file("roms/SFC/.Game.sfc.abc.tmp")
        real_stat = receive.Path.stat

        def stat(path, *args, **kwargs):
            if path.name.endswith(".tmp") and not kwargs and not args:
                raise OSError("gone")
            return real_stat(path, *args, **kwargs)

        with mock.patch.object(receive.Path, "stat", stat):
            self.transfer(self.full_game())
        self.assertTrue(temp.exists())

    def test_a_staged_file_is_invisible_to_the_scanner_and_the_save_finder(self):
        temp = self.lib.file("roms/SFC/.Game.sfc.abc.tmp", b"partial")
        self.lib.file("roms/SFC/.Game.srm.def.tmp", b"partial")
        self.assertEqual(RomScanner(self.lib.roms).scan_console("SFC"), [])
        self.assertFalse(is_battery_save(temp, "SFC"))
        self.assertFalse(is_battery_save(self.lib.roms / "SFC" / ".Game.srm.def.tmp", "SFC"))


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest import mock

from openemux.core import cores, window_title


class TitleTextTests(unittest.TestCase):
    def test_strips_extension_and_tags(self):
        self.assertEqual(window_title.game_title("/r/Chrono Trigger (USA) [!].smc"), "Chrono Trigger")
        self.assertEqual(window_title.game_title("/r/Asterix.smc"), "Asterix")

    def test_a_name_that_is_all_tags_keeps_its_stem(self):
        self.assertEqual(window_title.game_title("/r/(Proto).nes"), "(Proto)")

    def test_core_name_comes_from_the_info_file(self):
        with mock.patch.object(cores, "parse_core_info", return_value={"corename": "Snes9x"}) as info:
            self.assertEqual(window_title.core_name("/c/snes9x_libretro.so"), "Snes9x")
        info.assert_called_once_with(Path("/c/snes9x_libretro.info"))

    def test_core_name_falls_back_to_the_filename(self):
        with mock.patch.object(cores, "parse_core_info", return_value={}):
            self.assertEqual(window_title.core_name("/c/mesen_libretro.so"), "Mesen")

    @mock.patch.object(cores, "parse_core_info", return_value={})
    def test_compose(self, _info):
        self.assertEqual(
            window_title.compose("/r/Asterix.smc", "/nowhere/mesen_libretro.so"),
            "Asterix — Mesen · RetroArch",
        )


class _Proc:
    """Alive for ``ticks`` polls, then gone."""

    def __init__(self, ticks, pid=42):
        self.pid = pid
        self._ticks = ticks

    def poll(self):
        if self._ticks > 0:
            self._ticks -= 1
            return None
        return 0


class KeepTitleTests(unittest.TestCase):
    def test_finds_the_window_and_puts_the_title_back(self):
        # A fake X server: two windows (a fullscreen toggle swaps them).
        names = {7: "RetroArch Snes9x 1.63", 8: "RetroArch Snes9x 1.63"}
        found = iter([None, 7, 7, 7, 8, None, 8])
        ticks = iter([
            lambda: None,
            # RetroArch puts its own title back.
            lambda: names.update({7: "RetroArch Snes9x 1.63"}),
            lambda: None,
            lambda: None,
            lambda: None,
        ])
        embedder = mock.Mock()
        embedder.find_game_window.side_effect = lambda pid: next(found)
        embedder.window_title.side_effect = lambda xid: names[xid]
        embedder.set_window_title.side_effect = lambda xid, title: names.update({xid: title})

        def sleep(_seconds):
            next(ticks, lambda: None)()

        window_title.keep_title(_Proc(7), "T", embedder_factory=lambda: embedder, sleep=sleep)
        embedder.find_game_window.assert_called_with(42)
        self.assertEqual([c.args[0] for c in embedder.set_window_title.call_args_list], [7, 7, 8])
        self.assertEqual(names, {7: "T", 8: "T"})
        # The windows already on screen are noted before looking for ours.
        embedder.snapshot_existing.assert_called_once_with()
        embedder.close.assert_called_once()

    def test_gives_up_when_no_window_appears(self):
        embedder = mock.Mock()
        embedder.find_game_window.return_value = None
        with mock.patch.object(window_title, "FIND_TIMEOUT_SECONDS", 0.5):
            window_title.keep_title(_Proc(100), "T", embedder_factory=lambda: embedder,
                                    sleep=lambda s: None)
        embedder.set_window_title.assert_not_called()
        embedder.close.assert_called_once()

    def test_start_needs_xlib_and_a_core(self):
        with mock.patch.object(window_title, "XLIB_AVAILABLE", False):
            self.assertIsNone(window_title.start(_Proc(0), "/r/a.smc", "/c/x_libretro.so"))
        self.assertIsNone(window_title.start(_Proc(0), "/r/a.smc", None))

    def test_start_runs_on_a_daemon_thread(self):
        with mock.patch.object(window_title, "XLIB_AVAILABLE", True), \
                mock.patch.object(window_title, "keep_title") as keep:
            thread = window_title.start(_Proc(0), "/r/a.smc", "/c/x_libretro.so")
            thread.join(1)
        self.assertTrue(thread.daemon)
        keep.assert_called_once()


if __name__ == "__main__":
    unittest.main()

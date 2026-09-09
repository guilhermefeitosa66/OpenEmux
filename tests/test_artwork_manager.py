"""The per-ROM artwork manager (issue #77), end to end in widgets.

`ui/artwork_manager.py` sat at 0%: no test file imported it at all, while it
owns three decisions a user notices immediately -- which search result is the
picked one, what a crop rectangle means in pixbuf pixels, and whether "Save"
wrote anything. All three are guarded by `if`s that only run once the widgets
exist, so this builds the real window against a stand-in main window and drives
it.

The search itself is never let out: `search_artwork_async` and
`suggest_artwork_async` are replaced, so nothing here touches the network and
the sequence-number logic (a stale result must be dropped) can be exercised on
demand rather than by racing a thread.
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

    Adw.init()

    from openemux.core import artwork_search
    from openemux.core.hasher import compute_crc32
    from openemux.core.scraper import COVER_ART, LABEL_ART
    from openemux.ui import artwork_manager
    from openemux.ui.artwork_manager import ArtworkManagerWindow, _PreviewArea


class _Candidate:
    """Same three attributes `ArtworkCandidate` carries, without the download."""

    def __init__(self, path, provider="libretro", title=None):
        self.path = Path(path)
        self.provider = provider
        self.url = f"https://example.invalid/{Path(path).name}"
        self.title = title


class _ConfigManager:
    def __init__(self):
        self.settings = {"enabled": True}

    def get_cover_sync_settings(self):
        return dict(self.settings)


#: Every picker the import tab opens registers itself here, so a test can
#: reach the one it just caused and answer it.
_dialog_instances = []


def _gio_file(path):
    return Gio.File.new_for_path(str(path))


def _wait_for(predicate, timeout=5.0):
    """Block until a worker thread has done its one job, or give up.

    The hash runs on a thread the tab starts itself; polling is what keeps the
    assertion from racing it without the test having to reach inside.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError("the worker never reported back")


def _write_png(path, width=40, height=60, colour=0xFF0000FF):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(colour)
    pixbuf.savev(str(path), "png", [], [])
    return Path(path)


class _MainWindow(Gtk.Window):
    """Only what the artwork manager reaches for on its parent window.

    A real `Gtk.Window`, because the manager passes it as `transient_for` and
    hands it to `Gtk.FileDialog.open()`; everything else is recorded.
    """

    def __init__(self, roms_path):
        super().__init__()
        self.config_manager = _ConfigManager()
        self.roms_path = str(roms_path)
        self.toasts = []
        self.refreshed = []

    def t(self, key, **kwargs):
        return key

    def _toast(self, text):
        self.toasts.append(text)

    def refresh_rom_artwork(self, rom):
        self.refreshed.append(rom)


class _ArtworkManagerCase(unittest.TestCase):
    """Builds a real manager window over a throwaway library."""

    label_supported = True
    art_dir = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.roms = self.tmp / "roms"
        self.roms.mkdir()
        self.temp_root = self.tmp / "cache"

        patcher = mock.patch.object(
            artwork_search, "artwork_temp_root", lambda: self.temp_root
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.searches = []
        self.suggestions = []
        search_patch = mock.patch.object(
            artwork_search, "search_artwork_async", lambda **kw: self.searches.append(kw)
        )
        search_patch.start()
        self.addCleanup(search_patch.stop)
        suggest_patch = mock.patch.object(
            artwork_search,
            "suggest_artwork_async",
            lambda **kw: self.suggestions.append(kw),
        )
        suggest_patch.start()
        self.addCleanup(suggest_patch.stop)

        self.win = _MainWindow(self.roms)
        self.addCleanup(self.win.destroy)
        self.rom = {"name": "Chrono Trigger", "console": "SFC", "path": ""}
        kwargs = {"label_supported": self.label_supported}
        if self.art_dir is not None:
            kwargs["art_dir"] = self.art_dir
        self.manager = ArtworkManagerWindow(self.win, self.rom, **kwargs)
        self.addCleanup(self.manager.destroy)

    def cover_tab(self):
        return self.manager.cover_tab

    def add_result(self, tab, candidate, size=(40, 60)):
        """Push a decoded candidate into the results grid, as a search would."""
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, size[0], size[1]
        )
        pixbuf.fill(0x00FF00FF)
        tab._add_result(tab._search_seq, candidate, pixbuf, size[0], size[1])
        return tab.results.get_child_at_index(len(tab._candidates) - 1)


@needs_display
class TheWindowIsBuiltFromWhatTheConsoleSupportsTests(_ArtworkManagerCase):
    def test_a_console_with_labels_gets_all_three_tabs(self):
        self.assertIsNotNone(self.manager.label_tab)
        names = []
        for page in self.manager.stack.get_pages():
            names.append(page.get_name())
        self.assertEqual(names, ["cover", "label", "import"])

    def test_the_cover_tab_is_the_one_that_opens(self):
        self.assertEqual(self.manager.stack.get_visible_child_name(), "cover")

    def test_the_scratch_directory_exists_for_the_downloads_to_land_in(self):
        self.assertTrue(self.manager.temp_dir.is_dir())
        self.assertEqual(self.manager.temp_dir.parent, self.temp_root)

    def test_the_hash_search_waits_for_a_hash_before_it_can_be_used(self):
        self.assertFalse(self.cover_tab().by_hash_btn.get_sensitive())

    def test_a_toast_is_forwarded_to_the_main_window(self):
        self.manager.toast("hello")
        self.assertEqual(self.win.toasts, ["hello"])


@needs_display
class AConsoleWithoutLabelsTests(_ArtworkManagerCase):
    label_supported = False

    def test_the_label_tab_is_not_offered_at_all(self):
        self.assertIsNone(self.manager.label_tab)
        names = [page.get_name() for page in self.manager.stack.get_pages()]
        self.assertEqual(names, ["cover", "import"])

    def test_the_import_destination_offers_covers_only(self):
        self.assertEqual(self.manager.import_tab._dest_dirs, [COVER_ART])

    def test_asking_for_the_label_destination_leaves_covers_selected(self):
        # Nothing to switch to: a console with no label art must not end up
        # with the dropdown pointing past the end of its own model.
        self.manager.import_tab.set_default_destination(LABEL_ART)
        self.assertEqual(self.manager.import_tab.destination_dir(), COVER_ART)


@needs_display
class OpenedOnTheLabelTests(_ArtworkManagerCase):
    art_dir = LABEL_ART

    def test_the_label_tab_is_the_one_showing(self):
        # Right-clicking "Change label" must land on the label tab, not make
        # the user find it.
        self.assertEqual(self.manager.stack.get_visible_child_name(), "label")

    def test_the_import_destination_follows_the_same_choice(self):
        self.assertEqual(self.manager.import_tab.destination_dir(), LABEL_ART)


@needs_display
class TheSearchTabTests(_ArtworkManagerCase):
    def test_searching_by_name_passes_the_typed_name_not_the_rom_name(self):
        tab = self.cover_tab()
        tab.name_entry.set_text("  Chrono Trigger (USA)  ")
        tab._start_search(by_hash=False)
        self.assertEqual(len(self.searches), 1)
        self.assertEqual(self.searches[0]["rom_name"], "Chrono Trigger (USA)")
        self.assertIsNone(self.searches[0]["rom_path"])

    def test_an_empty_name_field_falls_back_to_the_rom(self):
        tab = self.cover_tab()
        tab.name_entry.set_text("   ")
        tab._start_search(by_hash=False)
        self.assertEqual(self.searches[0]["rom_name"], "Chrono Trigger")

    def test_searching_by_hash_hands_over_the_rom_path(self):
        self.manager.rom["path"] = str(self.tmp / "game.sfc")
        self.cover_tab()._start_search(by_hash=True)
        self.assertEqual(self.searches[0]["rom_path"], str(self.tmp / "game.sfc"))

    def test_a_running_search_locks_its_own_buttons_and_offers_a_way_out(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        self.assertTrue(tab.cancel_btn.get_visible())
        self.assertFalse(tab.by_name_btn.get_sensitive())
        self.assertFalse(tab.suggest_btn.get_sensitive())

    def test_cancelling_stops_the_search_and_says_so(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        seq = tab._search_seq
        tab._cancel_search()
        self.assertGreater(tab._search_seq, seq)
        self.assertFalse(tab.cancel_btn.get_visible())
        self.assertEqual(tab.status.get_text(), "artwork.search.cancelled")

    def test_the_cancel_makes_the_running_search_ask_to_stop(self):
        # The worker only knows it was cancelled through should_cancel; the
        # sequence bump is the whole mechanism.
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        should_cancel = self.searches[0]["should_cancel"]
        self.assertFalse(should_cancel())
        tab._cancel_search()
        self.assertTrue(should_cancel())

    def test_a_closed_window_also_stops_the_search(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        self.manager.closed = True
        self.assertTrue(self.searches[0]["should_cancel"]())

    def test_starting_a_search_clears_what_the_last_one_found(self):
        tab = self.cover_tab()
        self.add_result(tab, _Candidate(_write_png(self.tmp / "a.png")))
        tab._start_search(by_hash=False)
        self.assertEqual(tab._candidates, {})
        self.assertIsNone(tab.results.get_child_at_index(0))

    def test_a_hash_that_arrives_arms_the_hash_button(self):
        tab = self.cover_tab()
        tab._set_hash("DEADBEEF")
        self.assertEqual(tab.hash_entry.get_text(), "DEADBEEF")
        self.assertTrue(tab.by_hash_btn.get_sensitive())

    def test_a_hash_landing_mid_search_does_not_re_arm_the_button(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        tab._set_hash("DEADBEEF")
        self.assertFalse(tab.by_hash_btn.get_sensitive())

    def test_an_unreadable_rom_leaves_the_hash_field_empty(self):
        tab = self.cover_tab()
        tab._set_hash("")
        self.assertEqual(tab.hash_entry.get_text(), "")
        self.assertFalse(tab.by_hash_btn.get_sensitive())

    def test_the_hash_of_a_real_rom_is_computed_off_the_main_thread(self):
        rom_file = self.tmp / "game.sfc"
        rom_file.write_bytes(b"cartridge contents")
        self.manager.rom["path"] = str(rom_file)
        tab = self.cover_tab()
        with mock.patch.object(artwork_manager.GLib, "idle_add") as idle_add:
            tab._prefill_hash()
            _wait_for(lambda: idle_add.call_count == 1)
        callback, digest = idle_add.call_args[0]
        self.assertEqual(callback, tab._set_hash)
        self.assertEqual(digest, compute_crc32(rom_file))

    def test_a_rom_that_cannot_be_read_yields_an_empty_hash(self):
        self.manager.rom["path"] = str(self.tmp / "gone.sfc")
        tab = self.cover_tab()
        with mock.patch.object(artwork_manager.GLib, "idle_add") as idle_add:
            tab._prefill_hash()
            _wait_for(lambda: idle_add.call_count == 1)
        self.assertEqual(idle_add.call_args[0][1], "")

    def test_a_rom_with_no_path_never_starts_the_hash_worker(self):
        # _prefill_hash returns before the thread; the placeholder going empty
        # is how it says there is nothing to compute.
        tab = self.cover_tab()
        tab.hash_entry.set_placeholder_text("computing")
        tab._prefill_hash()
        self.assertEqual(tab.hash_entry.get_placeholder_text(), "")


@needs_display
class TheResultsGridTests(_ArtworkManagerCase):
    def setUp(self):
        super().setUp()
        self.tab = self.cover_tab()

    def test_the_first_result_is_selected_so_save_always_has_a_target(self):
        candidate = _Candidate(_write_png(self.tmp / "a.png"))
        self.add_result(self.tab, candidate)
        self.assertIs(self.tab.selected_candidate(), candidate)

    def test_the_selected_result_is_the_only_one_wearing_the_check(self):
        first = self.add_result(self.tab, _Candidate(_write_png(self.tmp / "a.png")))
        second = self.add_result(self.tab, _Candidate(_write_png(self.tmp / "b.png")))
        self.assertTrue(first.check.get_visible())
        self.assertFalse(second.check.get_visible())
        self.assertTrue(first.card.has_css_class("rom-card-selected"))

        self.tab.results.select_child(second)
        self.tab._sync_selection_marks()
        self.assertFalse(first.check.get_visible())
        self.assertTrue(second.check.get_visible())
        self.assertFalse(first.card.has_css_class("rom-card-selected"))
        self.assertTrue(second.card.has_css_class("rom-card-selected"))

    def test_a_suggestion_names_the_canonical_stem_on_its_card(self):
        candidate = _Candidate(
            _write_png(self.tmp / "a.png"),
            provider=artwork_search.SUGGESTION_MODE_FTS,
            title="Chrono Trigger (USA)",
        )
        child = self.add_result(self.tab, candidate)
        labels = []
        card = child.get_child()
        widget = card.get_first_child()
        while widget is not None:
            if isinstance(widget, Gtk.Label):
                labels.append(widget.get_text())
            widget = widget.get_next_sibling()
        self.assertIn("Chrono Trigger (USA)", labels)

    def test_a_result_from_a_search_that_was_replaced_is_dropped(self):
        self.tab._search_seq = 5
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 10, 10)
        self.tab._add_result(4, _Candidate(self.tmp / "a.png"), pixbuf, 10, 10)
        self.assertIsNone(self.tab.results.get_child_at_index(0))

    def test_nothing_selected_means_no_candidate(self):
        self.assertIsNone(self.tab.selected_candidate())

    def test_a_decoded_result_reaches_the_grid(self):
        path = _write_png(self.tmp / "a.png")
        with mock.patch.object(GLib, "idle_add", lambda fn, *a: fn(*a)):
            self.tab._decode_result(self.tab._search_seq, _Candidate(path))
        self.assertIsNotNone(self.tab.results.get_child_at_index(0))

    def test_a_stale_decode_never_touches_the_cover_cache(self):
        with mock.patch.object(artwork_manager.cover_cache, "load_cover") as load:
            self.tab._decode_result(self.tab._search_seq - 1, _Candidate("x.png"))
        load.assert_not_called()

    def test_a_decode_after_the_window_closed_is_dropped(self):
        self.manager.closed = True
        with mock.patch.object(artwork_manager.cover_cache, "load_cover") as load:
            self.tab._decode_result(self.tab._search_seq, _Candidate("x.png"))
        load.assert_not_called()

    def test_an_undecodable_pixbuf_adds_no_card(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 10, 10)
        with mock.patch.object(
            artwork_manager.Gdk.Texture,
            "new_for_pixbuf",
            side_effect=GLib.Error("bad texture"),
        ):
            self.tab._add_result(
                self.tab._search_seq, _Candidate("x.png"), pixbuf, 10, 10
            )
        self.assertIsNone(self.tab.results.get_child_at_index(0))

    def test_a_child_the_grid_did_not_build_is_skipped_when_marking(self):
        # Nothing else puts a plain child in there, but _sync_selection_marks
        # walks whatever the FlowBox holds and must not assume a card.
        self.add_result(self.tab, _Candidate(_write_png(self.tmp / "a.png")))
        self.tab.results.append(Gtk.FlowBoxChild())
        self.tab._sync_selection_marks()

    def test_an_image_the_cache_cannot_decode_adds_no_card(self):
        with mock.patch.object(
            artwork_manager.cover_cache, "load_cover", return_value=None
        ):
            self.tab._decode_result(self.tab._search_seq, _Candidate("x.png"))
        self.assertIsNone(self.tab.results.get_child_at_index(0))


@needs_display
class WhenTheSearchFinishesTests(_ArtworkManagerCase):
    def test_a_search_that_found_something_reports_the_count(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        tab._search_done(tab._search_seq, 3)
        self.assertEqual(tab.status.get_text(), "artwork.search.found")
        self.assertFalse(tab.cancel_btn.get_visible())

    def test_an_empty_cover_search_falls_through_to_the_suggestions(self):
        # Issue #185: coming up empty is exactly what the name-base
        # suggestions exist for, so the user never sees a dead end.
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        tab._search_done(tab._search_seq, 0)
        self.assertEqual(len(self.suggestions), 1)

    def test_an_empty_label_search_just_says_so(self):
        # The mirror behind the suggestions carries no cartridge labels, so
        # there is nothing to fall through to.
        tab = self.manager.label_tab
        tab._start_search(by_hash=False)
        tab._search_done(tab._search_seq, 0)
        self.assertEqual(tab.status.get_text(), "artwork.search.none")
        self.assertEqual(self.suggestions, [])

    def test_a_result_from_a_superseded_search_changes_nothing(self):
        tab = self.cover_tab()
        tab._start_search(by_hash=False)
        tab.status.set_text("kept")
        tab._search_done(tab._search_seq - 1, 7)
        self.assertEqual(tab.status.get_text(), "kept")


@needs_display
class TheNameBaseSuggestionsTests(_ArtworkManagerCase):
    def setUp(self):
        super().setUp()
        self.tab = self.cover_tab()

    def test_the_typed_name_is_what_gets_looked_up(self):
        self.tab.name_entry.set_text(" Chrono ")
        self.tab._start_suggestions()
        self.assertEqual(self.suggestions[0]["query"], "Chrono")

    def test_an_empty_field_falls_back_to_the_rom_name(self):
        self.tab.name_entry.set_text("")
        self.tab._start_suggestions()
        self.assertEqual(self.suggestions[0]["query"], "Chrono Trigger")

    def test_asking_for_suggestions_clears_the_previous_results(self):
        self.add_result(self.tab, _Candidate(_write_png(self.tmp / "a.png")))
        self.tab._start_suggestions()
        self.assertIsNone(self.tab.results.get_child_at_index(0))
        self.assertEqual(self.tab._candidates, {})

    def test_exact_matches_are_reported_plainly(self):
        self.tab._start_suggestions()
        self.tab._suggestions_done(
            self.tab._search_seq, artwork_search.SUGGESTION_MODE_FTS, 4
        )
        self.assertEqual(self.tab.status.get_text(), "artwork.search.suggestions_found")

    def test_approximate_matches_say_that_they_are_approximate(self):
        self.tab._start_suggestions()
        self.tab._suggestions_done(
            self.tab._search_seq, artwork_search.SUGGESTION_MODE_FUZZY, 4
        )
        self.assertEqual(self.tab.status.get_text(), "artwork.search.suggestions_fuzzy")

    def test_no_suggestion_at_all_reports_nothing_found(self):
        self.tab._start_suggestions()
        self.tab._suggestions_done(
            self.tab._search_seq, artwork_search.SUGGESTION_MODE_FTS, 0
        )
        self.assertEqual(self.tab.status.get_text(), "artwork.search.none")

    def test_a_superseded_suggestion_run_is_ignored(self):
        self.tab._start_suggestions()
        self.tab.status.set_text("kept")
        self.tab._suggestions_done(
            self.tab._search_seq - 1, artwork_search.SUGGESTION_MODE_FTS, 4
        )
        self.assertEqual(self.tab.status.get_text(), "kept")


@needs_display
class TheImportTabTests(_ArtworkManagerCase):
    def setUp(self):
        super().setUp()
        self.tab = self.manager.import_tab

    def test_it_opens_on_the_drop_invitation_with_nothing_to_act_on(self):
        self.assertEqual(self.tab.area.get_visible_child_name(), "empty")
        self.assertFalse(self.tab._action_bar.get_sensitive())

    def test_loading_an_image_swaps_in_the_preview(self):
        self.assertTrue(self.tab.load_file(_write_png(self.tmp / "art.png")))
        self.assertEqual(self.tab.area.get_visible_child_name(), "image")
        self.assertTrue(self.tab._action_bar.get_sensitive())
        self.assertIsNotNone(self.tab.pixbuf)

    def test_a_file_that_is_not_an_image_extension_is_refused(self):
        path = self.tmp / "notes.txt"
        path.write_text("not an image")
        self.assertFalse(self.tab.load_file(path))
        self.assertEqual(self.win.toasts, ["toast.cover.invalid_extension"])

    def test_a_png_that_is_not_really_a_png_is_refused_too(self):
        path = self.tmp / "broken.png"
        path.write_bytes(b"nope")
        self.assertFalse(self.tab.load_file(path))
        self.assertEqual(self.win.toasts, ["toast.cover.invalid_extension"])
        self.assertIsNone(self.tab.pixbuf)

    def test_clearing_goes_back_to_the_drop_area(self):
        self.tab.load_file(_write_png(self.tmp / "art.png"))
        self.tab._clear_image()
        self.assertIsNone(self.tab.pixbuf)
        self.assertEqual(self.tab.area.get_visible_child_name(), "empty")
        self.assertFalse(self.tab._action_bar.get_sensitive())

    def test_a_rotation_replaces_the_working_copy_and_leaves_the_file_alone(self):
        source = _write_png(self.tmp / "art.png", width=40, height=60)
        before = source.read_bytes()
        self.tab.load_file(source)
        self.tab._transform(
            lambda p: p.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
        )
        self.assertEqual(self.tab.pixbuf.get_width(), 60)
        self.assertEqual(self.tab.pixbuf.get_height(), 40)
        self.assertEqual(source.read_bytes(), before)

    def test_a_transform_with_no_image_loaded_does_nothing(self):
        self.tab._transform(lambda p: p.flip(True))
        self.assertIsNone(self.tab.pixbuf)

    def test_a_transform_that_fails_keeps_the_previous_image(self):
        self.tab.load_file(_write_png(self.tmp / "art.png"))
        kept = self.tab.pixbuf
        self.tab._transform(lambda _p: None)
        self.assertIs(self.tab.pixbuf, kept)

    def test_reset_brings_back_the_image_as_it_was_loaded(self):
        self.tab.load_file(_write_png(self.tmp / "art.png", width=40, height=60))
        self.tab._transform(
            lambda p: p.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
        )
        self.tab._reset()
        self.assertEqual(self.tab.pixbuf.get_width(), 40)

    def test_reset_with_nothing_loaded_is_harmless(self):
        self.tab._reset()
        self.assertIsNone(self.tab.pixbuf)

    def test_the_crop_toggle_shows_the_apply_button_and_the_rectangle(self):
        self.tab.load_file(_write_png(self.tmp / "art.png"))
        self.tab.crop_toggle.set_active(True)
        self.assertTrue(self.tab.crop_apply.get_visible())
        self.assertTrue(self.tab.preview.crop_mode)
        self.tab.crop_toggle.set_active(False)
        self.assertFalse(self.tab.crop_apply.get_visible())
        self.assertIsNone(self.tab.preview.crop_rect)

    def test_applying_a_crop_with_no_rectangle_leaves_the_image_alone(self):
        self.tab.load_file(_write_png(self.tmp / "art.png", width=40, height=60))
        self.tab._apply_crop()
        self.assertEqual(self.tab.pixbuf.get_width(), 40)

    def test_applying_a_crop_cuts_the_working_copy_down(self):
        self.tab.load_file(_write_png(self.tmp / "art.png", width=40, height=60))
        with mock.patch.object(
            self.tab.preview, "crop_in_pixbuf_coords", return_value=(4, 6, 20, 30)
        ):
            self.tab._apply_crop()
        self.assertEqual(self.tab.pixbuf.get_width(), 20)
        self.assertEqual(self.tab.pixbuf.get_height(), 30)

    def test_choosing_the_label_destination_sticks(self):
        self.tab.set_default_destination(LABEL_ART)
        self.assertEqual(self.tab.destination_dir(), LABEL_ART)

    def test_a_dropped_file_is_loaded(self):
        path = _write_png(self.tmp / "art.png")
        file_list = Gdk.FileList.new_from_array([_gio_file(path)])
        self.assertTrue(self.tab._on_drop(None, file_list, 0, 0))
        self.assertIsNotNone(self.tab.pixbuf)

    def test_dropping_something_that_is_not_a_file_list_is_ignored(self):
        self.assertFalse(self.tab._on_drop(None, object(), 0, 0))

    def test_dropping_a_file_the_tab_cannot_read_reports_no_load(self):
        path = self.tmp / "notes.txt"
        path.write_text("x")
        file_list = Gdk.FileList.new_from_array([_gio_file(path)])
        self.assertFalse(self.tab._on_drop(None, file_list, 0, 0))


@needs_display
class TheFilePickerTests(_ArtworkManagerCase):
    """The picker itself is never opened; only what it hands back matters."""

    class _Dialog:
        instances = []

        def __init__(self):
            self.title = None
            self.accept_label = None
            self.filters = None
            self.default_filter = None
            self.modal = None
            self.callback = None
            _dialog_instances.append(self)

        def set_title(self, value):
            self.title = value

        def set_accept_label(self, value):
            self.accept_label = value

        def set_modal(self, value):
            self.modal = value

        def set_filters(self, value):
            self.filters = value

        def set_default_filter(self, value):
            self.default_filter = value

        def open(self, _parent, _cancellable, callback):
            self.callback = callback

    def setUp(self):
        super().setUp()
        global _dialog_instances
        _dialog_instances = []
        patcher = mock.patch.object(
            artwork_manager.Gtk, "FileDialog", TheFilePickerTests._Dialog
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager.import_tab._choose_file()
        self.dialog = _dialog_instances[0]

    def test_the_picker_is_configured_with_the_translated_strings(self):
        self.assertEqual(self.dialog.title, "artwork.import.add")
        self.assertEqual(self.dialog.accept_label, "dialog.start")
        self.assertTrue(self.dialog.modal)
        self.assertIsNotNone(self.dialog.filters)

    def test_a_chosen_file_is_loaded(self):
        path = _write_png(self.tmp / "art.png")

        class _Result:
            def open_finish(self, _result):
                return _gio_file(path)

        self.dialog.callback(_Result(), None)
        self.assertIsNotNone(self.manager.import_tab.pixbuf)

    def test_dismissing_the_picker_loads_nothing(self):
        class _Dismissed:
            def open_finish(self, _result):
                raise GLib.Error("cancelled")

        self.dialog.callback(_Dismissed(), None)
        self.assertIsNone(self.manager.import_tab.pixbuf)

    def test_a_chosen_uri_with_no_local_path_is_skipped(self):
        class _Remote:
            def open_finish(self, _result):
                return Gio.File.new_for_uri("https://example.invalid/a.png")

        self.dialog.callback(_Remote(), None)
        self.assertIsNone(self.manager.import_tab.pixbuf)


@needs_display
class SavingTests(_ArtworkManagerCase):
    def test_saving_a_picked_cover_writes_it_into_the_library(self):
        tab = self.cover_tab()
        self.add_result(tab, _Candidate(_write_png(self.tmp / "a.png")))
        self.manager._save(close_after=False)
        self.assertTrue((self.roms / "SFC" / COVER_ART / "Chrono Trigger.png").is_file())
        self.assertEqual(self.win.toasts, ["toast.cover.updated"])
        self.assertEqual(self.win.refreshed, [self.rom])

    def test_saving_a_picked_label_says_label_not_cover(self):
        self.manager.stack.set_visible_child_name("label")
        tab = self.manager.label_tab
        self.add_result(tab, _Candidate(_write_png(self.tmp / "a.png")))
        self.manager._save(close_after=False)
        self.assertTrue((self.roms / "SFC" / LABEL_ART / "Chrono Trigger.png").is_file())
        self.assertEqual(self.win.toasts, ["toast.label.updated"])

    def test_saving_with_nothing_picked_says_so_and_writes_nothing(self):
        self.manager._save(close_after=False)
        self.assertEqual(self.win.toasts, ["artwork.toast.nothing_selected"])
        self.assertEqual(self.win.refreshed, [])

    def test_saving_an_imported_image_writes_the_edited_copy(self):
        self.manager.stack.set_visible_child_name("import")
        self.manager.import_tab.load_file(_write_png(self.tmp / "art.png"))
        self.manager._save(close_after=False)
        self.assertTrue((self.roms / "SFC" / COVER_ART / "Chrono Trigger.png").is_file())

    def test_saving_an_import_to_the_label_destination_honours_the_dropdown(self):
        self.manager.stack.set_visible_child_name("import")
        self.manager.import_tab.load_file(_write_png(self.tmp / "art.png"))
        self.manager.import_tab.set_default_destination(LABEL_ART)
        self.manager._save(close_after=False)
        self.assertTrue((self.roms / "SFC" / LABEL_ART / "Chrono Trigger.png").is_file())

    def test_saving_an_empty_import_tab_says_nothing_was_picked(self):
        self.manager.stack.set_visible_child_name("import")
        self.manager._save(close_after=False)
        self.assertEqual(self.win.toasts, ["artwork.toast.nothing_selected"])

    def test_a_failed_write_is_reported_rather_than_raised(self):
        tab = self.cover_tab()
        self.add_result(tab, _Candidate(_write_png(self.tmp / "a.png")))
        with mock.patch.object(
            artwork_manager, "save_local_art", side_effect=OSError("disk full")
        ):
            self.manager._save(close_after=False)
        self.assertEqual(self.win.toasts, ["artwork.toast.save_failed"])
        self.assertEqual(self.win.refreshed, [])

    def test_done_saves_and_closes(self):
        tab = self.cover_tab()
        self.add_result(tab, _Candidate(_write_png(self.tmp / "a.png")))
        with mock.patch.object(self.manager, "close") as close:
            self.manager._save(close_after=True)
        close.assert_called_once()


@needs_display
class ClosingTests(_ArtworkManagerCase):
    def test_closing_removes_the_scratch_directory_and_stops_the_searches(self):
        temp_dir = self.manager.temp_dir
        (temp_dir / "leftover.png").write_bytes(b"x")
        self.assertFalse(self.manager._on_close_request(self.manager))
        self.assertTrue(self.manager.closed)
        self.assertFalse(temp_dir.exists())

    def test_closing_twice_does_not_raise_over_the_gone_directory(self):
        self.manager._on_close_request(self.manager)
        self.manager._on_close_request(self.manager)


@needs_display
class ThePreviewGeometryTests(unittest.TestCase):
    """Crop coordinates, the one place a rounding slip silently ruins a cover."""

    def setUp(self):
        self.area = _PreviewArea()
        self.pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 200, 100)
        self.pixbuf.fill(0x0000FFFF)

    def _sized(self, width, height):
        # The widget is never allocated here, so geometry is asked for
        # explicitly -- exactly what _image_box takes its arguments for.
        return self.area._image_box(width, height)

    def test_with_no_image_there_is_no_box(self):
        self.assertIsNone(self._sized(400, 400))

    def test_an_unallocated_widget_has_no_box_either(self):
        self.area.set_pixbuf(self.pixbuf)
        self.assertIsNone(self._sized(0, 0))
        self.assertIsNone(self._sized(400, 0))

    def test_a_large_widget_never_scales_the_image_up(self):
        self.area.set_pixbuf(self.pixbuf)
        x, y, w, h, scale = self._sized(800, 800)
        self.assertEqual(scale, 1.0)
        self.assertEqual((w, h), (200, 100))
        self.assertEqual((x, y), (300, 350))

    def test_a_small_widget_fits_the_image_inside_it(self):
        self.area.set_pixbuf(self.pixbuf)
        _x, _y, w, h, scale = self._sized(100, 100)
        self.assertEqual(scale, 0.5)
        self.assertEqual((w, h), (100.0, 50.0))

    def test_setting_a_new_image_drops_the_old_crop(self):
        self.area.set_pixbuf(self.pixbuf)
        self.area.crop_rect = [1, 2, 3, 4]
        self.area.set_pixbuf(self.pixbuf)
        self.assertIsNone(self.area.crop_rect)

    def test_leaving_crop_mode_drops_the_rectangle(self):
        self.area.set_pixbuf(self.pixbuf)
        self.area.crop_rect = [1, 2, 3, 4]
        self.area.set_crop_mode(False)
        self.assertFalse(self.area.crop_mode)
        self.assertIsNone(self.area.crop_rect)

    def test_crop_mode_with_no_image_has_nothing_to_draw(self):
        self.area.set_crop_mode(True)
        self.assertTrue(self.area.crop_mode)
        self.assertIsNone(self.area.crop_rect)

    def test_a_crop_with_no_rectangle_maps_to_nothing(self):
        self.area.set_pixbuf(self.pixbuf)
        self.assertIsNone(self.area.crop_in_pixbuf_coords())


@needs_display
class TheCropRectangleTests(unittest.TestCase):
    """Driven at a fixed size, so the numbers below are the ones on screen."""

    WIDTH, HEIGHT = 400, 400

    def setUp(self):
        self.area = _PreviewArea()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 200, 100)
        pixbuf.fill(0x0000FFFF)
        self.area.set_pixbuf(pixbuf)
        # _image_box() reads the allocation; with none, pin it to a known size.
        patcher = mock.patch.object(
            self.area,
            "_image_box",
            lambda width=None, height=None: (100.0, 150.0, 200.0, 100.0, 1.0),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_entering_crop_mode_insets_the_rectangle_inside_the_image(self):
        self.area.set_crop_mode(True)
        x, y, w, h = self.area.crop_rect
        self.assertEqual((x, y), (120.0, 160.0))
        self.assertEqual((w, h), (160.0, 80.0))

    def test_the_rectangle_maps_back_to_pixbuf_pixels(self):
        self.area.set_crop_mode(True)
        self.assertEqual(self.area.crop_in_pixbuf_coords(), (20, 10, 160, 80))

    def test_a_rectangle_smaller_than_a_pixel_maps_to_nothing(self):
        self.area.crop_rect = [100.0, 150.0, 0.0, 0.0]
        self.assertIsNone(self.area.crop_in_pixbuf_coords())

    def test_dragging_the_middle_moves_the_whole_rectangle(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 200, 200)
        self.assertEqual(self.area._drag[0], "move")
        self.area._on_drag_update(None, 10, 5)
        self.assertEqual(self.area.crop_rect[:2], [130.0, 165.0])

    def test_a_move_stops_at_the_edge_of_the_image(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 200, 200)
        self.area._on_drag_update(None, 10_000, 10_000)
        x, y, w, h = self.area.crop_rect
        self.assertEqual(x + w, 300.0)
        self.assertEqual(y + h, 250.0)

    def test_a_move_stops_at_the_other_edge_too(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 200, 200)
        self.area._on_drag_update(None, -10_000, -10_000)
        self.assertEqual(self.area.crop_rect[:2], [100.0, 150.0])

    def test_dragging_the_top_left_corner_anchors_the_bottom_right(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 120, 160)
        self.assertEqual(self.area._drag[:2], ("corner", 0))
        self.area._on_drag_update(None, 10, 10)
        x, y, w, h = self.area.crop_rect
        self.assertEqual((x, y), (130.0, 170.0))
        self.assertEqual((x + w, y + h), (280.0, 240.0))

    def test_dragging_the_bottom_right_corner_anchors_the_top_left(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 280, 240)
        self.assertEqual(self.area._drag[:2], ("corner", 3))
        self.area._on_drag_update(None, -20, -10)
        x, y, w, h = self.area.crop_rect
        self.assertEqual((x, y), (120.0, 160.0))
        self.assertEqual((x + w, y + h), (260.0, 230.0))

    def test_a_corner_cannot_be_dragged_past_its_opposite(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 120, 160)
        self.area._on_drag_update(None, 10_000, 10_000)
        _x, _y, w, h = self.area.crop_rect
        self.assertEqual(w, self.area.MIN_SIZE)
        self.assertEqual(h, self.area.MIN_SIZE)

    def test_the_top_right_corner_moves_only_its_own_two_edges(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 280, 160)
        self.assertEqual(self.area._drag[:2], ("corner", 1))
        self.area._on_drag_update(None, -10, 10)
        x, y, w, h = self.area.crop_rect
        self.assertEqual(x, 120.0)
        self.assertEqual(y, 170.0)
        self.assertEqual(x + w, 270.0)

    def test_the_bottom_left_corner_moves_only_its_own_two_edges(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 120, 240)
        self.assertEqual(self.area._drag[:2], ("corner", 2))
        self.area._on_drag_update(None, 10, -10)
        x, y, w, h = self.area.crop_rect
        self.assertEqual(x, 130.0)
        self.assertEqual(y, 160.0)
        self.assertEqual(y + h, 230.0)

    def test_a_drag_starting_outside_the_rectangle_grabs_nothing(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 105, 155)
        self.assertIsNone(self.area._drag)
        before = list(self.area.crop_rect)
        self.area._on_drag_update(None, 50, 50)
        self.assertEqual(self.area.crop_rect, before)

    def test_a_drag_on_a_widget_with_no_geometry_yet_changes_nothing(self):
        self.area.set_crop_mode(True)
        self.area._on_drag_begin(None, 200, 200)
        before = list(self.area.crop_rect)
        with mock.patch.object(self.area, "_image_box", return_value=None):
            self.area._on_drag_update(None, 10, 10)
        self.assertEqual(self.area.crop_rect, before)

    def test_a_drag_outside_crop_mode_grabs_nothing(self):
        self.area._on_drag_begin(None, 200, 200)
        self.assertIsNone(self.area._drag)


@needs_display
class TheDrawingTests(unittest.TestCase):
    """The draw function runs against a real surface, never a live window."""

    def _context(self):
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 400)
        return cairo.Context(surface)

    def test_an_empty_area_draws_nothing_and_does_not_raise(self):
        area = _PreviewArea()
        area._draw(area, self._context(), 400, 400)

    def test_an_image_is_drawn(self):
        area = _PreviewArea()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 200, 100)
        pixbuf.fill(0x0000FFFF)
        area.set_pixbuf(pixbuf)
        area._draw(area, self._context(), 400, 400)

    def test_the_crop_rectangle_and_its_handles_are_drawn_over_it(self):
        area = _PreviewArea()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 200, 100)
        pixbuf.fill(0x0000FFFF)
        area.set_pixbuf(pixbuf)
        area.crop_mode = True
        area.crop_rect = [120.0, 160.0, 160.0, 80.0]
        area._draw(area, self._context(), 400, 400)


if __name__ == "__main__":
    unittest.main()

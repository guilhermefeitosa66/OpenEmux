"""Big Picture's import and cover-sync pages (issue 914), and the progress panel they share.

Against the real window with the mode on: the rows are checked for what
they ask the window to do, the panel for following the window's banner the
way a task would move it -- begun, advanced, stopped, finished.
"""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

# Pure Python: the theme's rules are checked with no display at all.
from openemux.ui.bigpicture import theme  # noqa: E402

if HAVE_DISPLAY:
    from openemux.ui.bigpicture.tasks import CoversPage, ImportPage, ProgressPanel


@needs_display
class TheImportPage(BigPictureCase):
    def test_the_rows_reach_the_windows_flows(self):
        page = self.shell.open_import()
        self.pump()
        self.assertIsInstance(page, ImportPage)
        self.assertIs(self.visible_page(), page)
        self.assertEqual(page.get_tag(), "bp-import")
        self.assertIs(self.shell.open_import(), page)
        with mock.patch.object(self.win.imports, "open_picker") as picker:
            page.pick_row.emit("clicked")
        picker.assert_called_once()
        with mock.patch.object(self.win, "_choose_roms_path") as folder:
            page.folder_row.emit("clicked")
        folder.assert_called_once()
        with mock.patch.object(self.win, "receive_games") as receive:
            page.receive_row.emit("clicked")
        receive.assert_called_once()
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            page.rescan_row.emit("clicked")
        rescan.assert_called_once_with(show_toast=True)
        self.assertEqual(page.pick_row.subtitle_label.get_label(), self.said("big_picture.tasks.import.files.subtitle"))
        hints = page.hints(self.win.navigation.glyphs(), self.win.t)
        self.assertEqual([label for _g, label in hints], [self.said("big_picture.hints.choose"), self.said("hints.back")])
        self.show()
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.pick_row)


@needs_display
class TheProgressPanel(BigPictureCase):
    def test_it_mirrors_the_banner_from_begin_to_finish(self):
        page = self.shell.open_import()
        self.pump()
        panel = page.panel
        self.assertIsInstance(panel, ProgressPanel)
        self.assertTrue(panel.idle_label.get_visible())
        self.assertFalse(panel.title_label.get_visible())
        self.assertFalse(panel.stop_button.get_visible())
        panel.stop()  # nothing running: nothing to stop

        cancelled = []
        task = self.win.tasks.begin("scan", "Scanning", total=10, on_cancel=lambda: cancelled.append(True))
        self.assertFalse(panel.idle_label.get_visible())
        self.assertTrue(panel.title_label.get_visible())
        self.assertEqual(panel.title_label.get_label(), self.win.banner.get_title())
        self.assertIn("Scanning", panel.title_label.get_label())
        self.assertTrue(panel.bar.get_visible())
        self.assertEqual(panel.bar.get_fraction(), 0.0)
        self.assertFalse(panel.spinner.get_visible())
        self.assertTrue(panel.stop_button.get_visible())
        self.win.tasks.update(task, current=5)
        self.assertEqual(panel.bar.get_fraction(), 0.5)
        panel.stop_button.emit("clicked")
        self.assertEqual(cancelled, [True])
        self.assertTrue(self.win.tasks.current_task()["cancelling"])
        self.assertFalse(panel.stop_button.get_visible())
        self.assertEqual(panel.title_label.get_label(), self.said("banner.stopping"))
        self.win.tasks.finish(task)
        self.assertTrue(panel.idle_label.get_visible())
        self.assertFalse(panel.bar.get_visible())

        # No total and no way to stop: a spinner, no bar, no button.
        task = self.win.tasks.begin("covers", "Syncing")
        self.assertTrue(panel.spinner.get_visible())
        self.assertTrue(panel.spinner.get_spinning())
        self.assertFalse(panel.bar.get_visible())
        self.assertFalse(panel.stop_button.get_visible())
        self.win.tasks.finish(task)
        self.assertFalse(panel.spinner.get_spinning())
        # A notice on the banner shows up too; refresh() re-reads by hand.
        self.win.tasks.show_notice("Drop the files here")
        self.assertEqual(panel.title_label.get_label(), "Drop the files here")
        self.win.tasks.refresh()
        page.refresh()
        self.assertTrue(panel.idle_label.get_visible())


@needs_display
class TheCoversPage(BigPictureCase):
    def test_the_consoles_are_rows_and_each_starts_its_sync(self):
        page = self.shell.open_covers()
        self.pump()
        self.assertIsInstance(page, CoversPage)
        self.assertEqual(page.get_tag(), "bp-covers")
        self.assertIs(self.shell.open_covers(), page)
        consoles = list(self.win.visible_consoles)
        self.assertEqual([row.console for row in page.console_rows], consoles)
        self.assertEqual(page.all_row.subtitle_label.get_label(), self.said("header.subtitle.games", count=3))
        sfc = next(row for row in page.console_rows if row.console == "SFC")
        self.assertEqual(sfc.title_label.get_label(), self.win.sidebar.label_for("SFC"))
        self.assertEqual(sfc.subtitle_label.get_label(), self.said("header.subtitle.games", count=2))
        fc = next(row for row in page.console_rows if row.console == "FC")
        self.assertEqual(fc.subtitle_label.get_label(), self.said("header.subtitle.one_game"))
        with mock.patch.object(self.win, "_start_cover_sync") as start:
            page.all_row.emit("clicked")
            sfc.emit("clicked")
        self.assertEqual(
            start.call_args_list,
            [mock.call(scope="all", selected_console=None), mock.call(scope="console", selected_console="SFC")],
        )
        # The real entry point, as the desktop's dialog would call it.
        with mock.patch.object(self.win, "_start_artwork_sync") as sync:
            fc.emit("clicked")
        self.assertEqual(list(sync.call_args.args[0][0][1]), ["FC"])
        # No console with games: no rows, and the window's own toast on A.
        self.win.visible_consoles = []
        try:
            page.refresh()
        finally:
            self.win.visible_consoles = consoles
        self.assertEqual(page.console_rows, [])
        self.assertEqual(page.all_row.subtitle_label.get_label(), self.said("header.subtitle.games", count=0))
        self.show()
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.all_row)

    def test_the_providers_are_listed_in_the_configs_order(self):
        page = self.shell.open_covers()
        self.pump()
        providers = self.config.get_artwork_providers()
        enabled = [entry["id"] for entry in providers if entry["enabled"]]
        self.assertTrue(enabled)
        self.assertEqual([row.provider_id for row in page.provider_rows], enabled)
        self.assertEqual(page.provider_rows[0].title_label.get_label(), self.said(f"prefs.provider.{enabled[0]}"))
        self.assertFalse(page.no_providers.get_visible())
        reordered = list(reversed(providers))
        self.config.set_artwork_providers(reordered)
        page.refresh()
        self.assertEqual([row.provider_id for row in page.provider_rows], [e["id"] for e in reordered if e["enabled"]])
        for entry in providers:
            entry["enabled"] = False
        self.config.set_artwork_providers(providers)
        page.refresh()
        self.assertEqual(page.provider_rows, [])
        self.assertTrue(page.no_providers.get_visible())


class TheDialogTheme(unittest.TestCase):
    def test_the_dialogs_and_the_pages_get_their_rules(self):
        css = theme.stylesheet(1.0, dark=True)
        for selector in (
            ".big-picture dialog.alert .message-area .title-2",
            ".big-picture dialog row .title",
            ".big-picture dialog.alert .response-area > button",
            ".big-picture dialog carouselindicatordots",
            ".big-picture statuspage .title",
            ".big-picture .bp-details-cover",
            ".big-picture .bp-tile.bp-state",
            ".big-picture .bp-panel",
            ".big-picture .bp-side",
            ".big-picture .bp-first-boot",
        ):
            self.assertIn(selector, css)
        self.assertIn(f"min-width: {theme.SIZES['cover_w']}px", css)
        self.assertIn(f"min-width: {theme.SIZES['side']}px", theme.stylesheet(1.0, dark=False))


if __name__ == "__main__":
    unittest.main()

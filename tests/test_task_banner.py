"""The progress banner's task registry (issue #237).

Several background tasks can be in flight at once -- a scan, a cover sync, an
import -- and one banner shows them. It renders the first and counts the rest,
offers Cancel only while the running task can be interrupted, and says
"stopping" between the request and the worker noticing.

It was five methods on `OpenEmuxWindow` with a widget in the middle of them,
so none of this had a test.
"""

import unittest

from openemux.ui.task_banner import TaskBanner


class FakeBanner:
    """Stands in for the Adw.Banner: records what it was told to show."""

    def __init__(self):
        self.title = None
        self.button_label = None
        self.revealed = None
        self.handlers = {}

    def connect(self, signal, handler):
        self.handlers[signal] = handler
        return 1

    def set_title(self, title):
        self.title = title

    def set_button_label(self, label):
        self.button_label = label

    def set_revealed(self, revealed):
        self.revealed = revealed

    def click(self):
        self.handlers["button-clicked"](self)


def _t(key, **kwargs):
    return key


def _attached():
    registry = TaskBanner(_t)
    banner = FakeBanner()
    registry.attach(banner)
    return registry, banner


class NothingRunningTests(unittest.TestCase):
    def test_an_empty_registry_hides_the_banner(self):
        _registry, banner = _attached()
        self.assertIs(banner.revealed, False)

    def test_a_task_begun_before_the_banner_exists_still_shows(self):
        # The window registers the object in __init__ and builds its header
        # bars afterwards; a task begun in between must not be lost.
        registry = TaskBanner(_t)
        registry.begin("scan", "Scanning")
        banner = FakeBanner()
        registry.attach(banner)
        self.assertIs(banner.revealed, True)
        self.assertEqual(banner.title, "Scanning")


class OneTaskTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.banner = _attached()

    def test_beginning_a_task_reveals_it(self):
        self.registry.begin("scan", "Scanning")
        self.assertIs(self.banner.revealed, True)
        self.assertEqual(self.banner.title, "Scanning")

    def test_the_id_carries_the_kind_and_is_unique(self):
        first = self.registry.begin("scan", "Scanning")
        second = self.registry.begin("scan", "Scanning again")
        self.assertTrue(first.startswith("scan-"))
        self.assertNotEqual(first, second)

    def test_a_counter_is_rendered_once_a_total_is_known(self):
        task = self.registry.begin("covers", "Syncing", total=10)
        self.registry.update(task, current=3)
        self.assertEqual(self.banner.title, "Syncing (3/10)")

    def test_a_task_with_no_total_shows_only_its_label(self):
        task = self.registry.begin("import", "Importing")
        self.registry.update(task, current=3)
        self.assertEqual(self.banner.title, "Importing")

    def test_finishing_the_last_task_hides_the_banner(self):
        task = self.registry.begin("scan", "Scanning")
        self.registry.finish(task)
        self.assertIs(self.banner.revealed, False)

    def test_updating_a_finished_task_is_not_an_error(self):
        # A worker's last progress callback can land after the done callback.
        task = self.registry.begin("scan", "Scanning")
        self.registry.finish(task)
        self.registry.update(task, current=99)
        self.assertIs(self.banner.revealed, False)


class SeveralTasksTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.banner = _attached()

    def test_the_first_is_rendered_and_the_rest_are_counted(self):
        self.registry.begin("scan", "Scanning")
        self.registry.begin("covers", "Syncing")
        self.registry.begin("import", "Importing")
        self.assertEqual(self.banner.title, "Scanning (+2)")

    def test_finishing_the_shown_one_promotes_the_next(self):
        first = self.registry.begin("scan", "Scanning")
        self.registry.begin("covers", "Syncing")
        self.registry.finish(first)
        self.assertEqual(self.banner.title, "Syncing")


class CancellingTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.banner = _attached()
        self.stopped = []

    def test_only_an_interruptible_task_offers_cancel(self):
        self.registry.begin("scan", "Scanning")
        self.assertIsNone(self.banner.button_label)

    def test_a_cancellable_task_gets_the_button(self):
        self.registry.begin("covers", "Syncing", on_cancel=self.stopped.append)
        self.assertEqual(self.banner.button_label, "banner.cancel")

    def test_the_button_signals_the_worker_and_says_stopping(self):
        self.registry.begin(
            "covers", "Syncing", on_cancel=lambda: self.stopped.append("asked")
        )
        self.banner.click()
        self.assertEqual(self.stopped, ["asked"])
        # The worker stops at its next checkpoint, so the banner must not
        # pretend the task is already gone.
        self.assertEqual(self.banner.title, "banner.stopping")
        self.assertIsNone(self.banner.button_label)
        self.assertIs(self.banner.revealed, True)

    def test_cancelling_twice_only_signals_once(self):
        task = self.registry.begin(
            "covers", "Syncing", on_cancel=lambda: self.stopped.append("asked")
        )
        self.registry.cancel(task)
        self.registry.cancel(task)
        self.assertEqual(self.stopped, ["asked"])

    def test_cancelling_an_uninterruptible_task_does_nothing(self):
        task = self.registry.begin("scan", "Scanning")
        self.registry.cancel(task)
        self.assertEqual(self.banner.title, "Scanning")


class BorrowingTheBannerTests(unittest.TestCase):
    def test_the_drop_hint_shows_and_the_task_comes_back(self):
        registry, banner = _attached()
        registry.begin("scan", "Scanning")
        registry.show_notice("Drop ROMs here")
        self.assertEqual(banner.title, "Drop ROMs here")
        registry.refresh()
        self.assertEqual(banner.title, "Scanning")

    def test_a_notice_with_no_banner_yet_is_ignored(self):
        TaskBanner(_t).show_notice("Drop ROMs here")


if __name__ == "__main__":
    unittest.main()

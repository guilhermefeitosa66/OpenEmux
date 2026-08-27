"""The registry that re-applies translated text (issue #237).

Every tooltip and label outside the widgets the library rebuilds wholesale
registers a callback here, next to the widget it belongs to. That is right for
a control built once and wrong for one the app rebuilds: the layout menu's
zoom stepper is rebuilt on every sidebar click, and left two closures behind
each time -- replayed in full on the next language change.
"""

import gc
import unittest

from openemux.ui.retranslate import RetranslateRegistry


class Widget:
    """Something a registration can be tied to."""


class ApplyingTests(unittest.TestCase):
    def setUp(self):
        self.registry = RetranslateRegistry()
        self.calls = []

    def test_registering_applies_it_once_right_away(self):
        self.registry.add(lambda: self.calls.append("now"))
        self.assertEqual(self.calls, ["now"])

    def test_a_language_change_applies_every_entry_again(self):
        self.registry.add(lambda: self.calls.append("a"))
        self.registry.add(lambda: self.calls.append("b"))
        self.calls.clear()
        self.registry.apply_all()
        self.assertEqual(self.calls, ["a", "b"])

    def test_they_run_in_registration_order(self):
        for name in "abc":
            self.registry.add(lambda n=name: self.calls.append(n))
        self.calls.clear()
        self.registry.apply_all()
        self.assertEqual(self.calls, ["a", "b", "c"])


class OwnedRegistrationsTests(unittest.TestCase):
    def setUp(self):
        self.registry = RetranslateRegistry()
        self.calls = []

    def test_an_owned_entry_survives_while_its_widget_does(self):
        widget = Widget()
        self.registry.add(lambda: self.calls.append("x"), owner=widget)
        self.calls.clear()
        self.registry.apply_all()
        self.assertEqual(self.calls, ["x"])
        self.assertEqual(len(self.registry), 1)

    def test_it_is_dropped_once_the_widget_is_gone(self):
        widget = Widget()
        self.registry.add(lambda: self.calls.append("x"), owner=widget)
        del widget
        gc.collect()
        self.calls.clear()
        self.registry.apply_all()
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.registry), 0)

    def test_rebuilding_a_control_does_not_grow_the_registry(self):
        # The zoom stepper: rebuilt on every sidebar click, each build
        # replacing the last. Unowned, N clicks left N registrations behind
        # and every language change replayed all of them.
        stepper = None
        for _ in range(50):
            stepper = Widget()  # the previous one is dropped here
            self.registry.add(lambda: self.calls.append("zoom"), owner=stepper)
            gc.collect()
            self.calls.clear()
            self.registry.apply_all()
        self.assertEqual(len(self.registry), 1)
        self.assertEqual(self.calls, ["zoom"])
        self.assertIsNotNone(stepper)

    def test_an_unowned_entry_is_kept_for_the_life_of_the_window(self):
        # The header buttons and the sidebar footer are built once and must
        # keep re-translating for as long as the window is open.
        self.registry.add(lambda: self.calls.append("header"))
        gc.collect()
        self.calls.clear()
        self.registry.apply_all()
        self.assertEqual(self.calls, ["header"])


if __name__ == "__main__":
    unittest.main()

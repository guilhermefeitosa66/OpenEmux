"""The shared color picker on its own (issue 1011; built for issue 983)."""

import unittest

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from openemux.ui.color_picker import ColorPicker


def _t(key, **_kwargs):
    return key


@needs_display
class ColorPickerTests(unittest.TestCase):
    def test_it_works_without_any_callback(self):
        picker = ColorPicker(_t, "#336699")
        self.assertEqual(picker.hex_entry.get_text(), "#336699")
        picker.set_color("#112233")
        picker.hex_entry.set_text("nope")
        self.assertTrue(picker.hex_entry.has_css_class("error"))
        self.assertEqual(picker.color, "#112233")
        picker.hex_entry.emit("activate")

    def test_callbacks_hear_changes_validity_and_enter(self):
        changes, validity, activated = [], [], []
        picker = ColorPicker(
            _t, "#336699",
            on_changed=changes.append,
            on_validity=validity.append,
            on_activate=lambda: activated.append(True),
        )
        # Building it tells nobody anything.
        self.assertEqual((changes, validity), ([], []))
        picker.hue_scale.set_value(120)
        self.assertEqual(changes[-1], picker.color)
        picker.hex_entry.set_text("zz")
        self.assertEqual(validity[-1], False)
        picker.hex_entry.set_text("#abcdef")
        self.assertEqual((validity[-1], changes[-1]), (True, "#abcdef"))
        picker.hex_entry.emit("activate")
        self.assertEqual(activated, [True])


if __name__ == "__main__":
    unittest.main()

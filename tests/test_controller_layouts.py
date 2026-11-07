import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openemux.core import controller_layouts as cl
from openemux.core.input_actions import get_actions_for_console

#: The 31 consoles the Android app ships a bundled skin for.
EXPORTED = {
    "A2600", "A5200", "A7800", "CV", "FC", "FDS", "GB", "GBA", "GBC", "GC", "GG", "INTV", "LYNX", "MCD", "MD",
    "N64", "NDS", "NGP", "O2", "PCE", "PCECD", "PS", "PSP", "S32X", "SATURN", "SFC", "SG1000", "SMS", "VB",
    "VECTREX", "WS",
}

#: launch/SkinBinds.kt in openemux-android, console by console: skin bind -> RetroPad.
SKINBINDS_KT = {
    "N64": {"a": "b", "b": "y", "z": "l2", "cUp": "r_y_minus", "cDown": "r_y_plus", "cLeft": "r_x_minus",
            "cRight": "r_x_plus"},
    "MD": {"a": "y", "b": "b", "c": "a", "x": "l", "y": "x", "z": "r", "mode": "select"},
    "S32X": {"a": "y", "b": "b", "c": "a", "x": "l", "y": "x", "z": "r", "mode": "select"},
    "MCD": {"a": "y", "b": "b", "c": "a", "x": "l", "y": "x", "z": "r", "mode": "select"},
    "SATURN": {"a": "b", "b": "a", "c": "r", "x": "y", "y": "x", "z": "l", "l": "l2", "r": "r2"},
    "GC": {"z": "r", "l": "l2", "r": "r2"},
    "FDS": {"disk": "l"},
    "LYNX": {"option1": "r", "option2": "l"},
    "NGP": {"a": "b", "b": "a"},
}

GENERIC_KT = {
    "up": "up", "down": "down", "left": "left", "right": "right", "a": "a", "b": "b", "x": "x", "y": "y",
    "l": "l", "r": "r", "l2": "l2", "r2": "r2", "l3": "l3", "r3": "r3", "start": "start", "select": "select",
    "l1": "l", "r1": "r", "menu": "menu_toggle", "quickSave": "save_state", "quickLoad": "load_state",
    "fastForward": "hold_fast_forward", "toggleFastForward": "toggle_fast_forward", "turbo": "turbo_fire_toggle",
    "screenshot": "screenshot", "restart": "reset", "reset": "reset",
}


class SkinBindsTableTests(unittest.TestCase):
    def test_console_tables_match_skinbinds_kt(self):
        for console, table in SKINBINDS_KT.items():
            for bind, retropad in table.items():
                with self.subTest(console=console, bind=bind):
                    self.assertEqual(cl.bind_to_retropad(console, bind), retropad)
        self.assertEqual(set(cl.CONSOLE_BINDS), set(SKINBINDS_KT))

    def test_generic_table_matches_skinbinds_kt(self):
        self.assertEqual(cl.GENERIC_BINDS, GENERIC_KT)
        # A console without its own table, and a name it does not override.
        self.assertEqual(cl.bind_to_retropad("FC", "a"), "a")
        self.assertEqual(cl.bind_to_retropad("N64", "start"), "start")

    def test_unknown_bind_and_console_specific_names_elsewhere(self):
        self.assertIsNone(cl.bind_to_retropad("FC", "keypadToggle"))
        self.assertIsNone(cl.bind_to_retropad("FC", "disk"))
        self.assertIsNone(cl.bind_to_retropad("SFC", "option1"))

    def test_aliases_resolve(self):
        self.assertEqual(cl.bind_to_retropad("md", "a"), "y")

    def test_second_dpad(self):
        self.assertEqual(cl.element_retropad("VB", "dpad", "dpad2"), ("l2", "l3", "r2", "r3"))
        self.assertEqual(cl.element_retropad("FC", "dpad", "dpad2"), ())
        self.assertEqual(cl.element_retropad("FC", "dpad", "dpad"), ("up", "down", "left", "right"))

    def test_sticks(self):
        self.assertEqual(cl.element_retropad("N64", "stick", "analogStick"),
                         ("l_y_minus", "l_y_plus", "l_x_minus", "l_x_plus"))
        self.assertEqual(cl.element_retropad("PS", "stick", "rightAnalogStick"),
                         ("r_y_minus", "r_y_plus", "r_x_minus", "r_x_plus"))
        self.assertEqual(cl.element_retropad("PS", "stick", "nothing"), ())

    def test_button_without_target(self):
        self.assertEqual(cl.element_retropad("FC", "button", "keypadToggle"), ())
        self.assertEqual(cl.element_retropad("INTV", "keypad", "keypad1"), ())


class ActionsTests(unittest.TestCase):
    def test_buttons_through_the_retropad(self):
        self.assertEqual(cl.actions_for_element("N64", "button", "a"), ("b",))
        self.assertEqual(cl.actions_for_element("N64", "button", "b"), ("y",))
        self.assertEqual(cl.actions_for_element("NGP", "button", "a"), ("b",))
        self.assertEqual(cl.actions_for_element("LYNX", "button", "option1"), ("r1",))
        self.assertEqual(cl.actions_for_element("MD", "button", "c"), ("a",))
        self.assertEqual(cl.actions_for_element("MD", "button", "x"), ("l1",))
        self.assertEqual(cl.actions_for_element("MD", "button", "mode"), ("select",))
        self.assertEqual(cl.actions_for_element("PS", "button", "l1"), ("l1",))
        self.assertEqual(cl.actions_for_element("FC", "button", "menu"), ("menu_toggle",))

    def test_every_control_a_core_reads_has_its_action(self):
        # Issue 816: each of these was drawn as not remappable (and, worse,
        # written as unbound at launch) because its RetroPad button was
        # missing from the console's actions.
        self.assertEqual(cl.actions_for_element("N64", "button", "z"), ("l2",))
        self.assertEqual(cl.actions_for_element("MD", "button", "a"), ("y",))
        self.assertEqual(cl.actions_for_element("S32X", "button", "y"), ("x",))
        self.assertEqual(cl.actions_for_element("PSP", "button", "x"), ("x",))
        self.assertEqual(cl.actions_for_element("PS", "button", "r2"), ("r2",))
        self.assertEqual(cl.actions_for_element("SATURN", "button", "l"), ("l2",))
        self.assertEqual(cl.actions_for_element("GC", "button", "r"), ("r2",))
        self.assertEqual(cl.actions_for_element("FDS", "button", "disk"), ("l1",))
        self.assertEqual(cl.actions_for_element("VB", "button", "l"), ("l1",))
        self.assertEqual(cl.actions_for_element("VB", "dpad", "dpad2"), ("l2", "l3", "r2", "r3"))
        self.assertEqual(cl.actions_for_element("VECTREX", "button", "y"), ("y",))
        self.assertEqual(cl.actions_for_element("A7800", "button", "x"), ("x",))
        self.assertEqual(cl.actions_for_element("INTV", "button", "y"), ("y",))

    def test_the_right_stick_and_the_c_buttons_remap_its_four_directions(self):
        self.assertEqual(cl.actions_for_element("N64", "button", "cUp"), ("r_up",))
        self.assertEqual(cl.actions_for_element("N64", "button", "cLeft"), ("r_left",))
        for console in ("PS", "GC"):
            self.assertEqual(
                cl.actions_for_element(console, "stick", "rightAnalogStick"),
                ("r_up", "r_down", "r_left", "r_right"),
            )

    def test_targets_outside_the_consoles_actions_are_not_remappable(self):
        # The Game Boy Advance has no X; nothing reads one there.
        self.assertEqual(cl.actions_for_element("GBA", "button", "x"), ())
        self.assertEqual(cl.actions_for_element("SFC", "button", "l2"), ())
        self.assertEqual(cl.actions_for_element("SFC", "stick", "rightAnalogStick"), ())
        # A quick-action name never reaches a desktop action, and neither does
        # the Android skins' own keypad switch.
        self.assertEqual(cl.actions_for_element("FC", "button", "quickSave"), ())
        self.assertEqual(cl.actions_for_element("CV", "button", "keypadToggle"), ())

    def test_dpad_and_left_stick(self):
        self.assertEqual(cl.actions_for_element("FC", "dpad", "dpad"), ("up", "down", "left", "right"))
        self.assertEqual(cl.actions_for_element("N64", "stick", "analogStick"),
                         ("l_up", "l_down", "l_left", "l_right"))

    def test_stick_falls_back_to_directions_without_a_dpad(self):
        self.assertEqual(cl.actions_for_element("A5200", "stick", "analogStick", has_dpad=False),
                         ("up", "down", "left", "right"))
        self.assertEqual(cl.actions_for_element("A5200", "stick", "analogStick", has_dpad=True), ())
        self.assertEqual(cl.actions_for_element("A5200", "stick", "rightAnalogStick", has_dpad=False), ())


class CommittedArtTests(unittest.TestCase):
    def test_every_bundled_console_has_a_layout(self):
        self.assertEqual({p.name for p in cl.CONTROLLERS_DIR.iterdir() if p.is_dir()}, EXPORTED)
        for console in sorted(EXPORTED):
            with self.subTest(console=console):
                layout = cl.layout_for(console)
                self.assertIsNotNone(layout)
                self.assertEqual(layout.console, console)
                self.assertTrue(layout.background.is_file())
                self.assertTrue(layout.elements)
                allowed = set(get_actions_for_console(console))
                for element in layout.elements:
                    self.assertGreaterEqual(element.x, 0)
                    self.assertGreaterEqual(element.y, 0)
                    self.assertLessEqual(element.x + element.width, layout.width)
                    self.assertLessEqual(element.y + element.height, layout.height)
                    self.assertTrue(all(p.is_file() for p in element.images.values()))
                    self.assertTrue(set(element.actions) <= allowed)
                # Every console's movement is remappable from the drawing.
                moves = {a for e in layout.elements for a in e.actions}
                self.assertTrue({"up", "down", "left", "right"} <= moves)

    def test_n64(self):
        layout = cl.layout_for("N64")
        by_id = {e.id: e for e in layout.elements}
        self.assertEqual(by_id["a"].actions, ("b",))
        self.assertEqual(by_id["dpad"].actions, ("up", "down", "left", "right"))
        self.assertEqual(by_id["stick"].actions, ("l_up", "l_down", "l_left", "l_right"))
        self.assertEqual(set(by_id["stick"].images), {"base", "knob"})
        self.assertEqual(by_id["z"].actions, ("l2",))
        self.assertEqual(by_id["c-down"].actions, ("r_down",))

    def test_only_the_android_keypad_switch_is_left_with_no_action(self):
        # Every control a core reads is remappable from its drawing (issue
        # 816). What is left opens the on-screen keypad of the Android skins,
        # which has nothing behind it on the desktop.
        left = sorted(
            (console, element.bind)
            for console in EXPORTED
            for element in cl.layout_for(console).elements
            if len(element.actions) < (4 if element.type in ("dpad", "stick") else 1)
        )
        self.assertEqual(left, [(console, "keypadToggle") for console in ("A5200", "CV", "INTV", "O2")])

    def test_aliases_and_missing(self):
        self.assertEqual(cl.layout_for("NES").console, "FC")
        self.assertIsNone(cl.layout_for("MSX"))
        self.assertIsNone(cl.layout_for(None))
        self.assertIsNone(cl.layout_for(""))

    def test_set_is_truecolor_and_small(self):
        total = 0
        for path in cl.CONTROLLERS_DIR.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
            if path.suffix == ".png":
                with open(path, "rb") as handle:
                    header = handle.read(26)
                # IHDR colour type 6: truecolor with alpha, never a palette.
                self.assertEqual(header[25], 6, path)
        self.assertLess(total, 6 * 1024 * 1024)


class BrokenLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(cl.CONTROLLERS_DIR / "FC", self.root / "FC")
        self.file = self.root / "FC" / "layout.json"
        self.good = json.loads(self.file.read_text(encoding="utf-8"))

    def write(self, data):
        self.file.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def assertBroken(self, data):
        self.write(data)
        with self.assertLogs("openemux.core.controller_layouts", "WARNING"):
            self.assertIsNone(cl.layout_for("FC", root=self.root))

    def mutated(self, change):
        data = json.loads(json.dumps(self.good))
        change(data)
        return data

    def test_copy_reads(self):
        self.assertEqual(cl.layout_for("FC", root=self.root).console, "FC")

    def test_no_folder(self):
        self.assertIsNone(cl.layout_for("SFC", root=self.root))

    def test_invalid_json(self):
        self.assertBroken("{not json")

    def test_not_an_object(self):
        self.assertBroken([])

    def test_unreadable(self):
        self.file.unlink()
        self.file.mkdir()
        self.assertIsNone(cl.layout_for("FC", root=self.root))

    def test_bad_values(self):
        def drop(key):
            return lambda d: d.pop(key)

        def element(key, value):
            def change(d):
                d["elements"][0][key] = value
            return change

        cases = [
            lambda d: d.update(format=2),
            drop("size"),
            lambda d: d.update(size={"width": 0, "height": 10}),
            lambda d: d.update(size={"width": True, "height": 10}),
            lambda d: d.update(background=""),
            lambda d: d.update(background="nope.png"),
            lambda d: d.update(elements={}),
            lambda d: d["elements"].append("x"),
            element("id", ""),
            element("type", "action"),
            element("type", ["button"]),
            element("bind", None),
            element("x", 1.5),
            element("width", 0),
            element("height", -4),
            element("images", {"wrong": "x.png"}),
            element("images", "x.png"),
        ]
        for index, change in enumerate(cases):
            with self.subTest(case=index):
                self.assertBroken(self.mutated(change))

    def test_bad_image_names(self):
        first = self.good["elements"][0]
        role = next(iter(first["images"]))
        for name in ("", "missing.png", 3):
            with self.subTest(name=name):
                self.assertBroken(self.mutated(lambda d, name=name: d["elements"][0]["images"].update({role: name})))


if __name__ == "__main__":
    unittest.main()

import unittest

from openemux.core import gamepad_reader as gr


# A realistic-ish Xbox-style pad: face/shoulder/thumb/menu buttons, two sticks,
# two triggers and one hat. Written as explicit code lists so the expected udev
# numbering is obvious.
XBOX_KEY_CODES = [
    0x130,  # BTN_SOUTH  -> button 0
    0x131,  # BTN_EAST   -> button 1
    0x133,  # BTN_NORTH  -> button 2
    0x134,  # BTN_WEST   -> button 3
    0x136,  # BTN_TL     -> button 4
    0x137,  # BTN_TR     -> button 5
    0x13A,  # BTN_SELECT -> button 6
    0x13B,  # BTN_START  -> button 7
    0x13C,  # BTN_MODE   -> button 8
    0x13D,  # BTN_THUMBL -> button 9
    0x13E,  # BTN_THUMBR -> button 10
]
XBOX_ABS_CODES = [
    0x00,  # ABS_X   -> axis 0
    0x01,  # ABS_Y   -> axis 1
    0x02,  # ABS_Z   -> axis 2
    0x03,  # ABS_RX  -> axis 3
    0x04,  # ABS_RY  -> axis 4
    0x05,  # ABS_RZ  -> axis 5
    0x10,  # ABS_HAT0X -> hat 0, horizontal
    0x11,  # ABS_HAT0Y -> hat 0, vertical
]


class BitmapParsingTests(unittest.TestCase):
    def test_rightmost_word_holds_low_bits(self):
        self.assertEqual(gr.parse_bitmap("3"), {0, 1})

    def test_words_are_64_bit_and_most_significant_first(self):
        # Taken from a real /proc entry for a power button: KEY_POWER (116).
        bits = gr.parse_bitmap("10000000000000 0")
        self.assertEqual(bits, {116})

    def test_zero_words_shift_the_offset(self):
        self.assertEqual(gr.parse_bitmap("1 0 0"), {128})

    def test_empty_and_garbage_are_tolerated(self):
        self.assertEqual(gr.parse_bitmap(""), set())
        self.assertEqual(gr.parse_bitmap(None), set())
        self.assertEqual(gr.parse_bitmap("zz 1"), {0})

    def test_btn_south_bit_round_trips(self):
        word_index, bit = divmod(gr.BTN_GAMEPAD, 64)
        # Most significant word first; the word holding the bit leads the list.
        words = [format(1 << bit, "x")] + ["0"] * word_index
        self.assertIn(gr.BTN_GAMEPAD, gr.parse_bitmap(" ".join(words)))


FAKE_PROC = """I: Bus=0019 Vendor=0000 Product=0005 Version=0000
N: Name="Lid Switch"
P: Phys=PNP0C0D/button/input0
H: Handlers=event0
B: PROP=0
B: EV=21
B: SW=1

I: Bus=0003 Vendor=045e Product=0b13 Version=0508
N: Name="Xbox Wireless Controller"
P: Phys=usb-0000:00:14.0-1/input0
H: Handlers=event20 js0
B: PROP=0
B: EV=20000b
B: KEY={key}
B: ABS={abs}
B: FF=107030000 0 0

I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
P: Phys=isa0060/serio0/input0
H: Handlers=sysrq kbd event3 leds
B: PROP=0
B: EV=120013
B: KEY=402000007 ff80307af830d001 feffffdfffcfffff fffffffffffffffe
B: MSC=10
"""


def _encode_bitmap(codes, max_bit):
    """Render a set of bit indices the way the kernel prints them."""
    value = 0
    for code in codes:
        value |= 1 << code
    word_count = (max_bit // 64) + 1
    words = [(value >> (64 * i)) & 0xFFFFFFFFFFFFFFFF for i in range(word_count)]
    while len(words) > 1 and words[-1] == 0:
        words.pop()
    return " ".join(format(w, "x") for w in reversed(words))


def fake_proc_content():
    return FAKE_PROC.format(
        key=_encode_bitmap(XBOX_KEY_CODES, gr.KEY_MAX),
        abs=_encode_bitmap(XBOX_ABS_CODES, gr.ABS_MAX),
    )


class ProcDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.entries = gr.parse_proc_input_devices(fake_proc_content())

    def test_parses_every_block(self):
        self.assertEqual(
            [e["name"] for e in self.entries],
            ["Lid Switch", "Xbox Wireless Controller", "AT Translated Set 2 keyboard"],
        )

    def test_only_the_pad_is_a_gamepad(self):
        pads = [e for e in self.entries if gr.is_gamepad(e)]
        self.assertEqual([e["name"] for e in pads], ["Xbox Wireless Controller"])

    def test_capabilities_round_trip(self):
        pad = self.entries[1]
        self.assertEqual(pad["key_codes"], sorted(XBOX_KEY_CODES))
        self.assertEqual(pad["abs_codes"], sorted(XBOX_ABS_CODES))
        self.assertEqual(pad["handlers"], ["event20", "js0"])

    def test_list_gamepads_resolves_device_nodes(self):
        pads = gr.list_gamepads(proc_content=fake_proc_content(), dev_dir="/dev/input")
        self.assertEqual(len(pads), 1)
        self.assertEqual(pads[0].name, "Xbox Wireless Controller")
        self.assertEqual(pads[0].event_path, "/dev/input/event20")
        self.assertEqual(pads[0].js_path, "/dev/input/js0")

    def test_keyboard_without_btn_gamepad_is_rejected(self):
        keyboard = self.entries[2]
        self.assertFalse(gr.is_gamepad(keyboard))

    def test_btn_joystick_also_counts(self):
        self.assertTrue(gr.is_gamepad({"key_codes": [gr.BTN_JOYSTICK]}))


class IndexMapTests(unittest.TestCase):
    def test_button_indices_follow_ascending_keycode_order(self):
        index_map = gr.build_button_index_map(XBOX_KEY_CODES)
        self.assertEqual(index_map[0x130], 0)
        self.assertEqual(index_map[0x131], 1)
        self.assertEqual(index_map[0x133], 2)  # 0x132 absent -> no gap
        self.assertEqual(index_map[0x134], 3)
        self.assertEqual(index_map[0x13E], 10)

    def test_button_map_ignores_codes_below_btn_misc(self):
        index_map = gr.build_button_index_map([0x1E, 0x130, 0x131])  # KEY_A, BTN_SOUTH, BTN_EAST
        self.assertNotIn(0x1E, index_map)
        self.assertEqual(index_map[0x130], 0)
        self.assertEqual(index_map[0x131], 1)

    def test_axis_indices_skip_hats(self):
        index_map = gr.build_axis_index_map(XBOX_ABS_CODES)
        self.assertEqual(index_map, {0x00: 0, 0x01: 1, 0x02: 2, 0x03: 3, 0x04: 4, 0x05: 5})
        self.assertNotIn(gr.ABS_HAT0X, index_map)
        self.assertNotIn(gr.ABS_HAT0Y if hasattr(gr, "ABS_HAT0Y") else 0x11, index_map)

    def test_hat_map(self):
        hat_map = gr.build_hat_map(XBOX_ABS_CODES)
        self.assertEqual(hat_map, {0x10: (0, False), 0x11: (0, True)})
        self.assertEqual(gr.build_hat_map([0x16, 0x17]), {0x16: (3, False), 0x17: (3, True)})


class TokenConversionTests(unittest.TestCase):
    def setUp(self):
        self.mapper = gr.TokenMapper(
            XBOX_KEY_CODES,
            XBOX_ABS_CODES,
            axis_ranges={
                0x00: (-32768, 32767),
                0x01: (-32768, 32767),
                0x02: (0, 1023),  # left trigger
                0x05: (0, 1023),  # right trigger
            },
        )

    def test_button_press_becomes_bare_index(self):
        self.assertEqual(self.mapper.token_for_event(gr.EV_KEY, 0x134, 1), "3")

    def test_button_release_is_ignored(self):
        self.assertIsNone(self.mapper.token_for_event(gr.EV_KEY, 0x134, 0))

    def test_unknown_keycode_is_ignored(self):
        self.assertIsNone(self.mapper.token_for_event(gr.EV_KEY, 0x2A0, 1))

    def test_axis_beyond_deadzone_becomes_signed_token(self):
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x01, 30000), "+1")
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x01, -30000), "-1")

    def test_axis_inside_deadzone_returns_none(self):
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x01, 0))
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x01, 5000))
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x01, -16000))

    def test_trigger_resting_at_zero_is_not_a_press(self):
        # Range 0..1023 -> threshold 511.5, measured from raw zero (as udev does).
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x02, 0))
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x02, 200))

    def test_pulled_trigger_yields_a_positive_token(self):
        # Matches the shipped default binding l2="+2".
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x02, 1023), "+2")
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x05, 900), "+5")

    def test_hat_becomes_retroarch_hat_token(self):
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x10, -1), "h0left")
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x10, 1), "h0right")
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x11, -1), "h0up")
        self.assertEqual(self.mapper.token_for_event(gr.EV_ABS, 0x11, 1), "h0down")

    def test_hat_recentre_returns_none(self):
        self.assertIsNone(self.mapper.token_for_event(gr.EV_ABS, 0x10, 0))

    def test_unrelated_event_types_are_ignored(self):
        self.assertIsNone(self.mapper.token_for_event(0x04, 0x04, 1))  # EV_MSC

    def test_hat_tokens_match_shipped_defaults(self):
        from openemux.core.input_actions import DEFAULT_GAMEPAD_BINDINGS

        self.assertEqual(
            {DEFAULT_GAMEPAD_BINDINGS[a] for a in ("up", "down", "left", "right")},
            {"h0up", "h0down", "h0left", "h0right"},
        )


class RawByteStreamTests(unittest.TestCase):
    """Feed the exact bytes the kernel would produce, no hardware involved."""

    def test_input_event_struct_decodes_to_a_button_token(self):
        import struct

        mapper = gr.TokenMapper(XBOX_KEY_CODES, XBOX_ABS_CODES)
        blob = (
            struct.pack(gr.INPUT_EVENT_FORMAT, 1, 0, gr.EV_KEY, 0x136, 1)
            + struct.pack(gr.INPUT_EVENT_FORMAT, 1, 0, gr.EV_KEY, 0x136, 0)
        )
        tokens = []
        for offset in range(0, len(blob), gr.INPUT_EVENT_SIZE):
            _s, _u, t, c, v = struct.unpack(
                gr.INPUT_EVENT_FORMAT, blob[offset:offset + gr.INPUT_EVENT_SIZE]
            )
            tokens.append(mapper.token_for_event(t, c, v))
        self.assertEqual(tokens, ["4", None])  # press then release

    def test_joydev_events(self):
        self.assertEqual(gr.joydev_token(0, 1, gr.JS_EVENT_BUTTON, 3), "3")
        self.assertIsNone(gr.joydev_token(0, 0, gr.JS_EVENT_BUTTON, 3))
        # Synthetic init events must not be mistaken for a press.
        self.assertIsNone(
            gr.joydev_token(0, 1, gr.JS_EVENT_BUTTON | gr.JS_EVENT_INIT, 3)
        )
        self.assertEqual(gr.joydev_token(0, 30000, gr.JS_EVENT_AXIS, 2), "+2")
        self.assertEqual(gr.joydev_token(0, -30000, gr.JS_EVENT_AXIS, 2), "-2")
        self.assertIsNone(gr.joydev_token(0, 100, gr.JS_EVENT_AXIS, 2))

    def test_struct_sizes_match_the_kernel_abi(self):
        self.assertEqual(gr.JS_EVENT_SIZE, 8)
        self.assertEqual(gr.INPUT_EVENT_SIZE, 24)


class DescribeTokenTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(gr.describe_token("3"), ("button", "3"))
        self.assertEqual(gr.describe_token("+2"), ("axis", "+2"))
        self.assertEqual(gr.describe_token("-11"), ("axis", "-11"))
        self.assertEqual(gr.describe_token("h0up"), ("hat", "up"))
        self.assertEqual(gr.describe_token("h1left"), ("hat", "left"))
        self.assertEqual(gr.describe_token(""), ("raw", ""))
        self.assertEqual(gr.describe_token("space"), ("raw", "space"))


class ReaderLifecycleTests(unittest.TestCase):
    def test_no_gamepad_reports_reason_without_touching_hardware(self):
        errors = []
        reader = gr.GamepadCaptureReader(on_token=lambda _t: None, on_error=errors.append)
        original = gr.list_gamepads
        gr.list_gamepads = lambda *a, **k: []
        try:
            reader._run()
        finally:
            gr.list_gamepads = original
        self.assertEqual(errors, ["no_gamepad"])

    def test_stop_is_safe_when_never_started(self):
        reader = gr.GamepadCaptureReader(on_token=lambda _t: None)
        reader.stop()
        self.assertTrue(reader.cancelled)

    def test_only_the_first_result_is_delivered(self):
        tokens = []
        reader = gr.GamepadCaptureReader(on_token=tokens.append)
        reader._emit_token("3")
        reader._emit_token("4")
        self.assertEqual(tokens, ["3"])


if __name__ == "__main__":
    unittest.main()

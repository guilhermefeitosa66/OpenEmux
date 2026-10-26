import json
import unittest
from unittest import mock

from openemux.core import share
from openemux.core.share import protocol
from openemux.core.share.protocol import ErrorCode, ShareError

ID = "a" * 32
FP = "b" * 64


def beacon(**overrides):
    payload = {
        "p": "openemux-share", "t": "hello", "id": ID, "name": "Den PC", "pf": "desktop",
        "v": 1, "vmin": 1, "port": 53319, "fp": FP,
    }
    payload.update(overrides)
    return json.dumps({k: v for k, v in payload.items() if v is not None}).encode()


def manifest(items=None, **overrides):
    items = items if items is not None else [
        {"id": "i1", "kind": "rom", "name": "Game.nes", "size": 10, "mtime": 1700000000}
    ]
    data = {
        "games": [{"id": "g1", "console": "FC", "title": "Game", "items": items}],
        "total_size": 10, "file_count": len(items),
    }
    data.update(overrides)
    return data


class AvailabilityTests(unittest.TestCase):
    def test_everything_installed(self):
        with mock.patch.object(share.importlib.util, "find_spec", return_value=object()):
            self.assertEqual(share.availability(), {"share": "ok", "mdns": "ok"})

    def test_without_cryptography_the_feature_is_off(self):
        with mock.patch.object(share.importlib.util, "find_spec", return_value=None):
            self.assertEqual(
                share.availability(),
                {"share": "unavailable:cryptography", "mdns": "unavailable:cryptography"},
            )

    def test_without_zeroconf_only_mdns_is_off(self):
        def find_spec(name):
            return None if name == "zeroconf" else object()

        with mock.patch.object(share.importlib.util, "find_spec", side_effect=find_spec):
            self.assertEqual(share.availability(), {"share": "ok", "mdns": "unavailable:zeroconf"})

    def test_a_broken_finder_counts_as_missing(self):
        with mock.patch.object(share.importlib.util, "find_spec", side_effect=ValueError):
            self.assertEqual(share.availability()["share"], "unavailable:cryptography")


class VersionTests(unittest.TestCase):
    def test_ranges(self):
        self.assertTrue(protocol.is_compatible(1, 1))
        self.assertTrue(protocol.is_compatible(1, 5))
        self.assertFalse(protocol.is_compatible(2, 5))
        self.assertFalse(protocol.is_compatible(0, 0))
        self.assertFalse(protocol.is_compatible(3, 2))
        self.assertFalse(protocol.is_compatible("1", 1))
        self.assertFalse(protocol.is_compatible(True, 1))

    def test_negotiate_picks_the_highest_common_version(self):
        self.assertEqual(protocol.negotiate(1, 9), 1)
        self.assertIsNone(protocol.negotiate(2, 9))

    def test_version_error_names_both_versions(self):
        error = protocol.version_error(2, 3)
        self.assertEqual(error.code, ErrorCode.INCOMPATIBLE_VERSION)
        self.assertEqual(error.message, "version 1 vs 3")
        self.assertEqual(error.details["peer"], {"min": 2, "max": 3})
        self.assertEqual(error.details["supported"], {"min": 1, "max": 1})


class ErrorEnvelopeTests(unittest.TestCase):
    def test_round_trip(self):
        error = protocol.version_error(2, 2)
        envelope = error.to_envelope()
        self.assertEqual(envelope["error"], "incompatible_version")
        back = ShareError.from_envelope(400, envelope)
        self.assertEqual((back.code, back.message, back.details), (error.code, error.message, error.details))
        self.assertEqual(back.http_status, 400)

    def test_message_defaults_to_the_code(self):
        self.assertEqual(ShareError(ErrorCode.BUSY).message, "busy")
        self.assertEqual(str(ShareError(ErrorCode.BUSY)), "busy")

    def test_a_local_code_has_no_wire_status(self):
        self.assertEqual(ShareError(ErrorCode.FINGERPRINT_MISMATCH).http_status, 500)

    def test_an_answer_without_an_envelope_is_internal(self):
        self.assertEqual(ShareError.from_envelope(502, None).code, ErrorCode.INTERNAL)
        self.assertEqual(ShareError.from_envelope(502, {"error": 3}).code, ErrorCode.INTERNAL)

    def test_a_non_string_message_is_ignored(self):
        self.assertEqual(ShareError.from_envelope(409, {"error": "busy", "message": 5}).message, "busy")


class SanitizeTests(unittest.TestCase):
    def test_control_characters_are_stripped_and_length_capped(self):
        self.assertEqual(protocol.sanitize_name("  Den\x00 PC\u200b\n "), "Den PC")
        self.assertEqual(len(protocol.sanitize_name("x" * 100)), 64)
        self.assertEqual(protocol.sanitize_name(None), "")

    def test_unknown_platform_is_desktop(self):
        self.assertEqual(protocol.sanitize_platform("phone"), "phone")
        self.assertEqual(protocol.sanitize_platform("fridge"), "desktop")

    def test_fingerprint_groups_of_four(self):
        self.assertEqual(protocol.format_fingerprint("abcd1234ef"), "abcd 1234 ef")

    def test_is_hex(self):
        self.assertTrue(protocol.is_hex("0f" * 16, 32))
        self.assertFalse(protocol.is_hex("0F" * 16, 32))
        self.assertFalse(protocol.is_hex("0f", 32))
        self.assertFalse(protocol.is_hex(None, 32))


class DecimalTests(unittest.TestCase):
    def test_ascii_digits_only(self):
        self.assertEqual(protocol.parse_decimal("042"), 42)
        for value in ("\u00b2", "\u0661", "", "-1", "1.0", None, 3):
            with self.subTest(value=value):
                self.assertIsNone(protocol.parse_decimal(value))

    def test_non_ascii_digits_are_dropped_not_raised(self):
        self.assertIsNone(protocol.parse_beacon(beacon(port="\u00b2")))
        parsed = protocol.parse_beacon(beacon(v="\u00b2"))
        self.assertEqual((parsed["v"], parsed["compatible"]), (0, False))


class BeaconTests(unittest.TestCase):
    def test_valid_hello(self):
        parsed = protocol.parse_beacon(beacon())
        self.assertEqual(parsed["type"], "hello")
        self.assertEqual((parsed["id"], parsed["fp"], parsed["port"]), (ID, FP, 53319))
        self.assertTrue(parsed["compatible"])

    def test_bye(self):
        self.assertEqual(protocol.parse_beacon(beacon(t="bye"))["type"], "bye")

    def test_round_trip_with_build(self):
        announcement = protocol.parse_beacon(beacon())
        rebuilt = protocol.parse_beacon(protocol.build_beacon("hello", announcement))
        self.assertEqual(rebuilt, announcement)

    def test_dropped(self):
        for data in (
            b"x" * 1025,
            b"\xff\xfe",
            b"not json",
            b"[1, 2]",
            "nope",
            beacon(p="other"),
            beacon(t="ping"),
            beacon(port=None),
            beacon(port=0),
            beacon(port=70000),
            beacon(port="x"),
            beacon(id="short"),
            beacon(fp=None),
        ):
            with self.subTest(data=data[:30]):
                self.assertIsNone(protocol.parse_beacon(data))

    def test_unknown_keys_are_ignored(self):
        self.assertIsNotNone(protocol.parse_beacon(beacon(extra={"a": 1})))

    def test_future_version_is_flagged_not_dropped(self):
        parsed = protocol.parse_beacon(beacon(v=7, vmin=5))
        self.assertEqual((parsed["vmin"], parsed["v"]), (5, 7))
        self.assertFalse(parsed["compatible"])

    def test_missing_or_garbled_versions(self):
        parsed = protocol.parse_beacon(beacon(v=None, vmin=None))
        self.assertEqual((parsed["vmin"], parsed["v"], parsed["compatible"]), (0, 0, False))
        parsed = protocol.parse_beacon(beacon(v="3", vmin=None))
        self.assertEqual((parsed["vmin"], parsed["v"]), (3, 3))
        parsed = protocol.parse_beacon(beacon(v=1, vmin=4))
        self.assertEqual((parsed["vmin"], parsed["v"]), (1, 1))

    def test_nameless_device_is_named_after_its_id(self):
        self.assertEqual(protocol.parse_beacon(beacon(name="\x01"))["name"], "aaaaaa")


class TxtTests(unittest.TestCase):
    def txt(self, overrides=None):
        record = {b"id": ID.encode(), b"name": "Sala".encode(), b"pf": b"phone", b"v": b"1",
                  b"vmin": b"1", b"fp": FP.encode(), b"flag": None}
        record.update(overrides or {})
        return record

    def test_valid(self):
        parsed = protocol.parse_txt(self.txt(), 53319)
        self.assertEqual((parsed["name"], parsed["platform"], parsed["v"]), ("Sala", "phone", 1))

    def test_str_keys_and_round_trip(self):
        announcement = protocol.parse_txt(self.txt(), 1234)
        built = protocol.build_txt(announcement)
        self.assertEqual(protocol.parse_txt(built, 1234), announcement)

    def test_rejected(self):
        self.assertIsNone(protocol.parse_txt("x", 1))
        self.assertIsNone(protocol.parse_txt(self.txt(), None))
        self.assertIsNone(protocol.parse_txt(self.txt({b"id": b"\xff"}), 1))
        self.assertIsNone(protocol.parse_txt(self.txt({b"fp": b"zz"}), 1))

    def test_undecodable_key_is_skipped(self):
        self.assertIsNotNone(protocol.parse_txt(self.txt({b"\xff": b"1"}), 1))

    def test_incompatible_is_flagged(self):
        self.assertFalse(protocol.parse_txt(self.txt({b"v": b"9", b"vmin": b"9"}), 1)["compatible"])


class InfoTests(unittest.TestCase):
    def test_valid(self):
        info = protocol.parse_info({"id": ID, "name": "X", "pf": "tablet", "v": 1, "vmin": 1})
        self.assertEqual((info["platform"], info["compatible"]), ("tablet", True))

    def test_malformed(self):
        for payload in (None, [], {"id": "x"}):
            with self.assertRaises(ShareError) as caught:
                protocol.parse_info(payload)
            self.assertEqual(caught.exception.code, ErrorCode.BAD_REQUEST)


class OfferTests(unittest.TestCase):
    def offer(self, **overrides):
        payload = {"sender": {"id": ID, "name": "PC", "pf": "desktop", "fp": FP},
                   "commit": "c" * 64, "manifest": manifest()}
        payload.update(overrides)
        return payload

    def assertBad(self, payload):
        with self.assertRaises(ShareError) as caught:
            protocol.parse_offer(payload)
        self.assertEqual(caught.exception.code, ErrorCode.BAD_REQUEST)

    def test_valid(self):
        parsed = protocol.parse_offer(self.offer())
        self.assertEqual(parsed["sender"], {"id": ID, "name": "PC", "platform": "desktop", "fp": FP})

    def test_envelope_errors(self):
        self.assertBad([])
        self.assertBad(self.offer(sender="x"))
        self.assertBad(self.offer(sender={"id": ID}))
        self.assertBad(self.offer(commit="x"))
        self.assertBad(self.offer(manifest=None))

    def test_manifest_errors(self):
        item = {"id": "i", "kind": "rom", "name": "a.nes", "size": 1, "mtime": 1}
        bad_items = [
            "x",
            dict(item, id=1),
            dict(item, name="../a.nes"),
            dict(item, name="a/b"),
            dict(item, name="a\\b"),
            dict(item, name="a\x00"),
            dict(item, name=".."),
            dict(item, name="x" * 256),
            dict(item, size=-1),
            dict(item, size=True),
            dict(item, mtime="now"),
            dict(item, mtime=False),
        ]
        for bad in bad_items:
            with self.subTest(item=bad):
                self.assertBad(self.offer(manifest=manifest([bad])))
        self.assertBad(self.offer(manifest={"games": [{"items": "x"}]}))
        self.assertBad(self.offer(manifest={"games": ["x"]}))
        self.assertBad(self.offer(manifest={"games": [{"items": [], "id": "g", "console": 1, "title": "t"}]}))
        self.assertBad(self.offer(manifest=manifest(total_size=-1)))
        self.assertBad(self.offer(manifest=manifest(file_count="1")))

    def test_item_limit(self):
        item = {"id": "i", "kind": "rom", "name": "a.nes", "size": 1, "mtime": 1.5}
        self.assertIsNotNone(protocol.parse_offer(self.offer(manifest=manifest([item] * 2000))))
        self.assertBad(self.offer(manifest=manifest([item] * 2001)))

    def test_unknown_kind_and_fields_pass(self):
        item = {"id": "i", "kind": "hologram", "name": "a", "size": 1, "mtime": 1, "x": 1}
        self.assertIsNotNone(protocol.parse_offer(self.offer(manifest=manifest([item]))))

    def test_safe_name(self):
        self.assertTrue(protocol.is_safe_file_name("Super Game (USA).sfc"))
        self.assertFalse(protocol.is_safe_file_name(""))
        self.assertFalse(protocol.is_safe_file_name("."))
        self.assertFalse(protocol.is_safe_file_name(None))


if __name__ == "__main__":
    unittest.main()

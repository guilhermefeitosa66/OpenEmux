import unittest

from openemux.core.share import address
from openemux.core.share.protocol import ErrorCode, ShareError

FP = "ab" * 32


class BuildTests(unittest.TestCase):
    def test_build(self):
        self.assertEqual(address.build("192.168.0.5"), "openemux-share://192.168.0.5:53319")
        self.assertEqual(address.build("pc.local", 9000, FP), f"openemux-share://pc.local:9000#{FP}")
        self.assertEqual(address.build("fe80::1", 9000), "openemux-share://[fe80::1]:9000")

    def test_round_trip(self):
        for host, port, fp in (("192.168.0.5", 53319, FP), ("pc.local", 1, None), ("fe80::1", 65535, FP)):
            with self.subTest(host=host):
                self.assertEqual(address.parse(address.build(host, port, fp)), (host, port, fp))


class ParseTests(unittest.TestCase):
    def test_non_ascii_digits_are_not_a_port(self):
        for text in ("pc:\u00b2", "pc:\u0661\u0662"):
            with self.subTest(text=text):
                with self.assertRaises(ShareError) as caught:
                    address.parse(text)
                self.assertEqual(caught.exception.code, ErrorCode.BAD_REQUEST)

    def test_forms(self):
        self.assertEqual(address.parse(" 10.0.0.2 "), ("10.0.0.2", 53319, None))
        self.assertEqual(address.parse("10.0.0.2:8080"), ("10.0.0.2", 8080, None))
        self.assertEqual(address.parse("[::1]:8080"), ("::1", 8080, None))
        self.assertEqual(address.parse("[::1]"), ("::1", 53319, None))
        self.assertEqual(address.parse("fe80::1"), ("fe80::1", 53319, None))
        self.assertEqual(address.parse("OPENEMUX-SHARE://pc:1/"), ("pc", 1, None))

    def test_fingerprint_is_normalized(self):
        grouped = " ".join(FP.upper()[i:i + 4] for i in range(0, 64, 4))
        self.assertEqual(address.parse(f"pc#{grouped}").fp, FP)

    def test_garbage(self):
        for text in (
            None, "", "   ", "pc:0", "pc:65536", "pc:http", "pc#abc", "[::1", "[::1]x",
            "[::1]:x", "a b", "user@pc", "pc/path", "openemux-share://",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ShareError) as caught:
                    address.parse(text)
                self.assertEqual(caught.exception.code, ErrorCode.BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()

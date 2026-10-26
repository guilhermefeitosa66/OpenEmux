import json
import unittest
from pathlib import Path

from openemux.core.share import verification

VECTORS = json.loads(
    (Path(__file__).parent / "data" / "share_vectors.json").read_text(encoding="utf-8")
)["vectors"]


class VectorTests(unittest.TestCase):
    """The vectors docs/share-protocol.md quotes, shared with the Android app."""

    def test_vectors(self):
        for vector in VECTORS:
            with self.subTest(vector["name"]):
                nonce_s = bytes.fromhex(vector["nonce_s"])
                nonce_r = bytes.fromhex(vector["nonce_r"])
                self.assertEqual(verification.commit(nonce_s), vector["commit"])
                self.assertTrue(verification.check_commit(vector["commit"], nonce_s))
                self.assertEqual(
                    verification.code(vector["fp_sender"], vector["fp_receiver"], nonce_s, nonce_r),
                    vector["code"],
                )

    def test_a_vector_pins_zero_padding(self):
        self.assertTrue(any(vector["code"].startswith("0") for vector in VECTORS))

    def test_the_spec_quotes_the_vectors(self):
        spec = (Path(__file__).parents[1] / "docs" / "share-protocol.md").read_text(encoding="utf-8")
        for vector in VECTORS[:2]:
            self.assertIn(vector["code"], spec)
            self.assertIn(vector["commit"], spec)


class CodeTests(unittest.TestCase):
    def setUp(self):
        self.fp_s, self.fp_r = "01" * 32, "02" * 32
        self.n_s, self.n_r = b"\x03" * 32, b"\x04" * 32
        self.base = verification.code(self.fp_s, self.fp_r, self.n_s, self.n_r)

    def test_six_digits(self):
        self.assertRegex(self.base, r"^\d{6}$")
        self.assertEqual(verification.format_code("012345"), "012 345")

    def test_every_input_changes_the_code(self):
        self.assertNotEqual(self.base, verification.code("05" * 32, self.fp_r, self.n_s, self.n_r))
        self.assertNotEqual(self.base, verification.code(self.fp_s, "05" * 32, self.n_s, self.n_r))
        self.assertNotEqual(self.base, verification.code(self.fp_s, self.fp_r, b"\x05" * 32, self.n_r))
        self.assertNotEqual(self.base, verification.code(self.fp_s, self.fp_r, self.n_s, b"\x05" * 32))

    def test_bad_commit(self):
        nonce = verification.new_nonce()
        self.assertEqual(len(nonce), 32)
        commitment = verification.commit(nonce)
        self.assertTrue(verification.check_commit(commitment.upper(), nonce))
        self.assertFalse(verification.check_commit(commitment, verification.new_nonce()))
        self.assertFalse(verification.check_commit(None, nonce))
        self.assertFalse(verification.check_commit(commitment, "nonce"))


if __name__ == "__main__":
    unittest.main()

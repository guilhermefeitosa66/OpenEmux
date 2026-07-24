import unittest
from pathlib import Path
from unittest import mock

from openemux.core import cover_sync, embedded_credentials


class ObfuscationRoundTripTests(unittest.TestCase):
    def test_round_trip(self):
        blob = embedded_credentials.obfuscate("dev-id-123", "s3cr3t-pass")
        self.assertEqual(embedded_credentials.deobfuscate(blob), ("dev-id-123", "s3cr3t-pass"))

    def test_blob_is_not_plaintext(self):
        # Light obfuscation: the raw values must not appear verbatim in the blob.
        blob = embedded_credentials.obfuscate("mydevid", "mypassword")
        self.assertNotIn("mydevid", blob)
        self.assertNotIn("mypassword", blob)


class EmbeddedCredentialsTests(unittest.TestCase):
    def test_empty_blob_yields_no_credentials(self):
        with mock.patch.object(embedded_credentials, "_EMBEDDED_BLOB", ""):
            self.assertEqual(embedded_credentials.get_embedded_dev_credentials(), ("", ""))
            self.assertFalse(embedded_credentials.has_embedded_dev_credentials())

    def test_populated_blob_yields_credentials(self):
        blob = embedded_credentials.obfuscate("build-dev", "build-pw")
        with mock.patch.object(embedded_credentials, "_EMBEDDED_BLOB", blob):
            self.assertEqual(
                embedded_credentials.get_embedded_dev_credentials(), ("build-dev", "build-pw")
            )
            self.assertTrue(embedded_credentials.has_embedded_dev_credentials())

    def test_malformed_blob_degrades_to_none(self):
        with mock.patch.object(embedded_credentials, "_EMBEDDED_BLOB", "!!!not-base64!!!"):
            self.assertEqual(embedded_credentials.get_embedded_dev_credentials(), ("", ""))
            self.assertFalse(embedded_credentials.has_embedded_dev_credentials())

    def test_source_ships_empty_blob(self):
        """Guard: the committed module must never carry a real credential."""
        module_path = Path(embedded_credentials.__file__)
        self.assertIn('_EMBEDDED_BLOB = ""', module_path.read_text(encoding="utf-8"))
        self.assertEqual(embedded_credentials._EMBEDDED_BLOB, "")


class ResolveDevCredentialsTests(unittest.TestCase):
    def test_user_credentials_override_embedded(self):
        settings = {"screenscraper_devid": "user-dev", "screenscraper_devpassword": "user-pw"}
        with mock.patch.object(
            embedded_credentials, "get_embedded_dev_credentials", return_value=("emb", "emb-pw")
        ):
            self.assertEqual(cover_sync._resolve_dev_credentials(settings), ("user-dev", "user-pw"))

    def test_embedded_used_when_user_empty(self):
        settings = {"screenscraper_devid": "", "screenscraper_devpassword": ""}
        with mock.patch.object(
            embedded_credentials, "get_embedded_dev_credentials", return_value=("emb", "emb-pw")
        ):
            self.assertEqual(cover_sync._resolve_dev_credentials(settings), ("emb", "emb-pw"))

    def test_partial_user_credentials_fall_back_to_embedded(self):
        # devid without devpassword is not a usable pair -> embedded wins.
        settings = {"screenscraper_devid": "only-id", "screenscraper_devpassword": ""}
        with mock.patch.object(
            embedded_credentials, "get_embedded_dev_credentials", return_value=("emb", "emb-pw")
        ):
            self.assertEqual(cover_sync._resolve_dev_credentials(settings), ("emb", "emb-pw"))

    def test_no_credentials_anywhere(self):
        settings = {}
        with mock.patch.object(
            embedded_credentials, "get_embedded_dev_credentials", return_value=("", "")
        ):
            self.assertEqual(cover_sync._resolve_dev_credentials(settings), ("", ""))


if __name__ == "__main__":
    unittest.main()

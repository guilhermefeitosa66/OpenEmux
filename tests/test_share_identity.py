import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from openemux.core.config import ConfigManager
from openemux.core.share import identity


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "share"

    def test_create(self):
        device = identity.load_or_create(self.dir, "Living room")
        self.assertRegex(device.id, r"^[0-9a-f]{32}$")
        self.assertEqual((device.name, device.platform), ("Living room", "desktop"))
        self.assertEqual(mode(self.dir), 0o700)
        self.assertEqual(mode(self.dir / "key.pem"), 0o600)
        self.assertEqual(mode(self.dir / "cert.pem"), 0o644)
        cert = x509.load_pem_x509_certificate((self.dir / "cert.pem").read_bytes())
        der = cert.public_bytes(serialization.Encoding.DER)
        self.assertEqual(device.fingerprint, hashlib.sha256(der).hexdigest())
        self.assertEqual(device.cert_path, self.dir / "cert.pem")
        self.assertEqual(device.key_path, self.dir / "key.pem")

    def test_reload_keeps_id_and_fingerprint(self):
        first = identity.load_or_create(self.dir, "A")
        second = identity.load_or_create(self.dir, "B")
        self.assertEqual((second.id, second.fingerprint), (first.id, first.fingerprint))
        self.assertEqual(second.name, "B")

    def test_hostname_is_the_default_name(self):
        with mock.patch.object(identity.socket, "gethostname", return_value="desk\x07top"):
            self.assertEqual(identity.load_or_create(self.dir).name, "desktop")
        with mock.patch.object(identity.socket, "gethostname", return_value=""):
            self.assertEqual(identity.default_device_name(), "OpenEmux")

    def test_configured_name(self):
        config = ConfigManager(config_file=Path(self.tmp.name) / "config.yaml")
        config.set_share_device_name("  Sofa  ")
        self.assertEqual(identity.load_or_create(self.dir, config.get_share_device_name()).name, "Sofa")

    def assertRegenerated(self, damage):
        first = identity.load_or_create(self.dir)
        damage()
        with self.assertLogs(identity.logger, "WARNING"):
            second = identity.load_or_create(self.dir)
        self.assertNotEqual(second.id, first.id)
        self.assertNotEqual(second.fingerprint, first.fingerprint)
        self.assertEqual(identity.load_or_create(self.dir).id, second.id)

    def test_corrupt_identity_json(self):
        self.assertRegenerated(lambda: (self.dir / "identity.json").write_text("{"))

    def test_bad_id(self):
        self.assertRegenerated(lambda: (self.dir / "identity.json").write_text(json.dumps({"id": "x"})))

    def test_missing_key(self):
        self.assertRegenerated(lambda: (self.dir / "key.pem").unlink())

    def test_corrupt_certificate(self):
        self.assertRegenerated(lambda: (self.dir / "cert.pem").write_text("garbage"))

    def test_certificate_of_another_id(self):
        def swap_id():
            (self.dir / "identity.json").write_text(json.dumps({"id": "0" * 32}))

        self.assertRegenerated(swap_id)

    def test_key_that_does_not_match_the_certificate(self):
        other = Path(self.tmp.name) / "other"
        identity.load_or_create(other)

        def swap_key():
            (self.dir / "key.pem").write_bytes((other / "key.pem").read_bytes())

        self.assertRegenerated(swap_key)

    def test_payloads(self):
        device = identity.load_or_create(self.dir, "PC")
        announcement = device.announcement(4242)
        self.assertEqual(announcement["port"], 4242)
        self.assertEqual((announcement["v"], announcement["vmin"]), (1, 1))
        self.assertEqual(device.info(), {"id": device.id, "name": "PC", "pf": "desktop", "v": 1, "vmin": 1})
        self.assertEqual(device.sender()["fp"], device.fingerprint)


class ShareConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.yaml"

    def test_default_is_empty(self):
        self.assertEqual(ConfigManager(config_file=self.path).get_share_device_name(), "")

    def test_set_persists_trimmed(self):
        ConfigManager(config_file=self.path).set_share_device_name("  Den  ")
        self.assertEqual(ConfigManager(config_file=self.path).get_share_device_name(), "Den")

    def test_clearing(self):
        manager = ConfigManager(config_file=self.path)
        manager.set_share_device_name("Den")
        manager.set_share_device_name(None)
        self.assertEqual(manager.get_share_device_name(), "")

    def test_malformed_section(self):
        manager = ConfigManager(config_file=self.path)
        manager.config["share"] = "oops"
        self.assertEqual(manager.get_share_device_name(), "")
        manager.config["share"] = {"device_name": 5}
        self.assertEqual(manager.get_share_device_name(), "")
        manager.config["share"] = None
        manager.set_share_device_name("Den")
        self.assertEqual(manager.get_share_device_name(), "Den")

    def test_store_path(self):
        manager = ConfigManager(config_file=self.path)
        self.assertEqual(manager.store_path("share"), Path(self.tmp.name) / "share")


if __name__ == "__main__":
    unittest.main()

"""Desktop to desktop through both dialogs, over 127.0.0.1 (#589).

Two real ``ShareService``s in one process -- real certificates, real TLS, real
threads -- with discovery limited to the manual path (no multicast). The
sender's dialog connects by address and sends; the receiver's Incoming Games
dialog shows the same code and accepts; the game lands in the receiver's
library and the library is refreshed. Nothing leaves the loopback interface.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Adw

    from openemux.core.config import ConfigManager
    from openemux.core.share.discovery import Discovery
    from openemux.core.share.service import ShareService
    from openemux.ui.share_coordinator import ShareCoordinator

HAVE_CRYPTOGRAPHY = importlib.util.find_spec("cryptography") is not None


@needs_display
@unittest.skipUnless(HAVE_CRYPTOGRAPHY, "cryptography is not installed")
class LoopbackTests(WindowCase):
    def coordinator(self, name, config):
        def factory(_config, **callbacks):
            return ShareService(
                config, share_dir=self.tmp / f"share-{name}",
                discovery_factory=lambda identity, port, on_change: Discovery(
                    identity, port, transports=[], on_change=on_change),
                **callbacks,
            )

        coordinator = ShareCoordinator(self.win, service_factory=factory, addresses=lambda: ["127.0.0.1"])
        self.addCleanup(coordinator.shutdown)
        return coordinator

    def setUp(self):
        super().setUp()
        receiver_config = ConfigManager(self.tmp / "receiver" / "config.yaml")
        receiver_config.set_roms_path(str(self.tmp / "receiver" / "roms"))
        receiver_config.set_share_device_name("Receiver")
        self.receiver_roms = Path(receiver_config.get_roms_path())
        self.config.set_share_device_name("Sender")
        self.sender = self.coordinator("sender", self.config)
        self.receiver = self.coordinator("receiver", receiver_config)
        self.presented = []
        patcher = mock.patch.object(Adw.Dialog, "present", lambda dialog, *a: self.presented.append(dialog))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_game_goes_across_and_shows_up(self):
        receiving = self.receiver.open_receive()
        self.assertTrue(self.pump_until(lambda: self.receiver.address() is not None, timeout=20))
        _host, port, fp, uri = self.receiver.address()

        sending = self.sender.open_send([self.rom("SFC", 0)])
        self.assertTrue(self.pump_until(lambda: sending.built is not None and self.sender.address(), timeout=20))
        sending._push_address()
        sending.address_entry.set_text(uri)
        sending.address_entry.emit("apply")
        self.assertTrue(self.pump_until(lambda: sending._peer_rows, timeout=20))
        row = sending._peer_rows[0]
        self.assertEqual(row.get_title(), "Receiver")
        self.assertIn("address", row.get_subtitle())

        row.emit("activated")
        self.assertTrue(self.pump_until(lambda: self.receiver.offer_dialog is not None, timeout=30))
        offer = self.receiver.offer_dialog
        self.assertTrue(self.pump_until(lambda: sending.waiting.code.get_visible(), timeout=10))
        self.assertEqual(sending.waiting.code.get_label().replace(" ", ""), offer.offer.code)

        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            offer.accept()
            self.assertTrue(self.pump_until(lambda: offer.result is not None, timeout=60))
            self.assertTrue(self.pump_until(lambda: getattr(sending, "result", None) is not None, timeout=30))
        rescan.assert_called_once_with("SFC")
        self.assertTrue((self.receiver_roms / "SFC" / "Chrono Trigger.sfc").is_file())
        self.assertEqual(sending.nav.get_visible_page().get_tag(), "result")
        self.assertIsNone(self.receiver.transfer)
        self.assertIsNone(self.sender.transfer)
        receiving.emit("closed")
        sending.emit("closed")

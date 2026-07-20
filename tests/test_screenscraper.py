"""Tests for the ScreenScraper cover source. All network I/O is mocked."""
import json
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from openemux.core import screenscraper
from openemux.core.screenscraper import (
    ScreenScraperCredentials,
    build_jeu_infos_url,
    get_screenscraper_system_id,
    lookup_media_urls,
    parse_media_urls,
    redact,
    region_priority_for,
)


# A trimmed but structurally realistic jeuInfos.php payload: one game with both
# box art and cartridge-label ("support") media across several regions.
SAMPLE_PAYLOAD = json.dumps(
    {
        "header": {"APIversion": "2", "success": "true"},
        "response": {
            "jeu": {
                "id": "2169",
                "noms": [{"region": "wor", "text": "Chrono Trigger"}],
                "systeme": {"id": "4", "text": "Super Nintendo"},
                "medias": [
                    {
                        "type": "ss",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=ss",
                        "region": "wor",
                        "format": "png",
                    },
                    {
                        "type": "box-2D",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=box-2D&region=jp",
                        "region": "jp",
                        "format": "png",
                        "crc": "1a2b3c4d",
                    },
                    {
                        "type": "box-2D",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=box-2D&region=us",
                        "region": "us",
                        "format": "png",
                    },
                    {
                        "type": "support-2D",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=support-2D&region=us",
                        "region": "us",
                        "format": "png",
                    },
                    {
                        "type": "support-2D",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=support-2D&region=eu",
                        "region": "eu",
                        "format": "png",
                    },
                    {
                        "type": "wheel",
                        "parent": "jeu",
                        "url": "https://www.screenscraper.fr/image.php?gameid=2169&media=wheel",
                        "region": "wor",
                        "format": "png",
                    },
                ],
            }
        },
    }
)


def _creds(user="player1", password="secretpw"):
    return ScreenScraperCredentials(
        devid="devuser", devpassword="devsecret", user=user, password=password
    )


class _FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class UrlBuildTests(unittest.TestCase):
    def setUp(self):
        # Keep the throttle from slowing the suite down.
        patcher = patch("openemux.core.screenscraper._throttle")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_url_contains_all_required_api_parameters(self):
        url = build_jeu_infos_url(
            credentials=_creds(),
            systemeid=4,
            rom_name="Chrono Trigger (USA).sfc",
            crc="A1B2C3D4",
            md5="0123456789ABCDEF0123456789ABCDEF",
            rom_size=4194304,
        )
        self.assertTrue(url.startswith("https://api.screenscraper.fr/api2/jeuInfos.php?"))
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(params["devid"], ["devuser"])
        self.assertEqual(params["devpassword"], ["devsecret"])
        self.assertEqual(params["softname"], ["OpenEmux"])
        self.assertEqual(params["output"], ["json"])
        self.assertEqual(params["ssid"], ["player1"])
        self.assertEqual(params["sspassword"], ["secretpw"])
        self.assertEqual(params["systemeid"], ["4"])
        self.assertEqual(params["romtype"], ["rom"])
        self.assertEqual(params["romnom"], ["Chrono Trigger (USA).sfc"])
        self.assertEqual(params["crc"], ["A1B2C3D4"])
        self.assertEqual(params["md5"], ["0123456789ABCDEF0123456789ABCDEF"])
        self.assertEqual(params["romtaille"], ["4194304"])

    def test_url_omits_user_account_when_not_configured(self):
        url = build_jeu_infos_url(
            credentials=_creds(user="", password=""), systemeid=3, rom_name="Metroid.nes"
        )
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertNotIn("ssid", params)
        self.assertNotIn("sspassword", params)
        self.assertEqual(params["devid"], ["devuser"])

    def test_url_is_none_without_developer_credentials(self):
        # Anonymous access is not possible against the ScreenScraper API.
        creds = ScreenScraperCredentials(user="player1", password="secretpw")
        self.assertFalse(creds.is_usable())
        self.assertIsNone(build_jeu_infos_url(creds, 4, "Chrono Trigger.sfc"))
        self.assertIsNone(build_jeu_infos_url(None, 4, "Chrono Trigger.sfc"))


class SystemMappingTests(unittest.TestCase):
    def test_openemux_console_ids_map_to_screenscraper_system_ids(self):
        self.assertEqual(get_screenscraper_system_id("FC"), 3)
        self.assertEqual(get_screenscraper_system_id("SFC"), 4)
        self.assertEqual(get_screenscraper_system_id("MD"), 1)
        self.assertEqual(get_screenscraper_system_id("GBA"), 12)
        self.assertEqual(get_screenscraper_system_id("PS"), 57)

    def test_aliases_resolve_through_resolve_system_id(self):
        self.assertEqual(get_screenscraper_system_id("NES"), 3)
        self.assertEqual(get_screenscraper_system_id("snes"), 4)

    def test_unmapped_console_returns_none(self):
        self.assertIsNone(get_screenscraper_system_id("NOT_A_CONSOLE"))


class MediaParsingTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(SAMPLE_PAYLOAD)

    def test_boxart_kind_selects_box_2d_media_only(self):
        urls = parse_media_urls(self.payload, art_kind="boxart")
        self.assertTrue(urls)
        self.assertTrue(all("media=box-2D" in url for url in urls))

    def test_cartridge_label_kind_selects_support_2d_media(self):
        urls = parse_media_urls(self.payload, art_kind="cartridge_label")
        self.assertTrue(urls)
        self.assertTrue(all("media=support-2D" in url for url in urls))

    def test_region_preference_orders_candidates(self):
        # USA first -> the us box art must precede the jp one.
        urls = parse_media_urls(
            self.payload, art_kind="boxart", region_priority=["USA", "Japan"]
        )
        self.assertIn("region=us", urls[0])
        self.assertIn("region=jp", urls[1])

        # Flip the preference and the order flips with it.
        urls = parse_media_urls(
            self.payload, art_kind="boxart", region_priority=["Japan", "USA"]
        )
        self.assertIn("region=jp", urls[0])

    def test_libretro_region_names_translate_to_screenscraper_codes(self):
        codes = region_priority_for(["USA", "World", "Europe", "Japan"])
        self.assertEqual(codes[:4], ["us", "wor", "eu", "jp"])

    def test_unknown_art_kind_falls_back_to_boxart(self):
        urls = parse_media_urls(self.payload, art_kind="nonsense")
        self.assertTrue(all("media=box-2D" in url for url in urls))

    def test_empty_and_malformed_payloads_yield_no_urls(self):
        for payload in (
            None,
            {},
            "not a dict",
            {"response": None},
            {"response": {}},
            {"response": {"jeu": None}},
            {"response": {"jeu": {}}},
            {"response": {"jeu": {"medias": "nope"}}},
            {"response": {"jeu": {"medias": []}}},
            {"response": {"jeu": {"medias": [{"type": "ss", "url": "u"}]}}},
        ):
            self.assertEqual(parse_media_urls(payload, art_kind="boxart"), [], payload)

    def test_media_entries_without_url_are_ignored(self):
        payload = {"response": {"jeu": {"medias": [{"type": "box-2D", "url": ""}]}}}
        self.assertEqual(parse_media_urls(payload, art_kind="boxart"), [])


class LookupTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("openemux.core.screenscraper._throttle")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_successful_lookup_returns_media_urls(self):
        def fake_open(url, timeout=None):
            self.assertIn("systemeid=4", url)
            return _FakeResponse(SAMPLE_PAYLOAD)

        urls = lookup_media_urls(
            credentials=_creds(),
            console="SFC",
            rom_name="Chrono Trigger (USA).sfc",
            art_kind="cartridge_label",
            opener=fake_open,
        )
        self.assertTrue(urls)
        self.assertTrue(all("support-2D" in url for url in urls))

    def test_lookup_without_credentials_returns_empty(self):
        called = []

        def fake_open(url, timeout=None):  # pragma: no cover - must not run
            called.append(url)
            return _FakeResponse(SAMPLE_PAYLOAD)

        urls = lookup_media_urls(
            credentials=ScreenScraperCredentials(),
            console="SFC",
            rom_name="Chrono Trigger.sfc",
            opener=fake_open,
        )
        self.assertEqual(urls, [])
        self.assertEqual(called, [])

    def test_lookup_for_unmapped_console_returns_empty(self):
        urls = lookup_media_urls(
            credentials=_creds(),
            console="NOT_A_CONSOLE",
            rom_name="Whatever.bin",
            opener=lambda url, timeout=None: _FakeResponse(SAMPLE_PAYLOAD),
        )
        self.assertEqual(urls, [])

    def test_quota_exceeded_response_is_treated_as_no_result(self):
        def fake_open(url, timeout=None):
            raise urllib.error.HTTPError(url, 430, "Quota exceeded", {}, None)

        urls = lookup_media_urls(
            credentials=_creds(), console="SFC", rom_name="X.sfc", opener=fake_open
        )
        self.assertEqual(urls, [])

    def test_thread_limit_response_is_treated_as_no_result(self):
        def fake_open(url, timeout=None):
            raise urllib.error.HTTPError(url, 429, "Too many threads", {}, None)

        urls = lookup_media_urls(
            credentials=_creds(), console="SFC", rom_name="X.sfc", opener=fake_open
        )
        self.assertEqual(urls, [])

    def test_http_404_is_treated_as_no_result(self):
        def fake_open(url, timeout=None):
            raise urllib.error.HTTPError(url, 404, "Not found", {}, None)

        urls = lookup_media_urls(
            credentials=_creds(), console="SFC", rom_name="X.sfc", opener=fake_open
        )
        self.assertEqual(urls, [])

    def test_malformed_json_body_is_treated_as_no_result(self):
        def fake_open(url, timeout=None):
            return _FakeResponse("Erreur: quota journalier depasse")

        urls = lookup_media_urls(
            credentials=_creds(), console="SFC", rom_name="X.sfc", opener=fake_open
        )
        self.assertEqual(urls, [])

    def test_network_failure_is_treated_as_no_result(self):
        def fake_open(url, timeout=None):
            raise urllib.error.URLError("connection refused")

        urls = lookup_media_urls(
            credentials=_creds(), console="SFC", rom_name="X.sfc", opener=fake_open
        )
        self.assertEqual(urls, [])

    def test_game_with_no_matching_media_returns_empty(self):
        payload = json.dumps({"response": {"jeu": {"medias": [{"type": "ss", "url": "u"}]}}})

        urls = lookup_media_urls(
            credentials=_creds(),
            console="SFC",
            rom_name="X.sfc",
            opener=lambda url, timeout=None: _FakeResponse(payload),
        )
        self.assertEqual(urls, [])


class RedactionTests(unittest.TestCase):
    def test_redact_masks_every_credential_parameter(self):
        url = build_jeu_infos_url(
            credentials=_creds(), systemeid=4, rom_name="Chrono Trigger.sfc"
        )
        safe = redact(url)
        for secret in ("devuser", "devsecret", "player1", "secretpw"):
            self.assertNotIn(secret, safe)
        # Non-secret parameters survive.
        self.assertIn("softname=OpenEmux", safe)
        self.assertIn("systemeid=4", safe)

    def test_redact_handles_messages_and_none(self):
        self.assertNotIn("hunter2", redact("failed for sspassword=hunter2 at end"))
        self.assertIsNone(redact(None))

    def test_credentials_repr_never_exposes_secrets(self):
        creds = _creds()
        for text in (repr(creds), str(creds)):
            for secret in ("devuser", "devsecret", "player1", "secretpw"):
                self.assertNotIn(secret, text)

    def test_lookup_never_logs_credentials(self):
        with self.assertLogs("openemux.core.screenscraper", level="DEBUG") as logs:
            with patch("openemux.core.screenscraper._throttle"):
                lookup_media_urls(
                    credentials=_creds(),
                    console="SFC",
                    rom_name="Chrono Trigger.sfc",
                    opener=lambda url, timeout=None: _FakeResponse(SAMPLE_PAYLOAD),
                )
        joined = "\n".join(logs.output)
        for secret in ("devuser", "devsecret", "player1", "secretpw"):
            self.assertNotIn(secret, joined)


class ThrottleTests(unittest.TestCase):
    def test_requests_are_spaced_by_the_minimum_interval(self):
        sleeps = []
        with (
            patch("openemux.core.screenscraper.time.sleep", side_effect=sleeps.append),
            patch("openemux.core.screenscraper.time.monotonic", side_effect=[100.0, 100.0, 100.1, 100.1]),
        ):
            screenscraper._last_request_at[0] = 0.0
            screenscraper._throttle()
            screenscraper._throttle()
        # The second call had to wait out the remainder of the interval.
        self.assertTrue(any(value > 0 for value in sleeps))


if __name__ == "__main__":
    unittest.main()

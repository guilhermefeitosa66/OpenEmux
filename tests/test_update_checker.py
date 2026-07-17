import json
import unittest
import urllib.error
from unittest.mock import patch

from openemux.core.update_checker import (
    check_for_update,
    fetch_latest_release,
    is_newer,
    parse_version,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ParseVersionTests(unittest.TestCase):
    def test_parses_tag_and_plain_forms(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("OpenEmux 1.2"), (1, 2))

    def test_returns_none_without_digits(self):
        self.assertIsNone(parse_version("nightly"))
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))


class IsNewerTests(unittest.TestCase):
    def test_detects_newer_versions(self):
        self.assertTrue(is_newer("v1.1.2", "1.1.1"))
        self.assertTrue(is_newer("v1.2.0", "1.1.9"))
        self.assertTrue(is_newer("v2.0.0", "1.9.9"))

    def test_same_or_older_is_not_newer(self):
        self.assertFalse(is_newer("v1.1.1", "1.1.1"))
        self.assertFalse(is_newer("v1.1.0", "1.1.1"))
        self.assertFalse(is_newer("v1.0.0", "1.1.1"))

    def test_different_lengths_compare_by_value_not_length(self):
        # 1.2 == 1.2.0, and 1.2.1 > 1.2
        self.assertFalse(is_newer("v1.2", "1.2.0"))
        self.assertFalse(is_newer("v1.2.0", "1.2"))
        self.assertTrue(is_newer("v1.2.1", "1.2"))

    def test_double_digit_components_are_not_compared_as_text(self):
        self.assertTrue(is_newer("v1.10.0", "1.9.0"))
        self.assertFalse(is_newer("v1.9.0", "1.10.0"))

    def test_unparseable_input_is_never_newer(self):
        self.assertFalse(is_newer("nightly", "1.1.1"))
        self.assertFalse(is_newer("v1.2.0", "unknown"))


class FetchLatestReleaseTests(unittest.TestCase):
    def test_returns_version_and_url(self):
        payload = {"tag_name": "v1.2.0", "html_url": "https://example.test/releases/v1.2.0"}
        with patch("openemux.core.update_checker.urllib.request.urlopen", return_value=FakeResponse(payload)):
            release = fetch_latest_release()
        self.assertEqual(release["version"], "v1.2.0")
        self.assertEqual(release["url"], "https://example.test/releases/v1.2.0")

    def test_network_failure_returns_none(self):
        with patch(
            "openemux.core.update_checker.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertIsNone(fetch_latest_release())

    def test_malformed_payload_returns_none(self):
        with patch("openemux.core.update_checker.urllib.request.urlopen", return_value=FakeResponse({})):
            self.assertIsNone(fetch_latest_release())


class CheckForUpdateTests(unittest.TestCase):
    def test_reports_release_when_newer(self):
        payload = {"tag_name": "v1.2.0", "html_url": "https://example.test/r"}
        with patch("openemux.core.update_checker.urllib.request.urlopen", return_value=FakeResponse(payload)):
            self.assertEqual(check_for_update("1.1.1")["version"], "v1.2.0")

    def test_silent_when_up_to_date(self):
        payload = {"tag_name": "v1.1.1", "html_url": "https://example.test/r"}
        with patch("openemux.core.update_checker.urllib.request.urlopen", return_value=FakeResponse(payload)):
            self.assertIsNone(check_for_update("1.1.1"))

    def test_silent_when_check_fails(self):
        with patch(
            "openemux.core.update_checker.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertIsNone(check_for_update("1.1.1"))


if __name__ == "__main__":
    unittest.main()

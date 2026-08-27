"""The RetroAchievements account (issue #300).

RetroArch does the achievement work; what it needs from us is a username and
a token. The password is exchanged for that token once and never kept, so
most of what is worth testing is about what does *not* end up anywhere.
"""

import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import retroachievements
from openemux.core.retroachievements import AchievementsStore, LoginError
from tests.platform_marks import posix_only


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _opener(payload, recorder=None):
    def open_url(request, timeout=None):
        if recorder is not None:
            recorder.append(request)
        return _Response(json.dumps(payload).encode("utf-8"))

    return open_url


class LoginTests(unittest.TestCase):
    def test_a_good_login_returns_the_token(self):
        token = retroachievements.login(
            "player", "hunter2", opener=_opener({"Success": True, "Token": "abc123"})
        )
        self.assertEqual(token, "abc123")

    def test_the_password_is_sent_to_nobody_but_retroachievements(self):
        seen = []
        retroachievements.login(
            "player", "hunter2", opener=_opener({"Success": True, "Token": "t"}, seen)
        )
        request = seen[0]
        self.assertEqual(request.full_url, retroachievements.LOGIN_URL)
        self.assertTrue(request.full_url.startswith("https://"))
        # In the body, not the URL: a query string lands in logs and history.
        self.assertNotIn("hunter2", request.full_url)
        self.assertIn(b"hunter2", request.data)

    def test_a_refusal_carries_the_services_own_message(self):
        with self.assertRaises(LoginError) as caught:
            retroachievements.login(
                "player", "wrong", opener=_opener({"Success": False, "Error": "bad login"})
            )
        self.assertIn("bad login", str(caught.exception))

    def test_success_without_a_token_is_still_a_failure(self):
        with self.assertRaises(LoginError):
            retroachievements.login(
                "player", "hunter2", opener=_opener({"Success": True})
            )

    def test_wrong_details_come_back_as_401_with_the_reason(self):
        # Verified against the real service: it answers 401 with the reason in
        # the body, and an HTTPError is also a response. Reading it is what
        # keeps "you mistyped your password" from reading as "the service is
        # down".
        import urllib.error

        def refuses(_request, timeout=None):
            raise urllib.error.HTTPError(
                retroachievements.LOGIN_URL,
                401,
                "Unauthorized",
                {},
                BytesIO(
                    json.dumps(
                        {
                            "Success": False,
                            "Code": "invalid_credentials",
                            "Error": "Invalid user/password combination. Please try again.",
                        }
                    ).encode("utf-8")
                ),
            )

        with self.assertRaises(LoginError) as caught:
            retroachievements.login("player", "wrong", opener=refuses)
        self.assertIn("Invalid user/password combination", str(caught.exception))

    def test_an_error_page_that_is_not_json_falls_back(self):
        import urllib.error

        def broken(_request, timeout=None):
            raise urllib.error.HTTPError(
                retroachievements.LOGIN_URL, 502, "Bad Gateway", {}, BytesIO(b"<html>")
            )

        with self.assertRaises(LoginError) as caught:
            retroachievements.login("player", "hunter2", opener=broken)
        self.assertIn("could not be reached", str(caught.exception))

    def test_a_network_failure_says_so_without_the_password(self):
        def broken(_request, timeout=None):
            raise OSError("no route to host")

        with self.assertRaises(LoginError) as caught:
            retroachievements.login("player", "hunter2", opener=broken)
        self.assertNotIn("hunter2", str(caught.exception))

    def test_empty_details_never_reach_the_network(self):
        def must_not_run(*_a, **_k):  # pragma: no cover - the point is it is not called
            raise AssertionError("a request was made")

        with self.assertRaises(LoginError):
            retroachievements.login("", "hunter2", opener=must_not_run)
        with self.assertRaises(LoginError):
            retroachievements.login("player", "", opener=must_not_run)


class StoreTests(unittest.TestCase):
    def _store(self, tmp_dir):
        return AchievementsStore(Path(tmp_dir) / "cheevos.config")

    def test_an_account_round_trips(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_account("player", "abc123")
            self.assertTrue(store.is_signed_in())
            self.assertEqual(store.get_username(), "player")
            self.assertEqual(store.get_token(), "abc123")

    @posix_only("0o600 on the file holding the account token")
    def test_the_file_is_owner_only(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_account("player", "abc123")
            self.assertEqual(os.stat(store.config_file).st_mode & 0o777, 0o600)

    def test_signing_out_drops_both(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_account("player", "abc123")
            store.set_enabled(True)
            store.sign_out()
            self.assertFalse(store.is_signed_in())
            # The preference survives; only the account went.
            self.assertTrue(store.get_enabled())

    def test_hardcore_is_off_until_asked_for(self):
        # It takes save states, rewind and fast-forward away.
        with TemporaryDirectory() as tmp_dir:
            self.assertFalse(self._store(tmp_dir).get_hardcore())

    def test_a_corrupt_store_reads_as_empty(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "cheevos.config"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(AchievementsStore(path).load(), {})


class RuntimeOverrideTests(unittest.TestCase):
    def _store(self, tmp_dir, **state):
        store = AchievementsStore(Path(tmp_dir) / "cheevos.config")
        if state.get("account", True):
            store.set_account("player", "abc123")
        store.set_enabled(state.get("enabled", True))
        store.set_hardcore(state.get("hardcore", False))
        return store

    def test_nothing_is_written_without_a_store(self):
        self.assertEqual(retroachievements.runtime_overrides(None), {})

    def test_nothing_is_written_when_it_is_off(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(
                retroachievements.runtime_overrides(self._store(tmp_dir, enabled=False)), {}
            )

    def test_nothing_is_written_without_an_account(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(
                retroachievements.runtime_overrides(self._store(tmp_dir, account=False)), {}
            )

    def test_the_account_reaches_retroarch(self):
        with TemporaryDirectory() as tmp_dir:
            overrides = retroachievements.runtime_overrides(self._store(tmp_dir))
        self.assertEqual(overrides["cheevos_enable"], '"true"')
        self.assertEqual(overrides["cheevos_username"], '"player"')
        self.assertEqual(overrides["cheevos_token"], '"abc123"')
        self.assertEqual(overrides["cheevos_hardcore_mode_enable"], '"false"')

    def test_the_password_key_is_written_empty(self):
        # A password must never reach a config file, and stating the key keeps
        # an older one from lingering in the user's own config.
        with TemporaryDirectory() as tmp_dir:
            overrides = retroachievements.runtime_overrides(self._store(tmp_dir))
        self.assertEqual(overrides["cheevos_password"], '""')

    def test_hardcore_travels_when_asked_for(self):
        with TemporaryDirectory() as tmp_dir:
            overrides = retroachievements.runtime_overrides(
                self._store(tmp_dir, hardcore=True)
            )
        self.assertEqual(overrides["cheevos_hardcore_mode_enable"], '"true"')


if __name__ == "__main__":
    unittest.main()

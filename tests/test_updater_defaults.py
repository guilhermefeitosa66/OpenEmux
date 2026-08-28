"""One source for the buildbot updater's settings (issue #239).

The URLs and timeouts were spelled out three times over -- in
``DEFAULT_CONFIG``, in the ``setdefault`` calls of ``_migrate_runtime_config``,
and in the fallbacks of ``get_retroarch_updater_settings``. Changing a URL
meant changing it in triplicate, or the copies drifted apart in silence, and
which one a given install used depended on how old its ``config.yaml`` was.

So: a fresh config, a config that predates the keys, and a config that sets
them must all resolve through the same dict.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from openemux.core.config import UPDATER_DEFAULTS, ConfigManager


def _manager(root, raw=None):
    path = Path(root) / "config.yaml"
    if raw is not None:
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return ConfigManager(config_file=path)


class TheDefaultsAreOneDictTests(unittest.TestCase):
    def test_it_covers_every_key_the_getter_returns(self):
        with TemporaryDirectory() as tmp:
            settings = _manager(tmp).get_retroarch_updater_settings()
        self.assertEqual(set(settings), set(UPDATER_DEFAULTS))

    def test_the_urls_are_only_written_down_once(self):
        source = (
            Path(__file__).resolve().parents[1] / "src/openemux/core/config.py"
        ).read_text(encoding="utf-8")
        for url in (
            UPDATER_DEFAULTS["core_info_base_url"],
            UPDATER_DEFAULTS["shader_glsl_url"],
            UPDATER_DEFAULTS["shader_slang_url"],
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    source.count(url), 1, f"{url} is written down more than once"
                )


class EveryVintageOfConfigResolvesTheSameTests(unittest.TestCase):
    def _settings(self, raw=None):
        with TemporaryDirectory() as tmp:
            return _manager(tmp, raw).get_retroarch_updater_settings()

    def test_a_fresh_config(self):
        settings = self._settings()
        for key in ("mode", "cores_base_url", "core_info_base_url", "retries"):
            with self.subTest(key=key):
                self.assertEqual(settings[key], UPDATER_DEFAULTS[key])

    def test_a_config_that_predates_the_updater_block(self):
        # The migration's job: an install from before the keys existed.
        settings = self._settings({"locale": "en", "runtime": {"retroarch": {}}})
        self.assertEqual(settings["cores_base_url"], UPDATER_DEFAULTS["cores_base_url"])
        self.assertEqual(settings["request_timeout_sec"], UPDATER_DEFAULTS["request_timeout_sec"])

    def test_a_config_with_half_the_block(self):
        settings = self._settings(
            {"runtime": {"retroarch": {"updater": {"retries": 9}}}}
        )
        self.assertEqual(settings["retries"], 9)
        self.assertEqual(settings["shader_glsl_url"], UPDATER_DEFAULTS["shader_glsl_url"])

    def test_what_the_user_set_wins_over_the_default(self):
        settings = self._settings(
            {
                "runtime": {
                    "retroarch": {
                        "updater": {"cores_base_url": "https://mirror.example/cores/"}
                    }
                }
            }
        )
        self.assertEqual(settings["cores_base_url"], "https://mirror.example/cores/")


class TheTypesTheCallerReliesOnTests(unittest.TestCase):
    def _settings(self, updater):
        with TemporaryDirectory() as tmp:
            return _manager(
                tmp, {"runtime": {"retroarch": {"updater": updater}}}
            ).get_retroarch_updater_settings()

    def test_the_numbers_come_back_as_numbers(self):
        # A hand-edited config can put a string where a number belongs, and
        # the updater does arithmetic with all three.
        settings = self._settings(
            {"request_timeout_sec": "45", "retries": "2", "parallel_downloads": "8"}
        )
        self.assertEqual(settings["request_timeout_sec"], 45)
        self.assertEqual(settings["retries"], 2)
        self.assertEqual(settings["parallel_downloads"], 8)

    def test_enabled_comes_back_as_a_bool(self):
        self.assertIs(self._settings({"enabled": 0})["enabled"], False)
        self.assertIs(self._settings({"enabled": 1})["enabled"], True)


if __name__ == "__main__":
    unittest.main()

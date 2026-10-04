"""Configurable artwork providers (issue #76): normalization, migration, chain."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from openemux.core import cover_sync
from openemux.core.config import (
    ConfigManager,
    COVER_ART_TYPE_BOXART,
    COVER_ART_TYPE_CARTRIDGE_LABEL,
    DEFAULT_ARTWORK_PROVIDERS,
    migrate_cover_source_to_providers,
    normalize_artwork_providers,
)

BOTH = [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL]


def provider_ids(providers, enabled_only=False):
    return [p["id"] for p in providers if not enabled_only or p["enabled"]]


class NormalizationTests(unittest.TestCase):
    def test_empty_config_yields_the_defaults(self):
        self.assertEqual(normalize_artwork_providers(None), DEFAULT_ARTWORK_PROVIDERS)
        self.assertEqual(normalize_artwork_providers([]), DEFAULT_ARTWORK_PROVIDERS)

    def test_configured_order_and_flags_win(self):
        value = [
            {"id": "screenscraper", "enabled": False, "kinds": BOTH},
            {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
        ]
        normalized = normalize_artwork_providers(value)
        # openemux was not mentioned: appended with its default entry.
        self.assertEqual(provider_ids(normalized), ["screenscraper", "libretro", "openemux"])
        self.assertFalse(normalized[0]["enabled"])

    def test_unknown_ids_and_impossible_kinds_are_dropped(self):
        value = [
            {"id": "bogus", "enabled": True, "kinds": BOTH},
            {"id": "libretro", "enabled": True, "kinds": BOTH},  # labels impossible
        ]
        normalized = normalize_artwork_providers(value)
        self.assertNotIn("bogus", provider_ids(normalized))
        libretro = next(p for p in normalized if p["id"] == "libretro")
        self.assertEqual(libretro["kinds"], [COVER_ART_TYPE_BOXART])

    def test_fresh_default_order_is_libretro_first_all_enabled(self):
        providers = normalize_artwork_providers(None)
        self.assertEqual(provider_ids(providers), ["libretro", "screenscraper", "openemux"])
        self.assertTrue(all(p["enabled"] for p in providers))

    def test_partial_kind_selections_are_restored_to_full_capabilities(self):
        # Per-kind opt-outs no longer exist: a stored partial selection (from
        # the short-lived kinds UI) must not keep silently skipping labels.
        value = [{"id": "screenscraper", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]}]
        normalized = normalize_artwork_providers(value)
        screenscraper = next(p for p in normalized if p["id"] == "screenscraper")
        self.assertEqual(screenscraper["kinds"], BOTH)

    def test_default_list_is_never_aliased(self):
        first = normalize_artwork_providers(None)
        first[0]["enabled"] = False
        first[0]["kinds"].clear()
        self.assertTrue(DEFAULT_ARTWORK_PROVIDERS[0]["enabled"])
        self.assertTrue(DEFAULT_ARTWORK_PROVIDERS[0]["kinds"])


class MigrationTests(unittest.TestCase):
    """The old cover_source enum keeps meaning exactly what it meant."""

    def test_libretro_only_disables_screenscraper(self):
        providers = migrate_cover_source_to_providers("libretro", "boxart")
        self.assertEqual(provider_ids(providers), ["libretro", "screenscraper", "openemux"])
        self.assertEqual(provider_ids(providers, enabled_only=True), ["libretro", "openemux"])

    def test_libretro_then_screenscraper_enables_both_in_order(self):
        providers = migrate_cover_source_to_providers("libretro_then_screenscraper", "boxart")
        self.assertEqual(
            provider_ids(providers, enabled_only=True),
            ["libretro", "screenscraper", "openemux"],
        )

    def test_screenscraper_only_leads_and_libretro_is_off(self):
        providers = migrate_cover_source_to_providers("screenscraper", "boxart")
        self.assertEqual(provider_ids(providers), ["screenscraper", "libretro", "openemux"])
        self.assertEqual(provider_ids(providers, enabled_only=True), ["screenscraper", "openemux"])

    def test_screenscraper_always_serves_both_kinds(self):
        # Per-kind opt-outs were dropped: an enabled provider serves
        # everything it can, whatever the old artwork type said.
        for art_type in ("boxart", "cartridge_label"):
            providers = migrate_cover_source_to_providers("libretro_then_screenscraper", art_type)
            screenscraper = next(p for p in providers if p["id"] == "screenscraper")
            self.assertEqual(screenscraper["kinds"], BOTH, art_type)


class ProviderChainTests(unittest.TestCase):
    """_ordered_providers driven by the configured list, per artwork kind."""

    def settings(self, providers, kind=COVER_ART_TYPE_BOXART):
        return {"providers": providers, "cover_art_type": kind}

    def test_order_and_enabled_follow_the_config(self):
        providers = [
            {"id": "openemux", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
            {"id": "libretro", "enabled": False, "kinds": [COVER_ART_TYPE_BOXART]},
            {"id": "screenscraper", "enabled": True, "kinds": BOTH},
        ]
        names = [n for n, _f in cover_sync._ordered_providers(self.settings(providers))]
        self.assertEqual(names, ["openemux", "screenscraper"])

    def test_label_pass_only_uses_label_capable_and_willing_providers(self):
        providers = [
            {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
            {"id": "screenscraper", "enabled": True, "kinds": BOTH},
            {"id": "openemux", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
        ]
        names = [
            n
            for n, _f in cover_sync._ordered_providers(
                self.settings(providers, kind=COVER_ART_TYPE_CARTRIDGE_LABEL)
            )
        ]
        self.assertEqual(names, ["screenscraper"])

    def test_a_kind_unticked_on_a_capable_provider_is_respected(self):
        providers = [
            {"id": "screenscraper", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
        ]
        self.assertFalse(
            cover_sync.has_provider_for_kind(
                self.settings(providers), COVER_ART_TYPE_CARTRIDGE_LABEL
            )
        )
        self.assertTrue(
            cover_sync.has_provider_for_kind(self.settings(providers), COVER_ART_TYPE_BOXART)
        )

    def test_legacy_settings_without_providers_still_work(self):
        names = [
            n
            for n, _f in cover_sync._ordered_providers(
                {"cover_source": "libretro_then_screenscraper"}
            )
        ]
        self.assertEqual(names, ["libretro", "screenscraper", "openemux"])

    def test_libretro_serves_no_label_pass_even_on_the_legacy_path(self):
        urls = cover_sync._libretro_candidates(
            "SFC", "Chrono Trigger", {"cover_art_type": "cartridge_label"}
        )
        self.assertEqual(urls, [])


class PassPlanningTests(unittest.TestCase):
    def test_label_pass_is_dropped_when_no_provider_serves_labels(self):
        providers = [
            {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
        ]
        rom = {"name": "A", "path": "/tmp/a.sfc", "console": "SFC"}
        passes = [
            (COVER_ART_TYPE_BOXART, {"SFC": [rom]}),
            (COVER_ART_TYPE_CARTRIDGE_LABEL, {"SFC": [rom]}),
        ]
        with patch("openemux.core.cover_sync._sync_covers") as sync_mock:
            sync_mock.return_value = {
                "cancelled": False, "total": 1, "downloaded": 0, "skipped": 1, "errors": 0,
            }
            summary = cover_sync._sync_artwork(
                passes, "/tmp", sync_settings={"providers": providers}
            )
        # Only the box-art pass ran.
        self.assertEqual(sync_mock.call_count, 1)
        self.assertEqual(
            sync_mock.call_args.kwargs.get("sync_settings", {}).get("cover_art_type"),
            COVER_ART_TYPE_BOXART,
        )
        self.assertEqual([p["art_kind"] for p in summary["passes"]], [COVER_ART_TYPE_BOXART])


class WhatANewConfigStartsWithTests(unittest.TestCase):
    """ScreenScraper is on for a new install, and only for one (issue #455)."""

    def _manager(self, tmp_dir, existing=None):
        config_file = Path(tmp_dir) / "config.yaml"
        if existing is not None:
            config_file.write_text(yaml.safe_dump(existing), encoding="utf-8")
        return ConfigManager(config_file=config_file)

    def test_a_new_config_has_screenscraper_on_in_the_order_the_ui_shows(self):
        with TemporaryDirectory() as tmp_dir:
            providers = self._manager(tmp_dir).get_artwork_providers()
        self.assertEqual(provider_ids(providers), ["libretro", "screenscraper", "openemux"])
        self.assertEqual(
            provider_ids(providers, enabled_only=True),
            ["libretro", "screenscraper", "openemux"],
        )

    def test_the_new_list_is_written_to_disk(self):
        with TemporaryDirectory() as tmp_dir:
            self._manager(tmp_dir)
            reopened = self._manager(tmp_dir)
            self.assertIn("screenscraper", provider_ids(
                reopened.get_artwork_providers(), enabled_only=True
            ))

    def test_a_config_that_predates_the_list_keeps_what_its_enum_meant(self):
        existing = {"covers": {"sync": {"cover_source": "libretro"}}}
        with TemporaryDirectory() as tmp_dir:
            providers = self._manager(tmp_dir, existing).get_artwork_providers()
        self.assertNotIn("screenscraper", provider_ids(providers, enabled_only=True))

    def test_an_existing_switch_is_left_alone(self):
        existing = {
            "covers": {
                "sync": {
                    "providers": [
                        {"id": "libretro", "enabled": True},
                        {"id": "screenscraper", "enabled": False},
                        {"id": "openemux", "enabled": True},
                    ]
                }
            }
        }
        with TemporaryDirectory() as tmp_dir:
            providers = self._manager(tmp_dir, existing).get_artwork_providers()
        self.assertNotIn("screenscraper", provider_ids(providers, enabled_only=True))

    def test_a_new_config_does_not_share_the_module_default(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.get_cover_sync_settings()
            manager.config["covers"]["sync"]["providers"][0]["enabled"] = False
        self.assertTrue(DEFAULT_ARTWORK_PROVIDERS[0]["enabled"])


if __name__ == "__main__":
    unittest.main()

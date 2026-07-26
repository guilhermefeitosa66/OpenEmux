"""Configurable artwork providers (issue #76): normalization, migration, chain."""

import unittest
from unittest.mock import patch

from openemux.core import cover_sync
from openemux.core.config import (
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

    def test_label_art_type_keeps_labels_on_screenscraper(self):
        providers = migrate_cover_source_to_providers("screenscraper", "cartridge_label")
        screenscraper = next(p for p in providers if p["id"] == "screenscraper")
        self.assertIn(COVER_ART_TYPE_CARTRIDGE_LABEL, screenscraper["kinds"])

    def test_boxart_type_leaves_screenscraper_boxart_only(self):
        providers = migrate_cover_source_to_providers("libretro_then_screenscraper", "boxart")
        screenscraper = next(p for p in providers if p["id"] == "screenscraper")
        self.assertEqual(screenscraper["kinds"], [COVER_ART_TYPE_BOXART])


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


if __name__ == "__main__":
    unittest.main()

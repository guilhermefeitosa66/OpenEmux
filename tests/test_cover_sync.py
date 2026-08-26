import re
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import patch

from openemux.core import cover_sync
from openemux.core.artwork_index import ArtworkNameIndex
from openemux.core.cover_sync import (
    _build_cover_url,
    _candidate_names,
    _libretro_candidates,
    _normalize_rom_name,
    _ordered_providers,
    _remote_cover_candidates,
    _sync_artwork,
    _sync_covers,
    build_artwork_passes,
    fuzzy_candidate_names,
)


#: The smallest bodies that pass the sniffer, padded past MIN_IMAGE_BYTES.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 96
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 96
_WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 96


def _image_response(payload, content_type):
    response = mock.MagicMock()
    response.read.return_value = payload
    response.headers.get_content_type.return_value = content_type
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    return response


class CoverSyncTests(unittest.TestCase):
    def test_cover_name_normalization_basic(self):
        self.assertEqual(
            _normalize_rom_name("Chrono Trigger (Rev 1) [!].sfc"),
            "Chrono Trigger",
        )

    def test_cover_candidate_generation_order(self):
        candidates = _candidate_names(
            rom_name="Chrono Trigger",
            matching_mode="normalized_region_priority",
            region_priority=["USA", "World", "Europe", "Japan"],
            name_cleanup=True,
        )
        # Bare name first, then the configured single regions, then the common
        # combined-region tags, then the multi-language tag.
        self.assertEqual(candidates[0], "Chrono Trigger")
        self.assertEqual(candidates[1], "Chrono Trigger (USA)")
        self.assertEqual(candidates[2], "Chrono Trigger (World)")
        self.assertEqual(candidates[3], "Chrono Trigger (Europe)")
        self.assertEqual(candidates[4], "Chrono Trigger (Japan)")
        self.assertEqual(candidates[5], "Chrono Trigger (USA, Europe)")
        self.assertIn("Chrono Trigger (En,Fr,De,Es,It)", candidates)

    def test_cover_candidates_bridge_common_naming_quirks(self):
        def bases(rom_name):
            # Strip region/lang tags to inspect the underlying name variants.
            names = _candidate_names(
                rom_name=rom_name,
                matching_mode="normalized_region_priority",
                region_priority=["USA"],
                name_cleanup=True,
            )
            return {re.sub(r"\s*\(.*\)$", "", n) for n in names}

        # Trailing sequence number dropped: "Donkey Kong 1" -> "Donkey Kong".
        self.assertIn("Donkey Kong", bases("Donkey Kong 1"))
        # Connector word lower-cased to match No-Intro casing.
        self.assertIn(
            "Castlevania - Harmony of Dissonance",
            bases("Castlevania - Harmony Of Dissonance"),
        )
        # Accents stripped: "Pokémon ..." -> "Pokemon ...".
        self.assertTrue(any(b.startswith("Pokemon") for b in bases("Pokémon 2.1 - Gold Version")))
        # Embedded ordering marker removed.
        self.assertIn("Pokemon Gold Version", bases("Pokémon 2.1 - Gold Version"))
        # Combined-region tag offered.
        combos = _candidate_names(
            rom_name="Sonic The Hedgehog",
            matching_mode="normalized_region_priority",
            region_priority=["USA"],
            name_cleanup=True,
        )
        self.assertIn("Sonic The Hedgehog (USA, Europe)", combos)

    def test_cover_url_build_uses_thumbnails_libretro_domain(self):
        url = _build_cover_url(
            "Nintendo - Super Nintendo Entertainment System",
            "Chrono Trigger (USA)",
        )
        self.assertEqual(
            url,
            "https://thumbnails.libretro.com/"
            "Nintendo%20-%20Super%20Nintendo%20Entertainment%20System/"
            "Named_Boxarts/Chrono%20Trigger%20%28USA%29.png",
        )

    def test_cover_sync_stops_on_first_success(self):
        library = {"snes": [{"name": "Chrono Trigger", "path": "/tmp/Chrono Trigger.sfc", "console": "snes"}]}
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch(
                    "openemux.core.cover_sync._staged_cover_candidates",
                    return_value=[
                        ("libretro", "exact", "u1"),
                        ("libretro", "normalized", "u2"),
                        ("openemux", "normalized", "u3"),
                    ],
                ),
                patch(
                    "openemux.core.cover_sync._download_cover",
                    side_effect=[False, False, True],
                ) as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(download_mock.call_count, 3)
        # The winning candidate's ladder stage lands in the tally (#175).
        self.assertEqual(summary["stages"]["normalized"], 1)
        self.assertEqual(summary["stages"]["exact"], 0)

    def test_cover_sync_existing_local_is_skipped(self):
        library = {"gba": [{"name": "Castlevania", "path": "/tmp/Castlevania.gba", "console": "gba"}]}
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=Path(tmp_dir) / "cover.png"),
                patch("openemux.core.cover_sync._download_cover") as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="gba",
                    sync_settings={},
                )
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["downloaded"], 0)
        self.assertEqual(download_mock.call_count, 0)

    def test_replace_existing_refetches_art_already_on_disk(self):
        # The single-ROM sync from the context menu is an explicit "get this
        # one again", so the skip-what-exists rule is off for it.
        library = {"gba": [{"name": "Castlevania", "path": "/tmp/Castlevania.gba", "console": "gba"}]}
        with TemporaryDirectory() as tmp_dir:
            covers = Path(tmp_dir) / "gba" / "covers"
            covers.mkdir(parents=True)
            (covers / "Castlevania.png").write_bytes(b"old")
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                patch(
                    "openemux.core.cover_sync._download_cover",
                    side_effect=lambda _url, dest: (dest.write_bytes(b"new"), dest)[1],
                ) as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="gba",
                    sync_settings={},
                    replace_existing=True,
                )
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(download_mock.call_count, 1)

    def test_replace_existing_drops_the_old_file_under_another_extension(self):
        # The new file lands under the source's own extension; the previous one
        # would still win find_local_art if it were left behind.
        library = {"gba": [{"name": "Castlevania", "path": "/tmp/Castlevania.gba", "console": "gba"}]}
        with TemporaryDirectory() as tmp_dir:
            covers = Path(tmp_dir) / "gba" / "covers"
            covers.mkdir(parents=True)
            (covers / "Castlevania.png").write_bytes(b"old")

            def _fake_download(_url, dest):
                written = dest.with_suffix(".jpg")
                written.write_bytes(b"new")
                return written

            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                patch("openemux.core.cover_sync._download_cover", side_effect=_fake_download),
            ):
                _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="gba",
                    sync_settings={},
                    replace_existing=True,
                )
            self.assertEqual(sorted(p.name for p in covers.iterdir()), ["Castlevania.jpg"])

    def test_replace_existing_keeps_the_file_it_just_wrote(self):
        # Same extension in and out: the cleanup must not delete the download.
        library = {"gba": [{"name": "Castlevania", "path": "/tmp/Castlevania.gba", "console": "gba"}]}
        with TemporaryDirectory() as tmp_dir:
            covers = Path(tmp_dir) / "gba" / "covers"
            covers.mkdir(parents=True)
            (covers / "Castlevania.png").write_bytes(b"old")
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                patch(
                    "openemux.core.cover_sync._download_cover",
                    side_effect=lambda _url, dest: (dest.write_bytes(b"new"), dest)[1],
                ),
            ):
                _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="gba",
                    sync_settings={},
                    replace_existing=True,
                )
            self.assertEqual((covers / "Castlevania.png").read_bytes(), b"new")

    def test_artwork_type_decides_the_destination_directory(self):
        # Cartridge labels are composited into a frame and box art is shown on
        # its own, so each kind gets its own directory instead of overwriting
        # the other under "covers".
        library = {"SFC": [{"name": "Chrono Trigger", "path": "/tmp/ct.sfc", "console": "SFC"}]}
        for art_type, expected_dir in (("boxart", "covers"), ("cartridge_label", "labels")):
            with TemporaryDirectory() as tmp_dir:
                with (
                    patch("openemux.core.cover_sync.find_local_art", return_value=None),
                    patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                    patch(
                        "openemux.core.cover_sync._download_cover", return_value=True
                    ) as download_mock,
                ):
                    _sync_covers(
                        library_by_console=library,
                        covers_dir=tmp_dir,
                        scope="console",
                        selected_console="SFC",
                        sync_settings={"cover_art_type": art_type},
                    )
                target = download_mock.call_args[0][1]
                self.assertEqual(target.parent.name, expected_dir, art_type)
                self.assertEqual(target.name, "Chrono Trigger.png")

    def test_label_sync_does_not_skip_a_rom_that_only_has_box_art(self):
        # The skip check must look at the kind being synced: a ROM with box art
        # but no label still needs its label downloaded.
        library = {"SFC": [{"name": "Chrono Trigger", "path": "/tmp/ct.sfc", "console": "SFC"}]}
        with TemporaryDirectory() as tmp_dir:
            cover = Path(tmp_dir) / "SFC" / "covers"
            cover.mkdir(parents=True)
            (cover / "Chrono Trigger.png").write_bytes(b"boxart")
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                patch("openemux.core.cover_sync._download_cover", return_value=True) as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="SFC",
                    sync_settings={"cover_art_type": "cartridge_label"},
                )
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(download_mock.call_args[0][1].parent.name, "labels")

    def test_download_names_the_file_after_the_bytes(self):
        # The default target says .png, but the file on disk must tell the
        # truth about its own format (issue #75). The bytes are the only
        # signal that cannot be wrong, so they win over the URL and the
        # Content-Type (issue #213).
        cases = [
            ("https://cdn.example/art/label.jpg", "image/jpeg", _PNG_BYTES, "Game.png"),
            ("https://cdn.example/art/label.png", "image/png", _JPEG_BYTES, "Game.jpg"),
            ("https://cdn.example/art/media?id=1", "text/plain", _WEBP_BYTES, "Game.webp"),
        ]
        from openemux.core.cover_sync import _download_cover

        for url, content_type, payload, expected_name in cases:
            with TemporaryDirectory() as tmp_dir:
                response = _image_response(payload, content_type)
                with patch(
                    "openemux.core.cover_sync.urllib.request.urlopen",
                    return_value=response,
                ):
                    ok = _download_cover(url, Path(tmp_dir) / "labels" / "Game.png")
                self.assertTrue(ok, url)
                written = sorted(p.name for p in (Path(tmp_dir) / "labels").iterdir())
                self.assertEqual(written, [expected_name], url)

    def test_the_extension_falls_back_to_the_url_then_the_content_type(self):
        # What _source_extension answers when the bytes are not available --
        # the path artwork_search still takes before it has read the body.
        from openemux.core.cover_sync import _source_extension

        cases = [
            ("https://cdn.example/art/label.jpg", "text/plain", "jpg"),
            ("https://cdn.example/art/label.jpeg", "text/plain", "jpg"),
            ("https://cdn.example/art/label.webp", "text/plain", "webp"),
            ("https://cdn.example/art/media?id=1", "image/jpeg", "jpg"),
            ("https://cdn.example/art/media?id=1", "image/webp", "webp"),
            ("https://cdn.example/art/media?id=1", "application/octet-stream", "png"),
        ]
        for url, content_type, expected in cases:
            response = mock.MagicMock()
            response.headers.get_content_type.return_value = content_type
            self.assertEqual(_source_extension(url, response), expected, url)

    def test_an_error_page_served_with_a_200_is_not_saved_as_a_cover(self):
        # ScreenScraper answers some quota failures with a plain-text body and
        # a 200; a captive portal answers everything with HTML. Whatever
        # landed at that path became the ROM's art forever (issue #213).
        from openemux.core.cover_sync import _download_cover

        for payload in (
            b"<html><body>Quota exceeded, please try again tomorrow</body></html>",
            b"Erreur : quota de telechargement depasse pour aujourd'hui",
            b"",
            b"\x89PNG\r\n\x1a\n",  # a signature and nothing behind it
        ):
            with TemporaryDirectory() as tmp_dir:
                response = _image_response(payload, "image/png")
                with patch(
                    "openemux.core.cover_sync.urllib.request.urlopen",
                    return_value=response,
                ):
                    ok = _download_cover(
                        "https://cdn.example/art/x.png", Path(tmp_dir) / "covers" / "Game.png"
                    )
                self.assertFalse(ok, payload[:20])
                self.assertEqual(list((Path(tmp_dir) / "covers").glob("*")), [], payload[:20])

    def test_a_failed_write_leaves_nothing_at_the_final_name(self):
        from openemux.core.cover_sync import _download_cover

        with TemporaryDirectory() as tmp_dir:
            response = _image_response(_PNG_BYTES, "image/png")
            with patch(
                "openemux.core.cover_sync.urllib.request.urlopen", return_value=response
            ):
                with patch(
                    "openemux.core.atomic_write.os.replace", side_effect=OSError("disk full")
                ):
                    ok = _download_cover(
                        "https://cdn.example/art/x.png", Path(tmp_dir) / "covers" / "Game.png"
                    )

            self.assertFalse(ok)
            self.assertEqual(list((Path(tmp_dir) / "covers").glob("*")), [])

    def test_junk_art_from_an_older_version_is_cleared_and_re_fetched(self):
        # The sticky half of issue #213: any file at that path counted as
        # art, so the ROM was skipped on every later fill-in sync and only a
        # blank card and a decode warning ever said otherwise.
        from openemux.core.cover_sync import _process_rom

        with TemporaryDirectory() as tmp_dir:
            roms_dir = Path(tmp_dir)
            art_path = roms_dir / "PS" / "covers" / "Game.png"
            art_path.parent.mkdir(parents=True, exist_ok=True)
            art_path.write_bytes(b"<html>Quota exceeded</html>" * 4)

            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "primary", "https://cdn.example/a.png")]),
                patch("openemux.core.cover_sync._download_cover",
                      side_effect=lambda url, dest: dest) as download_mock,
            ):
                result = _process_rom(
                    "PS",
                    {"name": "Game", "path": "/roms/PS/Game.cue"},
                    roms_dir,
                    "covers",
                    "boxart",
                    {},
                    None,
                    False,
                    None,
                    cover_sync._HostGates(),
                )

            self.assertEqual(result["status"], "downloaded")
            download_mock.assert_called_once()
            self.assertFalse(
                art_path.exists() and art_path.read_bytes().startswith(b"<html>")
            )

    def test_real_art_already_there_is_still_left_alone(self):
        from openemux.core.cover_sync import _process_rom

        with TemporaryDirectory() as tmp_dir:
            roms_dir = Path(tmp_dir)
            art_path = roms_dir / "PS" / "covers" / "Game.png"
            art_path.parent.mkdir(parents=True, exist_ok=True)
            art_path.write_bytes(_PNG_BYTES)

            with patch("openemux.core.cover_sync._download_cover") as download_mock:
                result = _process_rom(
                    "PS",
                    {"name": "Game", "path": "/roms/PS/Game.cue"},
                    roms_dir,
                    "covers",
                    "boxart",
                    {},
                    None,
                    False,
                    None,
                    cover_sync._HostGates(),
                )

            self.assertEqual(result["status"], "skipped")
            download_mock.assert_not_called()
            self.assertEqual(art_path.read_bytes(), _PNG_BYTES)

    def test_a_crashed_sync_still_reports_back(self):
        # on_done is what clears the caller's "a sync is running" flag; a
        # worker that dies without firing it wedges the app for the rest of
        # the session (issue #214).
        from openemux.core.cover_sync import sync_covers_async

        done = threading.Event()
        received = {}

        def _on_done(summary):
            received.update(summary)
            done.set()

        with patch("openemux.core.cover_sync._sync_covers", side_effect=RuntimeError("boom")):
            sync_covers_async(
                library_by_console={},
                covers_dir=Path("/tmp"),
                scope="all",
                selected_console=None,
                on_done=_on_done,
            )

        self.assertTrue(done.wait(5), "on_done never fired")
        self.assertEqual(received["crashed"], "boom")
        self.assertEqual(received["total"], 0)
        self.assertFalse(received["cancelled"])

    def test_a_crashed_artwork_sync_still_reports_back(self):
        from openemux.core.cover_sync import sync_artwork_async

        done = threading.Event()
        received = {}

        def _on_done(summary):
            received.update(summary)
            done.set()

        with patch("openemux.core.cover_sync._sync_artwork", side_effect=RuntimeError("boom")):
            sync_artwork_async(passes=[], covers_dir=Path("/tmp"), on_done=_on_done)

        self.assertTrue(done.wait(5), "on_done never fired")
        self.assertEqual(received["crashed"], "boom")
        self.assertEqual(received["passes"], [])

    def test_cover_sync_reports_progress(self):
        library = {
            "PS": [
                {"name": "Game A", "path": "/tmp/Game A.cue", "console": "PS"},
                {"name": "Game B", "path": "/tmp/Game B.cue", "console": "PS"},
            ]
        }
        events = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u1")]),
                patch("openemux.core.cover_sync._fts_stage_candidates", return_value=[]),
                patch("openemux.core.cover_sync._download_cover", side_effect=[True, False]),
            ):
                _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="PS",
                    sync_settings={},
                    on_progress=events.append,
                )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["processed"], 1)
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[1]["processed"], 2)
        self.assertEqual(events[1]["total"], 2)


class CoverSourceProviderTests(unittest.TestCase):
    """libretro leads every default chain; the OpenEmux mirror closes it."""

    def test_default_source_is_libretro_backed_by_the_mirror(self):
        for settings in ({}, {"cover_source": "libretro"}):
            names = [name for name, _fn in _ordered_providers(settings)]
            self.assertEqual(names, ["libretro", "openemux"], settings)

    def test_default_source_never_calls_screenscraper(self):
        with patch("openemux.core.cover_sync._screenscraper_candidates") as ss_mock:
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", {})
        ss_mock.assert_not_called()
        self.assertTrue(urls)

    def test_default_candidates_lead_with_the_libretro_provider(self):
        # The mirror only appends: every libretro candidate keeps its position,
        # so existing matches resolve exactly as they always did.
        settings = {"region_priority": ["USA", "World"], "name_cleanup": True}
        libretro = _libretro_candidates("SFC", "Chrono Trigger", settings)
        combined = _remote_cover_candidates("SFC", "Chrono Trigger", settings)
        self.assertEqual(combined[: len(libretro)], libretro)
        mirror_urls = combined[len(libretro):]
        self.assertTrue(mirror_urls)
        self.assertTrue(
            all(u.startswith(cover_sync.OPENEMUX_ARTWORK_BASE) for u in mirror_urls)
        )

    def test_openemux_mirror_urls_follow_the_repo_layout(self):
        urls = cover_sync._openemux_candidates("SFC", "Chrono Trigger (USA)", {})
        self.assertTrue(urls)
        self.assertEqual(
            urls[0],
            "https://raw.githubusercontent.com/guilhermefeitosa66/openemux-artwork/"
            "main/Nintendo_-_Super_Nintendo_Entertainment_System/"
            "Chrono%20Trigger%20%28USA%29.webp",
        )

    def test_openemux_mirror_serves_no_cartridge_labels(self):
        # The mirror only carries box art; a label pass must get nothing from
        # it, not box-art URLs that would be saved into labels/.
        urls = cover_sync._openemux_candidates(
            "SFC", "Chrono Trigger", {"cover_art_type": "cartridge_label"}
        )
        self.assertEqual(urls, [])

    def test_libretro_then_screenscraper_appends_screenscraper_candidates(self):
        settings = {"cover_source": "libretro_then_screenscraper"}
        with patch(
            "openemux.core.cover_sync._screenscraper_candidates", return_value=["ss1", "ss2"]
        ):
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", settings)
        libretro_urls = _libretro_candidates("SFC", "Chrono Trigger", settings)
        self.assertEqual(urls[: len(libretro_urls)], libretro_urls)
        self.assertEqual(
            urls[len(libretro_urls) : len(libretro_urls) + 2], ["ss1", "ss2"]
        )
        # The mirror still closes the chain, after both preferred sources.
        self.assertTrue(
            all(
                u.startswith(cover_sync.OPENEMUX_ARTWORK_BASE)
                for u in urls[len(libretro_urls) + 2 :]
            )
        )

    def test_screenscraper_only_source_skips_libretro(self):
        settings = {"cover_source": "screenscraper"}
        with patch(
            "openemux.core.cover_sync._screenscraper_candidates", return_value=["ss1"]
        ):
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", settings)
        self.assertEqual(urls[0], "ss1")
        self.assertNotIn("thumbnails.libretro.com", " ".join(urls))
        self.assertTrue(
            all(u.startswith(cover_sync.OPENEMUX_ARTWORK_BASE) for u in urls[1:])
        )

    def test_unknown_source_value_falls_back_to_libretro(self):
        names = [name for name, _fn in _ordered_providers({"cover_source": "bogus"})]
        self.assertEqual(names, ["libretro", "openemux"])

    def test_screenscraper_provider_swallows_errors(self):
        with patch(
            "openemux.core.cover_sync.screenscraper.lookup_media_urls",
            side_effect=RuntimeError("boom"),
        ):
            from openemux.core.cover_sync import _screenscraper_candidates

            self.assertEqual(_screenscraper_candidates("SFC", "Game", {}), [])


if __name__ == "__main__":
    unittest.main()


class CancellationTests(unittest.TestCase):
    """A long cover sync must be interruptible, and must keep what it fetched."""

    def _library(self, count):
        return {"SFC": [{"name": f"Game {i}", "path": f"/roms/SFC/Game {i}.sfc"} for i in range(count)]}

    def test_cancel_stops_early_and_reports_it(self):
        attempted = []

        def fake_download(url, dest):
            attempted.append(url)
            return True  # every ROM "finds" a cover on its first candidate

        # Cancel once three ROMs have been handled.
        def should_cancel():
            return len(attempted) >= 3

        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", fake_download):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(50),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=should_cancel,
                )

        self.assertTrue(summary["cancelled"])
        self.assertEqual(summary["downloaded"], 3)
        # Stopped well before the 50 ROMs the library actually holds.
        self.assertLess(summary["total"], 50)

    def test_cancelled_rom_is_not_counted_as_an_error(self):
        # Cancelling must not look like 47 failed lookups in the summary.
        calls = {"n": 0}

        def fake_download(url, dest):
            calls["n"] += 1
            return True

        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", fake_download):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(50),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=lambda: calls["n"] >= 2,
                )

        self.assertEqual(summary["errors"], 0)

    def test_not_cancelled_runs_to_completion(self):
        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", lambda url, dest: True):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(5),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=lambda: False,
                )

        self.assertFalse(summary["cancelled"])
        self.assertEqual(summary["downloaded"], 5)
        self.assertEqual(summary["total"], 5)


class ArtworkPassPlanningTests(unittest.TestCase):
    """build_artwork_passes: box art everywhere, labels only where a frame is."""

    LIB = {
        "SFC": [{"name": "Chrono Trigger", "path": "/r/SFC/ct.smc", "console": "SFC"}],
        "PS": [{"name": "Final Fantasy VII", "path": "/r/PS/ff7.cue", "console": "PS"}],
    }

    def test_labels_pass_covers_only_frame_capable_consoles(self):
        passes = build_artwork_passes(self.LIB, ["SFC", "FC"])
        self.assertEqual([kind for kind, _ in passes], ["boxart", "cartridge_label"])
        self.assertEqual(sorted(passes[0][1]), ["PS", "SFC"])
        # PS has no cartridge frame, so it must not appear in the label pass.
        self.assertEqual(sorted(passes[1][1]), ["SFC"])

    def test_no_label_pass_when_no_console_has_a_frame(self):
        passes = build_artwork_passes({"PS": self.LIB["PS"]}, ["SFC", "FC"])
        self.assertEqual([kind for kind, _ in passes], ["boxart"])

    def test_empty_label_console_list_yields_box_art_only(self):
        self.assertEqual(
            [kind for kind, _ in build_artwork_passes(self.LIB, [])], ["boxart"]
        )

    def test_consoles_with_no_roms_are_dropped(self):
        passes = build_artwork_passes({"SFC": [], "PS": self.LIB["PS"]}, ["SFC"])
        self.assertEqual([kind for kind, _ in passes], ["boxart"])
        self.assertEqual(sorted(passes[0][1]), ["PS"])

    def test_nothing_to_do_yields_no_passes(self):
        self.assertEqual(build_artwork_passes({}, ["SFC"]), [])
        self.assertEqual(build_artwork_passes({"SFC": []}, ["SFC"]), [])


class MultiPassArtworkSyncTests(unittest.TestCase):
    """_sync_artwork: run the passes in order and aggregate them into one run."""

    @staticmethod
    def _rom(console, name):
        return {"name": name, "path": f"/r/{console}/{name}", "console": console}

    def _passes(self):
        return [
            ("boxart", {"SFC": [self._rom("SFC", "A"), self._rom("SFC", "B")]}),
            ("cartridge_label", {"SFC": [self._rom("SFC", "A")]}),
        ]

    def test_each_pass_writes_to_its_own_directory(self):
        written = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u")]),
                patch(
                    "openemux.core.cover_sync._download_cover",
                    side_effect=lambda url, dest: written.append(dest) or True,
                ),
            ):
                summary = _sync_artwork(passes=self._passes(), covers_dir=tmp_dir)

        self.assertEqual([p.parent.name for p in written], ["covers", "covers", "labels"])
        self.assertEqual(summary["downloaded"], 3)
        self.assertEqual(summary["total"], 3)
        self.assertEqual([p["art_kind"] for p in summary["passes"]], ["boxart", "cartridge_label"])

    def test_progress_is_continuous_across_passes(self):
        events = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u")]),
                patch("openemux.core.cover_sync._download_cover", return_value=True),
            ):
                _sync_artwork(
                    passes=self._passes(),
                    covers_dir=tmp_dir,
                    on_progress=events.append,
                )

        # One combined total, and a counter that never restarts between kinds.
        self.assertTrue(all(e["total"] == 3 for e in events), events)
        self.assertEqual([e["processed"] for e in events], [1, 2, 3])
        self.assertEqual(
            [e["art_kind"] for e in events], ["boxart", "boxart", "cartridge_label"]
        )

    def test_empty_passes_are_dropped(self):
        with TemporaryDirectory() as tmp_dir:
            with patch("openemux.core.cover_sync._download_cover", return_value=True):
                summary = _sync_artwork(
                    passes=[("boxart", {}), ("cartridge_label", {"SFC": []})],
                    covers_dir=tmp_dir,
                )
        self.assertEqual(summary["passes"], [])
        self.assertEqual(summary["total"], 0)
        self.assertFalse(summary["cancelled"])

    def test_cancelling_stops_before_the_next_pass(self):
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u")]),
                patch("openemux.core.cover_sync._download_cover", return_value=True),
            ):
                summary = _sync_artwork(
                    passes=self._passes(),
                    covers_dir=tmp_dir,
                    should_cancel=lambda: True,
                )
        self.assertTrue(summary["cancelled"])
        # Cancelled before any pass ran, so the label pass never started.
        self.assertEqual(summary["passes"], [])

    def test_configured_artwork_type_does_not_leak_into_the_passes(self):
        # The post-import run wants both kinds regardless of the Preferences
        # setting, so each pass must override cover_art_type for itself.
        seen = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync._staged_cover_candidates",
                      return_value=[("libretro", "exact", "u")]),
                patch(
                    "openemux.core.cover_sync._download_cover",
                    side_effect=lambda url, dest: seen.append(dest.parent.name) or True,
                ),
            ):
                _sync_artwork(
                    passes=self._passes(),
                    covers_dir=tmp_dir,
                    sync_settings={"cover_art_type": "cartridge_label"},
                )
        self.assertEqual(seen, ["covers", "covers", "labels"])


class FuzzyTitleFallbackTests(unittest.TestCase):
    """Issue #127: last-resort guesses for the ~5% the exact names miss."""

    def test_the_parenthesised_alternate_title_is_tried_on_its_own(self):
        # The reporter's example: the thumbnail repo may file the game under
        # either name, so both halves are worth trying.
        candidates = fuzzy_candidate_names("Aero Fighters (Sonic Wings) (USA)")
        self.assertIn("Aero Fighters", candidates)
        self.assertIn("Sonic Wings", candidates)

    def test_region_and_revision_tags_are_not_mistaken_for_titles(self):
        for name in (
            "Contra (USA) (Rev A)",
            "Sonic (Japan, USA)",
            "Zelda (En,Fr,De,Es,It)",
            "Metroid (Beta)",
            "Doom (v1.1)",
            "Kirby [!]",
        ):
            for candidate in fuzzy_candidate_names(name):
                self.assertNotIn("(", candidate, name)
                self.assertNotIn("[", candidate, name)

    def test_mid_title_tags_are_stripped_not_only_trailing_ones(self):
        # _normalize_rom_name only peels tags off the end.
        candidates = fuzzy_candidate_names("Super Mario (USA) World [!] Deluxe")
        self.assertIn("Super Mario World Deluxe", candidates)

    def test_punctuation_is_dropped_as_a_separate_candidate(self):
        candidates = fuzzy_candidate_names("Castlevania - Aria of Sorrow")
        self.assertIn("Castlevania - Aria of Sorrow", candidates)
        self.assertIn("Castlevania Aria of Sorrow", candidates)

    def test_a_clean_name_produces_no_useless_duplicates(self):
        candidates = fuzzy_candidate_names("Chrono Trigger")
        self.assertEqual(len(candidates), len(set(candidates)))


class FtsStageWiringTests(unittest.TestCase):
    """Stage 4 (#175): the FTS resolution runs once, last, and only on a miss."""

    def _library(self):
        return {
            "snes": [
                {
                    "name": "Aero Fighters (Sonic Wings) (USA)",
                    "path": "/tmp/Aero Fighters (Sonic Wings) (USA).sfc",
                    "console": "snes",
                }
            ]
        }

    def test_the_fts_stage_only_runs_after_every_provider_missed(self):
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch(
                    "openemux.core.cover_sync._staged_cover_candidates",
                    return_value=[("libretro", "exact", "u1"), ("libretro", "normalized", "u2")],
                ),
                patch(
                    "openemux.core.cover_sync._fts_stage_candidates", return_value=[]
                ) as fts_mock,
                patch(
                    "openemux.core.cover_sync._download_cover", return_value=True
                ) as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=self._library(),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        # First candidate hit: the last-resort stage must not have run.
        self.assertEqual(download_mock.call_count, 1)
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(fts_mock.call_count, 0)

    def test_a_miss_falls_through_to_the_fts_stage(self):
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch(
                    "openemux.core.cover_sync._staged_cover_candidates",
                    return_value=[("libretro", "exact", "u1")],
                ),
                patch(
                    "openemux.core.cover_sync._fts_stage_candidates",
                    return_value=[("openemux", "fts", "fts-url")],
                ) as fts_mock,
                patch(
                    "openemux.core.cover_sync._download_cover", side_effect=[False, True]
                ),
            ):
                summary = _sync_covers(
                    library_by_console=self._library(),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        self.assertEqual(fts_mock.call_count, 1)
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["stages"]["fts"], 1)

    def test_an_unavailable_index_degrades_to_a_plain_miss(self):
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch(
                    "openemux.core.cover_sync._staged_cover_candidates",
                    return_value=[("libretro", "exact", "u1")],
                ),
                patch(
                    "openemux.core.cover_sync._get_name_index",
                    return_value=ArtworkNameIndex(db_path="/nonexistent/games.db",
                                                  shipped_zip="/nonexistent.zip"),
                ),
                patch("openemux.core.cover_sync._download_cover", return_value=False),
            ):
                summary = _sync_covers(
                    library_by_console=self._library(),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["missed"][0]["rom_name"], "Aero Fighters (Sonic Wings) (USA)")

    def test_the_summary_names_the_roms_that_still_need_artwork(self):
        # errors used to be a bare count, so the UI could say how many failed
        # but never which ones.
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch(
                    "openemux.core.cover_sync._staged_cover_candidates",
                    return_value=[("libretro", "exact", "u1")],
                ),
                patch("openemux.core.cover_sync._fts_stage_candidates", return_value=[]),
                patch("openemux.core.cover_sync._download_cover", return_value=False),
            ):
                summary = _sync_covers(
                    library_by_console=self._library(),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        self.assertEqual(
            summary["missed"],
            [{"console": "snes", "rom_name": "Aero Fighters (Sonic Wings) (USA)"}],
        )
        self.assertEqual(summary["errors"], len(summary["missed"]))

    def test_fts_candidates_come_from_the_resolved_stem_only(self):
        class _Index:
            def resolve_name(self, system, rom_name, region_priority=None):
                return ("Aero Fighters (USA)", "untagged")

        with patch("openemux.core.cover_sync._get_name_index", return_value=_Index()):
            triples = cover_sync._fts_stage_candidates(
                "SFC", "Aero Fighters (Sonic Wings) (USA)", {}, already_tried=set()
            )
        self.assertTrue(triples)
        self.assertTrue(all(stage == "fts" for _p, stage, _u in triples))
        # Only file-based providers, and only URLs for the resolved stem.
        self.assertTrue(all("Aero%20Fighters%20%28USA%29" in url for _p, _s, url in triples))
        providers = [p for p, _s, _u in triples]
        self.assertIn("libretro", providers)
        self.assertIn("openemux", providers)
        self.assertNotIn("screenscraper", providers)

    def test_fts_candidates_skip_urls_already_tried(self):
        class _Index:
            def resolve_name(self, system, rom_name, region_priority=None):
                return ("Aero Fighters (USA)", "untagged")

        with patch("openemux.core.cover_sync._get_name_index", return_value=_Index()):
            first = cover_sync._fts_stage_candidates("SFC", "Aero", {}, already_tried=set())
            tried = {url for _p, _s, url in first}
            second = cover_sync._fts_stage_candidates("SFC", "Aero", {}, already_tried=tried)
        self.assertTrue(first)
        self.assertEqual(second, [])


class StagedCandidateTests(unittest.TestCase):
    """The per-provider ladder (#175): hash -> exact -> normalized, in order."""

    def test_thumbnail_names_are_sanitized_at_url_build_time(self):
        # The reported bug: "&" must become "_" in the filename, for both
        # file-based providers, or every candidate 404s.
        url = cover_sync._build_cover_url("Sega - Mega Drive - Genesis",
                                          "Adventures of Batman & Robin, The (USA)")
        self.assertIn("Batman%20_%20Robin", url)
        mirror = cover_sync._build_openemux_art_url("Sega - Mega Drive - Genesis",
                                                    "Adventures of Batman & Robin, The (USA)")
        self.assertIn("Batman%20_%20Robin", mirror)

    def test_every_reserved_character_is_sanitized(self):
        for char in '&*/:`<>?\\|"':
            sanitized = cover_sync._sanitize_thumbnail_name(f"A{char}B")
            self.assertEqual(sanitized, "A_B", repr(char))

    def test_provider_ladders_run_in_order(self):
        with patch("openemux.core.cover_sync._resolve_hash_stem",
                   return_value="Hash Stem (USA)"):
            triples = cover_sync._staged_cover_candidates(
                "SFC", "Chrono Trigger", {}, rom_path="/tmp/ct.sfc"
            )
        stages = [(p, s) for p, s, _u in triples]
        # Default chain: libretro then openemux; each runs hash, exact, then
        # normalized before the next provider starts.
        self.assertEqual(stages[0], ("libretro", "hash"))
        libretro_stages = [s for p, s in stages if p == "libretro"]
        self.assertEqual(libretro_stages[0], "hash")
        self.assertIn("exact", libretro_stages)
        self.assertIn("normalized", libretro_stages)
        first_openemux = next(i for i, (p, _s) in enumerate(stages) if p == "openemux")
        self.assertTrue(all(p == "libretro" for p, _s in stages[:first_openemux]))
        self.assertIn("Hash%20Stem%20%28USA%29", triples[0][2])

    def test_hash_stage_is_skipped_without_an_index_hit(self):
        with patch("openemux.core.cover_sync._resolve_hash_stem", return_value=None):
            triples = cover_sync._staged_cover_candidates(
                "SFC", "Chrono Trigger", {}, rom_path="/tmp/ct.sfc"
            )
        self.assertTrue(all(s != "hash" for _p, s, _u in triples))
        self.assertEqual(triples[0][1], "exact")

    def test_rom_hashing_waits_for_a_crc_capable_index(self):
        # Hashing reads the whole ROM file; without a crc_index table it
        # must never run at all.
        class _Index:
            def has_crc_index(self):
                return False

        with (
            patch("openemux.core.cover_sync._get_name_index", return_value=_Index()),
            patch("openemux.core.cover_sync.hasher.compute_crc32") as crc_mock,
        ):
            stem = cover_sync._resolve_hash_stem("SFC", "/tmp/ct.sfc", {})
        self.assertIsNone(stem)
        self.assertEqual(crc_mock.call_count, 0)

    def test_a_crc_hit_resolves_through_the_index(self):
        class _Index:
            def has_crc_index(self):
                return True

            def resolve_by_crc(self, system, crc):
                assert system == "Nintendo - Super Nintendo Entertainment System"
                assert crc == "AABBCCDD"
                return "Chrono Trigger (USA)"

        with (
            patch("openemux.core.cover_sync._get_name_index", return_value=_Index()),
            patch("openemux.core.cover_sync.hasher.compute_crc32", return_value="AABBCCDD"),
        ):
            stem = cover_sync._resolve_hash_stem("SFC", "/tmp/rom001.md", {})
        self.assertEqual(stem, "Chrono Trigger (USA)")


class ParallelSyncTests(unittest.TestCase):
    """#186: bounded fan-out with per-host politeness budgets."""

    @staticmethod
    def _library(count):
        return {
            "SFC": [
                {"name": f"Game {i:02d}", "path": f"/tmp/g{i}.sfc", "console": "SFC"}
                for i in range(count)
            ]
        }

    def test_downloads_run_in_parallel_but_respect_the_host_budget(self):
        import threading as _threading
        import time as _time

        in_flight = {"mirror": 0, "libretro": 0}
        peaks = {"mirror": 0, "libretro": 0}
        track_lock = _threading.Lock()

        def _fake_download(url, dest):
            host = "mirror" if "raw.githubusercontent.com" in url else "libretro"
            with track_lock:
                in_flight[host] += 1
                peaks[host] = max(peaks[host], in_flight[host])
            _time.sleep(0.02)
            with track_lock:
                in_flight[host] -= 1
            return True

        def _staged(console, rom_name, settings, rom_path=None, provider_rotation=0, gates=None):
            return [
                ("libretro", "exact", f"https://thumbnails.libretro.com/x/{rom_name}.png"),
                ("openemux", "exact", f"https://raw.githubusercontent.com/x/{rom_name}.webp"),
            ]

        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch("openemux.core.cover_sync._staged_cover_candidates", side_effect=_staged),
                patch("openemux.core.cover_sync._download_cover", side_effect=_fake_download),
            ):
                summary = _sync_covers(
                    library_by_console=self._library(8),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="SFC",
                    sync_settings={},
                    max_workers=6,
                )
        self.assertEqual(summary["downloaded"], 8)
        # Third-party host: never more than one request in flight.
        self.assertEqual(peaks["libretro"], 1)

    def test_the_mirror_takes_real_concurrency(self):
        import threading as _threading
        import time as _time

        peak = {"value": 0, "now": 0}
        track_lock = _threading.Lock()

        def _fake_download(url, dest):
            with track_lock:
                peak["now"] += 1
                peak["value"] = max(peak["value"], peak["now"])
            _time.sleep(0.03)
            with track_lock:
                peak["now"] -= 1
            return True

        def _staged(console, rom_name, settings, rom_path=None, provider_rotation=0, gates=None):
            return [
                ("openemux", "exact", f"https://raw.githubusercontent.com/x/{rom_name}.webp"),
            ]

        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch("openemux.core.cover_sync._staged_cover_candidates", side_effect=_staged),
                patch("openemux.core.cover_sync._download_cover", side_effect=_fake_download),
            ):
                _sync_covers(
                    library_by_console=self._library(8),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="SFC",
                    sync_settings={},
                    max_workers=6,
                )
        self.assertGreater(peak["value"], 1)

    def test_progress_stays_monotonic_with_out_of_order_completions(self):
        import time as _time

        def _fake_download(url, dest):
            # Earlier submissions take longer, so completions arrive reversed.
            index = int(url.rsplit("-", 1)[1].split(".")[0])
            _time.sleep(0.03 - index * 0.005)
            return True

        def _staged(console, rom_name, settings, rom_path=None, provider_rotation=0, gates=None):
            index = rom_name.split()[-1]
            return [("openemux", "exact",
                     f"https://raw.githubusercontent.com/x/g-{int(index)}.webp")]

        events = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch("openemux.core.cover_sync._staged_cover_candidates", side_effect=_staged),
                patch("openemux.core.cover_sync._download_cover", side_effect=_fake_download),
            ):
                _sync_covers(
                    library_by_console=self._library(5),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="SFC",
                    sync_settings={},
                    on_progress=events.append,
                    max_workers=5,
                )
        self.assertEqual([e["processed"] for e in events], [1, 2, 3, 4, 5])
        self.assertTrue(all(e["total"] == 5 for e in events))

    def test_cancel_mid_run_keeps_completed_files_and_counts(self):
        import threading as _threading

        done = _threading.Event()
        calls = {"n": 0}

        def _fake_download(url, dest):
            calls["n"] += 1
            if calls["n"] == 1:
                done.set()  # first download lands, then the user cancels
            return True

        def _staged(console, rom_name, settings, rom_path=None, provider_rotation=0, gates=None):
            return [("openemux", "exact",
                     f"https://raw.githubusercontent.com/x/{rom_name}.webp")]

        with TemporaryDirectory() as tmp_dir:
            with (
                patch("openemux.core.cover_sync.find_local_art", return_value=None),
                patch("openemux.core.cover_sync._staged_cover_candidates", side_effect=_staged),
                patch("openemux.core.cover_sync._download_cover", side_effect=_fake_download),
            ):
                summary = _sync_covers(
                    library_by_console=self._library(30),
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="SFC",
                    sync_settings={},
                    should_cancel=done.is_set,
                    max_workers=2,
                )
        self.assertTrue(summary["cancelled"])
        # What completed stays counted; nothing completed is lost.
        self.assertEqual(summary["downloaded"], summary["total"] - summary["skipped"] - summary["errors"])
        self.assertLess(summary["total"], 30)

    def test_rotation_balances_the_equivalent_file_hosts(self):
        with patch("openemux.core.cover_sync._resolve_hash_stem", return_value=None):
            even = cover_sync._staged_cover_candidates(
                "SFC", "Chrono Trigger", {}, provider_rotation=0
            )
            odd = cover_sync._staged_cover_candidates(
                "SFC", "Chrono Trigger", {}, provider_rotation=1
            )
        self.assertEqual(even[0][0], "libretro")
        self.assertEqual(odd[0][0], "openemux")
        # Both rotations cover the same URL set: rotation changes order only.
        self.assertEqual({u for _p, _s, u in even}, {u for _p, _s, u in odd})

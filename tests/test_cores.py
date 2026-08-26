import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.cores import CoreCatalog, CoreConfigStore, parse_core_info
from openemux.core.platform import CORE_SUFFIX, core_stem


def _core_name(stem):
    """A core filename spelled the way this platform resolves it.

    ``.so`` on Linux, ``.dll`` on Windows. The catalogs in ``systems.py`` keep
    the ``.so`` spelling and the extension is applied at lookup time, so a
    fixture that hardcoded ``.so`` would pass on Linux and match nothing on
    Windows (issue #118).
    """
    return f"{stem}_libretro{CORE_SUFFIX}"


def _write_core(base, filename, info_fields=None):
    (base / filename).write_text("", encoding="utf-8")
    if info_fields is not None:
        stem = core_stem(filename)
        lines = [f'{k} = "{v}"' for k, v in info_fields.items()]
        (base / f"{stem}.info").write_text("\n".join(lines), encoding="utf-8")


class CoreCatalogTests(unittest.TestCase):
    def test_display_name_from_info_corename(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            _write_core(base, _core_name("snes9x"), {"corename": "Snes9x"})
            catalog = CoreCatalog(core_dirs=[base])
            self.assertEqual(catalog.display_name_for(_core_name("snes9x")), "Snes9x")

    def test_display_name_falls_back_to_humanized_filename(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            _write_core(base, _core_name("bsnes"))  # no .info
            catalog = CoreCatalog(core_dirs=[base])
            self.assertEqual(catalog.display_name_for(_core_name("bsnes")), "Bsnes")

    def test_cores_for_console_lists_candidates_first(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            # SFC candidates are snes9x then bsnes; mesen-s matches via database.
            _write_core(base, _core_name("snes9x"), {"corename": "Snes9x"})
            _write_core(base, _core_name("bsnes"), {"corename": "bsnes"})
            _write_core(
                base,
                _core_name("mesen-s"),
                {
                    "corename": "Mesen-S",
                    "database": "Nintendo - Super Nintendo Entertainment System",
                },
            )
            # An unrelated core must not appear.
            _write_core(base, _core_name("mgba"), {"corename": "mGBA"})

            catalog = CoreCatalog(core_dirs=[base])
            names = [c.filename for c in catalog.cores_for_console("SFC")]
            self.assertEqual(names[:2], [_core_name("snes9x"), _core_name("bsnes")])
            self.assertIn(_core_name("mesen-s"), names)
            self.assertNotIn(_core_name("mgba"), names)

    def test_cores_for_console_empty_when_none_installed(self):
        with TemporaryDirectory() as tmp_dir:
            catalog = CoreCatalog(core_dirs=[Path(tmp_dir)])
            self.assertEqual(catalog.cores_for_console("SFC"), [])

    def test_info_and_so_may_live_in_separate_dirs(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            so_dir = root / "flatpak"
            info_dir = root / "config"
            so_dir.mkdir()
            info_dir.mkdir()
            (so_dir / _core_name("snes9x")).write_text("", encoding="utf-8")
            (info_dir / "snes9x_libretro.info").write_text(
                'corename = "Snes9x"', encoding="utf-8"
            )
            catalog = CoreCatalog(core_dirs=[info_dir, so_dir])
            self.assertEqual(catalog.display_name_for(_core_name("snes9x")), "Snes9x")
            self.assertTrue(catalog.is_installed(_core_name("snes9x")))


class CoreConfigStoreTests(unittest.TestCase):
    def test_rom_override_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = Path(tmp_dir) / "cores.config"
            store = CoreConfigStore(config_file=cfg)
            store.set_rom_core("/g/SFC/ct.sfc", _core_name("bsnes"))
            self.assertEqual(
                CoreConfigStore(config_file=cfg).get_rom_core("/g/SFC/ct.sfc"),
                _core_name("bsnes"),
            )

    def test_none_clears_override(self):
        with TemporaryDirectory() as tmp_dir:
            store = CoreConfigStore(config_file=Path(tmp_dir) / "cores.config")
            rom = "/g/SFC/ct.sfc"
            store.set_rom_core(rom, _core_name("bsnes"))
            store.set_rom_core(rom, None)
            self.assertIsNone(store.get_rom_core(rom))

    def test_override_follows_rename_and_drops_on_delete(self):
        with TemporaryDirectory() as tmp_dir:
            store = CoreConfigStore(config_file=Path(tmp_dir) / "cores.config")
            old, new = "/g/SFC/a.sfc", "/g/SFC/b.sfc"
            store.set_rom_core(old, _core_name("snes9x"))
            store.repath_rom(old, new)
            self.assertIsNone(store.get_rom_core(old))
            self.assertEqual(store.get_rom_core(new), _core_name("snes9x"))
            store.forget_rom(new)
            self.assertIsNone(store.get_rom_core(new))


class ParseCoreInfoTests(unittest.TestCase):
    def test_parses_quoted_fields(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "x.info"
            path.write_text(
                'corename = "Snes9x"\n'
                'database = "Nintendo - SNES|Nintendo - Satellaview"\n'
                "unrelated = 3\n",
                encoding="utf-8",
            )
            fields = parse_core_info(path)
            self.assertEqual(fields["corename"], "Snes9x")
            self.assertIn("Satellaview", fields["database"])
            self.assertNotIn("unrelated", fields)


if __name__ == "__main__":
    unittest.main()

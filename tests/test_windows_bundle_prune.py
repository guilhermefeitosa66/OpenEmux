"""What the Windows bundle drops, and what it must never drop (#365).

Installing the Windows bundle was slow because of *file count*, not byte count:
NSIS extracts one file at a time and the 1.11.3 bundle held 21.909 of them. The
prune lists in ``packaging/windows/stage.py`` were written against size, which
is the wrong axis, and stopped well short.

These tests run the real ``prune_prefix`` against a fixture prefix rather than
asserting on the text of the lists: what a build actually deletes is behaviour.
The one thing they do read as text is ``build.sh``'s phase 5, because the two
findings that cost the most to rediscover -- Qt5 is load-bearing, ozone is the
menu driver -- live there as gates.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_PATH = REPO_ROOT / "packaging/windows/stage.py"
BUILD_SH = REPO_ROOT / "packaging/windows/build.sh"


def _load_stage():
    spec = importlib.util.spec_from_file_location("windows_stage", STAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage = _load_stage()

#: A prefix with one file in each place the prune has an opinion about. Written
#: as the MSYS2 packages leave it -- under ``mingw64/`` -- so ``relocate_prefix``
#: runs too and the paths under test are the ones a real build sees.
FIXTURE = (
    # Dropped: nothing in a GTK4 app reads terminal capabilities, and ncurses
    # ships the tree twice.
    "mingw64/share/terminfo/x/xterm",
    "mingw64/lib/terminfo/v/vt100",
    # Dropped: unreachable on Windows (Python's TZPATH is a POSIX string baked
    # at build time; GLib reads the registry).
    "mingw64/share/zoneinfo/America/Sao_Paulo",
    "mingw64/share/zoneinfo/Europe/Berlin",
    # Dropped: a Tcl extension, now that tkinter and Tcl itself are gone.
    "mingw64/lib/itcl4.3.7/pkgIndex.tcl",
    "mingw64/lib/itcl4.3.7/libitcl4.3.7.dll",
    # Kept: not a Tcl package -- no pkgIndex.tcl -- and GTK loads it.
    "mingw64/lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.dll",
    "mingw64/lib/girepository-1.0/Gtk-4.0.typelib",
    # Kept: the app's own languages. Dropped: everything else of the 185.
    "mingw64/share/locale/pt_BR/LC_MESSAGES/gtk40.mo",
    "mingw64/share/locale/pt/LC_MESSAGES/gtk40.mo",
    "mingw64/share/locale/zh_CN/LC_MESSAGES/glib20.mo",
    "mingw64/share/locale/ja/LC_MESSAGES/libadwaita.mo",
    "mingw64/share/locale/it/LC_MESSAGES/gtk40.mo",
    "mingw64/share/locale/ru/LC_MESSAGES/gtk40.mo",
    "mingw64/share/locale/zh_TW/LC_MESSAGES/gtk40.mo",
    # Kept: a loose file under share/locale is not a language directory.
    "mingw64/share/locale/locale.alias",
    # Kept, and pruned before this change already -- the fixture carries them
    # so a regression in the old half shows up here too.
    "mingw64/share/glib-2.0/schemas/org.gtk.gschema.xml",
    "mingw64/etc/ssl/certs/ca-bundle.crt",
    "mingw64/include/glib-2.0/glib.h",
    "mingw64/share/man/man1/gtk4-demo.1",
)


class PruneDropsWhatNothingReadsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        extracted = tmp / "extracted"
        for relative in FIXTURE:
            path = extracted / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        self.bundle = tmp / "OpenEmux"
        stage.relocate_prefix(extracted, self.bundle)
        stage.prune_prefix(self.bundle)

    def tearDown(self):
        self._tmp.cleanup()

    def assertGone(self, relative):
        self.assertFalse(
            (self.bundle / relative).exists(), f"{relative} should have been pruned"
        )

    def assertKept(self, relative):
        self.assertTrue(
            (self.bundle / relative).is_file(), f"{relative} should have survived"
        )

    def test_terminfo_goes_from_both_places_ncurses_puts_it(self):
        self.assertGone("share/terminfo")
        self.assertGone("lib/terminfo")

    def test_the_tzdata_tree_goes(self):
        self.assertGone("share/zoneinfo")

    def test_tcl_extension_packages_go_with_tcl(self):
        self.assertGone("lib/itcl4.3.7")

    def test_a_directory_without_a_pkgindex_is_not_a_tcl_package(self):
        self.assertKept("lib/girepository-1.0/Gtk-4.0.typelib")
        self.assertKept("lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.dll")

    def test_the_languages_the_app_ships_keep_their_gtk_strings(self):
        self.assertKept("share/locale/pt_BR/LC_MESSAGES/gtk40.mo")
        self.assertKept("share/locale/zh_CN/LC_MESSAGES/glib20.mo")
        self.assertKept("share/locale/ja/LC_MESSAGES/libadwaita.mo")

    def test_the_base_language_survives_so_gettext_has_its_fallback(self):
        # pt_PT gets OpenEmux in pt_BR (i18n's LANGUAGE_FALLBACKS) and GTK from
        # `pt`, which is where gettext looks after pt_PT.
        self.assertKept("share/locale/pt/LC_MESSAGES/gtk40.mo")

    def test_languages_the_app_is_not_translated_into_go(self):
        self.assertGone("share/locale/it")
        self.assertGone("share/locale/ru")
        self.assertGone("share/locale/zh_TW")

    def test_a_loose_file_under_share_locale_is_left_alone(self):
        self.assertKept("share/locale/locale.alias")

    def test_the_build_time_half_still_goes(self):
        self.assertGone("include")
        self.assertGone("share/man")

    def test_what_the_app_needs_at_runtime_is_untouched(self):
        self.assertKept("share/glib-2.0/schemas/org.gtk.gschema.xml")
        self.assertKept("etc/ssl/certs/ca-bundle.crt")


class LocaleKeepFollowsTheAppTests(unittest.TestCase):
    def test_every_language_the_app_ships_is_kept(self):
        from openemux.i18n import SUPPORTED_LOCALES

        for locale in SUPPORTED_LOCALES:
            self.assertIn(locale, stage.LOCALE_KEEP)

    def test_each_regional_locale_brings_its_base_language(self):
        self.assertIn("pt_BR", stage.LOCALE_KEEP)
        self.assertIn("pt", stage.LOCALE_KEEP)
        self.assertIn("zh_CN", stage.LOCALE_KEEP)
        self.assertIn("zh", stage.LOCALE_KEEP)

    def test_the_list_is_not_a_second_copy_of_the_supported_locales(self):
        # If someone adds a language to src/openemux/i18n/, the bundle has to
        # start shipping GTK's strings for it without a second edit here.
        from openemux.i18n import SUPPORTED_LOCALES

        expected = set(SUPPORTED_LOCALES)
        expected |= {locale.split("_", 1)[0] for locale in SUPPORTED_LOCALES}
        self.assertEqual(set(stage.LOCALE_KEEP), expected)


class RetroArchPruneTests(unittest.TestCase):
    def test_the_xmb_icon_themes_go(self):
        self.assertIn("assets/xmb", stage.RETROARCH_PRUNE_DIRS)

    def test_the_menu_driver_the_build_runs_is_not_pruned(self):
        # RetroArch 1.22.2 -- the vendored version -- writes menu_driver =
        # "ozone" into a config generated from its own defaults, and OpenEmux
        # never sets that key.
        for kept in ("assets", "assets/ozone", "assets/pkg", "assets/rgui"):
            self.assertNotIn(kept, stage.RETROARCH_PRUNE_DIRS)

    def test_no_prune_list_names_a_qt5_dll(self):
        # retroarch.exe names all four in its PE import table: Windows resolves
        # them before the process starts, so dropping them for the 20 MB stops
        # RetroArch launching at all.
        lists = stage.RETROARCH_PRUNE_DIRS + stage.PREFIX_PRUNE_DIRS
        for entry in lists:
            self.assertNotIn("qt5", entry.lower())


class Phase5GuardsTheFindingsTests(unittest.TestCase):
    def setUp(self):
        self.script = BUILD_SH.read_text(encoding="utf-8")

    def test_the_qt5_dlls_are_asserted_present(self):
        for dll in ("Qt5Core", "Qt5Gui", "Qt5Network", "Qt5Widgets"):
            self.assertIn(dll, self.script)

    def test_ozone_and_its_fonts_are_asserted_present(self):
        self.assertIn('test -d "$BUNDLE/vendors/RetroArch-Win64/assets/ozone"', self.script)
        self.assertIn("assets/pkg/osd-font.ttf", self.script)

    def test_the_prune_itself_is_asserted(self):
        for gone in (
            'test ! -d "$BUNDLE/share/terminfo"',
            'test ! -d "$BUNDLE/lib/terminfo"',
            'test ! -d "$BUNDLE/share/zoneinfo"',
            'test ! -d "$BUNDLE/vendors/RetroArch-Win64/assets/xmb"',
        ):
            self.assertIn(gone, self.script)

    def test_a_translated_locale_is_asserted_present(self):
        self.assertIn("share/locale/pt_BR/LC_MESSAGES/gtk40.mo", self.script)


if __name__ == "__main__":
    unittest.main()

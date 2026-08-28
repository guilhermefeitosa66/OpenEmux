"""Every user-facing string goes through the catalogue, and nothing else does.

Two directions, both of which had drifted (issue #232).

*Out:* four strings reached the user in English whatever the locale -- a
tooltip rewritten on click, a file-filter name, a core error sentence, and two
pt_BR values left byte-identical to English.

*In:* 34 keys survived the Preferences refactor with nothing left to show
them, and were carried -- and translated -- in all seven locales anyway: 238
entries of pure maintenance. Nothing was watching, which is why they lasted.
"""

import ast
import os
import unittest

from openemux.core import runtime_manager as runtime_manager_module
from openemux.i18n import LOCALE_TRANSLATIONS, SUPPORTED_LOCALES, tr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_ROOTS = ("src/openemux", "tools", "scripts", "tests")

#: Keys built at runtime, as the constant head of the f-string that builds
#: them. Every one is a closed enum walked in full by the code that renders it
#: -- the console list, the action list, the theme names -- so a key under one
#: of these prefixes is reachable even though no literal spells it out.
DYNAMIC_PREFIXES = (
    "artwork.provider.",
    "context.cover.",
    "context.label.",
    "import_mode.",
    "input.action.",
    "input.analog_dpad.mode.",
    "input.device.",
    "input.tuning.",
    "input.turbo.mode.",
    "prefs.provider.",
    "sort_order.",
    "theme.",
    "view_mode.",
    "welcome.",
)

#: The keys retired in issue #232. Listed by name rather than merely deleted:
#: the unreachable-key test below would pass with them present *and* absent if
#: the scan were ever weakened, and a name here is a claim that stays checked.
RETIRED = frozenset(
    """
    about.website bios.none console.gba.full console.nes.full console.snes.full
    context.rescan.all dialog.scan.all dialog.scan.console dialog.sync.all
    dialog.sync.console dialog.sync.current empty.indexed favorites.empty
    input.capture.keyboard_only settings.back.subtitle settings.back.title
    settings.bios.subtitle settings.input.subtitle settings.input.title
    settings.roms.subtitle settings.roms.title settings.shaders.subtitle
    settings.shaders.title settings.system.subtitle settings.system.title
    settings.title settings.ui.render_cartridge.subtitle
    settings.ui.render_cartridge.title settings.ui.subtitle settings.ui.title
    sidebar.library sidebar.settings status.idle status.running
    """.split()
)


def _string_literals():
    """Every string constant in the source, minus the catalogues themselves."""
    found = set()
    for root in SOURCE_ROOTS:
        for dirpath, dirs, files in os.walk(os.path.join(REPO_ROOT, root)):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", "locales"}]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as handle:
                    try:
                        tree = ast.parse(handle.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        found.add(node.value)
    return found


class NoKeyIsCarriedWithNothingToShowItTests(unittest.TestCase):
    """A key no code can reach is 7 translations nobody will ever read."""

    def test_every_english_key_is_reachable_from_the_source(self):
        literals = _string_literals()
        unreachable = sorted(
            key
            for key in LOCALE_TRANSLATIONS["en"]
            if key not in literals
            and not key.startswith(DYNAMIC_PREFIXES)
        )
        self.assertEqual(
            unreachable,
            [],
            "unreachable keys -- delete them, or add the prefix that builds "
            f"them to DYNAMIC_PREFIXES: {unreachable}",
        )

    def test_the_retired_keys_are_gone_from_every_locale(self):
        for locale in SUPPORTED_LOCALES:
            leftover = sorted(RETIRED & set(LOCALE_TRANSLATIONS[locale]))
            with self.subTest(locale=locale):
                self.assertEqual(leftover, [], f"{locale} still carries {leftover}")

    def test_a_dynamic_prefix_still_names_something(self):
        # A prefix left behind after its family is deleted silently exempts
        # whatever key happens to start with it.
        for prefix in DYNAMIC_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    any(k.startswith(prefix) for k in LOCALE_TRANSLATIONS["en"]),
                    f"{prefix} covers no key any more",
                )


class TheFourStringsThatBypassedTheCatalogueTests(unittest.TestCase):
    def test_the_pause_button_has_a_translated_resume(self):
        # The button is *built* with the translated "game_window.pause" and
        # was *rewritten* with an English literal, so the tooltip flipped to
        # English on the first click and stayed there for the session.
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertIn("game_window.resume", LOCALE_TRANSLATIONS[locale])

    def test_the_image_filter_name_is_translated(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertIn("dialog.filter.images", LOCALE_TRANSLATIONS[locale])

    def test_the_two_pt_br_dialog_titles_are_no_longer_english(self):
        for key in ("dialog.sync.title", "dialog.scan.title"):
            with self.subTest(key=key):
                self.assertNotEqual(tr("pt_BR", key), tr("en", key))


class CoreReturnsAKeyNotASentenceTests(unittest.TestCase):
    """``RuntimeManager`` has no locale, so it names the failure instead."""

    class _AlwaysRunning(runtime_manager_module.RuntimeManager):
        def __init__(self):  # noqa: D107 - deliberately skips the real setup
            pass

        def is_running(self):
            return True

    def test_launching_over_a_running_game_returns_the_key(self):
        ok, message = self._AlwaysRunning().launch("/roms/x.sfc", "SFC")

        self.assertFalse(ok)
        self.assertEqual(message, "toast.launch.already_running")

    def test_the_key_resolves_in_every_locale(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                text = tr(locale, "toast.launch.already_running")
                self.assertNotEqual(text, "toast.launch.already_running")

    def test_free_text_from_the_launcher_survives_translation(self):
        # The UI runs every failure through tr(), which must be the identity
        # for a sentence that is not a key -- otherwise the launcher's own
        # messages ("Could not start the game: ...") would come out as
        # themselves-as-a-key and read like a bug report.
        sentence = "Could not start the game: no such file"
        self.assertEqual(tr("pt_BR", sentence), sentence)


if __name__ == "__main__":
    unittest.main()

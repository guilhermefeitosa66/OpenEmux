"""The console table, and the resolver every other subsystem calls (issue #245).

`systems.py` had no test file at all, while `resolve_system_id()` is called by
the scanner, the playlist manager, the launcher, the cover sync, the BIOS
catalog and the UI -- so a typo in the table, a duplicate id or an alias that
resolves to nothing surfaces as a console that quietly has no games rather
than as an error.

Two kinds of test here: the accessors (behaviour) and the table itself
(invariants every entry must hold, checked entry by entry so a new console
cannot be added half-filled).
"""

import unittest

from openemux.core.platform import CORE_SUFFIX, normalize_core_filename
from openemux.core.systems import (
    ALIAS_TO_ID,
    LEGACY_ID_MAP,
    SYSTEM_IDS,
    SYSTEMS,
    SYSTEMS_BY_ID,
    get_icon_name,
    get_runtime_core_candidates,
    get_supported_extensions,
    get_system,
    get_system_display_name,
    get_thumbnail_system,
    resolve_system_id,
)

DEFAULT_ICON = "applications-games-symbolic"


class ResolveSystemIdTests(unittest.TestCase):
    def test_a_canonical_id_resolves_to_itself(self):
        self.assertEqual(resolve_system_id("SFC"), "SFC")

    def test_the_familiar_western_names_resolve_to_the_canonical_ids(self):
        # The rename users notice: the library is keyed by the Japanese ids.
        self.assertEqual(resolve_system_id("NES"), "FC")
        self.assertEqual(resolve_system_id("SNES"), "SFC")

    def test_case_and_surrounding_space_do_not_matter(self):
        # Config files and folder names are typed by hand.
        self.assertEqual(resolve_system_id("  sfc "), "SFC")
        self.assertEqual(resolve_system_id("snes"), "SFC")

    def test_none_stays_none(self):
        # "no console" is a real state in the UI (the Favourites view), and it
        # must not become the string "NONE".
        self.assertIsNone(resolve_system_id(None))

    def test_an_unknown_value_comes_back_upper_cased_rather_than_dropped(self):
        # Deliberate: a console the table does not know still keys a folder
        # consistently, instead of collapsing to None and losing the ROMs.
        self.assertEqual(resolve_system_id("dreamcast"), "DREAMCAST")

    def test_every_alias_in_the_table_resolves_to_a_real_system(self):
        for alias, system_id in ALIAS_TO_ID.items():
            with self.subTest(alias=alias):
                self.assertIn(system_id, SYSTEMS_BY_ID)
                self.assertEqual(resolve_system_id(alias), system_id)

    def test_every_legacy_id_resolves_to_a_real_system(self):
        for legacy, target in LEGACY_ID_MAP.items():
            with self.subTest(legacy=legacy):
                self.assertIn(target, SYSTEMS_BY_ID)
                self.assertEqual(resolve_system_id(legacy), target)


class AccessorTests(unittest.TestCase):
    def test_the_accessors_take_an_alias_as_readily_as_an_id(self):
        self.assertEqual(get_system_display_name("NES"), get_system_display_name("FC"))
        self.assertEqual(get_supported_extensions("SNES"), get_supported_extensions("SFC"))

    def test_an_unknown_console_gets_answers_it_can_live_with(self):
        # Every one of these is read straight into the UI or a path, so None
        # would be a crash and an empty list is the honest answer.
        self.assertIsNone(get_system("DREAMCAST"))
        self.assertEqual(get_system_display_name("dreamcast"), "DREAMCAST")
        self.assertEqual(get_supported_extensions("DREAMCAST"), [])
        self.assertEqual(get_runtime_core_candidates("DREAMCAST"), [])
        self.assertIsNone(get_thumbnail_system("DREAMCAST"))
        self.assertEqual(get_icon_name("DREAMCAST"), DEFAULT_ICON)

    def test_extensions_come_back_lower_cased(self):
        # The scanner compares against a lower-cased suffix, so an entry typed
        # ".BIN" would silently match nothing.
        for system_id in SYSTEM_IDS:
            with self.subTest(system=system_id):
                extensions = get_supported_extensions(system_id)
                self.assertEqual(extensions, [ext.lower() for ext in extensions])

    def test_core_candidates_carry_this_platform_s_extension(self):
        # The table spells every candidate ".so"; this is the only reader that
        # corrects it, and on Windows the ".so" name resolves to nothing.
        for system_id in SYSTEM_IDS:
            for name in get_runtime_core_candidates(system_id):
                with self.subTest(system=system_id, core=name):
                    self.assertTrue(name.endswith(CORE_SUFFIX))

    def test_the_correction_is_the_shared_one(self):
        candidates = get_runtime_core_candidates("SFC")
        raw = SYSTEMS_BY_ID["SFC"]["runtime_core_candidates"]
        self.assertEqual(candidates, [normalize_core_filename(name) for name in raw])

    def test_the_accessors_hand_back_copies_the_caller_cannot_corrupt(self):
        # get_system returns the live dict, so the lists must not be shared
        # with what a caller may mutate.
        extensions = get_supported_extensions("SFC")
        extensions.append(".bogus")
        self.assertNotIn(".bogus", get_supported_extensions("SFC"))


class TheTableItselfTests(unittest.TestCase):
    """Invariants a new console entry has to hold, checked one by one."""

    def test_there_are_systems(self):
        self.assertGreater(len(SYSTEMS), 20)

    def test_ids_are_unique(self):
        self.assertEqual(len(SYSTEM_IDS), len(set(SYSTEM_IDS)))

    def test_every_entry_carries_every_field_the_app_reads(self):
        for system in SYSTEMS:
            with self.subTest(system=system.get("id")):
                for field in (
                    "id",
                    "display_name",
                    "aliases",
                    "extensions",
                    "thumbnail_system",
                    "runtime_core_candidates",
                    "icon_name",
                ):
                    self.assertIn(field, system)

    def test_ids_are_upper_case_and_free_of_path_separators(self):
        # An id is a directory name under ~/games/roms and ~/.openemux.
        for system_id in SYSTEM_IDS:
            with self.subTest(system=system_id):
                self.assertEqual(system_id, system_id.upper())
                self.assertNotIn("/", system_id)
                self.assertNotIn("\\", system_id)
                self.assertTrue(system_id.strip())

    def test_display_names_are_unique_and_non_empty(self):
        names = [system["display_name"] for system in SYSTEMS]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertTrue(name.strip())

    def test_every_extension_is_a_dotted_suffix(self):
        for system in SYSTEMS:
            for ext in system["extensions"]:
                with self.subTest(system=system["id"], ext=ext):
                    self.assertTrue(ext.startswith("."), "an extension needs its dot")
                    self.assertNotIn("*", ext)

    def test_no_system_lists_the_same_extension_twice(self):
        for system in SYSTEMS:
            with self.subTest(system=system["id"]):
                extensions = system["extensions"]
                self.assertEqual(len(extensions), len(set(extensions)))

    def test_no_alias_collides_with_another_system_s_id(self):
        # An alias that shadows a real id makes that console unreachable.
        for system in SYSTEMS:
            for alias in system["aliases"]:
                with self.subTest(system=system["id"], alias=alias):
                    other = SYSTEMS_BY_ID.get(str(alias).upper())
                    if other is not None:
                        self.assertIs(other, system)

    def test_no_alias_is_claimed_by_two_systems(self):
        # ALIAS_TO_ID is built by overwriting, so a second claim silently wins
        # and one console becomes unreachable by its own name.
        claimed = {}
        for system in SYSTEMS:
            for alias in system["aliases"]:
                key = str(alias).upper()
                with self.subTest(alias=alias):
                    self.assertEqual(
                        claimed.get(key, system["id"]),
                        system["id"],
                        f"{alias} is claimed by {claimed.get(key)} too",
                    )
                claimed[key] = system["id"]

    def test_no_system_lists_two_spellings_of_the_same_alias(self):
        # resolve_system_id() upper-cases before the lookup, so ["nes", "NES"]
        # is one alias written twice -- dead weight that reads like two.
        for system in SYSTEMS:
            with self.subTest(system=system["id"]):
                folded = [str(alias).upper() for alias in system["aliases"]]
                self.assertEqual(len(folded), len(set(folded)))

    def test_no_alias_merely_restates_its_own_id(self):
        # ALIAS_TO_ID already maps every id to itself, so such an entry is
        # dead weight that reads as though the console needed it.
        for system in SYSTEMS:
            for alias in system["aliases"]:
                with self.subTest(system=system["id"], alias=alias):
                    self.assertNotEqual(str(alias).upper(), system["id"])

    def test_the_ids_users_know_the_consoles_by_still_resolve(self):
        # The three renames are the ones people type: whatever the table does
        # internally, these have to keep working.
        self.assertEqual(resolve_system_id("NES"), "FC")
        self.assertEqual(resolve_system_id("SNES"), "SFC")
        self.assertEqual(resolve_system_id("GBA"), "GBA")

    def test_every_core_candidate_looks_like_a_libretro_core(self):
        for system in SYSTEMS:
            for name in system["runtime_core_candidates"]:
                with self.subTest(system=system["id"], core=name):
                    self.assertTrue(name.endswith("_libretro.so"), "the table spells .so")

    def test_thumbnail_systems_are_unique_where_they_are_set(self):
        # Two consoles pointing at one libretro thumbnail directory would make
        # each other's covers appear in the wrong library.
        seen = {}
        for system in SYSTEMS:
            name = system["thumbnail_system"]
            if not name:
                continue
            with self.subTest(system=system["id"], thumbnail=name):
                self.assertNotIn(name, seen, f"also used by {seen.get(name)}")
            seen[name] = system["id"]

    def test_icon_names_are_symbolic(self):
        for system in SYSTEMS:
            with self.subTest(system=system["id"]):
                self.assertTrue(system["icon_name"].endswith("-symbolic"))


if __name__ == "__main__":
    unittest.main()

"""The BIOS requirement table and its accessors (issue #245).

`bios_catalog.py` had no test file. It is static data plus deep-copy
accessors, and it decides two user-visible things: what the "BIOS" page
reports as missing, and whether a launch is blocked before RetroArch is even
started. A malformed entry there is a console that either demands a file that
does not exist or never asks for one it needs.
"""

import unittest

from openemux.core.bios_catalog import (
    CONSOLE_BIOS_REQUIREMENTS,
    consoles_with_bios_entries,
    get_console_bios_requirements,
    get_console_bios_union,
    get_console_candidate_cores,
    get_optional_for_core,
    get_required_for_core,
    has_any_bios_requirement,
)
from openemux.core.platform import normalize_core_filename
from openemux.core.systems import SYSTEMS_BY_ID, get_runtime_core_candidates


def _all_entries():
    for system_id, data in CONSOLE_BIOS_REQUIREMENTS.items():
        for kind in ("required", "optional"):
            for entry in data.get(kind, []):
                yield system_id, kind, entry


class LookupTests(unittest.TestCase):
    def test_a_console_with_no_entry_gets_empty_lists_not_none(self):
        # The BIOS page iterates the result for every console it lists.
        self.assertEqual(
            get_console_bios_requirements("GB"), {"required": [], "optional": []}
        )
        self.assertFalse(has_any_bios_requirement("GB"))

    def test_an_unknown_console_is_answered_the_same_way(self):
        self.assertEqual(
            get_console_bios_requirements("DREAMCAST"), {"required": [], "optional": []}
        )
        self.assertFalse(has_any_bios_requirement("DREAMCAST"))

    def test_lookups_go_through_the_system_resolver(self):
        # "NES" is FC; a caller handing over the familiar name must not get an
        # empty answer for a console that does have requirements.
        self.assertEqual(
            get_console_bios_requirements("nes"), get_console_bios_requirements("FC")
        )

    def test_a_known_console_reports_its_required_file(self):
        required = get_console_bios_requirements("LYNX")["required"]
        self.assertEqual([entry["file"] for entry in required], ["lynxboot.img"])
        self.assertTrue(has_any_bios_requirement("LYNX"))

    def test_the_caller_gets_a_copy_it_cannot_corrupt(self):
        # The table is module state shared by the BIOS page, the launcher and
        # the pre-launch check; a caller mutating it would poison all three.
        first = get_console_bios_requirements("LYNX")
        first["required"][0]["file"] = "tampered"
        self.assertEqual(
            get_console_bios_requirements("LYNX")["required"][0]["file"],
            "lynxboot.img",
        )

    def test_the_union_is_a_copy_too(self):
        union = get_console_bios_union("LYNX")
        union["required"].clear()
        self.assertTrue(get_console_bios_union("LYNX")["required"])

    def test_the_union_drops_entries_that_say_the_same_thing_twice(self):
        for system_id in CONSOLE_BIOS_REQUIREMENTS:
            with self.subTest(system=system_id):
                union = get_console_bios_union(system_id)
                requirements = get_console_bios_requirements(system_id)
                for kind in ("required", "optional"):
                    self.assertLessEqual(len(union[kind]), len(requirements[kind]))

    def test_consoles_with_entries_are_listed_sorted_and_all_real(self):
        listed = consoles_with_bios_entries()
        self.assertEqual(listed, sorted(listed))
        for system_id in listed:
            with self.subTest(system=system_id):
                self.assertTrue(has_any_bios_requirement(system_id))

    def test_a_console_whose_lists_are_both_empty_is_not_listed(self):
        empty = [
            system_id
            for system_id, data in CONSOLE_BIOS_REQUIREMENTS.items()
            if not data.get("required") and not data.get("optional")
        ]
        for system_id in empty:
            with self.subTest(system=system_id):
                self.assertNotIn(system_id, consoles_with_bios_entries())


class PerCoreFilteringTests(unittest.TestCase):
    """Which files *this* core needs -- the check that gates a launch."""

    def test_an_entry_with_no_cores_applies_to_every_core(self):
        # LYNX names no core, so whatever is resolved must still be asked for.
        self.assertEqual(
            [entry["file"] for entry in get_required_for_core("LYNX", "anything.so")],
            ["lynxboot.img"],
        )

    def test_an_entry_naming_cores_applies_only_to_those(self):
        # FDS needs disksys.rom for nestopia and fceumm, and for nothing else.
        needed = get_required_for_core("FDS", "nestopia_libretro.so")
        self.assertEqual([entry["file"] for entry in needed], ["disksys.rom"])
        self.assertEqual(get_required_for_core("FDS", "mesen_libretro.so"), [])

    def test_the_core_extension_does_not_decide_the_match(self):
        # The table spells every core ".so"; on Windows the resolved name is
        # ".dll", and duplicating ~20 core lists per platform is how one copy
        # drifts (issue #118).
        by_so = get_required_for_core("FDS", "nestopia_libretro.so")
        by_dll = get_required_for_core("FDS", "nestopia_libretro.dll")
        self.assertEqual(by_so, by_dll)
        self.assertTrue(by_so)

    def test_optional_files_are_filtered_by_core_the_same_way(self):
        optional = get_optional_for_core("FDS", "fceumm_libretro.so")
        self.assertEqual([entry["file"] for entry in optional], ["gamegenie.nes"])
        self.assertEqual(get_optional_for_core("FDS", "nestopia_libretro.so"), [])

    def test_a_core_that_needs_nothing_blocks_no_launch(self):
        self.assertEqual(get_required_for_core("GG", "gearsystem_libretro.so"), [])

    def test_candidate_cores_come_from_the_system_table(self):
        for system_id in CONSOLE_BIOS_REQUIREMENTS:
            with self.subTest(system=system_id):
                self.assertEqual(
                    get_console_candidate_cores(system_id),
                    get_runtime_core_candidates(system_id),
                )


class TheTableItselfTests(unittest.TestCase):
    def test_every_console_in_the_table_is_a_real_system(self):
        for system_id in CONSOLE_BIOS_REQUIREMENTS:
            with self.subTest(system=system_id):
                self.assertIn(system_id, SYSTEMS_BY_ID)

    def test_every_console_declares_both_lists(self):
        for system_id, data in CONSOLE_BIOS_REQUIREMENTS.items():
            with self.subTest(system=system_id):
                self.assertIn("required", data)
                self.assertIn("optional", data)

    def test_every_entry_is_one_shape_or_the_other(self):
        # "file" or "any_of", never both and never neither: _entry_key reads
        # "file" first, so an entry carrying both silently loses its any_of.
        for system_id, kind, entry in _all_entries():
            with self.subTest(system=system_id, kind=kind, entry=entry):
                self.assertEqual(
                    ("file" in entry) ^ ("any_of" in entry),
                    True,
                    "an entry needs exactly one of file/any_of",
                )

    def test_no_entry_carries_an_unknown_key(self):
        for system_id, kind, entry in _all_entries():
            with self.subTest(system=system_id, kind=kind, entry=entry):
                self.assertLessEqual(set(entry), {"file", "any_of", "cores"})

    def test_filenames_are_plain_names_not_paths(self):
        # They are joined onto ~/.openemux/bios/<console>/ and compared against
        # a directory listing.
        for system_id, kind, entry in _all_entries():
            for name in [entry["file"]] if "file" in entry else entry["any_of"]:
                with self.subTest(system=system_id, kind=kind, name=name):
                    self.assertTrue(name.strip())
                    self.assertNotIn("/", name)
                    self.assertNotIn("\\", name)

    def test_an_any_of_entry_offers_more_than_one_file(self):
        for system_id, kind, entry in _all_entries():
            if "any_of" not in entry:
                continue
            with self.subTest(system=system_id, kind=kind):
                self.assertGreater(len(entry["any_of"]), 1)

    def test_every_named_core_is_one_the_console_can_actually_resolve(self):
        # A core named here that the system table never offers is a
        # requirement that can never apply -- and reads as though it does.
        for system_id, kind, entry in _all_entries():
            candidates = {
                normalize_core_filename(name)
                for name in get_runtime_core_candidates(system_id)
            }
            for core in entry.get("cores", []):
                with self.subTest(system=system_id, kind=kind, core=core):
                    self.assertIn(normalize_core_filename(core), candidates)

    @staticmethod
    def _names(data, kind):
        found = set()
        for entry in data.get(kind, []):
            found.update([entry["file"]] if "file" in entry else entry["any_of"])
        return found

    def test_no_file_is_both_required_and_optional_for_one_console(self):
        # The BIOS page renders the two lists separately, so a file in both
        # shows as missing and optional at once.
        for system_id, data in CONSOLE_BIOS_REQUIREMENTS.items():
            with self.subTest(system=system_id):
                self.assertEqual(
                    self._names(data, "required") & self._names(data, "optional"),
                    set(),
                )


if __name__ == "__main__":
    unittest.main()

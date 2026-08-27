"""Platform skips have to go through one place, and say what they mean.

The suite runs on Linux and on Windows (issue #118), so some tests must skip on
one of them. That is fine -- what is not fine is a skip nobody can read. A bare
``skipIf(sys.platform == "win32")`` scattered through the suite makes a platform
truth indistinguishable from a bug nobody got around to fixing, and that is how
a port quietly stops being tested: the number of skips creeps up and no one can
say which of them should have been fixed instead.
"""

import re
import unittest
from pathlib import Path

from tests.platform_marks import IS_LINUX, IS_WINDOWS, linux_only, posix_only

TESTS_DIR = Path(__file__).resolve().parent

#: A skip decided from the platform, written by hand rather than imported.
_RAW_PLATFORM_SKIP = re.compile(
    r"skip(?:If|Unless)\s*\(\s*(?:sys\.platform|os\.name|platform\.system)"
)

#: A call to one of the marks, with whatever reason it was given.
_MARK_CALL = re.compile(r"@(posix_only|linux_only)\(\s*[\"\']([^\"\']*)")


class MarksAreCentralisedTests(unittest.TestCase):
    def test_no_test_file_rolls_its_own_platform_skip(self):
        offenders = sorted(
            path.name
            for path in TESTS_DIR.glob("test_*.py")
            if path.name != Path(__file__).name
            and _RAW_PLATFORM_SKIP.search(path.read_text(encoding="utf-8"))
        )
        self.assertEqual(
            offenders, [],
            "use tests.platform_marks so the reason is stated and greppable",
        )

    def test_platform_marks_is_the_only_place_that_asks(self):
        marks = (TESTS_DIR / "platform_marks.py").read_text(encoding="utf-8")
        self.assertIn("sys.platform", marks)


class ReasonsAreStatedTests(unittest.TestCase):
    def test_a_posix_skip_names_the_posix_behaviour(self):
        decorator = posix_only("0o600 on the token file")
        case = decorator(unittest.TestCase)
        if IS_WINDOWS:
            self.assertIn("POSIX-only: 0o600 on the token file",
                          case.__unittest_skip_why__)
        else:
            self.assertFalse(getattr(case, "__unittest_skip__", False))

    def test_a_linux_skip_names_the_linux_behaviour(self):
        decorator = linux_only("struct input_event is the kernel ABI")
        case = decorator(unittest.TestCase)
        if IS_LINUX:
            self.assertFalse(getattr(case, "__unittest_skip__", False))
        else:
            self.assertIn("Linux-only: struct input_event is the kernel ABI",
                          case.__unittest_skip_why__)

    def test_every_use_in_the_suite_gives_a_reason(self):
        # The rule the module states, enforced rather than trusted: a mark
        # whose reason is empty is the bare "skipped on Windows" this exists to
        # prevent, and it would read as a stated reason in a diff.
        empty = []
        for path in TESTS_DIR.glob("test_*.py"):
            if path.name == Path(__file__).name:
                continue
            for mark, reason in _MARK_CALL.findall(path.read_text(encoding="utf-8")):
                if not reason.strip():
                    empty.append(f"{path.name}: {mark}")
        self.assertEqual(empty, [])

    def test_the_suite_actually_uses_them(self):
        # If this ever finds nothing, either the marks were removed or the
        # tests that need them were, and the Windows job is green for the
        # wrong reason.
        users = [
            path.name
            for path in TESTS_DIR.glob("test_*.py")
            if path.name != Path(__file__).name
            and _MARK_CALL.search(path.read_text(encoding="utf-8"))
        ]
        self.assertTrue(users, "nothing in the suite is marked platform-specific")

if __name__ == "__main__":
    unittest.main()

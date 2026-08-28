"""Marks for tests whose subject is the platform, not OpenEmux.

The suite runs on Linux and, since issue #118, on Windows too. A handful of
tests assert things that only exist on one of them: POSIX permission bits, the
FHS install prefixes, the evdev kernel ABI, a filename holding bytes that are
not valid UTF-8. Skipping those on Windows is not lowering the bar -- the
behaviour they describe *is* a Linux behaviour, and asserting it elsewhere
would only be asserting that Windows is Windows.

Mark the narrowest thing that fits -- a method, not its class, unless the whole
class is about the platform -- and say in the reason which platform behaviour
is at stake. A bare "skipped on Windows" leaves the next reader unable to tell
a platform truth from a bug nobody got around to fixing.
"""

import sys
import unittest

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def posix_only(reason):
    """Skip on Windows. ``reason`` names the POSIX behaviour under test."""
    return unittest.skipIf(IS_WINDOWS, f"POSIX-only: {reason}")


def linux_only(reason):
    """Skip anywhere but Linux: the kernel ABI, /proc, the FHS, AppImages."""
    return unittest.skipUnless(IS_LINUX, f"Linux-only: {reason}")

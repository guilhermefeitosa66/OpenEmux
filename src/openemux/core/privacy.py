"""Keep the user's name out of what they are asked to share.

A home directory is named after its user -- ``/home/guilherme``,
``C:\\Users\\Guilherme`` -- and nearly every path the app logs starts with
one. Many people are not comfortable posting their name in a public bug
report, so the log and the report spell the home directory ``~`` instead.

Only a whole home directory is replaced: ``/home/guilherme2`` is somebody
else's, and stays as it is.
"""

import functools
import re
from pathlib import Path

from openemux.core.paths import get_real_home

HOME_MARKER = "~"


@functools.lru_cache(maxsize=8)
def _pattern(homes):
    # Longest first, so a home nested in another (a Flatpak's private one
    # lives under the real one) is replaced whole. The lookahead stops a
    # prefix match inside a longer name; both separators, for Windows paths
    # written either way.
    alternatives = "|".join(re.escape(home) for home in sorted(homes, key=len, reverse=True))
    return re.compile(rf"(?:{alternatives})(?=$|[\\/\s\"'`),;:\]}}])")


def _homes():
    homes = set()
    for home in (Path.home(), get_real_home()):
        text = str(home).rstrip("\\/")
        # A home of "/" or "" would rewrite every path on the machine.
        if len(text) > 1:
            homes.add(text)
            homes.add(text.replace("\\", "/"))
    return tuple(sorted(homes))


def redact_home(text):
    """``text`` with every whole home directory written as ``~``."""
    if not text:
        return text
    homes = _homes()
    if not homes:
        return text
    return _pattern(homes).sub(HOME_MARKER, text)


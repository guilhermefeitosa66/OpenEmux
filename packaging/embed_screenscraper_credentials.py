#!/usr/bin/env python3
"""Bake the project's ScreenScraper developer credentials into a build.

Run this during official packaging (never committed to git) to rewrite the
empty ``_EMBEDDED_BLOB`` placeholder in
``src/openemux/core/embedded_credentials.py`` with the obfuscated project
developer credential, read from environment variables (CI secrets):

    SCREENSCRAPER_DEVID       the developer account id
    SCREENSCRAPER_DEVPASSWORD the developer account password

Usage (from the repo root, inside the build environment):

    SCREENSCRAPER_DEVID=... SCREENSCRAPER_DEVPASSWORD=... \\
        python3 packaging/embed_screenscraper_credentials.py [path/to/embedded_credentials.py]

If either variable is missing/empty the script is a no-op and exits 0, so local
and untrusted builds simply ship no embedded credential (ScreenScraper stays
opt-in). The rewrite is idempotent and only ever replaces the ``_EMBEDDED_BLOB``
assignment line.
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "src" / "openemux" / "core" / "embedded_credentials.py"

# Reuse the exact obfuscation the runtime expects, without importing GTK et al.
sys.path.insert(0, str(REPO_ROOT / "src"))
from openemux.core.embedded_credentials import obfuscate  # noqa: E402

_BLOB_LINE = re.compile(r'^_EMBEDDED_BLOB = ".*"$', re.MULTILINE)


def main(argv):
    devid = (os.environ.get("SCREENSCRAPER_DEVID") or "").strip()
    devpassword = (os.environ.get("SCREENSCRAPER_DEVPASSWORD") or "").strip()
    if not (devid and devpassword):
        print("embed_screenscraper_credentials: no credentials in env; leaving build unmodified")
        return 0

    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    if not target.exists():
        print(f"embed_screenscraper_credentials: target not found: {target}", file=sys.stderr)
        return 1

    blob = obfuscate(devid, devpassword)
    source = target.read_text(encoding="utf-8")
    new_source, count = _BLOB_LINE.subn(f'_EMBEDDED_BLOB = "{blob}"', source)
    if count != 1:
        print(
            f"embed_screenscraper_credentials: expected exactly one _EMBEDDED_BLOB line, "
            f"found {count}",
            file=sys.stderr,
        )
        return 1

    target.write_text(new_source, encoding="utf-8")
    print(f"embed_screenscraper_credentials: embedded developer credential into {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

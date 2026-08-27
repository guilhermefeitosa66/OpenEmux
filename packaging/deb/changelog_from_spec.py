#!/usr/bin/env python3
"""Render the Debian changelog from the RPM spec's ``%changelog``.

The ``.deb`` shipped no changelog at all -- lintian's
``debian-changelog-file-missing`` -- while the same release history was already
written down, and kept up to date on every release, in
``packaging/rpm/openemux.spec`` (issue #256). Generating one from the other
keeps a single source: a release that documents itself in the spec documents
itself in the ``.deb``.

Usage:

    python3 packaging/deb/changelog_from_spec.py > changelog

The output is the plain text; ``deb/build.sh`` gzips it into
``/usr/share/doc/openemux/changelog.Debian.gz``.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging/rpm/openemux.spec"

#: `* Wed Aug 19 2026 Guilherme Feitoza <someone@example.com> - 1.11.3-1`
HEADER = re.compile(
    r"^\* (?P<weekday>\w{3}) (?P<month>\w{3}) (?P<day>\d{2}) (?P<year>\d{4}) "
    r"(?P<maintainer>.+?) - (?P<version>[^-\s]+)-(?P<release>\d+)$"
)


def entries():
    """(version, rfc822 date, maintainer, [bullets]) per spec entry."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    current = None
    for line in lines[lines.index("%changelog") + 1 :]:
        match = HEADER.match(line)
        if match:
            if current:
                yield current
            fields = match.groupdict()
            # Debian wants RFC 822. The spec records the day only, so the time
            # is fixed rather than invented -- what matters here is the date.
            date = (
                f"{fields['weekday']}, {fields['day']} {fields['month']} "
                f"{fields['year']} 12:00:00 +0000"
            )
            current = (fields["version"], date, fields["maintainer"], [])
            continue
        if current is None:
            continue
        if line.startswith("- "):
            current[3].append(line[2:].strip())
        elif line.strip() and current[3]:
            # A wrapped bullet: the spec wraps long ones with a leading indent.
            current[3][-1] += " " + line.strip()
    if current:
        yield current


def render():
    blocks = []
    for version, date, maintainer, bullets in entries():
        body = "\n".join(f"  * {bullet}" for bullet in bullets) or "  * No changes recorded."
        blocks.append(
            f"openemux ({version}) stable; urgency=medium\n"
            f"\n{body}\n\n"
            f" -- {maintainer}  {date}\n"
        )
    if not blocks:
        raise SystemExit("changelog_from_spec: the spec has no %changelog entries")
    return "\n".join(blocks)


if __name__ == "__main__":
    sys.stdout.write(render())

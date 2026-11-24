#!/usr/bin/env python3
"""Writes the release AUR recipes for one OpenEmux release (issue #991).

    python3 packaging/aur/release.py v1.24.0 --out build/aur/release [--pkgrel N]

The tracked recipes under packaging/aur/{openemux,openemux-bin,openemux-appimage}/
are templates: `pkgver=0.0.0`, `pkgrel=1` and `sha256sums=('SKIP')`. This fills
them in for a published release and writes `<out>/<package>/PKGBUILD`:

* `openemux-bin` and `openemux-appimage` take their checksum from the release's
  own SHA256SUMS -- the one `make checksums` wrote over the very files they
  download. A release without the file a recipe needs is an error, not a
  recipe pointing at nothing.
* `openemux` builds from GitHub's archive of the tag, which no SHA256SUMS
  covers, so it is downloaded here and its checksum pinned.

`.SRCINFO` needs makepkg, so packaging/aur/release.sh writes it, in the Arch
image. Standard library only: this runs on the host, in that image and in CI.
"""

import argparse
import hashlib
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "guilhermefeitosa66/OpenEmux"
RECIPES = Path(__file__).resolve().parent
PACKAGES = ("openemux", "openemux-bin", "openemux-appimage")
TIMEOUT = 120


class ReleaseError(Exception):
    """Anything that stops a recipe from being written, said plainly."""


def tag_to_version(tag):
    """`v1.24.0` -> `1.24.0`; anything else is not a release tag of ours."""
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if match is None:
        raise ReleaseError(f"'{tag}' is not a release tag (expected vX.Y.Z)")
    return match.group(1)


def parse_sha256sums(text):
    """The `<sha256>  <file>` lines of SHA256SUMS, as {file: sha256}."""
    sums = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](\S.*)", line.strip())
        if match is None:
            raise ReleaseError(f"SHA256SUMS line {number} is malformed: {line!r}")
        sums[match.group(2)] = match.group(1)
    return sums


def release_assets(version, sums):
    """The two release files the -bin and -appimage recipes download.

    Returns {"pkg": (file, sha256, srcrel), "appimage": (file, sha256)}. The
    Arch package's file name carries the pkgrel it was built with, which the
    -bin recipe has to repeat to find it.
    """
    pattern = re.compile(rf"openemux-{re.escape(version)}-(\d+)-x86_64\.pkg\.tar\.zst")
    packages = sorted(name for name in sums if pattern.fullmatch(name))
    if len(packages) != 1:
        raise ReleaseError(
            f"expected one x86_64 Arch package for {version} in SHA256SUMS, "
            f"found {len(packages)}"
        )
    pkg = packages[0]
    appimage = f"OpenEmux-{version}-x86_64.AppImage"
    if appimage not in sums:
        raise ReleaseError(f"{appimage} is not in the release's SHA256SUMS")
    return {
        "pkg": (pkg, sums[pkg], pattern.fullmatch(pkg).group(1)),
        "appimage": (appimage, sums[appimage]),
    }


def _replace_line(text, name, value, recipe):
    """Rewrites the one top-level `name=...` line; it must exist exactly once."""
    pattern = re.compile(rf"(?m)^{re.escape(name)}=.*$")
    if len(pattern.findall(text)) != 1:
        raise ReleaseError(f"{recipe}: expected exactly one '{name}=' line")
    return pattern.sub(lambda _m: f"{name}={value}", text)


def render(template, recipe, values):
    """The template with each `name=` line in `values` rewritten."""
    for name, value in values.items():
        template = _replace_line(template, name, value, recipe)
    return template


def fetch(url):
    """The bytes at `url`, or a ReleaseError saying which download failed."""
    request = urllib.request.Request(url, headers={"User-Agent": "openemux-aur-release"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as error:
        raise ReleaseError(f"could not download {url}: {error}") from error


def generate(tag, out, pkgrel=1, fetch=fetch, recipes=RECIPES):
    """Writes the three PKGBUILDs for `tag` under `out`; returns their paths."""
    version = tag_to_version(tag)
    if pkgrel < 1:
        raise ReleaseError(f"pkgrel must be 1 or more, not {pkgrel}")
    base = f"https://github.com/{REPO}"
    sums_text = fetch(f"{base}/releases/download/{tag}/SHA256SUMS").decode("utf-8")
    assets = release_assets(version, parse_sha256sums(sums_text))
    archive = hashlib.sha256(fetch(f"{base}/archive/refs/tags/{tag}.tar.gz")).hexdigest()

    common = {"pkgver": version, "pkgrel": str(pkgrel)}
    values = {
        "openemux": {**common, "sha256sums": f"('{archive}')"},
        "openemux-bin": {
            **common,
            "_srcrel": assets["pkg"][2],
            "sha256sums": f"('{assets['pkg'][1]}')",
        },
        "openemux-appimage": {**common, "sha256sums": f"('{assets['appimage'][1]}')"},
    }
    written = []
    for package in PACKAGES:
        template = (Path(recipes) / package / "PKGBUILD").read_text(encoding="utf-8")
        target = Path(out) / package / "PKGBUILD"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(template, package, values[package]), encoding="utf-8")
        written.append(target)
    return written


def main(argv=None, fetch=fetch):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the release tag, e.g. v1.24.0")
    parser.add_argument("--out", required=True, help="where <package>/PKGBUILD go")
    parser.add_argument("--pkgrel", type=int, default=1,
                        help="1 for a new release; more for a recipe fix on the same one")
    args = parser.parse_args(argv)
    try:
        written = generate(args.tag, args.out, args.pkgrel, fetch=fetch)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover -- the command line itself
    sys.exit(main())

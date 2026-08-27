#!/usr/bin/env python3
"""Fetch the MINGW64 runtime out of the MSYS2 repository, from Linux.

The Windows bundle needs GTK 4, libadwaita, Python and the GObject bindings,
and MSYS2 is the only place all four exist as one coherent, ABI-compatible set
for Windows. Everything else about the build runs on Linux in Docker, so this
module does what pacman would do -- resolve a dependency closure, download it,
check it -- without needing Windows or pacman anywhere.

Two modes:

``--update``
    Read the live repository index and rewrite ``packages.lock``. Run this to
    move the bundle to newer upstream packages; the diff is the review.

(default)
    Read ``packages.lock``, download exactly what it names, verify every file
    against the recorded SHA-256, and extract into a staging prefix. Never
    touches the network index, so two builds of the same commit install the
    same bytes.

The lock is what makes the build reproducible. MSYS2 is a rolling repository:
resolving against the live index at build time would mean the artifact quietly
changes from one afternoon to the next, and a GTK regression would be
impossible to bisect. The hashes come from the repository's own signed index
rather than from us -- see the note on trust in ``update_lock``.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / "packages.lock"

REPO_URL = "https://repo.msys2.org/mingw/mingw64"
DB_NAME = "mingw64.db"

#: What the bundle actually needs, before dependencies. Everything else in the
#: lock is pulled in by these.
#:
#: Deliberately absent, and present in ``make install-sys-deps-windows``:
#: python-coverage, make, git and 7zip are development tools. A user running
#: the installer never needs them, and each one is tens of megabytes.
ROOT_PACKAGES = [
    "mingw-w64-x86_64-gtk4",
    "mingw-w64-x86_64-libadwaita",
    "mingw-w64-x86_64-gobject-introspection-runtime",
    "mingw-w64-x86_64-librsvg",
    "mingw-w64-x86_64-adwaita-icon-theme",
    "mingw-w64-x86_64-hicolor-icon-theme",
    "mingw-w64-x86_64-gsettings-desktop-schemas",
    "mingw-w64-x86_64-shared-mime-info",
    "mingw-w64-x86_64-webp-pixbuf-loader",
    "mingw-w64-x86_64-python",
    "mingw-w64-x86_64-python-gobject",
    "mingw-w64-x86_64-python-cairo",
    "mingw-w64-x86_64-python-yaml",
    "mingw-w64-x86_64-ca-certificates",
    "mingw-w64-x86_64-SDL2",
]


def _fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _zstd_decompress(blob):
    """``blob`` decompressed, whichever zstd this interpreter can reach.

    ``compression.zstd`` only exists from Python 3.14. The container runs
    Debian's interpreter, which is older, so the ``zstd`` command line -- which
    the build needs anyway to unpack the packages -- is the fallback.
    """
    try:
        from compression.zstd import decompress  # noqa: PLC0415 - 3.14+ only

        return decompress(blob)
    except ImportError:
        pass
    if not shutil.which("zstd"):
        raise SystemExit(
            "zstd is required to read the MSYS2 index "
            "(Python 3.14+ would provide it in the standard library)"
        )
    result = subprocess.run(
        ["zstd", "-d", "-c"], input=blob, stdout=subprocess.PIPE, check=True
    )
    return result.stdout


def _parse_db(blob):
    """The repository index as ``{package name: entry}``.

    ``mingw64.db`` is a zstd-compressed tar of one ``desc`` file per package,
    each a flat list of ``%FIELD%`` sections. Only five fields matter here.
    """
    entries = {}
    provides = {}
    with tarfile.open(fileobj=BytesIO(_zstd_decompress(blob)), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.name.endswith("/desc"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            fields = _parse_desc(handle.read().decode("utf-8"))
            name = fields.get("NAME", [None])[0]
            if not name:
                continue
            entry = {
                "name": name,
                "version": fields.get("VERSION", [""])[0],
                "filename": fields.get("FILENAME", [""])[0],
                "sha256": fields.get("SHA256SUM", [""])[0],
                "depends": fields.get("DEPENDS", []),
            }
            entries[name] = entry
            # A dependency may name something a package *provides* rather than
            # its real name (libfoo.dll=1.0 style). Index those too, or the
            # closure walk drops real dependencies on the floor.
            for provided in fields.get("PROVIDES", []):
                provides.setdefault(_strip_constraint(provided), name)
    return entries, provides


def _parse_desc(text):
    fields = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("%") and line.endswith("%"):
            current = line.strip("%")
            fields[current] = []
        elif current:
            fields[current].append(line)
    return fields


def _strip_constraint(dependency):
    """``"glib2>=2.80"`` -> ``"glib2"``.

    Version constraints are dropped rather than checked. The repository is a
    single consistent snapshot, so whatever it currently serves already
    satisfies them; re-implementing pacman's version comparison would add a
    second opinion with nothing to disagree about.
    """
    for separator in (">=", "<=", "==", "=", ">", "<"):
        if separator in dependency:
            return dependency.split(separator, 1)[0]
    return dependency


def resolve(entries, provides, roots):
    """Every package needed to install ``roots``, as a sorted name list."""
    seen = set()
    missing = []
    queue = list(roots)
    while queue:
        raw = queue.pop()
        name = _strip_constraint(raw)
        name = name if name in entries else provides.get(name, name)
        if name in seen:
            continue
        entry = entries.get(name)
        if entry is None:
            missing.append(raw)
            continue
        seen.add(name)
        queue.extend(entry["depends"])
    if missing:
        raise SystemExit(
            "packages missing from the MSYS2 index: " + ", ".join(sorted(set(missing)))
        )
    return sorted(seen)


def update_lock():
    """Rewrite ``packages.lock`` from the live repository index.

    On trust: the hashes recorded here are the ones MSYS2 publishes in its own
    index, so this pins *what this build saw*, not an independent audit of
    upstream. That is the same guarantee ``vendors/manifest.json`` gives for
    RetroArch, and it buys the thing that matters day to day -- after the lock
    is committed, a package changing underneath us fails the build loudly
    instead of silently shipping different bytes.
    """
    print(f"==> reading {REPO_URL}/{DB_NAME}")
    entries, provides = _parse_db(_fetch(f"{REPO_URL}/{DB_NAME}"))
    print(f"    {len(entries)} packages in the index")

    names = resolve(entries, provides, ROOT_PACKAGES)
    print(f"==> {len(names)} packages in the closure of {len(ROOT_PACKAGES)} roots")

    locked = []
    for name in names:
        entry = entries[name]
        if not entry["filename"] or not entry["sha256"]:
            raise SystemExit(f"{name}: the index has no filename or checksum")
        locked.append(
            {
                "name": name,
                "version": entry["version"],
                "filename": entry["filename"],
                "sha256": entry["sha256"],
            }
        )

    document = {
        "_comment": [
            "The MINGW64 runtime shipped inside the Windows bundle. Generated by",
            "packaging/windows/msys2_packages.py --update; do not edit by hand.",
            "",
            "Regenerating is how the bundle moves to newer GTK/Python: run --update,",
            "read the diff, build, smoke-test, commit. Between regenerations every",
            "build installs exactly these bytes.",
        ],
        "repository": REPO_URL,
        "roots": ROOT_PACKAGES,
        "packages": locked,
    }
    LOCK_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"==> wrote {LOCK_PATH} ({len(locked)} packages)")


def load_lock():
    if not LOCK_PATH.exists():
        raise SystemExit(
            f"{LOCK_PATH} is missing. Run: python3 {Path(__file__).name} --update"
        )
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def download(document, cache_dir):
    """Download every locked package into ``cache_dir``, verifying each one."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    repository = document.get("repository", REPO_URL)
    packages = document["packages"]
    paths = []
    for index, package in enumerate(packages, start=1):
        target = cache_dir / package["filename"]
        if target.exists() and _sha256(target) == package["sha256"]:
            paths.append(target)
            continue
        print(f"    [{index}/{len(packages)}] {package['filename']}")
        blob = _fetch(f"{repository}/{package['filename']}")
        digest = hashlib.sha256(blob).hexdigest()
        if digest != package["sha256"]:
            raise SystemExit(
                f"{package['filename']}: checksum mismatch\n"
                f"  locked:   {package['sha256']}\n"
                f"  received: {digest}\n"
                "The upstream file changed. Review it, then re-run with --update."
            )
        # Written under a temporary name and moved into place, so an
        # interrupted download can never be mistaken for a verified one on the
        # next run.
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(blob)
        temporary.replace(target)
        paths.append(target)
    return paths


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(paths, prefix):
    """Unpack the packages into ``prefix``, which ends up holding ``mingw64/``.

    Delegated to GNU tar rather than Python's tarfile: these are zstd-compressed
    and ``compression.zstd`` only exists from Python 3.14, which is newer than
    the Debian interpreter this runs on inside the container.
    """
    prefix.mkdir(parents=True, exist_ok=True)
    if not shutil.which("tar"):
        raise SystemExit("tar is required to unpack the MSYS2 packages")
    for path in paths:
        subprocess.run(
            [
                "tar",
                "--use-compress-program=zstd -d",
                "-xf",
                str(path),
                "-C",
                str(prefix),
                # pacman metadata, not files the bundle should carry.
                "--exclude=.BUILDINFO",
                "--exclude=.MTREE",
                "--exclude=.PKGINFO",
                "--exclude=.INSTALL",
            ],
            check=True,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite packages.lock from the live MSYS2 index and exit",
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        help="directory to extract into (it receives a mingw64/ subtree)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("build/win/msys2-cache"),
        help="where downloaded packages are kept between builds",
    )
    args = parser.parse_args(argv)

    if args.update:
        update_lock()
        return 0

    if args.prefix is None:
        parser.error("--prefix is required unless --update is given")

    document = load_lock()
    print(f"==> {len(document['packages'])} locked packages")
    paths = download(document, args.cache)
    print(f"==> extracting into {args.prefix}")
    extract(paths, args.prefix)
    return 0


if __name__ == "__main__":
    sys.exit(main())

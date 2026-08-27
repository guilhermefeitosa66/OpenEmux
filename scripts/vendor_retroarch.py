#!/usr/bin/env python3
"""Fetch and verify the vendored RetroArch builds described by vendors/manifest.json.

RetroArch is not built here -- it is redistributed. That makes provenance the
whole job of this script: what was downloaded, from where, and does it still
hash to what we recorded.

Two artifacts, two policies:

* ``linux-x86_64`` is committed to git (10.9 MiB) and is only ever *verified*.
* ``win64`` is 193 MiB and is gitignored, so it is fetched on demand. Putting it
  in git would inflate the repository permanently for every clone on every
  platform.

Runs on the Linux dev box, inside the Windows MSYS2 shell, and inside the Debian
build container -- so: standard library only, no third-party downloader.

Usage::

    python scripts/vendor_retroarch.py                 # the current platform
    python scripts/vendor_retroarch.py win64           # a named artifact
    python scripts/vendor_retroarch.py --all
    python scripts/vendor_retroarch.py --verify        # check, never download
    python scripts/vendor_retroarch.py win64 --record  # record the hash (see below)

``--record`` is trust on first use. libretro publishes no checksums, so the
first fetch of a new upstream version has nothing to check against; ``--record``
writes the hash it observed into the manifest for review and commit. Every fetch
after that verifies against it, and a mismatch is a hard failure.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "vendors" / "manifest.json"
CACHE_DIR = REPO_ROOT / "vendors" / ".cache"

#: Read in 1 MiB blocks: big enough that hashing 193 MiB is not syscall-bound,
#: small enough to keep peak memory flat.
CHUNK_SIZE = 1024 * 1024

#: The 7-Zip CLI, in order of preference. Not py7zr: it documents BCJ2 as
#: unsupported ("Standard lzma module does not provide"), and BCJ2 is 7-Zip's
#: default filter for x86 executables -- which is most of what RetroArch.7z is.
SEVENZIP_CANDIDATES = ("7zz", "7z", "7za")


class VendorError(RuntimeError):
    """Anything that should stop the build with a readable message."""


# --- manifest ----------------------------------------------------------------


def load_manifest():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise VendorError(f"{_rel(MANIFEST_PATH)} is missing.")
    except json.JSONDecodeError as exc:
        raise VendorError(f"{_rel(MANIFEST_PATH)} is not valid JSON: {exc}")


def save_manifest(manifest):
    # Rewritten only by --record, so a plain write is fine; the file is small
    # and a torn write here is recoverable from git.
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    MANIFEST_PATH.write_text(text, encoding="utf-8")


def default_artifact_name():
    return "win64" if sys.platform == "win32" else "linux-x86_64"


def _rel(path):
    """``path`` relative to the repo root when it is inside it, for readable logs."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# --- hashing -----------------------------------------------------------------


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root):
    """A stable digest of a directory: every relative path and its content.

    Paths are hashed as POSIX strings so the same tree digests identically on
    Windows and Linux, which is the point -- the Windows box fetches the tree
    and the Linux build container has to agree it is the same one.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    return digest.hexdigest()


def digest_of(entry, dest):
    return sha256_tree(dest) if entry["kind"] == "archive-7z" else sha256_file(dest)


# --- download ----------------------------------------------------------------


def download(url, dest, expected_size=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    print(f"    fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            total = expected_size or int(response.headers.get("Content-Length") or 0)
            done = 0
            last_percent = -1
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total:
                        percent = done * 100 // total
                        # Only redraw on a whole-percent change: a progress bar
                        # that writes per chunk floods CI logs.
                        if percent != last_percent:
                            last_percent = percent
                            print(
                                f"\r    {percent:3d}%  {done // (1024 * 1024)} / "
                                f"{total // (1024 * 1024)} MiB",
                                end="",
                                flush=True,
                            )
            if total:
                print()
    except urllib.error.URLError as exc:
        tmp.unlink(missing_ok=True)
        raise VendorError(f"download failed: {url}\n  {exc}")

    if expected_size and tmp.stat().st_size != expected_size:
        actual = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        raise VendorError(
            f"size mismatch for {url}\n"
            f"  expected {expected_size} bytes, got {actual}.\n"
            f"  Upstream may have republished this version -- re-run with --record "
            f"after confirming the change is legitimate."
        )

    tmp.replace(dest)
    return dest


# --- extraction --------------------------------------------------------------


def find_sevenzip():
    for name in SEVENZIP_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    raise VendorError(
        "no 7-Zip CLI found (looked for: " + ", ".join(SEVENZIP_CANDIDATES) + ").\n"
        "  Windows (MSYS2):  pacman -S mingw-w64-x86_64-7zip\n"
        "  Debian/Ubuntu:    apt-get install 7zip\n"
        "  Fedora:           dnf install p7zip"
    )


def extract_7z(archive, dest):
    """Extract ``archive`` so that ``dest`` holds its payload directly.

    RetroArch.7z wraps everything in a single top-level directory, but that
    name is not contractual and has changed between releases -- so it is
    discovered rather than assumed. The extraction goes to a temporary
    directory and is swapped into place only once it succeeds, so an
    interrupted run never leaves a half-populated vendors/ tree behind.
    """
    sevenzip = find_sevenzip()
    dest.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=str(dest.parent)))
    try:
        print(f"    extracting with {Path(sevenzip).name}")
        result = subprocess.run(
            [sevenzip, "x", "-y", f"-o{staging}", str(archive)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            raise VendorError(
                f"{Path(sevenzip).name} failed (exit {result.returncode}):\n"
                + (result.stdout or "").strip()
            )

        payload = staging
        entries = list(staging.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            payload = entries[0]
            print(f"    stripping top-level directory {entries[0].name}/")

        # Replace, not merge: a stale file from an older RetroArch left behind
        # in dest would otherwise survive forever and be impossible to explain.
        if dest.exists():
            shutil.rmtree(dest)
        payload.replace(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return dest


# --- the operations ----------------------------------------------------------


def verify(name, entry):
    """Check what is on disk against the manifest. Returns True when it matches."""
    dest = REPO_ROOT / entry["dest"]

    if not dest.exists():
        if entry["committed"]:
            print(f"  {name}: MISSING -- {_rel(dest)} should be committed to git")
        else:
            print(f"  {name}: not vendored yet (run without --verify to fetch)")
        return False

    expected = entry.get("sha256")
    if not expected:
        print(f"  {name}: present, but the manifest records no sha256 (use --record)")
        return False

    actual = digest_of(entry, dest)
    if actual == expected:
        print(f"  {name}: OK  {_rel(dest)}")
        return True

    print(f"  {name}: MISMATCH  {_rel(dest)}")
    print(f"      expected {expected}")
    print(f"      actual   {actual}")
    return False


def fetch(name, entry, manifest, record=False, force=False):
    dest = REPO_ROOT / entry["dest"]
    expected = entry.get("sha256")

    if entry["committed"]:
        # Committed artifacts are never re-downloaded -- git is the source of
        # truth for them, so the only sane action is to verify.
        print(f"  {name}: committed to git; verifying instead of fetching")
        if not verify(name, entry):
            raise VendorError(
                f"{name} does not match the manifest. Restore it with:\n"
                f"  git checkout -- {entry['dest']}"
            )
        return

    if dest.exists() and not force:
        if expected and digest_of(entry, dest) == expected:
            print(f"  {name}: up to date  {_rel(dest)}")
            return
        if not expected:
            print(f"  {name}: present but unverified (no sha256 in the manifest)")
            if not record:
                return

    if not entry.get("url"):
        raise VendorError(f"{name} has no url in the manifest, so it cannot be fetched.")

    print(f"  {name}: {entry['description']} {entry.get('version') or ''}".rstrip())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / Path(entry["url"]).name

    # Reuse a cached download only when it already hashes correctly; otherwise
    # a truncated or tampered file would be trusted forever.
    if cached.exists() and expected and sha256_file(cached) == expected:
        print(f"    reusing cached {_rel(cached)}")
    else:
        download(entry["url"], cached, entry.get("size"))

    actual = sha256_file(cached)
    if expected:
        if actual != expected:
            cached.unlink(missing_ok=True)
            raise VendorError(
                f"checksum mismatch for {name}\n"
                f"  expected {expected}\n"
                f"  actual   {actual}\n"
                f"  The upstream file changed. Do not proceed until you know why."
            )
        print("    sha256 verified")
    elif record:
        entry["sha256"] = actual
        save_manifest(manifest)
        print(f"    sha256 recorded: {actual}")
        print(f"    -> review and commit {_rel(MANIFEST_PATH)}")
    else:
        raise VendorError(
            f"{name} has no recorded sha256 and libretro publishes none.\n"
            f"  The download hashed to:\n"
            f"    {actual}\n"
            f"  Re-run with --record to write that into the manifest (trust on\n"
            f"  first use), then review and commit the change."
        )

    if entry["kind"] == "archive-7z":
        extract_7z(cached, REPO_ROOT / entry["dest"])
    else:
        shutil.copy2(cached, REPO_ROOT / entry["dest"])

    entrypoint = entry.get("entrypoint")
    if entrypoint:
        resolved = REPO_ROOT / entry["dest"] / entrypoint
        if not resolved.exists():
            raise VendorError(
                f"{name} extracted, but {entrypoint} is not at {_rel(resolved)}.\n"
                f"  The archive layout changed; update 'entrypoint' in the manifest."
            )
        print(f"    entrypoint {_rel(resolved)}")

    print(f"  {name}: ready  {_rel(REPO_ROOT / entry['dest'])}")


# --- cli ---------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch and verify the vendored RetroArch builds.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "names",
        nargs="*",
        help="artifacts to act on (default: the one for this platform)",
    )
    parser.add_argument("--all", action="store_true", help="act on every artifact")
    parser.add_argument(
        "--verify", action="store_true", help="check what is on disk; never download"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="record the observed sha256 into the manifest (trust on first use)",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-fetch even when already up to date"
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest()
        artifacts = manifest["artifacts"]

        if args.all or (args.verify and not args.names):
            names = list(artifacts)
        elif args.names:
            names = args.names
        else:
            names = [default_artifact_name()]

        unknown = [n for n in names if n not in artifacts]
        if unknown:
            raise VendorError(
                f"unknown artifact(s): {', '.join(unknown)}\n"
                f"  known: {', '.join(artifacts)}"
            )

        if args.verify:
            print(f"Verifying against {_rel(MANIFEST_PATH)}")
            results = [verify(name, artifacts[name]) for name in names]
            if not all(results):
                return 1
            return 0

        for name in names:
            fetch(
                name,
                artifacts[name],
                manifest,
                record=args.record,
                force=args.force,
            )
        return 0

    except VendorError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

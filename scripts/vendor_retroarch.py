#!/usr/bin/env python3
"""Fetch and verify the vendored RetroArch builds described by vendors/manifest.json.

RetroArch is not built here -- it is redistributed. That makes provenance the
whole job of this script: what was downloaded, from where, and does it still
hash to what we recorded.

Both artifacts are gitignored and fetched on demand: 193 MiB for Windows and
171 MiB for Linux, neither of which belongs in a repository every clone on
every platform pays for.

Both are also *trees* rather than files. RetroArch loads libretro cores with
``dlopen`` and resolves ``libGL``, the X11/Wayland client libraries and the
host's audio stack from the host, so a single static binary is not reachable on
any platform -- the Windows build is ``retroarch.exe`` plus its DLLs, and the
Linux one is ``usr/bin/retroarch`` plus the 56 libraries it finds through
``RUNPATH=$ORIGIN/../lib`` (issue #328).

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
writes the hashes it observed into the manifest for review and commit. Every
fetch after that verifies against them, and a mismatch is a hard failure.

Two hashes, because there are two things a mismatch can mean. ``sha256`` pins
the *download* -- an upstream archive that changed under a URL we already
recorded. ``tree_sha256`` pins what unpacking it produced, which is what
actually ships, and is the only one ``--verify`` can check once the archive
itself is gone from the cache.
"""

import argparse
import hashlib
import json
import platform
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

#: Kinds that unpack into a directory tree. What lands in vendors/ for these is
#: not the thing that was downloaded, so the manifest records a hash for each
#: (see the module docstring).
TREE_KINDS = ("archive-7z", "appimage-in-7z")

#: The AppImage runtime's own unpacker. Writes ./squashfs-root and needs no
#: FUSE -- which is the whole reason the Linux artifact can be a tree at all.
APPIMAGE_EXTRACT = "--appimage-extract"


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


def _machine():
    """This machine's architecture, spelled the way the manifest spells it.

    A copy of ``openemux.core.platform._machine``, deliberately: this script
    runs in build containers and on CI runners with no ``PYTHONPATH``, and
    importing the app to read one constant is what would make it need one.
    """
    name = platform.machine().strip().lower()
    if name in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if name in ("arm64", "aarch64", "armv8l"):
        return "aarch64"
    return name or "x86_64"


def default_artifact_name():
    """The artifact this platform needs -- which the manifest may not have.

    Architecture-aware on Linux. libretro publishes an x86_64 build and no ARM
    one, so on aarch64 this names an artifact that does not exist, and the
    caller reports that as the design rather than as a failure: the ARM
    packages use the distribution's RetroArch instead (issue #119).
    """
    return "win64" if sys.platform == "win32" else f"linux-{_machine()}"


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


def unpacks_to_a_tree(entry):
    return entry["kind"] in TREE_KINDS


def digest_of(entry, dest):
    """The hash of what is on disk at ``dest``."""
    return sha256_tree(dest) if unpacks_to_a_tree(entry) else sha256_file(dest)


def recorded_digest(entry):
    """The hash ``dest`` is expected to have, or ``None`` when none is recorded.

    For a tree that is ``tree_sha256``; ``sha256`` describes the archive it came
    out of, which is a different number and is not on disk at all once the
    download cache is cleared. Comparing the two is how `make verify-vendors`
    reported a MISMATCH on a perfectly good vendors/RetroArch-Win64.
    """
    return entry.get("tree_sha256") if unpacks_to_a_tree(entry) else entry.get("sha256")


def cache_path(name, url):
    """Where ``name``'s download is cached.

    Prefixed with the artifact name because libretro publishes every platform's
    archive as ``RetroArch.7z``: keyed on the URL's basename alone, the Windows
    and Linux downloads are the same file and each fetch overwrites the other.
    """
    return CACHE_DIR / f"{name}-{Path(url).name}"


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


def extract_appimage_tree(archive, dest):
    """Unwrap the AppImage inside ``archive`` into a portable tree at ``dest``.

    libretro publishes the Linux build as a .7z holding a single AppImage, and
    that AppImage is a squashfs image of an ordinary directory: ``AppRun`` is a
    symlink to ``usr/bin/retroarch``, and the binary finds its 56 bundled
    libraries through ``RUNPATH=$ORIGIN/../lib``. Nothing in RetroArch knows or
    cares that it was launched from an image -- ``strings`` finds no
    ``APPIMAGE``, ``APPDIR``, ``ARGV0`` or ``OWD`` reference in it -- so the
    tree is relocatable exactly as extracted, and unwrapping it here is what
    frees every Linux artifact from FUSE (issue #328).

    Two steps, and only the first is 7-Zip's: the archive also carries a 390 MiB
    ``.home`` tree of assets and shaders that nothing here ships, so the AppImage
    is the only member extracted. ``--appimage-extract`` then does the second,
    which does mean *running* the downloaded binary -- acceptable because it is
    the x86_64 Linux host this artifact is for and its sha256 was verified
    before we got here, and unavoidable because 7-Zip cannot read the squashfs
    appended to an ELF ("E_NOTIMPL").
    """
    sevenzip = find_sevenzip()
    dest.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=str(dest.parent)))
    try:
        print(f"    extracting the AppImage with {Path(sevenzip).name}")
        result = subprocess.run(
            [sevenzip, "x", "-y", f"-o{staging}", str(archive), "-r", "*.AppImage"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            raise VendorError(
                f"{Path(sevenzip).name} failed (exit {result.returncode}):\n"
                + (result.stdout or "").strip()
            )

        images = sorted(staging.rglob("*.AppImage"))
        if len(images) != 1:
            raise VendorError(
                f"expected exactly one .AppImage in {_rel(archive)}, found "
                f"{len(images)}.\n"
                f"  The archive layout changed; this artifact's 'kind' may no "
                f"longer fit."
            )
        image = images[0]
        image.chmod(0o755)

        print(f"    unwrapping {image.name}")
        result = subprocess.run(
            [str(image), APPIMAGE_EXTRACT],
            cwd=str(staging),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            raise VendorError(
                f"{image.name} {APPIMAGE_EXTRACT} failed (exit "
                f"{result.returncode}):\n" + (result.stdout or "").strip() + "\n"
                "  This runs the downloaded binary, so it needs an x86_64 Linux "
                "host (it needs no FUSE)."
            )

        payload = staging / "squashfs-root"
        if not payload.is_dir():
            raise VendorError(
                f"{image.name} {APPIMAGE_EXTRACT} wrote no squashfs-root/."
            )

        # Drop the AppDir scaffolding: AppRun, .DirIcon and the two top-level
        # links to the desktop entry and the icon. All four are symlinks into
        # usr/, they exist only so an *image* can be launched and integrated,
        # and nothing here launches one -- OpenEmux execs usr/bin/retroarch.
        # Keeping them costs a hidden-file warning, four dangling-symlink
        # errors from rpmlint, and 17 MiB of the tree digest spent hashing the
        # same binary twice.
        for entry in sorted(payload.iterdir()):
            if entry.is_symlink():
                print(f"    dropping the AppDir link {entry.name}")
                entry.unlink()

        # Replace, not merge: a stale library from an older RetroArch left
        # behind in dest would be found through RUNPATH and be impossible to
        # explain.
        if dest.exists():
            shutil.rmtree(dest)
        payload.replace(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return dest


def extract(entry, archive, dest):
    """Put ``archive``'s payload at ``dest``, however this kind is packed."""
    if entry["kind"] == "archive-7z":
        return extract_7z(archive, dest)
    if entry["kind"] == "appimage-in-7z":
        return extract_appimage_tree(archive, dest)
    return shutil.copy2(archive, dest)


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

    field = "tree_sha256" if unpacks_to_a_tree(entry) else "sha256"
    expected = recorded_digest(entry)
    if not expected:
        print(f"  {name}: present, but the manifest records no {field} (use --record)")
        return False

    actual = digest_of(entry, dest)
    if actual == expected:
        print(f"  {name}: OK  {_rel(dest)}")
        return True

    print(f"  {name}: MISMATCH  {_rel(dest)}")
    print(f"      expected {expected}")
    print(f"      actual   {actual}")
    return False


def _reconcile(name, entry, field, actual, record, what):
    """Compare one observed hash with the manifest, or record it. True = recorded.

    ``--record`` is trust on first use: libretro publishes no checksums, so the
    first fetch of a new upstream version has nothing to check against.
    """
    expected = entry.get(field)
    if expected:
        if actual != expected:
            raise VendorError(
                f"checksum mismatch for {name} ({what})\n"
                f"  expected {expected}\n"
                f"  actual   {actual}\n"
                f"  Either the upstream file changed or this script unpacks it\n"
                f"  differently than when the hash was recorded. Do not proceed\n"
                f"  until you know which."
            )
        print(f"    {field} verified")
        return False
    if record:
        entry[field] = actual
        print(f"    {field} recorded: {actual}")
        return True
    raise VendorError(
        f"{name} has no recorded {field} and libretro publishes none.\n"
        f"  The {what} hashed to:\n"
        f"    {actual}\n"
        f"  Re-run with --record to write that into the manifest (trust on\n"
        f"  first use), then review and commit the change."
    )


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

    on_disk = recorded_digest(entry)
    if dest.exists() and not force:
        if on_disk and digest_of(entry, dest) == on_disk:
            print(f"  {name}: up to date  {_rel(dest)}")
            return
        if not on_disk:
            print(f"  {name}: present but unverified (no hash in the manifest)")
            if not record:
                return

    if not entry.get("url"):
        raise VendorError(f"{name} has no url in the manifest, so it cannot be fetched.")

    print(f"  {name}: {entry['description']} {entry.get('version') or ''}".rstrip())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = cache_path(name, entry["url"])

    # Reuse a cached download only when it already hashes correctly; otherwise
    # a truncated or tampered file would be trusted forever.
    if cached.exists() and expected and sha256_file(cached) == expected:
        print(f"    reusing cached {_rel(cached)}")
    else:
        download(entry["url"], cached, entry.get("size"))

    try:
        recorded = _reconcile(
            name, entry, "sha256", sha256_file(cached), record, "download"
        )
    except VendorError:
        # A download that does not match what we recorded is not worth keeping:
        # left in the cache it would be "reused" by every later run.
        if expected:
            cached.unlink(missing_ok=True)
        raise

    extract(entry, cached, dest)

    entrypoint = entry.get("entrypoint")
    if entrypoint:
        resolved = dest / entrypoint
        if not resolved.exists():
            raise VendorError(
                f"{name} extracted, but {entrypoint} is not at {_rel(resolved)}.\n"
                f"  The archive layout changed; update 'entrypoint' in the manifest."
            )
        print(f"    entrypoint {_rel(resolved)}")

    if unpacks_to_a_tree(entry):
        # What ships is the tree, not the archive, and it is the only one
        # --verify can check later.
        recorded |= _reconcile(
            name, entry, "tree_sha256", sha256_tree(dest), record, "extracted tree"
        )

    if recorded:
        save_manifest(manifest)
        print(f"    -> review and commit {_rel(MANIFEST_PATH)}")

    print(f"  {name}: ready  {_rel(dest)}")


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
            default = default_artifact_name()
            if default not in artifacts:
                # Not an error: libretro publishes no ARM RetroArch, so on
                # aarch64 there is deliberately nothing to vendor and the
                # packages lean on the distribution's instead (issue #119).
                # Failing here would fail `make bootstrap` on every Pi.
                print(f"No RetroArch is vendored for this platform ({default}).")
                print("  The launcher falls back to a distribution or Flatpak")
                print("  RetroArch; nothing to fetch.")
                return 0
            names = [default]

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

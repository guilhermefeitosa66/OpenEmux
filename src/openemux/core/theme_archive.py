"""A custom theme as one shareable file, ``.openemux-theme`` (issue 1012).

The file is a zip holding the theme's ``theme.yaml`` and, under ``images/``,
the background images it names. ``docs/THEME_FORMAT.md`` is the contract,
for this app and for the Android one.

A theme file comes from somebody else, so importing one treats every byte as
hostile. The zip is checked from its central directory before anything is
read: a short list of entry names (``theme.yaml``, ``images/<name>``), no
absolute paths, ``..``, backslashes, links, other folders or duplicates, and
sizes and compression ratios a theme can sensibly have, so a zip bomb is
turned away unopened. Since a header can lie, the same limits are enforced
again on the bytes actually read. ``theme.yaml`` is parsed with
``yaml.safe_load`` and goes through the same whitelist as a theme on disk
(unknown keys dropped, numbers clamped); every image is decoded and written
again as a PNG by ``theme_images.import_image``, so what lands on disk is a
picture this app made, never the file as it came.

Everything is built in a hidden folder inside the themes folder and only
then saved as a theme; a file that fails any check raises
:class:`ThemeImportError` and leaves nothing behind. Nothing is ever written
outside the themes folder: entry names never become paths, and the images
are stored under names this module chooses.
"""

import io
import logging
import os
import shutil
import tempfile
import zipfile
import zlib
from pathlib import Path

import yaml

from openemux.core import theme_images
from openemux.core.custom_themes import (
    IMAGE_NAME,
    IMAGES_DIR,
    KIND_IMAGE,
    THEME_FILE,
    THEME_KEYS,
    ThemeError,
    parse_theme,
    serialize,
)

logger = logging.getLogger(__name__)

EXTENSION = ".openemux-theme"

#: Entries a theme file may have, all told.
MAX_ENTRIES = 16
#: ``theme.yaml``, uncompressed.
MAX_THEME_BYTES = 64 * 1024
#: Each image, uncompressed.
MAX_IMAGE_BYTES = 20 * 1024 * 1024
#: Every entry together, uncompressed.
MAX_TOTAL_BYTES = 40 * 1024 * 1024
#: Uncompressed size over compressed size, for entries larger than
#: :data:`RATIO_FLOOR`; real pictures and YAML never come close.
MAX_RATIO = 100
RATIO_FLOOR = 1024 * 1024

_IMAGES_PREFIX = IMAGES_DIR + "/"
_CHUNK = 64 * 1024

_FILE_TYPE = 0o170000
_SYMLINK = 0o120000
_REGULAR = 0o100000
_DIRECTORY = 0o040000
#: Bit 0 of the general purpose flags: the entry is encrypted.
_ENCRYPTED = 0x1


class ThemeImportError(ValueError):
    """A theme file that cannot be imported; ``reason`` is a short code.

    The codes: ``not-a-zip``, ``too-many-entries``, ``bad-entry`` (a name
    outside the list, a duplicate, an encrypted or special entry),
    ``symlink``, ``too-large``, ``ratio``, ``corrupt`` (the zip breaks while
    being read), ``bad-yaml``, ``bad-theme``, ``bad-image`` and
    ``write-failed`` (the themes folder could not be written).
    """

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _image_keys():
    return [spec.key for spec in THEME_KEYS if spec.kind == KIND_IMAGE]


def _stored_name(key):
    """The file an image key's picture is stored as: ``library_image`` -> ``library.png``.

    One file per key, named by this module, so two archive names that would
    both become ``<stem>.png`` can never collide.
    """
    return key[: -len("_image")] + ".png"


# -- export ----------------------------------------------------------------


def export_theme(store, theme_id, destination):
    """Write the theme ``theme_id`` to ``destination`` as a theme file.

    Raises :class:`KeyError` for a theme the store does not have. The file is
    written beside ``destination`` and renamed over it, never half-written.
    """
    theme = store.get(theme_id)
    if theme is None:
        raise KeyError(theme_id)
    destination = Path(destination)
    handle, temp = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                THEME_FILE,
                yaml.safe_dump(serialize(theme), sort_keys=False, allow_unicode=True),
            )
            written = set()
            for key in _image_keys():
                name = theme.values.get(key)
                if not name or name in written:
                    continue
                path = theme.image_path(key[: -len("_image")])
                if path is None:
                    logger.warning("Theme %s: image %s is missing, not exported", theme_id, name)
                    continue
                archive.write(path, _IMAGES_PREFIX + name)
                written.add(name)
        os.replace(temp, destination)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return destination


# -- import ----------------------------------------------------------------


def _check_entry(info):
    """Reject one central-directory entry that a theme file cannot have."""
    mode = (info.external_attr >> 16) & _FILE_TYPE
    if mode == _SYMLINK:
        raise ThemeImportError("symlink", info.filename)
    if mode not in (0, _REGULAR, _DIRECTORY):
        raise ThemeImportError("bad-entry", f"special file {info.filename!r}")
    if info.flag_bits & _ENCRYPTED:
        raise ThemeImportError("bad-entry", f"encrypted {info.filename!r}")
    name = info.filename
    # The list of names is all there is: an absolute path, "..", a
    # backslash or a nested folder simply is not on it.
    if name == _IMAGES_PREFIX:
        return
    if name == THEME_FILE:
        limit = MAX_THEME_BYTES
    elif name.startswith(_IMAGES_PREFIX) and IMAGE_NAME.fullmatch(name[len(_IMAGES_PREFIX):]):
        limit = MAX_IMAGE_BYTES
    else:
        raise ThemeImportError("bad-entry", repr(name))
    if info.file_size > limit:
        raise ThemeImportError("too-large", f"{name}: {info.file_size} bytes")
    if info.file_size > RATIO_FLOOR and (
        info.compress_size <= 0 or info.file_size / info.compress_size > MAX_RATIO
    ):
        raise ThemeImportError("ratio", f"{name}: {info.file_size}/{info.compress_size}")


def _check_directory(archive):
    """Every entry by name, after checking the central directory as a whole."""
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ThemeImportError("too-many-entries", str(len(infos)))
    entries = {}
    total = 0
    for info in infos:
        if info.filename in entries:
            raise ThemeImportError("bad-entry", f"duplicate {info.filename!r}")
        _check_entry(info)
        entries[info.filename] = info
        total += info.file_size
    if total > MAX_TOTAL_BYTES:
        raise ThemeImportError("too-large", f"{total} bytes in all")
    if THEME_FILE not in entries:
        raise ThemeImportError("bad-theme", f"no {THEME_FILE}")
    return entries


class _Budget:
    """What is left of :data:`MAX_TOTAL_BYTES` while entries are read."""

    def __init__(self, total):
        self.left = total


def copy_bounded(source, target, limit, budget=None):
    """Copy the stream ``source`` into ``target``, at most ``limit`` bytes.

    Raises ``too-large`` as soon as the stream yields more than ``limit``
    bytes or more than ``budget`` has left, whatever the zip header said.
    Returns the number of bytes copied.
    """
    copied = 0
    while True:
        chunk = source.read(_CHUNK)
        if not chunk:
            return copied
        copied += len(chunk)
        if copied > limit:
            raise ThemeImportError("too-large", f"more than {limit} bytes read")
        if budget is not None:
            budget.left -= len(chunk)
            if budget.left < 0:
                raise ThemeImportError("too-large", "more than the total read")
        target.write(chunk)


def _read_yaml(archive, info, budget):
    buffer = io.BytesIO()
    with archive.open(info) as source:
        copy_bounded(source, buffer, MAX_THEME_BYTES, budget)
    try:
        data = yaml.safe_load(buffer.getvalue().decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ThemeImportError("bad-yaml", str(exc)) from exc
    try:
        return parse_theme(data, "imported")
    except ThemeError as exc:
        raise ThemeImportError("bad-theme", str(exc)) from exc


def _extract_images(archive, entries, theme, work, budget):
    """Re-encode every image the theme names into ``work/images``.

    Returns the theme's values with each image key pointing at its stored
    PNG; a key whose image is not in the file is dropped.
    """
    values = dict(theme.values)
    raw_dir = work / "raw"
    images = work / IMAGES_DIR
    raw_dir.mkdir()
    images.mkdir()
    extracted = {}
    for key in _image_keys():
        name = values.get(key)
        if not name:
            continue
        info = entries.get(_IMAGES_PREFIX + name)
        if info is None:
            logger.warning("Imported theme: image %s is not in the file; %s dropped", name, key)
            del values[key]
            continue
        if name not in extracted:
            raw = raw_dir / name
            with archive.open(info) as source, open(raw, "wb") as target:
                copy_bounded(source, target, MAX_IMAGE_BYTES, budget)
            extracted[name] = raw
        stored = _stored_name(key)
        try:
            theme_images.import_image(extracted[name], images / stored)
        except theme_images.ThemeImageError as exc:
            raise ThemeImportError("bad-image", f"{name}: {exc}") from exc
        values[key] = stored
    return values, images


def import_theme(store, path):
    """Import the theme file at ``path`` into ``store``; returns the new theme.

    A name the store already has is imported as "Name (2)". Raises
    :class:`ThemeImportError` on anything wrong, leaving the themes folder as
    it was.
    """
    try:
        if not zipfile.is_zipfile(path):
            raise ThemeImportError("not-a-zip")
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ThemeImportError("not-a-zip", str(exc)) from exc
    with archive:
        entries = _check_directory(archive)
        budget = _Budget(MAX_TOTAL_BYTES)
        try:
            store.root.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=store.IMPORT_PREFIX, dir=store.root))
        except OSError as exc:
            raise ThemeImportError("write-failed", str(exc)) from exc
        try:
            try:
                theme = _read_yaml(archive, entries[THEME_FILE], budget)
                values, images = _extract_images(archive, entries, theme, work, budget)
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as exc:
                raise ThemeImportError("corrupt", str(exc)) from exc
            except OSError as exc:
                raise ThemeImportError("write-failed", str(exc)) from exc
            name = store.unique_name(theme.name)
            theme_id = store.new_id(name)
            try:
                return store.create(name, theme.base, values, images_from=images)
            except OSError as exc:
                # ``new_id`` picked a folder that did not exist, so whatever
                # is there now is this import's half-written theme.
                shutil.rmtree(store.root / theme_id, ignore_errors=True)
                raise ThemeImportError("write-failed", str(exc)) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

"""Theme files: export, import and every check a hostile file meets (issue 1012)."""

import io
import os
import struct
import unittest
import warnings
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import gi
import yaml

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from openemux.core import theme_archive, theme_images
from openemux.core.custom_themes import THEME_FILE, ThemeStore
from openemux.core.theme_archive import (
    EXTENSION,
    ThemeImportError,
    copy_bounded,
    export_theme,
    import_theme,
)


def make_picture(path, width=40, height=30, fmt="png", color=0x3366CCFF):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, fmt == "png", 8, width, height)
    pixbuf.fill(color)
    pixbuf.savev(str(path), fmt, [], [])
    return Path(path)


def picture_bytes(tmp, fmt="png", width=40, height=30):
    path = make_picture(Path(tmp) / f"source.{fmt}", width, height, fmt)
    data = path.read_bytes()
    path.unlink()
    return data


def theme_yaml(**fields):
    data = {"version": 1, "name": "Midnight", "base": "dark"}
    data.update(fields)
    return yaml.safe_dump(data, sort_keys=False)


def build_zip(path, entries, compression=zipfile.ZIP_DEFLATED):
    """``entries`` is a list of (name or ZipInfo, bytes or str)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names, on purpose
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, data in entries:
                if isinstance(name, str):
                    # ZipInfo turns os.sep into "/" -- a backslash on
                    # Windows -- so the name is set after it, exactly as a
                    # hostile file would carry it.
                    info = zipfile.ZipInfo(name)
                    info.filename = name
                    info.compress_type = compression
                    name = info
                archive.writestr(name, data)
    return Path(path)


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = ThemeStore(self.tmp / "themes")
        self.store.root.mkdir()
        self.file = self.tmp / f"theme{EXTENSION}"

    def tearDown(self):
        self._tmp.cleanup()

    def root_entries(self):
        return sorted(os.listdir(self.store.root))

    def assertRejected(self, reason, path=None):
        before = self.root_entries()
        with self.assertRaises(ThemeImportError) as caught:
            import_theme(self.store, path or self.file)
        self.assertEqual(caught.exception.reason, reason, str(caught.exception))
        self.assertIsInstance(caught.exception, ValueError)
        # Nothing new in the themes folder, hidden folders included.
        self.assertEqual(self.root_entries(), before)
        return caught.exception


class ExportTests(ArchiveTestCase):
    def _theme_with_images(self):
        source = self.tmp / "staging"
        (source / "images").mkdir(parents=True)
        make_picture(source / "images" / "library.png", 64, 48)
        make_picture(source / "images" / "sidebar.png", 20, 50)
        return self.store.create(
            "Midnight", "dark",
            {"library_bg": "#24283b", "corner_radius": 6, "library_image": "images/library.png",
             "library_image_dim": 0.55, "sidebar_image": "images/sidebar.png",
             "font_family": "Cantarell"},
            images_from=source,
        )

    def test_export_writes_the_yaml_and_the_images(self):
        theme = self._theme_with_images()
        result = export_theme(self.store, theme.id, self.file)
        self.assertEqual(result, self.file)
        with zipfile.ZipFile(self.file) as archive:
            self.assertEqual(
                archive.namelist(),
                [THEME_FILE, "images/library.png", "images/sidebar.png"],
            )
            data = yaml.safe_load(archive.read(THEME_FILE))
            self.assertEqual(archive.getinfo(THEME_FILE).compress_type, zipfile.ZIP_DEFLATED)
        self.assertEqual(data["name"], "Midnight")
        # The entries are written under the values that name them.
        self.assertEqual(data["library_image"], "images/library.png")
        self.assertEqual(data["library_image_dim"], 0.55)
        # No temp file is left beside it.
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["staging", "theme.openemux-theme", "themes"])

    def test_round_trip_into_a_fresh_store(self):
        theme = self._theme_with_images()
        export_theme(self.store, theme.id, self.file)
        other = ThemeStore(self.tmp / "other")
        imported = import_theme(other, self.file)
        self.assertEqual(imported.name, theme.name)
        self.assertEqual(imported.base, theme.base)
        self.assertEqual(imported.values, theme.values)
        self.assertEqual(theme_images.image_size(imported.image_path("library")), (64, 48))
        self.assertEqual(theme_images.image_size(imported.image_path("sidebar")), (20, 50))
        self.assertEqual(other.get(imported.id).values, theme.values)
        # The import folder is gone.
        self.assertEqual(os.listdir(other.root), [imported.id])

    def test_an_image_shared_by_two_keys_is_written_once(self):
        source = self.tmp / "staging"
        (source / "images").mkdir(parents=True)
        make_picture(source / "images" / "bg.png")
        theme = self.store.create(
            "Shared", "light",
            {"library_image": "images/bg.png", "sidebar_image": "images/bg.png"},
            images_from=source,
        )
        export_theme(self.store, theme.id, self.file)
        with zipfile.ZipFile(self.file) as archive:
            self.assertEqual(archive.namelist(), [THEME_FILE, "images/bg.png"])
        imported = import_theme(ThemeStore(self.tmp / "other"), self.file)
        # Each key gets a file of its own on import.
        self.assertEqual(imported.values["library_image"], "images/library.png")
        self.assertEqual(imported.values["sidebar_image"], "images/sidebar.png")
        self.assertIsNotNone(imported.image_path("library"))
        self.assertIsNotNone(imported.image_path("sidebar"))

    def test_a_missing_image_is_left_out(self):
        with self.assertLogs("openemux.core.custom_themes", "WARNING"):
            theme = self.store.create("Plain", "light", {"library_image": "images/library.png"},
                                      images_from=self.tmp)
        with self.assertLogs("openemux.core.theme_archive", "WARNING"):
            export_theme(self.store, theme.id, self.file)
        with zipfile.ZipFile(self.file) as archive:
            self.assertEqual(archive.namelist(), [THEME_FILE])

    def test_unknown_theme(self):
        with self.assertRaises(KeyError), self.assertLogs("openemux.core.custom_themes"):
            export_theme(self.store, "nope", self.file)
        self.assertFalse(self.file.exists())

    def test_a_failed_write_leaves_nothing(self):
        theme = self.store.create("Plain", "light", {})
        self.file.write_bytes(b"old")
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                export_theme(self.store, theme.id, self.file)
        self.assertEqual(self.file.read_bytes(), b"old")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["theme.openemux-theme", "themes"])


class ImportTests(ArchiveTestCase):
    def test_minimal_theme(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(library_bg="#24283b"))])
        theme = import_theme(self.store, self.file)
        self.assertEqual((theme.name, theme.base), ("Midnight", "dark"))
        self.assertEqual(theme.values, {"library_bg": "#24283b"})
        self.assertEqual(self.root_entries(), [theme.id])

    def test_name_clash_imports_as_name_2(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml())])
        first = import_theme(self.store, self.file)
        second = import_theme(self.store, self.file)
        self.assertEqual(first.name, "Midnight")
        self.assertEqual(second.name, "Midnight (2)")
        self.assertNotEqual(first.id, second.id)

    def test_no_name_falls_back(self):
        build_zip(self.file, [(THEME_FILE, "version: 1\nbase: light\n")])
        self.assertEqual(import_theme(self.store, self.file).name, "imported")

    def test_unknown_keys_dropped_and_ranges_clamped(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(
            evil="rm -rf /", corner_radius=999, border_width=-5, density=61.6,
            library_bg="not a color", android_only_key=3, shadow_strength=0.333,
            font_scale=2, icon_scale=1.1,
        ))])
        theme = import_theme(self.store, self.file)
        self.assertEqual(theme.values, {"corner_radius": 28, "border_width": 0,
                                        "shadow_strength": 0.33, "icon_scale": 1.1,
                                        "font_scale": 1.3})

    def test_a_newer_version_still_imports(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(version=7, accent="#ff0000"))])
        self.assertEqual(import_theme(self.store, self.file).values, {"accent": "#ff0000"})

    def test_images_are_re_encoded_as_png(self):
        jpeg = picture_bytes(self.tmp, "jpeg", 50, 20)
        build_zip(self.file, [
            (THEME_FILE, theme_yaml(library_image="images/bg.jpg")),
            ("images/", b""),
            ("images/bg.jpg", jpeg),
            ("images/unused.png", b"never read"),
        ])
        theme = import_theme(self.store, self.file)
        self.assertEqual(theme.values, {"library_image": "images/library.png"})
        path = theme.image_path("library")
        self.assertEqual(theme_images.sniff(path), "png")
        self.assertEqual(theme_images.image_size(path), (50, 20))
        self.assertEqual(sorted(os.listdir(path.parent)), ["library.png"])

    def test_missing_image_drops_the_key(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(
            library_image="images/gone.png", library_image_dim=0.5, sidebar_image="",
        ))])
        with self.assertLogs("openemux.core.theme_archive", "WARNING"):
            theme = import_theme(self.store, self.file)
        self.assertEqual(theme.values, {"library_image_dim": 0.5})
        self.assertFalse((self.store.root / theme.id / "images").exists())

    def test_a_single_top_folder_is_stripped(self):
        build_zip(self.file, [
            ("Midnight/", b""),
            ("Midnight/theme.yaml", theme_yaml(library_image="images/bg.png")),
            ("Midnight/images/", b""),
            ("Midnight/images/bg.png", picture_bytes(self.tmp)),
        ])
        theme = import_theme(self.store, self.file)
        self.assertEqual(theme.values, {"library_image": "images/library.png"})
        self.assertIsNotNone(theme.image_path("library"))

    def test_two_top_folders_are_not_stripped(self):
        build_zip(self.file, [
            ("a/theme.yaml", theme_yaml()), ("b/theme.yaml", theme_yaml()),
        ])
        self.assertRejected("bad-theme")

    def test_macosx_is_ignored(self):
        build_zip(self.file, [
            ("__MACOSX/", b""),
            ("__MACOSX/Midnight/._theme.yaml", b"\0\5\x16\x07 resource fork"),
            ("__MACOSX/theme.yaml", "base: light\n"),
            ("Midnight/theme.yaml", theme_yaml(accent="#ff0000")),
        ])
        theme = import_theme(self.store, self.file)
        self.assertEqual((theme.base, theme.values), ("dark", {"accent": "#ff0000"}))

    def test_a_theme_yaml_only_under_macosx_is_no_theme(self):
        build_zip(self.file, [("__MACOSX/theme.yaml", theme_yaml())])
        self.assertRejected("bad-theme")

    def test_other_entries_are_skipped_unread(self):
        link = zipfile.ZipInfo("notes/link")
        link.external_attr = (0o120777 << 16)
        build_zip(self.file, [
            (THEME_FILE, theme_yaml(library_image="images/bg.png")),
            ("images/bg.png", picture_bytes(self.tmp)),
            ("readme.txt", os.urandom(300)),
            ("images/BIG.PNG", b"x"), ("images/a.gif", b"x"),
            ("images/sub/", b""), ("images/sub/a.png", b"x"), ("other/", b""),
            (link, "/etc/passwd"),
        ])
        opened = []
        real_open = zipfile.ZipFile.open

        def recording_open(archive, name, *args, **kwargs):
            opened.append(getattr(name, "filename", name))
            return real_open(archive, name, *args, **kwargs)

        # Larger than an image may be, but never read, so never refused.
        with mock.patch.object(theme_archive, "MAX_IMAGE_BYTES", 2000), \
                mock.patch.object(zipfile.ZipFile, "open", recording_open):
            theme = import_theme(self.store, self.file)
        self.assertEqual(sorted(opened), ["images/bg.png", THEME_FILE])
        self.assertEqual(theme.values, {"library_image": "images/library.png"})


class RejectionTests(ArchiveTestCase):
    def test_not_a_zip(self):
        self.file.write_bytes(b"version: 1\n")
        self.assertRejected("not-a-zip")

    def test_missing_file(self):
        self.assertRejected("not-a-zip", self.tmp / "nowhere")

    def test_zip_that_fails_to_open(self):
        self.file.write_bytes(b"junk")
        with mock.patch.object(zipfile, "is_zipfile", return_value=True):
            self.assertRejected("not-a-zip")

    def test_too_many_entries(self):
        entries = [(THEME_FILE, theme_yaml())]
        entries += [(f"images/a{n}.png", b"x") for n in range(theme_archive.MAX_ENTRIES - 1)]
        build_zip(self.file, entries)
        self.assertEqual(import_theme(self.store, self.file).name, "Midnight")
        # Skipped entries count too.
        build_zip(self.file, entries + [("__MACOSX/x", b"x")])
        self.assertRejected("too-many-entries")

    def test_file_too_big_is_refused_before_it_is_opened(self):
        self.file.write_bytes(b"x" * 200)
        with mock.patch.object(theme_archive, "MAX_FILE_BYTES", 100), \
                mock.patch.object(zipfile, "is_zipfile") as is_zip:
            self.assertRejected("too-large")
        is_zip.assert_not_called()

    def _bad_name(self, name):
        build_zip(self.file, [(THEME_FILE, theme_yaml()), (name, b"x")])
        return self.assertRejected("bad-entry")

    def test_traversal(self):
        self._bad_name("../x")
        self._bad_name("images/../../x.png")

    def test_absolute(self):
        self._bad_name("/etc/x")

    def test_backslash(self):
        self._bad_name("images\\a.png")
        self._bad_name("notes\\readme.txt")

    def test_unsafe_names_refuse_wherever_they_are(self):
        # Even where nothing would be read: in __MACOSX/, an unknown folder.
        self._bad_name("__MACOSX/../x")
        self._bad_name("other/../../x")
        self._bad_name("/__MACOSX/x")
        build_zip(self.file, [("Midnight/theme.yaml", theme_yaml()), ("Midnight/../x", b"x")])
        self.assertRejected("bad-entry")

    def test_duplicate_entry(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml()), (THEME_FILE, theme_yaml())])
        self.assertRejected("bad-entry")

    def test_symlink(self):
        info = zipfile.ZipInfo("images/a.png")
        info.external_attr = (0o120777 << 16)
        build_zip(self.file, [(THEME_FILE, theme_yaml()), (info, "/etc/passwd")])
        self.assertRejected("symlink")

    def test_special_file(self):
        info = zipfile.ZipInfo("images/a.png")
        info.external_attr = (0o010644 << 16)  # a FIFO
        build_zip(self.file, [(THEME_FILE, theme_yaml()), (info, b"")])
        self.assertRejected("bad-entry")

    def test_encrypted_entry(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml())])
        data = bytearray(self.file.read_bytes())
        # Set bit 0 of the flags in the central directory header.
        at = data.index(b"PK\x01\x02") + 8
        data[at] |= 0x1
        self.file.write_bytes(bytes(data))
        self.assertRejected("bad-entry")

    def test_no_theme_yaml(self):
        build_zip(self.file, [("images/a.png", b"x")])
        self.assertRejected("bad-theme")

    def test_theme_yaml_too_big(self):
        with mock.patch.object(theme_archive, "MAX_THEME_BYTES", 100):
            build_zip(self.file, [(THEME_FILE, theme_yaml(name="x" * 200))])
            self.assertRejected("too-large")

    def test_image_too_big(self):
        with mock.patch.object(theme_archive, "MAX_IMAGE_BYTES", 100):
            build_zip(self.file, [(THEME_FILE, theme_yaml()), ("images/a.png", os.urandom(200))])
            self.assertRejected("too-large")

    def test_total_too_big(self):
        with mock.patch.object(theme_archive, "MAX_TOTAL_BYTES", 300):
            build_zip(self.file, [
                (THEME_FILE, theme_yaml()),
                ("images/a.png", os.urandom(200)), ("images/b.png", os.urandom(200)),
            ])
            self.assertRejected("too-large")

    def test_zip_bomb_ratio(self):
        with mock.patch.object(theme_archive, "RATIO_FLOOR", 1000):
            build_zip(self.file, [(THEME_FILE, theme_yaml()), ("images/a.png", b"\0" * 200_000)])
            self.assertRejected("ratio")

    def test_large_but_incompressible_entry_passes_the_ratio(self):
        with mock.patch.object(theme_archive, "RATIO_FLOOR", 1000):
            build_zip(self.file, [(THEME_FILE, theme_yaml()), ("images/a.png", os.urandom(5000))])
            self.assertEqual(import_theme(self.store, self.file).name, "Midnight")

    def test_ratio_with_nothing_compressed(self):
        info = SimpleNamespace(filename="images/a.png", external_attr=0, flag_bits=0,
                               file_size=theme_archive.RATIO_FLOOR + 1, compress_size=0)
        with self.assertRaises(ThemeImportError) as caught:
            theme_archive._check_entry(info, "images/a.png")
        self.assertEqual(caught.exception.reason, "ratio")

    def test_lying_header(self):
        # The central directory says theme.yaml is 4 bytes; it holds more.
        build_zip(self.file, [(THEME_FILE, theme_yaml())], compression=zipfile.ZIP_STORED)
        data = bytearray(self.file.read_bytes())
        at = data.index(b"PK\x01\x02") + 24
        data[at:at + 4] = struct.pack("<I", 4)
        self.file.write_bytes(bytes(data))
        self.assertRejected("corrupt")

    def test_unsupported_compression(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml())], compression=zipfile.ZIP_STORED)
        data = bytearray(self.file.read_bytes())
        at = data.index(b"PK\x01\x02") + 10
        data[at:at + 2] = struct.pack("<H", 99)
        self.file.write_bytes(bytes(data))
        self.assertRejected("corrupt")

    def test_bad_yaml(self):
        build_zip(self.file, [(THEME_FILE, "name: [unclosed\n")])
        self.assertRejected("bad-yaml")

    def test_not_utf8(self):
        build_zip(self.file, [(THEME_FILE, b"name: \xff\xfe\n")])
        self.assertRejected("bad-yaml")

    def test_non_mapping_yaml(self):
        build_zip(self.file, [(THEME_FILE, "- just\n- a list\n")])
        self.assertRejected("bad-theme")

    def test_bad_base(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(base="purple"))])
        self.assertRejected("bad-theme")

    def test_bad_version(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml(version=0))])
        self.assertRejected("bad-theme")

    def test_image_not_a_picture(self):
        build_zip(self.file, [
            (THEME_FILE, theme_yaml(library_image="images/a.png")),
            ("images/a.png", b"#!/bin/sh\necho hi\n"),
        ])
        self.assertRejected("bad-image")

    def test_a_bad_image_after_a_good_one_leaves_nothing(self):
        good = picture_bytes(self.tmp)
        build_zip(self.file, [
            (THEME_FILE, theme_yaml(library_image="images/a.png", sidebar_image="images/b.png")),
            ("images/a.png", good), ("images/b.png", b"nope"),
        ])
        self.assertRejected("bad-image")

    def test_temp_folder_cannot_be_made(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml())])
        with mock.patch.object(theme_archive.tempfile, "mkdtemp", side_effect=OSError("ro")):
            self.assertRejected("write-failed")

    def test_write_error_while_extracting(self):
        build_zip(self.file, [
            (THEME_FILE, theme_yaml(library_image="images/a.png")),
            ("images/a.png", picture_bytes(self.tmp)),
        ])
        with mock.patch.object(theme_images, "import_image", side_effect=OSError("full")):
            self.assertRejected("write-failed")

    def test_write_error_while_saving_the_theme(self):
        build_zip(self.file, [(THEME_FILE, theme_yaml())])
        real_save = ThemeStore.save

        def failing_save(store, theme, images_from=None):
            (store.root / theme.id).mkdir()
            raise OSError("disk full")

        with mock.patch.object(ThemeStore, "save", failing_save):
            self.assertRejected("write-failed")
        self.assertIs(ThemeStore.save, real_save)


class BoundedCopyTests(unittest.TestCase):
    def test_copies_within_the_limit(self):
        target = io.BytesIO()
        budget = theme_archive._Budget(100)
        self.assertEqual(copy_bounded(io.BytesIO(b"x" * 10), target, 10, budget), 10)
        self.assertEqual(target.getvalue(), b"x" * 10)
        self.assertEqual(budget.left, 90)

    def test_without_a_budget(self):
        self.assertEqual(copy_bounded(io.BytesIO(b"abc"), io.BytesIO(), 3), 3)

    def test_a_stream_longer_than_its_limit(self):
        with self.assertRaises(ThemeImportError) as caught:
            copy_bounded(io.BytesIO(b"x" * 11), io.BytesIO(), 10)
        self.assertEqual(caught.exception.reason, "too-large")

    def test_a_stream_past_the_total(self):
        budget = theme_archive._Budget(5)
        with self.assertRaises(ThemeImportError) as caught:
            copy_bounded(io.BytesIO(b"x" * 8), io.BytesIO(), 10, budget)
        self.assertEqual(caught.exception.reason, "too-large")

    def test_error_message_carries_the_detail(self):
        self.assertEqual(str(ThemeImportError("ratio", "a.png")), "ratio: a.png")
        self.assertEqual(str(ThemeImportError("not-a-zip")), "not-a-zip")


if __name__ == "__main__":
    unittest.main()

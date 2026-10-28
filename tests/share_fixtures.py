"""Throwaway libraries and cores for the Share nearby transfer tests (#588)."""

import os
import tempfile
from pathlib import Path

from openemux.core.cores import CoreCatalog
from openemux.core.platform import CORE_SUFFIX, core_stem

#: The smallest PNG header ``scraper.is_image`` recognises, plus padding.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 64


def core_file(stem):
    return f"{stem}_libretro{CORE_SUFFIX}"


def make_catalog(base, cores):
    """A real :class:`CoreCatalog` over ``{stem: (corename, display_version)}``."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    for stem, identity in cores.items():
        filename = core_file(stem)
        (base / filename).write_text("", encoding="utf-8")
        if identity is not None:
            name, version = identity
            lines = [f'corename = "{name}"']
            if version:
                lines.append(f'display_version = "{version}"')
            (base / f"{core_stem(filename)}.info").write_text("\n".join(lines), encoding="utf-8")
    return CoreCatalog(core_dirs=[base])


class FakeConfig:
    """The four per-ROM overrides the manifest reads."""

    def __init__(self, colors=None, cores=None, shaders=None):
        self.colors = colors or {}
        self.cores = cores or {}
        self.shaders = shaders or {}

    def get_rom_cartridge_color_override(self, rom_path):
        return self.colors.get(str(rom_path))

    def get_rom_core_override(self, rom_path):
        return self.cores.get(str(rom_path))

    def get_rom_shader_override(self, rom_path):
        return self.shaders.get(str(rom_path))


class FakePlaylists:
    def __init__(self, favorites=()):
        self.favorites = {str(p) for p in favorites}

    def is_favorite(self, rom_path):
        return str(rom_path) in self.favorites


class Library:
    """``roms/`` and ``states/`` under one temporary directory."""

    def __init__(self, root):
        self.root = Path(root)
        self.roms = self.root / "roms"
        self.states = self.root / "states"

    def file(self, relative, data=b"x", mtime=None):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def rom(self, console, name, data=b"rom", mtime=None):
        path = self.file(f"roms/{console}/{name}", data, mtime)
        return {"name": path.stem, "path": str(path), "console": console}

    def cue_game(self, console, stem, bins=("Track 1.bin", "Track 2.bin"), folder=""):
        directory = f"roms/{console}/{folder + '/' if folder else ''}"
        lines = []
        for index, name in enumerate(bins):
            self.file(f"{directory}{name}", bytes([index + 1]) * (100 + index))
            lines.append(f'FILE "{name}" BINARY')
        cue = self.file(f"{directory}{stem}.cue", "\n".join(lines) + "\n")
        return {"name": stem, "path": str(cue), "console": console}

    def tree(self):
        return sorted(
            str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()
        )


def temp_library(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Library(tmp.name)

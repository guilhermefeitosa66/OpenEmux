#!/usr/bin/env python3
"""Export the Android app's bundled controller art for the desktop input page.

The Android app ships one skin per console in OpenEmux's own skin format
(`pkg/android/openemux/docs/skin-format.md` in openemux-android): a zip with a
`skin.json` and one PNG per element per layout. Every one of them has a
`phone-portrait` layout whose controls all sit below the game screen, so
cropping that layout below its screens and frame leaves the controller alone:
the console body with its printed labels, and each control's own image on top.

Per console this writes `src/openemux/ui/assets/controllers/<CONSOLE>/`:

* `background.png` -- the layout's background, cropped and scaled;
* one image per control: `<id>.png` for a button or keypad key, the pad for a
  D-pad (its ball is not needed), `<id>-base.png` and `<id>-knob.png` for a
  stick;
* `layout.json` -- the crop's size and each control's id, type, bind, rect
  (re-based on the crop, scaled) and image names, which
  `openemux.core.controller_layouts` reads.

Quick actions (`type: action`), the frame and the screens are left out. The
output is truecolor RGBA PNG and deterministic: the same skins give the same
bytes, so re-running the tool after an unrelated Android change is a no-op.

Run it by hand when the Android skins change; the desktop build never reaches
into the Android repository.

    tools/export_controller_art.py                      # every console
    tools/export_controller_art.py N64 PS               # only these
    tools/export_controller_art.py --android DIR        # another checkout
    tools/export_controller_art.py --skins DIR          # a folder of <CONSOLE>.zip
"""

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "src" / "openemux" / "ui" / "assets" / "controllers"
DEFAULT_ANDROID = REPO.parent / "openemux-android"
SKINS_IN_ANDROID = Path("pkg/android/openemux/src/main/assets/skins")

#: The layout that holds every control below the game screen, on every skin.
SOURCE_LAYOUT = "phone-portrait"

#: The layouts are 1080 px wide; half of that keeps the 31 consoles near 4 MB.
SCALE = 0.5

#: Layout pixels skipped below the screens and frame, so the edge of the
#: screen's shadow does not show as a line at the top. Never past a control.
CROP_MARGIN = 16

#: The element types that are part of the controller (not a quick action).
CONTROL_TYPES = ("button", "keypad", "dpad", "stick")

FORMAT = 1

ZIP_NAME_RE = re.compile(r"^([A-Z0-9]+)\.zip$")


class ExportError(Exception):
    """A skin that cannot be exported; the message says which and why."""


class SkinPackage:
    """A skin zip: its `skin.json` and its images, wherever the folder sits."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ExportError(f"{self.path.name}: not a readable zip ({error})") from error
        try:
            names = self._zip.namelist()
            roots = [
                n[: -len("skin.json")] for n in names
                if n == "skin.json" or (n.endswith("/skin.json") and n.count("/") == 1)
            ]
            if not roots:
                raise ExportError(f"{self.path.name}: no skin.json")
            self.prefix = sorted(roots)[0]
            self._names = set(names)
            try:
                self.skin = json.loads(self._zip.read(self.prefix + "skin.json"))
            except ValueError as error:
                raise ExportError(f"{self.path.name}: skin.json is not JSON ({error})") from error
        except ExportError:
            self._zip.close()
            raise

    def close(self):
        self._zip.close()

    def image(self, layout, base):
        """The layout's image `base` (PNG or WebP) as RGBA, or None when absent."""
        for ext in (".png", ".webp"):
            name = f"{self.prefix}{layout}/{base}{ext}"
            if name in self._names:
                with Image.open(io.BytesIO(self._zip.read(name))) as image:
                    return image.convert("RGBA")
        return None


def crop_top(layout):
    """Where the controller starts: a little below the screens and the frame."""
    bottoms = [s["y"] + s["height"] for s in layout["screens"]]
    frame = layout.get("frame")
    if frame:
        bottoms.append(frame["y"] + frame["height"])
    controls = [e["y"] for e in layout.get("elements", []) if e["type"] in CONTROL_TYPES]
    return min([max(bottoms, default=-CROP_MARGIN) + CROP_MARGIN] + controls)


def scaled_rect(element, top, scale=SCALE):
    """The element's rect re-based on the crop and scaled, edges rounded."""
    left = round(element["x"] * scale)
    upper = round((element["y"] - top) * scale)
    right = round((element["x"] + element["width"]) * scale)
    lower = round((element["y"] + element["height"] - top) * scale)
    return {"x": left, "y": upper, "width": max(1, right - left), "height": max(1, lower - upper)}


def scaled(image, scale=SCALE):
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.LANCZOS)


def save_png(image, path):
    """Truecolor RGBA, optimized, no metadata: the same pixels, the same bytes."""
    image.convert("RGBA").save(path, "PNG", optimize=True)


def element_images(element):
    """Role -> image base name in the skin, for a control element."""
    base = element.get("image") or element["id"]
    if element["type"] == "stick":
        return {"base": f"{base}-base", "knob": f"{base}-knob"}
    if element["type"] == "dpad":
        return {"pad": base}
    return {"button": base}


def export_console(package, out_dir, scale=SCALE):
    """Write one console's controller art from a SkinPackage into `out_dir`."""
    skin = package.skin
    console = skin.get("console")
    if skin.get("format") != FORMAT or not console:
        raise ExportError(f"{package.path.name}: not a format-{FORMAT} skin")
    layout = skin.get("layouts", {}).get(SOURCE_LAYOUT)
    if layout is None:
        raise ExportError(f"{package.path.name}: no {SOURCE_LAYOUT} layout")

    top = crop_top(layout)
    width = layout["size"]["width"]
    height = layout["size"]["height"]
    background_name = (layout.get("background") or {}).get("image") or "background"
    background = package.image(SOURCE_LAYOUT, background_name)
    if background is None:
        raise ExportError(f"{package.path.name}: no {SOURCE_LAYOUT}/{background_name} image")
    background = background.resize((width, height), Image.LANCZOS) if background.size != (width, height) else background
    crop = background.crop((0, top, width, height))
    crop_size = (round(width * scale), round(height * scale) - round(top * scale))
    crop = crop.resize(crop_size, Image.LANCZOS)

    # Every image is rendered before anything is written, so a skin that
    # fails halfway leaves the console's committed art as it was.
    files = {"background.png": crop}
    elements = []
    for element in layout.get("elements", []):
        if element["type"] not in CONTROL_TYPES:
            continue
        rect = scaled_rect(element, top, scale)
        images = {}
        for role, base in element_images(element).items():
            image = package.image(SOURCE_LAYOUT, base)
            if image is None:
                raise ExportError(f"{package.path.name}: no {SOURCE_LAYOUT}/{base} image")
            if role == "knob":
                image = scaled(image, scale)
            else:
                image = image.resize((rect["width"], rect["height"]), Image.LANCZOS)
            file_name = f"{base}.png"
            if file_name in files:
                # Two controls sharing an image at different sizes, or one
                # named like the background, would overwrite each other.
                raise ExportError(f"{package.path.name}: {file_name} would be written twice")
            files[file_name] = image
            images[role] = file_name
        bind = element.get("bind") or ("dpad" if element["type"] == "dpad" else "")
        elements.append({"id": element["id"], "type": element["type"], "bind": bind, **rect, "images": images})

    document = {
        "format": FORMAT,
        "console": console,
        "source": SOURCE_LAYOUT,
        "scale": scale,
        "size": {"width": crop_size[0], "height": crop_size[1]},
        "background": "background.png",
        "elements": elements,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("*.png")) + list(out_dir.glob("layout.json")):
        stale.unlink()
    for file_name, image in files.items():
        save_png(image, out_dir / file_name)
    (out_dir / "layout.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return console


def skins_to_export(skins_dir, consoles=None):
    """The default skin zips in `skins_dir`, `<CONSOLE>.zip`, sorted."""
    found = {}
    for path in sorted(Path(skins_dir).glob("*.zip")):
        match = ZIP_NAME_RE.match(path.name)
        if match:
            found[match.group(1)] = path
    if consoles:
        missing = [c for c in consoles if c not in found]
        if missing:
            raise ExportError(f"no bundled skin for: {', '.join(missing)}")
        return [found[c] for c in consoles]
    return list(found.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("consoles", nargs="*", help="console ids (default: every bundled skin)")
    parser.add_argument("--android", type=Path, default=DEFAULT_ANDROID, help="openemux-android checkout")
    parser.add_argument("--skins", type=Path, help="folder of <CONSOLE>.zip (overrides --android)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="destination folder")
    args = parser.parse_args(argv)

    skins_dir = args.skins or args.android / SKINS_IN_ANDROID
    if not skins_dir.is_dir():
        print(f"export_controller_art: no skins folder at {skins_dir}", file=sys.stderr)
        return 1
    try:
        paths = skins_to_export(skins_dir, args.consoles)
        for path in paths:
            package = SkinPackage(path)
            try:
                console = export_console(package, args.out / path.stem)
            finally:
                package.close()
            print(f"{console}: {args.out / path.stem}")
    except ExportError as error:
        print(f"export_controller_art: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

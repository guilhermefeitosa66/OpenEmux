# OpenEmux 1.5.2

A fix for the AppImage, where every game in a console's library showed an empty
placeholder instead of its cartridge and cover art. The `.deb` and `.rpm` are
unaffected — nothing else changed.

## What went wrong

Compositing a cover into a cartridge frame hands a cairo drawing context to the
SVG renderer, and that crossing needs the GObject-introspection ↔ cairo bridge
(`python3-gi-cairo`). It was never bundled. Running from source, or from the
`.deb`/`.rpm`, it comes from the system, which is why this only ever showed up
in the AppImage.

Worse, the failure raised an error the renderer did not catch, on the thread
that loads cover art. That killed the whole card update, so the game lost its
plain cover too and fell back to the generic placeholder — a missing frame
should only have cost the cartridge, not the artwork.

Both are fixed: the bridge is bundled, and a cartridge that cannot be
composited now degrades to the plain cover.

## The check that was missing

The build verified the *pieces* — image loaders present, Rsvg bindings present
— and every one of them passed while the bundle could not actually draw a
cartridge. It now composites a real frame inside the finished AppImage and
fails the build if nothing comes out, which reproduces this exact bug.

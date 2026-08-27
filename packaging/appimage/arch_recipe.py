#!/usr/bin/env python3
"""Render the AppImage recipe for one architecture.

Four values in ``AppImageBuilder.yml`` are architecture-dependent, and
everything else in it -- ninety lines of package list and the reasons each
entry is there -- is not. Forking the recipe per architecture would mean two
copies of that list, and a package added to one of them (issue #119).

So there is one recipe, written for x86_64, and this rewrites those four values
for another target:

===========================  ==========================  ===========================
value                        x86_64                      aarch64
===========================  ==========================  ===========================
``AppImage.arch``            ``x86_64``                  ``aarch64``
``apt.arch``                 ``amd64``                   ``arm64``
library triplet              ``x86_64-linux-gnu``        ``aarch64-linux-gnu``
apt archive host             ``archive.ubuntu.com``      ``ports.ubuntu.com``
===========================  ==========================  ===========================

Textual, not a YAML round trip: PyYAML would drop every comment in the file,
and the comments are why the package list is maintainable. Every substitution
asserts how many times it matched, so a recipe edit that moves an anchor fails
the build loudly instead of quietly producing an x86_64 recipe on an ARM
machine -- which would build, and then not run.

Standard library only: it runs inside the build container.
"""

import argparse
import sys
from pathlib import Path

#: The Ubuntu ports archive. ARM packages are not on archive.ubuntu.com at all.
PORTS_HOST = "https://ports.ubuntu.com/ubuntu-ports/"
ARCHIVE_HOST = "https://archive.ubuntu.com/ubuntu/"

#: target arch -> (substitutions, expected count each)
TARGETS = {
    "x86_64": [],
    "aarch64": [
        ("  arch: x86_64\n", "  arch: aarch64\n", 1),
        ("    arch: amd64\n", "    arch: arm64\n", 1),
        ("x86_64-linux-gnu", "aarch64-linux-gnu", 3),
        (ARCHIVE_HOST, PORTS_HOST, 2),
    ],
}


class RecipeError(RuntimeError):
    """A substitution did not match what the recipe actually says."""


def render(text, arch):
    """The recipe rewritten for ``arch``. x86_64 returns it unchanged."""
    try:
        substitutions = TARGETS[arch]
    except KeyError:
        raise RecipeError(
            f"no AppImage recipe for {arch}; known: {', '.join(sorted(TARGETS))}"
        ) from None
    for old, new, expected in substitutions:
        found = text.count(old)
        if found != expected:
            raise RecipeError(
                f"expected {expected} occurrence(s) of {old!r} in the recipe, "
                f"found {found}. The recipe changed; update {__file__}."
            )
        text = text.replace(old, new)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recipe", type=Path, help="the x86_64 recipe to render")
    parser.add_argument("--arch", required=True, help="target architecture")
    parser.add_argument("--output", type=Path, help="write here (default: stdout)")
    args = parser.parse_args(argv)

    try:
        rendered = render(args.recipe.read_text(encoding="utf-8"), args.arch)
    except (OSError, RecipeError) as exc:
        print(f"arch_recipe: {exc}", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

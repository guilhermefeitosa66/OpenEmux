"""What the collaborators reach for on the window has to be there.

`OpenEmuxWindow` was one class with fourteen responsibilities; it is a shell
plus six collaborators now -- the sidebar, the page cache, the import flow,
the game session, the task banner, the navigation controller -- and each of
them holds the window and calls back into it (issue #237).

Nothing else can check those calls. Constructing the window needs a display
and a full GTK stack, so the suite never builds one; a collaborator calling a
method the refactor renamed fails at run time, inside a signal handler, where
PyGObject prints the traceback and swallows it -- the menu entry simply does
nothing. That is exactly what a rename of `_ensure_console_loaded` did to the
sidebar's Layout submenu.

So: read every `self.win.<name>` / `self.window.<name>` in the UI package and
check the name against the window's own attributes, resolved statically.
"""

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "src" / "openemux" / "ui"
WINDOW = UI_DIR / "window.py"

#: The names a collaborator may hold the window under.
WINDOW_ALIASES = ("win", "window")


def _window_class():
    tree = ast.parse(WINDOW.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "OpenEmuxWindow":
            return node
    raise AssertionError("OpenEmuxWindow is not in ui/window.py any more")


def window_attributes():
    """Every name reachable on the window, without importing GTK.

    Three sources: methods and class-level constants, the ``self.x = ...``
    assignments anywhere in the class, and the GTK/Adwaita API it inherits --
    which is read from the real class when a display is available and taken
    on trust when it is not.
    """
    names = set()
    klass = _window_class()
    for node in klass.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    for node in ast.walk(klass):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                names.add(node.attr)
    return names


def _referenced(path):
    """``(lineno, name)`` for every ``self.win.<name>`` in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        holder = node.value
        if not isinstance(holder, ast.Attribute) or holder.attr not in WINDOW_ALIASES:
            continue
        if not (isinstance(holder.value, ast.Name) and holder.value.id == "self"):
            continue
        yield node.lineno, node.attr


class EveryCallbackIntoTheWindowResolvesTests(unittest.TestCase):
    def test_no_collaborator_calls_a_method_the_window_lost(self):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        known = window_attributes() | set(dir(Adw.ApplicationWindow))
        unknown = []
        for source in sorted(UI_DIR.glob("*.py")):
            for lineno, name in _referenced(source):
                if name not in known:
                    unknown.append(f"{source.name}:{lineno} window.{name}")

        self.assertEqual(
            sorted(set(unknown)),
            [],
            "these reach for something the window does not have; a signal "
            "handler would swallow the AttributeError and the control would "
            "just do nothing (issue #237)",
        )

    def test_the_reader_actually_finds_the_references(self):
        # A parser that quietly matched nothing would make the test above
        # pass for the wrong reason.
        found = {
            name
            for source in UI_DIR.glob("*.py")
            for _lineno, name in _referenced(source)
        }
        self.assertIn("t", found, "no window.t() call was found anywhere")
        self.assertGreater(len(found), 20, f"suspiciously few references: {found}")

    def test_the_window_attributes_include_both_kinds(self):
        names = window_attributes()
        self.assertIn("refresh_library", names)  # a method
        self.assertIn("current_console", names)  # assigned in __init__


if __name__ == "__main__":
    unittest.main()

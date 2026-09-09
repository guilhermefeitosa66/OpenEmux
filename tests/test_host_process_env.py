"""Nothing OpenEmux starts inherits the AppImage's environment by accident.

An AppImage rewrites the loader path for everything it launches, which is
right for the bundle and wrong for every host program the app runs.
``appimage_env.host_env`` exists to undo it, and the bug is never that the
helper is wrong -- it is that a new ``subprocess`` call forgets to use it.
Four did, and each failed in its own quiet way on a distribution that is not
Ubuntu:

* the vendored RetroArch resolved a GTK4 app's libraries (issue #249);
* "Open folder" ran ``xdg-open``, a ``#!/bin/sh`` script, so the *host's*
  shell was loaded against the bundle's readline -- ``Popen`` succeeded, the
  child died, and the button silently did nothing;
* ``flatpak info``, the probe that finds a RetroArch Flatpak when there is no
  other, exited non-zero under the bundle's loader path (measured on Arch:
  ``libcrypto.so.3: version 'OPENSSL_3.4.0' not found``), so the app reported
  "RetroArch was not found" on a machine that had it;
* the PulseAudio probe runs ``sh`` for the same reason the second one does.

So this is a structural test rather than four more behavioural ones: every
``subprocess`` call in the app either passes an ``env``, or is listed below
with the reason it cannot be reached from a bundle.
"""

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "openemux"

#: Calls that legitimately inherit the environment, by ``file:function``, each
#: with the reason. Windows is the whole list today: there is no AppImage
#: there, so there is no bundle environment to shed.
ALLOWED = {
    "ui/window.py:_reveal_in_file_manager": (
        "Explorer's /select, on Windows -- guarded by IS_WINDOWS, and Windows "
        "ships no AppImage"
    ),
}


def _subprocess_calls(tree):
    """Every ``subprocess.run``/``subprocess.Popen`` call node in ``tree``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"run", "Popen"}
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            yield node


def _enclosing_function(tree, node):
    """The name of the function ``node`` sits in, or ``"<module>"``."""
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(parent):
            if child is node:
                return parent.name
    return "<module>"


class EveryStartedProcessGetsAnEnvironmentTests(unittest.TestCase):
    def test_no_subprocess_call_inherits_the_bundle_environment(self):
        offenders = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            for call in _subprocess_calls(tree):
                if any(keyword.arg == "env" for keyword in call.keywords):
                    continue
                where = f"{relative}:{_enclosing_function(tree, call)}"
                if where in ALLOWED:
                    continue
                offenders.append(f"{where} (line {call.lineno})")

        self.assertEqual(
            offenders,
            [],
            "these start a process with the AppImage's environment; pass "
            "env=host_env(os.environ), or add the call to ALLOWED with the "
            f"reason it cannot be reached from a bundle: {offenders}",
        )

    def test_the_allowlist_still_names_something(self):
        # An entry left behind after its call is deleted silently exempts
        # whatever function later takes that name.
        found = set()
        for path in PACKAGE_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            for call in _subprocess_calls(tree):
                found.add(f"{relative}:{_enclosing_function(tree, call)}")

        stale = sorted(set(ALLOWED) - found)
        self.assertEqual(stale, [], f"ALLOWED names calls that are gone: {stale}")


if __name__ == "__main__":
    unittest.main()

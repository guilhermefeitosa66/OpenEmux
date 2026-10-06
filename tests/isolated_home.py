"""A throwaway ``~/.openemux`` for tests that build the real thing.

Most of the suite hands ``ConfigManager`` a path and is done: every store sits
beside ``config.yaml``, wherever that is (issue #239). Four directories do not
follow it -- the playlists, the runtime, the save states and the ROM library --
because they are module-level defaults resolved from the real home at import,
and one of them, ``playlists_dir``, is also written into the default config
document itself.

That is fine until a test constructs something that reads them. An
``OpenEmuxWindow`` built against a bare temporary ``ConfigManager`` loads the
*developer's own* playlists, and its first rescan writes them back.

So: patch the four defaults, and overwrite the copy the config document
already carries. Everything the object under test touches then lands under one
directory the test owns and deletes.
"""

import tempfile
from pathlib import Path
from unittest import mock

#: The module-level defaults that do not follow ``config.yaml``, and the
#: subdirectory each one gets inside the throwaway home.
_REDIRECTED_DEFAULTS = {
    "DEFAULT_PLAYLISTS_DIR": "playlists",
    "DEFAULT_RUNTIME_DIR": "runtime",
    "DEFAULT_STATES_DIR": "states",
    "DEFAULT_ROMS_PATH": "roms",
    "DEFAULT_INPUT_DIR": "input",
}


class IsolatedHome:
    """Everything OpenEmux writes, redirected under ``root``.

    Call :meth:`start` for the ``ConfigManager`` to hand the object under
    test, and :meth:`stop` when the test is over -- ``addCleanup`` is the
    natural place for both.
    """

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path(tempfile.mkdtemp())
        self.roms = self.root / "roms"
        self.playlists = self.root / "playlists"
        self.states = self.root / "states"
        self.runtime = self.root / "runtime"
        self._patchers = []
        self.config = None

    def start(self):
        from openemux.core import config as config_module
        from openemux.core.config import ConfigManager

        for name, subdir in _REDIRECTED_DEFAULTS.items():
            patcher = mock.patch.object(config_module, name, self.root / subdir)
            patcher.start()
            self._patchers.append(patcher)

        self.roms.mkdir(parents=True, exist_ok=True)
        self.config = ConfigManager(self.root / "config.yaml")
        # The default config document was built at import time and carries the
        # real playlists path inside it, so patching the constant is not
        # enough.
        self.config.config.setdefault("library", {})["playlists_dir"] = str(
            self.playlists
        )
        self.config.config["roms_path"] = str(self.roms)
        # Two things a constructed window would otherwise do for real: run the
        # first-boot bootstrap (every libretro core, from the buildbot) and
        # ask GitHub whether there is a newer release.
        self.config.config.setdefault("updates", {})["check_on_startup"] = False
        self.config.save_config()
        self.config.finish_bootstrap_success()
        return self.config

    def stop(self):
        while self._patchers:
            self._patchers.pop().stop()

    def console_dir(self, console):
        """Create and return ``roms/<console>``."""
        path = self.roms / console
        path.mkdir(parents=True, exist_ok=True)
        return path

    def add_rom(self, console, filename, contents=b"rom"):
        """Drop a file the scanner will pick up, and return its path."""
        path = self.console_dir(console) / filename
        path.write_bytes(contents)
        return path

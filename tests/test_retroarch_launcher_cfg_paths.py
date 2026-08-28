"""Guard: no path written into RetroArch's runtime override may contain a backslash.

RetroArch's config parser treats ``\\`` inside a quoted value as an escape. So
``savestate_directory = "C:\\Users\\me\\.openemux\\states\\SFC"`` is read with
``\\U``, ``\\m``, ``\\.`` and ``\\S`` consumed, and the directory silently
becomes something else. Nothing raises, nothing is logged: the user just finds
their save states missing and concludes the app lost them.

That makes this the most dangerous class of bug in the Windows port -- silent,
data-losing, and invisible on the platform most of the development happens on.
The test therefore runs on **both** platforms, driving the writer with Windows
paths regardless of the host, so Linux CI catches a regression before a Windows
user does.
"""

import re
import unittest
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core.platform import cfg_path
from openemux.core.retroarch_launcher import RetroArchLauncher

from tests.test_retroarch_launcher import _DummyConfig

#: A RetroArch override line: ``key = "value"``. Only quoted values matter --
#: an unquoted numeric value cannot contain a path.
_QUOTED_VALUE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$')

#: Keys whose values are paths. Listed explicitly rather than inferred, so that
#: a new path-valued override added later fails this test until it is
#: considered -- which is the point.
_PATH_KEYS = {
    "system_directory",
    "savestate_directory",
    "video_shader",
    "core_options_path",
}


def _write_override(base, **kwargs):
    """Run the override writer, returning (lines, values cfg_path produced).

    ``cfg_path`` is wrapped rather than the output merely inspected. Checking
    the file for backslashes proves nothing on Linux, where the paths under
    test never contain one to begin with -- the test would pass whether or not
    the conversion happened, which is worthless on the platform that runs CI.
    Recording what the converter returned instead lets us assert that each
    path-valued override actually came *out of it*, and that holds identically
    on both platforms.
    """
    produced = []
    real = cfg_path

    def recording(value):
        result = real(value)
        produced.append(result)
        return result

    cfg = _DummyConfig(base, base / "retroarch", base / "mednafen_psx_libretro.so")
    # PS, not GBA: system_directory is only emitted for a core with a BIOS
    # requirement, and it is one of the values under test. The directory has
    # to exist as well.
    cfg.get_console_bios_dir("PS").mkdir(parents=True, exist_ok=True)
    launcher = RetroArchLauncher(base, cfg)
    with patch("openemux.core.retroarch_launcher.cfg_path", recording):
        path = launcher._write_runtime_override(
            "PS", core_filename="mednafen_psx_libretro.so", **kwargs
        )
    return Path(path).read_text(encoding="utf-8").splitlines(), produced


class RuntimeOverridePathTests(unittest.TestCase):
    def test_every_path_valued_override_goes_through_the_converter(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            lines, produced = _write_override(
                base,
                shader_path=str(base / "shaders" / "dot.glslp"),
                shader_enabled=True,
            )

        seen = set()
        for line in lines:
            match = _QUOTED_VALUE.match(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if key not in _PATH_KEYS:
                continue
            seen.add(key)
            self.assertIn(
                value,
                produced,
                f"{key} was written without going through cfg_path(); on Windows "
                f"its backslashes become escape sequences and the directory "
                f"silently resolves somewhere else",
            )

        # Without this, the loop above would also pass if the writer stopped
        # emitting paths altogether.
        self.assertIn("savestate_directory", seen)
        self.assertIn("system_directory", seen)

    def test_no_quoted_value_contains_a_backslash(self):
        # Meaningful on Windows, where the temporary paths really do contain
        # backslashes. Vacuous but harmless on Linux.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            lines, _ = _write_override(
                base,
                shader_path=str(base / "shaders" / "dot.glslp"),
                shader_enabled=True,
            )

        offenders = [
            line
            for line in lines
            if (match := _QUOTED_VALUE.match(line)) and "\\" in match.group(2)
        ]
        self.assertEqual(
            offenders,
            [],
            "these override values contain a backslash, which RetroArch reads as "
            "an escape sequence:\n  " + "\n  ".join(offenders),
        )

    def test_a_windows_path_is_converted_whatever_the_host(self):
        # The conversion is not conditional on sys.platform, so this is
        # meaningful on Linux too -- which is where it will actually run.
        windows_path = PureWindowsPath(r"C:\Users\me\.openemux\states\SFC")
        self.assertEqual(cfg_path(windows_path), "C:/Users/me/.openemux/states/SFC")

    def test_the_escapes_this_prevents(self):
        # Spelled out so the failure mode stays obvious to whoever reads this
        # next: every one of these is a valid escape to RetroArch's parser.
        raw = r"C:\Users\me\.openemux\states"
        self.assertIn("\\U", raw)
        self.assertIn("\\m", raw)
        self.assertIn("\\.", raw)
        self.assertNotIn("\\", cfg_path(raw))


if __name__ == "__main__":
    unittest.main()

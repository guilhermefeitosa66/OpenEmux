"""Choosing RetroArch's audio driver from the host (issue #176).

The bug this guards: OpenEmux ships its own RetroArch but launches it against
the user's global retroarch.cfg. When that names a driver the bundled build
lacks ("pipewire" is the one that bites), RetroArch falls back to alsa, alsa
fails on a PipeWire host, and audio never starts -- which surfaces as the
emulation running several times too fast, because RetroArch paces off the
audio clock.
"""

import os
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core.audio_driver import (
    AUTO,
    INHERIT,
    PULSE_DRIVER,
    detect_audio_driver,
    host_has_pulse,
    resolve_audio_driver,
)


class _Env:
    """Swap the audio-related environment for the duration of a test."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self._patch = mock.patch.dict(
            os.environ,
            {k: v for k, v in self.values.items() if v is not None},
            clear=True,
        )
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class HostDetectionTests(unittest.TestCase):
    def test_a_pulse_socket_in_the_runtime_dir_is_found(self):
        with TemporaryDirectory() as tmp:
            socket_dir = os.path.join(tmp, "pulse")
            os.makedirs(socket_dir)
            open(os.path.join(socket_dir, "native"), "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp):
                self.assertTrue(host_has_pulse())
                self.assertEqual(detect_audio_driver(), PULSE_DRIVER)

    def test_no_socket_means_no_opinion(self):
        # Nothing is written rather than guessing: a wrong guess could only
        # break a setup that currently works.
        with TemporaryDirectory() as tmp:
            with _Env(XDG_RUNTIME_DIR=tmp):
                self.assertFalse(host_has_pulse())
                self.assertIsNone(detect_audio_driver())

    def test_a_unix_pulse_server_path_is_honoured(self):
        with TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "custom-socket")
            open(sock, "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp, PULSE_SERVER=f"unix:{sock}"):
                self.assertTrue(host_has_pulse())

    def test_a_missing_unix_pulse_server_path_is_not_invented(self):
        with TemporaryDirectory() as tmp:
            with _Env(XDG_RUNTIME_DIR=tmp, PULSE_SERVER=f"unix:{tmp}/nope"):
                self.assertFalse(host_has_pulse())

    def test_a_remote_pulse_server_is_taken_at_its_word(self):
        # tcp: cannot be probed from here, but it was set deliberately.
        with TemporaryDirectory() as tmp:
            with _Env(XDG_RUNTIME_DIR=tmp, PULSE_SERVER="tcp:192.168.0.10:4713"):
                self.assertTrue(host_has_pulse())

    def test_no_runtime_dir_at_all_does_not_raise(self):
        with _Env():
            self.assertFalse(host_has_pulse())


class FlatpakHostDetectionTests(unittest.TestCase):
    """Under Flatpak the emulator runs on the host, so the host is asked.

    The sandbox is granted no audio socket of its own, so looking in its own
    runtime directory always answered "no PulseAudio here" -- the key went
    unwritten, RetroArch used whatever its config said, and the Flatpak
    install ran games at the monitor's refresh rate with no sound.
    """

    def _run_result(self, returncode):
        result = mock.Mock()
        result.returncode = returncode
        return result

    def test_a_host_socket_makes_it_pulse(self):
        with TemporaryDirectory() as tmp, _Env(XDG_RUNTIME_DIR=tmp):
            with mock.patch(
                "openemux.core.audio_driver.is_running_in_flatpak", return_value=True
            ), mock.patch(
                "openemux.core.audio_driver.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ), mock.patch(
                "openemux.core.audio_driver.subprocess.run",
                return_value=self._run_result(0),
            ) as run_mock:
                self.assertEqual(detect_audio_driver(), PULSE_DRIVER)
            command = run_mock.call_args[0][0]
            self.assertEqual(command[:4], ["flatpak-spawn", "--host", "sh", "-c"])
            self.assertIn(f"{tmp}/pulse/native", command[4])

    def test_a_host_without_pulse_keeps_its_silence(self):
        with TemporaryDirectory() as tmp, _Env(XDG_RUNTIME_DIR=tmp):
            with mock.patch(
                "openemux.core.audio_driver.is_running_in_flatpak", return_value=True
            ), mock.patch(
                "openemux.core.audio_driver.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ), mock.patch(
                "openemux.core.audio_driver.subprocess.run",
                return_value=self._run_result(1),
            ):
                self.assertIsNone(detect_audio_driver())

    def test_a_probe_that_fails_never_breaks_the_launch(self):
        with TemporaryDirectory() as tmp, _Env(XDG_RUNTIME_DIR=tmp):
            with mock.patch(
                "openemux.core.audio_driver.is_running_in_flatpak", return_value=True
            ), mock.patch(
                "openemux.core.audio_driver.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ), mock.patch(
                "openemux.core.audio_driver.subprocess.run",
                side_effect=OSError("no relay"),
            ):
                self.assertIsNone(detect_audio_driver())

    def test_outside_a_flatpak_the_host_is_never_asked(self):
        with TemporaryDirectory() as tmp, _Env(XDG_RUNTIME_DIR=tmp):
            with mock.patch(
                "openemux.core.audio_driver.is_running_in_flatpak", return_value=False
            ), mock.patch(
                "openemux.core.audio_driver.subprocess.run"
            ) as run_mock:
                self.assertIsNone(detect_audio_driver())
            run_mock.assert_not_called()


class SettingResolutionTests(unittest.TestCase):
    def test_auto_detects_from_the_host(self):
        with TemporaryDirectory() as tmp:
            socket_dir = os.path.join(tmp, "pulse")
            os.makedirs(socket_dir)
            open(os.path.join(socket_dir, "native"), "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp):
                self.assertEqual(resolve_audio_driver(AUTO), PULSE_DRIVER)

    def test_auto_is_the_default_for_an_unset_value(self):
        with TemporaryDirectory() as tmp:
            socket_dir = os.path.join(tmp, "pulse")
            os.makedirs(socket_dir)
            open(os.path.join(socket_dir, "native"), "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp):
                for unset in (None, "", "   "):
                    self.assertEqual(resolve_audio_driver(unset), PULSE_DRIVER)

    def test_inherit_writes_nothing(self):
        # The escape hatch back to the pre-#176 behaviour.
        with TemporaryDirectory() as tmp:
            socket_dir = os.path.join(tmp, "pulse")
            os.makedirs(socket_dir)
            open(os.path.join(socket_dir, "native"), "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp):
                self.assertIsNone(resolve_audio_driver(INHERIT))

    def test_an_explicit_driver_is_passed_through(self):
        # A deliberate JACK or bare-ALSA setup says so and is obeyed, even
        # where detection would have chosen pulse.
        with TemporaryDirectory() as tmp:
            socket_dir = os.path.join(tmp, "pulse")
            os.makedirs(socket_dir)
            open(os.path.join(socket_dir, "native"), "w").close()
            with _Env(XDG_RUNTIME_DIR=tmp):
                self.assertEqual(resolve_audio_driver("jack"), "jack")
                self.assertEqual(resolve_audio_driver("alsathread"), "alsathread")

    def test_the_value_is_normalised(self):
        self.assertIsNone(resolve_audio_driver("  INHERIT "))
        self.assertEqual(resolve_audio_driver(" JACK "), "jack")


if __name__ == "__main__":
    unittest.main()

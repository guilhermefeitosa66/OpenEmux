"""The seven concerns that make up a launch's ``--appendconfig`` file.

`_write_runtime_override` assembled all of them inline: bindings for five
device slots, stock-hotkey conflicts, analog modes, controller types, tuning,
turbo, notifications, the BIOS directory, shaders, the command channel, the audio
driver, save states and the window overrides -- 170 lines, each block carrying
its own comment saying which concern it was, which is structure standing in
for a name (issue #238).

They are helpers returning dicts now, and each can be asked its own question.
The existing tests in `test_retroarch_launcher.py` go through the writer and
read the file back; these go at the pieces directly, which is how the window
block -- the one that heals what the old game window leaked into users'
`retroarch.cfg` -- gets a test of its own rather than being read out of an
assembled file.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from openemux.core import retroarch_command, retroarch_launcher
from openemux.core.retroarch_launcher import RetroArchLauncher
from tests.test_retroarch_launcher import _DummyConfig


def _launcher(tmp="/tmp/openemux-test", **config_attrs):
    config = _DummyConfig(Path(tmp), "/usr/bin/retroarch", "/cores/core.so")
    for key, value in config_attrs.items():
        setattr(config, key, value)
    return RetroArchLauncher("/project", config), config


class TheShaderPieceTests(unittest.TestCase):
    def test_a_chosen_shader_is_named_and_switched_on(self):
        overrides = RetroArchLauncher._shader_overrides("/shaders/crt.slangp", True)
        self.assertEqual(overrides["video_shader_enable"], '"true"')
        self.assertIn("crt.slangp", overrides["video_shader"])

    def test_no_shader_says_so_rather_than_staying_quiet(self):
        # Silence would leave whatever the user's retroarch.cfg had turned on.
        overrides = RetroArchLauncher._shader_overrides(None, False)
        self.assertEqual(overrides, {"video_shader_enable": '"false"'})

    def test_a_path_with_the_switch_off_is_still_off(self):
        overrides = RetroArchLauncher._shader_overrides("/shaders/crt.slangp", False)
        self.assertEqual(overrides, {"video_shader_enable": '"false"'})
        self.assertNotIn("video_shader", overrides)


class TheSaveStatePieceTests(unittest.TestCase):
    def test_states_land_in_the_directory_they_are_given(self):
        overrides = RetroArchLauncher._savestate_overrides(Path("/states/SFC"), None)
        self.assertIn("/states/SFC", overrides["savestate_directory"])
        self.assertEqual(overrides["savestate_thumbnail_enable"], '"true"')

    def test_a_launch_with_no_slot_starts_on_zero(self):
        overrides = RetroArchLauncher._savestate_overrides(Path("/states/SFC"), None)
        self.assertEqual(overrides["state_slot"], '"0"')

    def test_a_play_from_this_state_launch_names_its_slot(self):
        overrides = RetroArchLauncher._savestate_overrides(Path("/states/SFC"), 3)
        self.assertEqual(overrides["state_slot"], '"3"')


class TheWindowPieceTests(unittest.TestCase):
    """RetroArch's own window, healed of what the game window leaked (#469)."""

    def _overrides(self, display):
        env = {"DISPLAY": display} if display else {}
        with patch.dict(retroarch_launcher.os.environ, env, clear=True), patch.object(
            retroarch_launcher, "IS_WINDOWS", False
        ):
            return RetroArchLauncher._window_overrides()

    def test_it_writes_retroarchs_defaults_back(self):
        # Stated rather than left alone: it heals a config an earlier version
        # already polluted -- borderless, and never pausing on focus loss.
        overrides = self._overrides(":0")
        self.assertEqual(overrides["video_window_show_decorations"], '"true"')
        self.assertEqual(overrides["pause_nonactive"], '"true"')

    def test_the_fullscreen_hotkey_is_left_to_the_profile(self):
        # The game window unbound it while it wrapped the game; the input
        # profile's own binding is what wins now.
        self.assertNotIn("input_toggle_fullscreen", self._overrides(":0"))

    def test_on_x11_the_context_is_probed_and_the_mouse_comes_from_x(self):
        overrides = self._overrides(":0")
        # Empty means "probe". Naming a context the build lacks would leave
        # the game with no video at all.
        self.assertEqual(overrides["video_context_driver"], '""')
        self.assertEqual(overrides["input_driver"], '"x"')

    def test_without_x_nothing_about_the_backend_is_imposed(self):
        overrides = self._overrides(None)
        self.assertNotIn("video_context_driver", overrides)
        self.assertNotIn("input_driver", overrides)
        self.assertEqual(overrides["log_to_file"], '"false"')


class TheSessionPieceTests(unittest.TestCase):
    def test_outside_windows_the_channel_is_stdin_and_udp_is_off(self):
        # Off rather than unset: a user's retroarch.cfg may have it on, and
        # RetroArch binds that socket on every interface.
        launcher, _config = _launcher()
        with patch.object(retroarch_command, "IS_WINDOWS", False):
            overrides = launcher._session_overrides(54321)
        self.assertEqual(overrides["stdin_cmd_enable"], '"true"')
        self.assertEqual(overrides["network_cmd_enable"], '"false"')
        self.assertNotIn("network_cmd_port", overrides)

    def test_on_windows_the_command_channel_is_on_and_on_the_given_port(self):
        launcher, _config = _launcher()
        with patch.object(retroarch_command, "IS_WINDOWS", True):
            overrides = launcher._session_overrides(54321)
        self.assertEqual(overrides["network_cmd_enable"], '"true"')
        self.assertEqual(overrides["network_cmd_port"], '"54321"')
        self.assertNotIn("stdin_cmd_enable", overrides)

    def test_no_port_falls_back_to_the_configured_one(self):
        launcher, _config = _launcher()
        with patch.object(retroarch_command, "IS_WINDOWS", True):
            overrides = launcher._session_overrides(None)
        self.assertEqual(overrides["network_cmd_port"], '"55355"')

    def test_nothing_this_launch_imposes_is_written_back(self):
        # The whole reason the embed overrides used to escape into the user's
        # own retroarch.cfg.
        launcher, _config = _launcher()
        self.assertEqual(launcher._session_overrides(None)["config_save_on_exit"], '"false"')

    def test_a_single_quit_datagram_is_enough(self):
        launcher, _config = _launcher()
        self.assertEqual(launcher._session_overrides(None)["quit_press_twice"], '"false"')


class TheAudioPieceTests(unittest.TestCase):
    def test_inheriting_writes_nothing(self):
        launcher, _config = _launcher(audio_driver="inherit")
        self.assertEqual(launcher._av_overrides(), {})

    def test_a_chosen_driver_is_named(self):
        launcher, _config = _launcher(audio_driver="pulse")
        self.assertEqual(launcher._av_overrides(), {"audio_driver": '"pulse"'})


class TheBiosPieceTests(unittest.TestCase):
    def test_a_core_that_needs_no_bios_gets_no_system_directory(self):
        launcher, _config = _launcher()
        self.assertEqual(launcher._bios_overrides("SFC", "snes9x_libretro.so"), {})

    def test_a_launch_with_no_core_chosen_gets_none_either(self):
        launcher, _config = _launcher()
        self.assertEqual(launcher._bios_overrides("PS", None), {})


class TheInputPieceTests(unittest.TestCase):
    def test_the_keyboard_profile_reaches_player_one(self):
        launcher, _config = _launcher()
        overrides = launcher._input_overrides("GBA")
        self.assertEqual(overrides["input_player1_a"], '"z"')
        self.assertEqual(overrides["input_player1_b"], '"x"')

    def test_turbo_timing_is_always_stated(self):
        launcher, _config = _launcher()
        overrides = launcher._input_overrides("GBA")
        for key in ("input_turbo_period", "input_turbo_duty_cycle", "input_turbo_mode"):
            self.assertIn(key, overrides)

    def test_select_as_a_modifier_gets_its_block_delay(self):
        launcher, _config = _launcher()
        self.assertEqual(launcher._input_overrides("GBA")["input_hotkey_block_delay"], '"5"')

    def test_a_disabled_extra_port_contributes_nothing(self):
        launcher, config = _launcher()
        config.input_profile = {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z"}},
                "gamepad_p2": {"type": "gamepad", "enabled": False, "bindings": {"a": "0"}},
            },
        }
        overrides = launcher._input_overrides("GBA")
        self.assertFalse([key for key in overrides if "player2" in key])

    def test_an_enabled_extra_port_gets_its_own_analog_mode(self):
        launcher, config = _launcher()
        config.input_profile = {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z"}},
                "gamepad_p2": {"type": "gamepad", "enabled": True, "bindings": {"a": "0"}},
            },
        }
        overrides = launcher._input_overrides("GBA")
        self.assertIn("input_player2_analog_dpad_mode", overrides)


if __name__ == "__main__":
    unittest.main()

"""The seven concerns that make up a launch's ``--appendconfig`` file.

`_write_runtime_override` assembled all of them inline: bindings for five
device slots, stock-hotkey conflicts, analog modes, controller types, tuning,
turbo, notifications, the BIOS directory, shaders, the UDP channel, the audio
driver, save states and the embed overrides -- 170 lines, each block carrying
its own comment saying which concern it was, which is structure standing in
for a name (issue #238).

They are helpers returning dicts now, and each can be asked its own question.
The existing tests in `test_retroarch_launcher.py` go through the writer and
read the file back; these go at the pieces directly, which is how the embed
block -- the one that leaked into users' `retroarch.cfg` -- gets a test of its
own rather than being read out of an assembled file.
"""

import unittest
from pathlib import Path

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


class TheEmbedPieceTests(unittest.TestCase):
    """The block that leaked into users' own retroarch.cfg (issues #199, #267)."""

    def test_without_a_wrapper_it_writes_retroarchs_defaults_back(self):
        launcher, _config = _launcher(game_window=False)
        overrides = launcher._embed_overrides()
        # Stated rather than left alone: it heals a config an earlier version
        # already polluted.
        self.assertEqual(overrides["video_window_show_decorations"], '"true"')
        self.assertEqual(overrides["pause_nonactive"], '"true"')

    def test_without_a_wrapper_nothing_else_is_imposed(self):
        launcher, _config = _launcher(game_window=False)
        overrides = launcher._embed_overrides()
        for key in ("video_fullscreen", "video_context_driver", "log_to_file"):
            self.assertNotIn(key, overrides)

    def test_without_a_wrapper_the_fullscreen_hotkey_is_left_alone(self):
        # With no wrapper the input profile's own binding is what should win;
        # unbinding it here is what left it permanently "nul".
        launcher, _config = _launcher(game_window=False)
        overrides = launcher._embed_overrides()
        self.assertNotIn("input_toggle_fullscreen", overrides)

    def test_with_a_wrapper_the_window_is_plain_and_undecorated(self):
        launcher, _config = _launcher(game_window=True)
        overrides = launcher._embed_overrides()
        self.assertEqual(overrides["video_fullscreen"], '"false"')
        self.assertEqual(overrides["video_windowed_fullscreen"], '"false"')
        self.assertEqual(overrides["video_window_show_decorations"], '"false"')
        self.assertEqual(overrides["video_window_save_positions"], '"false"')

    def test_with_a_wrapper_focus_hops_do_not_pause_the_game(self):
        launcher, _config = _launcher(game_window=True)
        self.assertEqual(launcher._embed_overrides()["pause_nonactive"], '"false"')

    def test_with_a_wrapper_the_fullscreen_hotkey_is_unbound_on_every_device(self):
        # Only the keyboard one was unbound before, and the gamepad binding
        # from the input profile survived: one press destroyed the embed
        # (issue #267).
        launcher, _config = _launcher(game_window=True)
        overrides = launcher._embed_overrides()
        for suffix in ("", "_btn", "_axis"):
            self.assertEqual(overrides[f"input_toggle_fullscreen{suffix}"], '"nul"')

    def test_with_a_wrapper_the_context_driver_is_emptied_not_pinned(self):
        # Empty means "probe". Naming a context the build lacks would leave
        # the game with no video at all.
        launcher, _config = _launcher(game_window=True)
        self.assertEqual(launcher._embed_overrides()["video_context_driver"], '""')


class TheSessionPieceTests(unittest.TestCase):
    def test_the_command_channel_is_on_and_on_the_given_port(self):
        launcher, _config = _launcher()
        overrides = launcher._session_overrides(54321)
        self.assertEqual(overrides["network_cmd_enable"], '"true"')
        self.assertEqual(overrides["network_cmd_port"], '"54321"')

    def test_no_port_falls_back_to_the_configured_one(self):
        launcher, _config = _launcher()
        self.assertEqual(launcher._session_overrides(None)["network_cmd_port"], '"55355"')

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

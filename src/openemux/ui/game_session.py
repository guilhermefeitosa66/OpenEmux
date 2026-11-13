"""The running game: launching it, relaunching it, and noticing when it is
over.

Everything about a game between the click and the exit toast. It was several
responsibilities' worth of methods on `OpenEmuxWindow` -- launch, the relaunch
dance, the input hot-apply and the runtime poll -- held together by state
nothing else in the window touched (issue #237). The game itself plays in
RetroArch's own window, with the controls RetroArch draws (issue #469).

The relaunch is the reason they belong together: applying a remap to a running
game (issue #129) means snapshotting to a scratch slot, waiting for the file
to land, relaunching with the regenerated override and loading the snapshot
back -- four steps across three timers, each of which has to know what the
others are doing.
"""

import logging
import threading
from pathlib import Path

from openemux.core.play_history import format_play_time
from openemux.core.systems import get_system_display_name

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

logger = logging.getLogger(__name__)

#: Relaunch polls for the old process to exit rather than blocking the main
#: loop on wait(). The budget has to outlast the stop escalation it is
#: waiting on -- QUIT, then SIGTERM, then SIGKILL, two seconds apart -- or a
#: RetroArch that ignores QUIT is declared un-relaunchable while it is still
#: being killed. 200 ms x 40 gives it 8 s, comfortably past the ~6 s walk
#: (issues #129, #267).
RELAUNCH_POLL_INTERVAL_MS = 200
RELAUNCH_MAX_POLLS = 40

#: Applying a remap to a running game waits for the scratch save state to hit
#: the disk before relaunching (issue #129). 200 ms x 25 gives a slow core
#: ~5 s to write it; a core without save-state support never does, and the
#: timeout is what keeps that from becoming a relaunch that loses the game.
SNAPSHOT_POLL_INTERVAL_MS = 200
SNAPSHOT_MAX_POLLS = 25

#: How long after a relaunch the scratch state is loaded back, mirroring
#: launch_at_state's boot allowance; the scratch file is deleted a few
#: seconds after that, once RetroArch can no longer need it.
RESUME_LOAD_DELAY_S = 4
RESUME_DISCARD_DELAY_S = 10

#: How long a launch-and-load-state waits before sending LOAD_STATE. RetroArch
#: has no launch-and-load flag to pass, so the state goes out as a command once
#: the game has had a moment to boot.
STATE_LOAD_DELAY_S = 4


def _run_in_worker(target):
    """Run ``target`` on a daemon thread; the one seam the tests replace."""
    threading.Thread(target=target, name="openemux-launch", daemon=True).start()


class GameSession:
    """Owns the running game.

    Holds the window for the things a session has to reach -- the runtime
    manager, toasts, the play history -- and owns the one piece of state that
    is nobody else's: whether a relaunch is walking the stop/start dance right
    now.
    """

    def __init__(self, window):
        self.win = window
        #: True while a relaunch is walking the stop/start dance, so the
        #: runtime poll does not announce the game as finished mid-relaunch.
        self._relaunch_in_flight = False
        #: The ROM whose launch is on the worker right now, or None (issue
        #: 904); the banner task that says "Starting…" and then "Playing";
        #: and whether Stop was pressed before the process was even up.
        self._launching = None
        self._launch_task = None
        self._stop_requested = False
        #: Set by Stop while a core is still downloading for the launch.
        self._cancel_event = None

    # ----- launching ------------------------------------------------------
    def _error_text(self, message):
        """What core said, in the user's language.

        ``RuntimeManager`` has no locale and no business having one, so a
        failure it can name returns a translation key ("a game is already
        running") rather than an English sentence (issue #232). ``tr`` falls
        back to its argument for anything it does not know, so the launcher's
        free-text failures -- a core that will not start, a path that is not
        there -- still pass through untouched, and so does text this class
        already translated itself.
        """
        return self.win.t(message)

    def launch(self, rom, resume=True, check_bios=True):
        """Start ``rom``; ``resume=False`` is "Start fresh" (issue 910).

        With "Resume where I left off" on, a launch picks up the automatic
        state RetroArch saved on the last exit; "Start fresh" skips it once.
        ``check_bios=False`` is "Launch anyway" from the BIOS dialog.

        The launch itself runs on a worker (issue 904): the card shows
        "Starting…" in the same frame as the click, and the cfg parsing,
        the globs and the process start never block the window.
        """
        if self._launching is not None:
            logger.info("launch ignored while another starts: rom=%s", rom.get("name"))
            return
        # Whatever the user just changed reaches the disk before the game
        # does: a session that ends with the app is the one that would lose
        # the last half second of settings (issue 905).
        self.win.config_manager.flush()
        if check_bios:
            missing = self.win.missing_bios_for_console(rom["console"])
            if missing:
                self._ask_about_bios(rom, missing, resume)
                return
        self._start(rom, {"resume": resume, "check_bios": check_bios})

    def _ask_about_bios(self, rom, missing, resume):
        """Name the system files the core lacks, and offer the BIOS page (issue 904).

        A 5-second toast with an absolute path used to be all the user got.
        "Launch anyway" lets RetroArch try without them, which some cores
        survive.
        """
        t = self.win.t
        dialog = Adw.AlertDialog(
            heading=t("bios.dialog.heading", console=get_system_display_name(rom["console"])),
            body=t("bios.dialog.body", names=", ".join(missing)),
        )
        dialog.add_response("cancel", t("bios.dialog.cancel"))
        dialog.add_response("launch", t("bios.dialog.launch"))
        dialog.add_response("open", t("bios.dialog.open"))
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("open")
        dialog.set_close_response("cancel")

        def _on_response(_dialog, response):
            if response == "open":
                self.win.open_bios_settings(rom["console"])
            elif response == "launch":
                self._start(rom, {"resume": resume, "check_bios": False})

        dialog.connect("response", _on_response)
        dialog.present(self.win)

    def _start(self, rom, kwargs, on_started=None, announce=True):
        """Run the launch on a worker; ``_finish_start`` picks up on the main loop."""
        self._launching = rom
        self._stop_requested = False
        self.win.set_rom_launching(rom, True)
        self._launch_task = self.win.tasks.begin(
            "launch",
            self.win.t("banner.starting", name=rom["name"]),
            on_cancel=self.stop,
            cancel_label=self.win.t("banner.stop"),
        )
        runtime = self.win.runtime_manager
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        task_id = self._launch_task

        def _progress(evt):
            # "Preparing Super Nintendo… (2/3)": the core coming down for
            # this launch, on the same banner (issue 909).
            GLib.idle_add(
                self.win.tasks.update,
                task_id,
                evt.get("current", 0),
                evt.get("total", 0),
                self.win.t(
                    "banner.preparing", console=get_system_display_name(rom["console"])
                ),
            )

        def _work():
            try:
                state = self.win.prepare_console_core(
                    rom["console"], on_progress=_progress, cancel_event=cancel_event
                )
                if state == "cancelled":
                    result = (False, None)
                elif state == "failed":
                    result = (
                        False,
                        self.win.t(
                            "toast.core_download_failed",
                            console=get_system_display_name(rom["console"]),
                        ),
                    )
                else:
                    result = runtime.launch(rom["path"], rom["console"], **kwargs)
            except Exception as exc:
                # The worker is where an exception would go to die quietly;
                # it comes back as the message the user sees (issue #226).
                logger.exception("launch failed")
                result = (False, self.win.t("toast.launch_failed", error=str(exc)))
            GLib.idle_add(self._finish_start, rom, result, on_started, announce)

        _run_in_worker(_work)

    def _finish_start(self, rom, result, on_started, announce):
        success, error_msg = result
        self._launching = None
        self.win.set_rom_launching(rom, False)
        if success:
            # Stamped here rather than on exit: a game that fails to close
            # cleanly was still played, and this is the only point that knows
            # which ROM was asked for.
            self.win.play_history.record_launch(rom["path"])
            self.win.tasks.update(
                self._launch_task, label=self.win.t("banner.playing", name=rom["name"])
            )
            if self._stop_requested:
                # Stop was pressed while the process was still coming up.
                self.win.runtime_manager.stop_active()
            if announce:
                self._toast_now(
                    self.win.t(
                        "toast.running",
                        name=rom["name"],
                        console=get_system_display_name(rom["console"]),
                    ),
                    3,
                )
                self._announce_launch_notice()
            if on_started is not None:
                on_started()
        else:
            self.win.tasks.finish(self._launch_task)
            self._launch_task = None
            if self._stop_requested and not error_msg:
                # Cancelled by the user: nothing to report.
                return GLib.SOURCE_REMOVE
            if error_msg:
                # Logged as well as toasted: the toast is gone in five
                # seconds, and a bug report built from the log must show
                # what the user saw. The untranslated message, so the report
                # reads the same whatever language the reporter runs in.
                logger.error(
                    "launch failed: console=%s rom=%s error=%s",
                    rom["console"], rom["name"], error_msg,
                )
                self._toast_now(self._error_text(error_msg), 5)
        return GLib.SOURCE_REMOVE

    def stop(self):
        """The banner's Stop button: quit the game, or the one about to start.

        While a core is still downloading for the launch, Stop cancels the
        download and the launch with it (issue 909).
        """
        if self._launching is not None:
            self._stop_requested = True
            if self._cancel_event is not None:
                self._cancel_event.set()
            return
        self.win.runtime_manager.stop_active()

    def _announce_launch_notice(self):
        """Say what a launch that *worked* still could not do.

        A console configured with a CRT shader that comes up without one is
        invisible otherwise -- the game runs, nothing is wrong on screen, and
        the only trace used to be an INFO line in a log file (issue #366).
        Queued behind the "Running" toast, which Adwaita handles.
        """
        notice = getattr(self.win.runtime_manager, "launch_notice", None)
        if not notice:
            return
        key, kwargs = notice
        self._toast_now(self.win.t(key, **kwargs), 6)

    def launch_at_state(self, rom, slot):
        """Launch a ROM parked on ``slot`` and load that state once it is up.

        RetroArch has no launch-and-load flag OpenEmux could pass, so this is
        best effort: the slot is seeded via the runtime override, and the
        LOAD_STATE command goes out after the game had a moment to
        boot. If the game is slower than that, the state is one hotkey away
        on the already-selected slot.
        """
        if self._launching is not None:
            return

        def _load_when_up():
            if self.win.runtime_manager.is_running():
                self.win.runtime_manager.load_state()
            return False

        def _started():
            self.win._toast(self.win.t("states.toast.launching", name=rom["name"], slot=slot))
            GLib.timeout_add_seconds(STATE_LOAD_DELAY_S, _load_when_up)

        self._start(rom, {"state_slot": slot}, on_started=_started, announce=False)

    def relaunch(self, resume_marker=None):
        """Stop the running game and start the same ROM again.

        Not the same thing as Restart (#130): only a fresh process re-reads
        the runtime override, so this is the only way an input remap takes
        effect (#129). The wait for the old process is polled rather than
        blocking -- wait() on the main loop would freeze the UI.

        With ``resume_marker`` (a confirmed snapshot from
        ``RuntimeManager.snapshot_active``), the scratch state is loaded back
        once the new process has had time to boot, so the relaunch carries
        the gameplay across instead of starting the game over.
        """
        runtime = self.win.runtime_manager
        rom, error_msg = runtime.relaunch_active()
        if rom is None:
            if error_msg:
                self.win._toast(error_msg, timeout=4)
            return False

        # Held across the whole dance: the process is about to exit on
        # purpose, and the runtime poll must not report that as the game
        # finishing.
        self._relaunch_in_flight = True
        self.win._toast(self.win.t("toast.relaunching"))
        remaining = [RELAUNCH_MAX_POLLS]

        def _discard_scratch():
            runtime.discard_snapshot(resume_marker)
            return False

        def _resume_when_up():
            if runtime.is_running():
                runtime.load_state_slot(resume_marker["slot"])
                GLib.timeout_add_seconds(RESUME_DISCARD_DELAY_S, _discard_scratch)
            return False

        def _launch_when_free():
            if runtime.is_running():
                remaining[0] -= 1
                if remaining[0] > 0:
                    return True
                self._relaunch_in_flight = False
                self.win._toast(self.win.t("toast.relaunch_failed"), timeout=5)
                return False
            self._relaunch_in_flight = False
            success, launch_error = runtime.relaunch_rom(rom)
            if not success and launch_error:
                self.win._toast(launch_error, timeout=5)
            if success and resume_marker is not None:
                GLib.timeout_add_seconds(RESUME_LOAD_DELAY_S, _resume_when_up)
            return False

        GLib.timeout_add(RELAUNCH_POLL_INTERVAL_MS, _launch_when_free)
        return True

    def apply_input_changes(self):
        """Make a saved remap reach the running game, keeping its progress.

        The whole of issue #129: the process only reads bindings at spawn and
        the command interface has no config or remap verb, so the change is
        carried across a relaunch -- snapshot to a scratch slot, wait for the
        file to actually land, relaunch with the regenerated override, load
        the snapshot back. If the core cannot save states the timeout fires
        and nothing is relaunched: losing the game to apply a binding is
        worse than the binding waiting for the next launch.
        """
        runtime = self.win.runtime_manager
        if not runtime.is_running():
            return False
        marker = runtime.snapshot_active()
        if marker is None:
            self.win._toast(self.win.t("toast.input_apply.no_state"), timeout=5)
            return False
        self.win._toast(self.win.t("toast.input_apply.saving"))
        remaining = [SNAPSHOT_MAX_POLLS]

        def _relaunch_when_saved():
            if runtime.snapshot_ready(marker):
                self.relaunch(resume_marker=marker)
                return False
            if not runtime.is_running():
                # The game quit on its own mid-apply; the change simply
                # applies to the next launch, nothing to report.
                return False
            remaining[0] -= 1
            if remaining[0] > 0:
                return True
            self.win._toast(self.win.t("toast.input_apply.no_state"), timeout=5)
            return False

        GLib.timeout_add(SNAPSHOT_POLL_INTERVAL_MS, _relaunch_when_saved)
        return True

    # ----- noticing the end -----------------------------------------------
    def poll(self):
        # Always polled, even mid-relaunch: this is what closes the log
        # handle and clears the finished process. Only the announcement is
        # held back, because a relaunch stops the game on purpose and
        # "Game finished" would be a lie (issue #267).
        result = self.win.runtime_manager.poll_active()
        if result is not None and self._relaunch_in_flight:
            return True
        if result is not None:
            rom = result.get("rom") or {}
            name = self._game_name(rom)
            reason = result.get("failure_reason")
            if self._launch_task is not None:
                self.win.tasks.finish(self._launch_task)
                self._launch_task = None
            if rom.get("path") and not reason:
                # The session's length goes on the game's play time (issue
                # 910); a launch that died never ran, so it adds nothing.
                self.win.play_history.record_play_time(rom["path"], result.get("ran_for"))
            if reason:
                # It never started. Say so, and say what the log said -- the
                # exit code alone reads exactly like a clean quit (#226).
                title = self.win.t("toast.launch_died", name=name, reason=reason)
                self._toast_now(title, 10, show_log=True)
            else:
                # What the player did, in their words (issue 904): the game's
                # title and the time; the exit code only when it is not zero,
                # with the log one click away.
                played = self._duration_text(result.get("ran_for"))
                code = result.get("exit_code") or 0
                if code:
                    title = self.win.t("toast.played.code", name=name, time=played, code=code)
                    self._toast_now(title, 8, show_log=True)
                else:
                    self._toast_now(self.win.t("toast.played", name=name, time=played), 4)
            if rom.get("path"):
                self.win.on_game_ended(rom)
        return True

    def _game_name(self, rom):
        """The game's title for a message: the index's name, else the file's stem."""
        path = rom.get("path")
        if not path:
            return "Game"
        name = None
        if rom.get("console"):
            name = self.win.playlist_manager.name_for_path(rom["console"], path)
        return name or Path(path).stem

    def _duration_text(self, seconds):
        hours, minutes = format_play_time(seconds)
        if hours:
            return self.win.t("duration.hours", hours=hours, minutes=minutes)
        if minutes:
            return self.win.t("duration.minutes", minutes=minutes)
        return self.win.t("duration.under_minute")

    def _toast_now(self, title, timeout, show_log=False):
        toast = Adw.Toast(title=title)
        toast.set_timeout(timeout)
        if show_log:
            # The log panel holds what RetroArch said (issue 904).
            toast.set_button_label(self.win.t("toast.show_log"))
            toast.connect("button-clicked", lambda _toast: self.win.set_log_panel_visible(True))
        self.win.toast_overlay.add_toast(toast)

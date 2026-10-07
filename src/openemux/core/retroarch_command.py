"""RetroArch's command interface: how the app talks to a running game (#69).

RetroArch accepts plain-text commands. The app sends few: ``QUIT`` when it
closes a game, and ``SAVE_STATE_SLOT n`` / ``LOAD_STATE_SLOT n`` /
``LOAD_STATE`` for the state manager and the input hot-apply. The in-game
controls do not come through here at all -- they are RetroArch's own overlay
(issue #469). RetroArch reads commands from two places, and which one a launch uses is a
security decision, not a detail:

- **Its standard input** (``stdin_cmd_enable``), everywhere RetroArch has it
  -- every Linux build. The launcher starts RetroArch with a pipe for stdin
  and this process holds the only other end, so nothing else on the machine,
  let alone the network, can send the game a command.
- **UDP** (``network_cmd_enable`` + ``network_cmd_port``), on Windows only:
  libretro's Windows build is compiled without the stdin interface -- the
  vendored ``retroarch.exe`` carries none of its runtime messages; configure
  gates it on ``fcntl`` -- and there is no third way in. The Unix-socket
  interface upstream has is built for Lakka alone.

The UDP socket is **not** loopback-only, whatever it looks like. RetroArch
binds it with a NULL host, which ``socket_init`` turns into ``AI_PASSIVE`` --
the wildcard address. Measured against the vendored 1.22.2 and the Flathub
build: the socket is ``0.0.0.0:<port>``, and a ``VERSION`` sent to the
machine's LAN address was answered. Unless a host firewall drops it, anyone
on the local network can QUIT, RESET, pause, save over or load a state in a
game while it runs, with no authentication at all. That is why Linux does not
use it -- and why the launcher turns it *off* there rather than leaving it
unset, since a user's own ``retroarch.cfg`` may have it on.

Fire-and-forget on purpose: RetroArch's replies are never read, and the UI
must never block on the emulator.
"""

import logging
import os
import socket
import threading

from openemux.core.platform import IS_WINDOWS

logger = logging.getLogger(__name__)


def uses_stdin_channel():
    """Does a launch talk to RetroArch through its stdin rather than UDP?

    Everywhere but Windows, whose RetroArch build has no stdin interface. The
    launcher asks this to decide what to enable and whether to give the
    process a stdin pipe; see the module docstring for why UDP is the last
    resort.
    """
    return not IS_WINDOWS


DEFAULT_NETWORK_CMD_PORT = 55355

#: ``network_cmd_port`` set to this means "pick a free one per launch".
AUTO_NETWORK_CMD_PORT = 0


def pick_free_udp_port(host="127.0.0.1"):
    """A UDP port nothing is listening on, for one launch's command channel.

    RetroArch's own default is 55355, and it binds the socket with the reuse
    flags set: a standalone RetroArch the user started themselves binds the
    same port happily, and the kernel then hands each datagram to one of the
    two by a hash of the sending socket. A whole session's volume, save-state
    and QUIT commands can land in the wrong emulator, which looks exactly like
    the controls drifting out of sync (issue #227).

    Falls back to the default port if the probe fails -- a broken channel is
    still better than refusing to launch.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((host, 0))
            return int(probe.getsockname()[1])
    except OSError as exc:
        logger.warning("could not pick a free command port: %s", exc)
        return DEFAULT_NETWORK_CMD_PORT

class StdinCommandClient:
    """Writes commands into a running RetroArch's stdin pipe. Never raises.

    One command per line, which is how RetroArch's stdin interface splits
    them. Never blocks either: the pipe is switched to non-blocking, so a
    RetroArch that stops reading -- hung, or a build without the stdin
    interface -- fills the pipe buffer and from then on a command is refused
    instead of freezing the thread that sent it, which for most commands is
    the UI's. Every command is far below ``PIPE_BUF``, so POSIX makes each
    write all-or-nothing: a refused command never leaves half a line in the
    pipe to corrupt the next one.
    """

    def __init__(self, stream):
        #: The ``Popen.stdin`` this client writes into; the runtime manager
        #: compares it to tell whether the cached client is for this game.
        self.stream = stream
        self._lock = threading.Lock()
        self._fd = None
        try:
            fd = stream.fileno()
            os.set_blocking(fd, False)
            self._fd = fd
        except (AttributeError, OSError, ValueError) as exc:
            logger.warning("retroarch stdin channel unusable: %s", exc)

    def close(self):
        """Close our end of the pipe. RetroArch reads EOF and plays on."""
        with self._lock:
            self._fd = None
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass

    def send(self, command):
        """Send one command; True when the whole line went into the pipe."""
        payload = (command or "").strip()
        if not payload:
            return False
        line = (payload + "\n").encode("utf-8")
        with self._lock:
            if self._fd is None:
                return False
            try:
                return os.write(self._fd, line) == len(line)
            except OSError as exc:
                # BlockingIOError: the pipe is full, so RetroArch is not
                # reading. BrokenPipeError: RetroArch is gone.
                logger.warning("retroarch command failed: cmd=%s error=%s", payload, exc)
                return False


class RetroArchCommandClient:
    """Sends UDP network commands to a running RetroArch. Never raises.

    The Windows channel only -- see the module docstring for why a Linux
    launch never opens the socket this talks to.
    """

    def __init__(self, port=DEFAULT_NETWORK_CMD_PORT, host="127.0.0.1"):
        self.port = int(port)
        self.host = host
        # One reusable socket rather than one per packet: a volume walk is
        # dozens of datagrams and each fresh socket is a syscall pair for no
        # gain. Guarded because the pacer sends from its own thread.
        self._sock = None
        self._sock_lock = threading.Lock()

    def _ensure_socket(self):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return self._sock

    def _drop_socket(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        with self._sock_lock:
            self._drop_socket()

    def send(self, command):
        """Send one command; True when the packet left, False otherwise."""
        payload = (command or "").strip()
        if not payload:
            return False
        try:
            with self._sock_lock:
                self._ensure_socket().sendto(
                    payload.encode("utf-8"), (self.host, self.port)
                )
            return True
        except OSError as exc:
            # A broken socket must not stay cached, or every later command
            # fails against the same dead handle.
            with self._sock_lock:
                self._drop_socket()
            logger.warning("retroarch command failed: cmd=%s error=%s", payload, exc)
            return False

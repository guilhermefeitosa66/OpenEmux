# OpenEmux 1.11.1

A single fix, for the worst kind of bug: the one where closing a window did not actually close anything.

## A closed game kept playing

Launch a game, then close its window with the "×". The window went away — and the game kept running. You could still hear it, there was nothing left on screen to click, and the only way to end it was to find `retroarch` in a process manager and kill it by hand. The next launch then refused to start, because as far as OpenEmux was concerned a game was already running.

Underneath were **two separate failures**, and the game had to survive both of them to get away.

**The polite request was ignored.** When its window closes, OpenEmux asks RetroArch to quit over the network command channel — the clean shutdown, the one that flushes battery saves on the way out. But RetroArch routes that command through the same path as its own quit key, and its default answers the *first* quit with *"press again to exit"* rather than quitting. So the request that was supposed to end the game reliably did nothing at all, every single time.

**The signal behind it could not reach the emulator.** When that request goes unanswered, OpenEmux terminates the process instead. On a **Flatpak** install, though, the process OpenEmux holds is only a relay into the host, and the signal it forwards stops one step short of the sandbox RetroArch actually runs in — which lives on happily. Meanwhile the game window had already handed RetroArch's own window back before closing (so the emulator does not crash on losing it), and that is exactly why the game turned invisible but stayed audible.

## The fix

Every launch now tells RetroArch that a single quit command means quit, and the Flatpak launch ties the emulator's sandbox to the process OpenEmux holds, so a stop signal reaches it.

Stopping a game is now **one escalation that does not give up**: ask RetroArch to quit, then terminate, then kill — each step only if the game is still there. In practice it ends at the first step, in a fraction of a second, with save data flushed. The stock RetroArch configuration on your machine is left untouched; all of this is applied per launch.

## Closing the library now closes the game

A game OpenEmux started should never outlive OpenEmux. Closing the library window while a game is running now ends that game too — including when the game has its own RetroArch window ("Play in an OpenEmux window" turned off) — instead of leaving a process behind that nothing in the app can reach anymore.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to configure: update and the next game you launch is already covered. Settings, playlists, artwork, save states and input profiles are all kept. If a game from a previous session is still running in the background right now, end it once from your process manager — from this version on, OpenEmux takes care of it.

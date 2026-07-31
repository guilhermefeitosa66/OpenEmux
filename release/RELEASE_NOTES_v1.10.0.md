# OpenEmux 1.10.0

This one is about controls. A detailed hands-on test of 1.9.2 from the community turned up something uncomfortable: on almost every console, OpenEmux was sending RetroArch **no gamepad configuration at all**. Games still responded, because RetroArch maps common pads by itself — which is exactly why nobody caught it. That single bug was hiding a dozen others behind it.

So this release fixes the foundation, and then builds the controller settings that should have been there all along: analog sticks that work, the hotkeys that were missing, deadzone and sensitivity for a worn stick, and control changes that reach a game **while you are playing it**.

## Your controller is actually configured now

OpenEmux wrote only one input device's mapping — whichever was set as the profile's "input device", which defaulted to keyboard on every console. In practice that meant 30 of 31 profiles sent RetroArch nothing for the pad: no button map, no hotkeys, no analog stick.

There was never a reason to choose. RetroArch keeps keyboard and joypad bindings under separate keys, so both can be live at once without colliding. **Both are now sent, always.** The N64 profile that produced the report went from zero controller settings to 26, the analog stick among them — which is very likely why the stick did nothing in Super Mario 64.

The "Input device" row no longer decides what reaches the emulator. It is what it always looked like: which mapping you are currently editing.

## Change your controls without losing your game

Previously, remapping a button while playing did nothing until you closed the game and opened it again — and the relaunch we offered started you over from the beginning, which is not a fix anybody wants mid-boss.

Now, **saving your controls applies them to the running game and puts you back exactly where you were.** OpenEmux snapshots the game to an internal slot, relaunches with the new bindings, and restores the snapshot — your own save states are never touched. If the core cannot save states, nothing is relaunched and OpenEmux tells you the change waits for the next launch, rather than gambling with your progress.

## The hotkeys that were missing

Nine more actions can be bound, each with a keyboard default: **rewind** (`w`), **pause** (`p`), **slow motion** (`o`), **hold to fast-forward** (`h`), **screenshot** (`F8`), **game focus** (`g`), and disk control — **eject** (`F9`), **next disk** (`n`), **previous disk** (`b`).

Disk control is not a convenience. Without it, a two-disc PlayStation, Saturn or Mega CD game simply could not be finished from inside OpenEmux.

Save and load state hotkeys also work on a gamepad for the first time: the defaults pointed at buttons 11–15, which most controllers do not have. And **Restart** is now a bindable hotkey rather than a header button, so you can reset a game without reaching for the mouse.

## Analog sticks, from both sides

- **Play the stick from the keyboard.** An N64 or PlayStation game that needs analog could not be played without a pad. The stick is now four bindable directions on `i` / `j` / `k` / `l` — WASD-shaped, but on the right hand, leaving the arrows on the D-pad.
- **Let a pad's D-pad move the stick**, per console, for games that only read analog.
- **Forced analog-to-digital modes** are offered where they are the only ones that do anything — the consoles whose cores read the stick natively.
- The stick's axes are now actually declared to RetroArch, so the analog-to-D-pad setting stops being a no-op.

## Tune it to your hardware

A drifting or worn stick is one of the most common real-world controller faults, and the app offered nothing for it. **Deadzone, sensitivity and the axis threshold** are now settings, alongside **vibration strength, input latency, game focus** and the core's own button names.

You can also **choose which controller the core is told is plugged in** — a PlayStation boots as a digital pad, and an analog game needs DualShock selected here just as it does in RetroArch.

These are global rather than per console: a stick drifts the same on every system, and setting the deadzone thirty-one times is not a feature. Each carries RetroArch's own default, and a value you have not changed is not written at all — an untouched install produces exactly the configuration it did before.

## Keyboard bindings that RetroArch can read

Keyboard bindings were stored under GTK's key names, which RetroArch cannot parse — so some keys silently never worked. They are now written as names RetroArch resolves. Restart, mute, turbo and save-slot stepping also get sensible keyboard defaults, and the RetroArch hotkeys that would have fired alongside them are cleared, so one key does one thing.

## The volume slider reaches the game

Dragging the master volume did nothing while mute worked, which was a strange pair of symptoms. RetroArch reads its control channel once per frame, and a drag was firing dozens of steps into a single frame, where nearly all of them were dropped. The steps are now paced, so the slider moves the volume of the running game.

## Artwork you can see and fix

**Missing artwork is now visible.** In the cartridge shelf a game with no art quietly rendered a blank sticker, so you could not tell it apart from one that simply had a plain label. A muted badge now marks it in every view, there is a **"Only without artwork"** filter in the view menu, and the empty cover carries a **Search artwork…** button that opens the artwork manager right where you noticed the gap.

Cover sync also gained a last-resort fuzzy pass for titles that no exact match reaches — `Aero Fighters (Sonic Wings)` now tries both halves — and the sync summary names the games that missed instead of only counting them.

**Covers no longer stall the interface.** Decoding ran on the main thread with one unbounded thread per ROM, which saturated a single core and made a large library feel stuck. Decoding now happens off the main thread on a bounded pool.

## Every icon ships with the app

Screenshots from users showed blank buttons and empty menu entries. The interface asked the desktop's icon theme for around sixty symbolic icons, and themes that do not inherit from Adwaita — Mint-Y, Papirus, Breeze — simply do not have them.

All of them are now **bundled inside OpenEmux** and used as a fallback: your desktop's theme still wins wherever it has the icon, and nothing can be missing where it does not. The build now fails if an icon is ever left out, in all four package formats.

## Around the app

- **Settings is one click from the header**, instead of only through the menu, and a console's page can jump straight to its controller settings.
- **Set a console's default core and shader from the sidebar**, without opening Settings at all.
- Context submenus open on hover rather than needing a click, and the ROM menu has been tidied.
- The window opens at 80% of your screen instead of a fixed box, so it fits laptops and large displays alike.

## Language and first run

The five stub translations — Spanish, French, German, Japanese and Chinese — are **complete**, and changing the language now updates every part of the interface immediately, including the window behind the dialog. "Preferences" is called **Settings**, matching the rest of GNOME.

The Welcome Assistant was rebuilt around a real misunderstanding: people were reading "New collection" as the way to import ROMs. Collections are now **playlists** everywhere, importing has its own labelled button, the empty library page leads with drag-and-drop, and the first slide carries a language picker — because someone who cannot read that slide cannot find Settings either.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to do. Settings, playlists, artwork and input profiles are all kept.

Your existing input profiles are migrated once to pick up the new hotkey defaults, and — this is the one worth knowing — **your gamepad will now be configured by OpenEmux where it previously fell back to RetroArch's own mapping.** If a pad behaved a certain way before and you preferred it, Settings → Input is now the place that decides.

## Thanks

This release exists because **[@mozertdev](https://github.com/mozertdev)** worked through 1.9.2 in detail on [Diolinux Plus](https://plus.diolinux.com.br/) and wrote up everything that was wrong with it — including the gamepad bug that was hiding behind RetroArch's autoconfig. Most of what is above traces back to that report.

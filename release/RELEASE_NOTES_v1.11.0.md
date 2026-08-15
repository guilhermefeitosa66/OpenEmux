# OpenEmux 1.11.0

Two things change shape in this release. Games no longer disappear into a separate emulator window — they play **inside OpenEmux**, in a window whose header bar carries the controls you actually reach for mid-game. And cover art stops guessing: the app now ships a database of **60,600 real game names**, so it looks your ROM up by title instead of firing speculative URLs at a server and hoping one sticks.

## Games play inside OpenEmux

Launching a game used to hand you off. RetroArch opened its own window, with its own decorations and its own idea of what the app was, and OpenEmux became a thing you alt-tabbed back to.

Now the running emulator is **adopted into an OpenEmux game window**. Its header bar holds pause and resume, reset, save state and load state, mute and a volume slider, RetroArch's own menu, and a button that opens your input settings — the whole set, in the window you are already looking at, without pausing to find the right hotkey.

It is on by default, with a switch at the top of **Settings → Video** if you would rather keep the old separate window. Embedding is an X11 operation, so on a session where it cannot work — native Wayland with no X server, or a Flatpak sandbox that was handed no X socket — OpenEmux detects that up front and launches the game standalone, exactly as before. Nothing fails; you simply get the old behaviour where the new one is impossible.

Because the game window carries volume and stop, the **library header no longer does**. Ending a game means closing the game's window, not walking back to the frontend for a button.

## Artwork that finds the right game

The old cover search worked by construction: take the filename, normalize it a few ways, and try each guess as a URL against the thumbnail servers. A miss cost up to forty speculative requests, and a ROM named anything unusual — which is most of them — simply never resolved.

**OpenEmux now ships the name database itself.** 60,600 titles across all 31 systems, generated from our own artwork mirror, indexed for full-text search, and consulted locally before any request goes out. The lookup became an explicit ladder: content hash first where a provider supports it, then the exact filename, then the normalized forms, and finally a full-text resolution against the local database. Reserved characters are escaped where they belong, so `Adventures of Batman & Robin, The (USA)` finds its cover instead of 404ing forever.

That last stage does real work. `Donald Duck - Maui Mallard in Cold Shadow (E) [!]` resolves to `Maui Mallard in Cold Shadow (USA)` — the game's actual US title, which shares barely half its words with the filename. `Final Fantasy 2` finds `Final Fantasy II`, because arabic and roman numerals are tried both ways. When two genuinely different games are plausible, OpenEmux does not pick one; regional variants of a single title are one answer, chosen by region.

The database comes from **[@mozertdev](https://github.com/mozertdev)**, who built it, measured it, and contributed it in [#188](https://github.com/guilhermefeitosa66/OpenEmux/pull/188) — along with the proofs of concept that settled how the lookup ladder and the suggestion UI should behave.

## Ask the cover picker what your game is called

When a search still comes up empty, you no longer have to guess the canonical title yourself. The cover picker gained a **Suggestions** button — and it fires automatically when a provider search returns nothing.

Type what you remember and it answers from the local database, scoped to the console, with the artwork shown next to each candidate so you are picking a picture, not a string. Misspell it — `Chrno Triger` — and it falls back to approximate matching and tells you that is what it did. Picking a suggestion saves the cover through the normal flow; **your ROM file is never renamed.**

## Covers arrive while you watch

Cover sync downloaded one file at a time, which on a large library meant a progress bar and a long wait for a grid that only filled in at the very end.

It now downloads **in parallel**, with a budget per host: our own mirror gets the full pool, while the third-party servers stay at one request at a time — going faster is not worth being rude to infrastructure we do not pay for. Work alternates between sources so both drain at once instead of everything queuing behind the slowest.

And the covers **appear as they land**, cross-fading into the grid in small batches rather than all at once when the run finishes. Cancelling mid-run keeps everything already downloaded.

## Renaming a ROM keeps your progress

Renaming a game from the library moved the ROM and left everything else behind. Your **save states stopped existing** as far as the emulator was concerned — including the auto state, so a game you had quit mid-level reopened at the title screen. Battery saves went the same way: renamed cartridge, empty save file. And for a multi-ROM archive, the artwork detached from the card that was still showing it.

All three now follow the rename: save states and their thumbnails, in every per-core layout; `.srm`, `.rtc` and whatever else a core invented next to the ROM; and the artwork of an archive entry that cannot itself be renamed. A name collision refuses rather than overwrites — nothing of yours is destroyed to make a rename succeed.

## Light, dark, or whatever your desktop says

**Settings → System → Interface** gained a **Theme** row: System, Light, Dark. System remains the default, so nothing changes unless you go looking. There is also a one-click toggle in the header bar next to search, which flips the appearance you are actually seeing.

## Around the app

- **Controller settings from the sidebar.** A console's controller mapping was reachable only while that console was the one on screen. It now sits in the sidebar's right-click menu alongside core and shader — and it configures the console you right-clicked, not the one that happens to be displayed.
- **The save-slot setting is gone** from Settings → System. A slot is chosen where you use it: the save/load hotkeys step through slots, and RetroArch's own menu picks one directly.
- **The regression test book** ([`tests/regression/TESTBOOK.md`](https://github.com/guilhermefeitosa66/OpenEmux/blob/main/tests/regression/TESTBOOK.md)) is now part of the repository, and test coverage is measured on every CI run.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to do. Settings, playlists, artwork, save states and input profiles are all kept.

Two things are worth knowing before you launch a game:

- **The game window is on by default.** If you prefer RetroArch in its own window, turn it off at the top of Settings → Video. Where embedding cannot work at all, OpenEmux falls back to the separate window on its own.
- **The name database is unpacked on first use**, into `~/.openemux/artwork-index/`. It ships inside the package, so there is no download; a cover sync run after upgrading will resolve titles the old one gave up on.

## Thanks

**[@mozertdev](https://github.com/mozertdev)** contributed the game-name database and the prototypes behind the staged lookup and the suggestion picker — [#175](https://github.com/guilhermefeitosa66/OpenEmux/issues/175), [#184](https://github.com/guilhermefeitosa66/OpenEmux/issues/184), [#185](https://github.com/guilhermefeitosa66/OpenEmux/issues/185) and [#186](https://github.com/guilhermefeitosa66/OpenEmux/issues/186) all trace back to his work. Most of the artwork half of this release is his.

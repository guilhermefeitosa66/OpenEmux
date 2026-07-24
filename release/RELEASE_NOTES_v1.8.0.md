# OpenEmux 1.8.0

A release about the first five minutes. New users now get a guided tour instead of a blank library, and cover art starts filling in on its own — no account, no configuration. Everything an existing install already had is untouched; the new pieces are there to make the *start* smoother.

## A proper welcome

The first time OpenEmux opens, a **Welcome Assistant** now walks you through the essentials: importing ROMs, adjusting how each console's shelf looks, syncing cover art, applying shaders, the keyboard shortcuts, and driving the whole thing from a gamepad.

- It is a set of illustrated slides with a **topic list** on the side, so you can read it front to back or jump straight to the one thing you care about.
- **Back / Next**, a page indicator, and full keyboard and gamepad navigation — the same as the rest of the app.
- A **Show on startup** checkbox sits at the bottom: leave it on to see the tour again next launch, or turn it off once you are settled.

It is reopenable any time from the main menu, and from **Preferences → System**, which also carries a matching **Show on startup** switch and a button to launch the tour on demand.

## Cover art out of the box

ScreenScraper is a richer art source than the libretro thumbnails — it matches by ROM hash rather than filename and carries cartridge-label scans — but until now using it meant requesting a developer account and pasting credentials into Preferences.

Official builds of OpenEmux now **bundle the developer credential**, so ScreenScraper works out of the box: pick it as a cover source and covers start resolving, no setup required.

- The old developer-credential fields are gone from plain view — they now live behind an **Advanced** disclosure, for the rare case of overriding the built-in credential with your own developer account.
- Adding **your own ScreenScraper account** (username + password) is still worthwhile and encouraged: it draws on your own daily quota rather than the shared one, for faster, more reliable scraping.

## A steadier sidebar

Moving the pointer down the console list used to make the rows twitch — the per-console options button appeared on hover and nudged everything below it. The list now holds still: only the highlight and that button's fade change under the cursor, never the layout.

## Upgrading

Nothing to do. Existing installs keep their settings; the Welcome Assistant simply won't reappear if you have already turned it off, and cover sources you have already chosen are unchanged. If you had previously entered ScreenScraper developer credentials by hand, they still work and now sit under **Advanced**.

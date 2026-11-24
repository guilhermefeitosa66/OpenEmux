# The `.openemux-theme` file format

A custom theme travels as one file with the extension `.openemux-theme`. The
desktop app writes and reads it (`src/openemux/core/theme_archive.py`); the
Android app follows the same contract, so a theme made on one opens on the
other. This document is that contract.

## Layout

The file is a ZIP archive (deflate or stored) with at most these entries:

```
theme.yaml              required
images/                 optional directory entry
images/<name>           zero or more background images
```

Nothing else is allowed: any other name, a nested folder, an absolute path,
`..`, a backslash, a symbolic link or other special file (ZIP external
attributes), an encrypted entry or two entries with the same name rejects the
whole file.

## `theme.yaml`

A YAML mapping, UTF-8, read with a safe loader (no tags, no objects).

| Field | Type | Meaning |
|---|---|---|
| `version` | integer ≥ 1 | Format version. Currently `1`. Missing means `1`. A higher number still loads: the keys a reader knows are read and the rest ignored. `0`, a negative number or a non-integer rejects the file. |
| `name` | string | Display name. Whitespace is collapsed to single spaces and the name is cut at 64 characters. Missing or empty: the importer names it `imported`. |
| `base` | `light` \| `dark` | The built-in look the theme starts from. Required; anything else rejects the file. |
| any key below | see the table | A setting the theme changes. |

Only the settings the theme changes are written; an absent key means "same as
the base", using the default for that base in the table below.

**Unknown keys are ignored on read**, never an error. A platform may write
keys of its own (for example an Android-only setting); the other platform
drops them. A value of the wrong type is dropped as if absent, and a number
out of range is clamped to it and rounded to a whole number. An empty string
for a font or an image is the same as the key being absent.

Writers should emit `version`, `name`, `base` first, then the keys in the
table's order.

### Keys

| Key | Section | Kind | Range / choices / format | Light default | Dark default |
|---|---|---|---|---|---|
| `window_bg` | colors | color | `#rrggbb` | `#fafafa` | `#242424` |
| `sidebar_bg` | colors | color | `#rrggbb` | `#ebebeb` | `#303030` |
| `headerbar_bg` | colors | color | `#rrggbb` | `#ebebeb` | `#303030` |
| `library_bg` | colors | color | `#rrggbb` | `#ffffff` | `#1e1e1e` |
| `card_bg` | colors | color | `#rrggbb` | `#ffffff` | `#363636` |
| `popover_bg` | colors | color | `#rrggbb` | `#ffffff` | `#383838` |
| `details_bg` | colors | color | `#rrggbb` | `#fafafa` | `#383838` |
| `text_primary` | text | color | `#rrggbb` | `#323232` | `#ffffff` |
| `text_secondary` | text | color | `#rrggbb` | `#6e6e6e` | `#a8a8a8` |
| `sidebar_text_primary` | text | color | `#rrggbb` | `#2f2f2f` | `#ffffff` |
| `sidebar_text_secondary` | text | color | `#rrggbb` | `#626262` | `#b0b0b0` |
| `accent` | accent | color | `#rrggbb` | `#1c71d8` | `#78aeed` |
| `selection_bg` | accent | color | `#rrggbb` | `#d6d6d6` | `#474747` |
| `accent_button_bg` | accent | color | `#rrggbb` | `#3584e4` | `#3584e4` |
| `accent_button_fg` | accent | color | `#rrggbb` | `#ffffff` | `#ffffff` |
| `border_color` | borders | color | `#rrggbb` | `#dcdcdc` | `#454545` |
| `border_width` | borders | number | 0–3 px | 0 | 0 |
| `corner_radius` | borders | number | 0–24 px | 12 | 12 |
| `shadow_color` | borders | color | `#rrggbb` | `#000000` | `#000000` |
| `shadow_strength` | borders | number | 0–100 % | 35 | 35 |
| `sidebar_icon_size` | icons | choice | `16`, `20`, `24` (px) | `16` | `16` |
| `toolbar_icon_size` | icons | choice | `16`, `20`, `24` (px) | `16` | `16` |
| `icon_color` | icons | color | `#rrggbb` | `#323232` | `#ffffff` |
| `font_scale` | typography | number | 80–150 % | 100 | 100 |
| `font_family` | typography | font | family name matching `[\w .&+()-]{1,64}`, no leading/trailing space | (system font) | (system font) |
| `density` | spacing | number | 60–140 % (presets: compact 80, default 100, comfortable 120) | 100 | 100 |
| `grid_gap` | spacing | number | 4–48 px | 24 | 24 |
| `card_scale` | spacing | number | 70–150 % | 100 | 100 |
| `sidebar_width` | spacing | number | 200–420 px | 300 | 300 |
| `library_image` | backgrounds | image | a file name in `images/` (see below) | (none) | (none) |
| `library_image_fit` | backgrounds | choice | `cover`, `contain`, `tile` | `cover` | `cover` |
| `library_image_dim` | backgrounds | number | 0–90 % | 40 | 40 |
| `library_image_blur` | backgrounds | number | 0–30 px | 0 | 0 |
| `sidebar_image` | backgrounds | image | a file name in `images/` (see below) | (none) | (none) |
| `sidebar_image_fit` | backgrounds | choice | `cover`, `contain`, `tile` | `cover` | `cover` |
| `sidebar_image_dim` | backgrounds | number | 0–90 % | 40 | 40 |
| `sidebar_image_blur` | backgrounds | number | 0–30 px | 0 | 0 |

Value formats:

- **color**: a string. Readers accept `#rrggbb`, `rrggbb` and the `#rgb`
  shorthand in either case and store `#rrggbb` lower-case; writers emit
  `#rrggbb` lower-case.
- **number**: a YAML integer (a float is rounded). Booleans are not numbers.
- **choice**: exactly one of the listed values; the icon sizes are integers,
  the fits are strings.
- **font**: a family name; quotes, backslashes and braces are never allowed.
- **image**: a file name, never a path (see below).

## Images

- An image key names a file under `images/` in the same archive. The name
  matches `[a-z0-9][a-z0-9_-]{0,40}\.(png|jpg|jpeg|webp)`: lower case, at most
  45 characters with the extension.
- Formats: PNG, JPEG or WebP, recognized by the file's signature, not its
  extension. Anything else rejects the whole file.
- At most 8192 px on either side (checked from the header before decoding).
- **Every image is decoded and re-encoded as PNG on import**, scaled down to
  at most 2560 px on its long side (EXIF orientation applied). The stored copy
  is named after its key, `library.png` or `sidebar.png`, and the key is
  rewritten to that name; the original file is never kept.
- An image key whose file is not in the archive is dropped (logged), and the
  rest of the theme imports. Images no key names are ignored.
- Exporters include exactly the images the theme's keys name, once each.

## Limits

Checked on the ZIP central directory before anything is read, and enforced
again on the bytes actually decompressed, so a header that lies does not get
around them:

| Limit | Value |
|---|---|
| Entries, directory entry included | 16 |
| `theme.yaml`, uncompressed | 64 KiB |
| Each image, uncompressed | 20 MiB |
| All entries together, uncompressed | 40 MiB |
| Compression ratio, per entry over 1 MiB | 100 : 1 |

Breaking any of them rejects the whole file.

## Importing

- Validation happens first, and the theme is built in a hidden temporary
  folder inside the themes folder; only a complete theme is saved. A rejected
  file leaves nothing behind.
- **Name clash**: if a theme with the same name (case-insensitive) exists,
  the import is named `Name (2)`, then `(3)` and so on. The folder id is a
  fresh slug of the name; an existing theme is never overwritten.
- The desktop reports a rejection with one of these reason codes in its log:
  `not-a-zip`, `too-many-entries`, `bad-entry`, `symlink`, `too-large`,
  `ratio`, `corrupt`, `bad-yaml`, `bad-theme`, `bad-image`, `write-failed`.

## Example

```
Midnight.openemux-theme
├── theme.yaml
└── images/
    └── library.png
```

```yaml
version: 1
name: Midnight
base: dark
library_bg: '#24283b'
card_bg: '#2f3549'
text_primary: '#c0caf5'
accent: '#7aa2f7'
corner_radius: 8
density: 80
library_image: library.png
library_image_dim: 60
library_image_blur: 4
```

## Ready-made themes

Both apps ship the same five read-only themes, with these ids and exactly these
values (anything not listed is the base's default). They are not files: each
app builds them from its own code and ships its own copy of the background
picture (`library.png`, 1600 × 1000, drawn for OpenEmux by
`tools/theme_backgrounds.py`, MIT). A ready-made id is reserved: a user theme
never takes it, and `ui.theme` may name it. "Duplicate" turns one into an
ordinary, editable theme; exporting one writes an ordinary theme file.

| Key | `pastel` | `dracula` | `kitty` | `neon` | `tokyo-night` |
|---|---|---|---|---|---|
| base | light | dark | dark | dark | dark |
| name (English) | Pastel | Dracula | Kitty | Neon | Tokyo Night |
| `window_bg` | `#fff7fb` | `#282a36` | `#2a2438` | `#0d0221` | `#1a1b26` |
| `sidebar_bg` | `#fce7f3` | `#21222c` | `#241f31` | `#12062b` | `#16161e` |
| `headerbar_bg` | `#fce7f3` | `#21222c` | `#241f31` | `#12062b` | `#16161e` |
| `library_bg` | `#fff7fb` | `#282a36` | `#2a2438` | `#0d0221` | `#1a1b26` |
| `card_bg` | `#ffffff` | `#44475a` | `#3b3250` | `#1b0838` | `#24283b` |
| `popover_bg` | `#ffffff` | `#343746` | `#352c47` | `#1b0838` | `#24283b` |
| `details_bg` | `#fff7fb` | `#2e303e` | `#30293f` | `#150530` | `#1f2335` |
| `text_primary` | `#3f3350` | `#f8f8f2` | `#f5e0ee` | `#d1f7ff` | `#c0caf5` |
| `text_secondary` | `#5f526f` | `#c6c9de` | `#cdbcd9` | `#a8b8e8` | `#a9b1d6` |
| `sidebar_text_primary` | `#3f3350` | `#f8f8f2` | `#f5e0ee` | `#d1f7ff` | `#c0caf5` |
| `sidebar_text_secondary` | `#5f526f` | `#c6c9de` | `#cdbcd9` | `#a8b8e8` | `#a9b1d6` |
| `accent` | `#7c3aed` | `#bd93f9` | `#f5c2e7` | `#05d9e8` | `#7aa2f7` |
| `selection_bg` | `#ede0ff` | `#44475a` | `#4a3b5c` | `#2a0b4a` | `#292e42` |
| `accent_button_bg` | `#7c3aed` | `#bd93f9` | `#f5c2e7` | `#ff2a6d` | `#7aa2f7` |
| `accent_button_fg` | `#ffffff` | `#282a36` | `#2a2438` | `#0d0221` | `#1a1b26` |
| `border_color` | `#f5d0e6` | `#44475a` | `#4a3b5c` | `#ff2a6d` | `#3b4261` |
| `border_width` |  |  |  | `1` |  |
| `corner_radius` | `16` |  | `20` |  |  |
| `shadow_color` | `#c084fc` |  | `#f5c2e7` | `#ff2a6d` |  |
| `shadow_strength` | `20` | `45` | `20` | `60` |  |
| `icon_color` | `#6d28d9` | `#ff79c6` | `#b4befe` | `#05d9e8` | `#bb9af7` |
| `library_image` | `library.png` | `library.png` | `library.png` | `library.png` | `library.png` |
| `library_image_dim` | `55` | `45` | `30` | `35` | `40` |

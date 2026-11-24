# The `.openemux-theme` file format

A custom theme travels as one file with the extension `.openemux-theme`. The
desktop app writes and reads it (`src/openemux/core/theme_archive.py`) and the
Android app follows the same contract (its copy is
`pkg/android/openemux/docs/theme-format.md` in `openemux-android`), so a theme
made on one opens on the other. This page is that contract, as the desktop
implements it.

## The file

A zip (deflate or stored) with the extension `.openemux-theme`, holding:

```
theme.yaml              required, at most 64 KiB
images/<name>           the background pictures the settings name
```

- A **single top folder** around the two is accepted (`Midnight/theme.yaml`,
  `Midnight/images/...`): it is stripped before anything else is looked at.
- `__MACOSX/` is ignored.
- **Any other entry is skipped without being read**: other files, nested
  folders, directory entries, pictures no key names, even an entry that would
  be refused if it were read (too large, a link).
- An entry whose name starts with `/`, holds a `\` or a `..` segment refuses
  the whole file, wherever it is (inside `__MACOSX/` or an unknown folder
  too). So do two entries with the same name.
- Of the entries that are read, a symbolic link or other special file, or an
  encrypted entry, refuses the whole file.

## `theme.yaml`

One flat YAML mapping of scalars, UTF-8, read with a safe loader:

```yaml
version: 1
name: Midnight
base: dark
library_bg: '#24283b'
corner_radius: 8
shadow_strength: 0.5
density: compact
library_image: images/library.png
library_image_dim: 0.6
```

- `version`: an integer, `1` today; missing means `1`. A newer number still
  loads: the keys a build knows are read, the rest ignored. `0`, a negative
  number or a non-integer refuses the file.
- `name`: one line (whitespace collapsed), at most 64 characters. Missing or
  empty, the import is named `imported`.
- `base`: `light` or `dark`, the built-in look every setting starts from.
  Anything else refuses the file.
- Every other key is a setting from the table below. **Only the settings the
  person changed are written** (in the table's order, after `version`, `name`
  and `base`); a missing key paints as the base does on that platform.

Reading is forgiving and safe: an unknown key, a value of the wrong type and
a nested value are dropped (logged); a number out of range is clamped into
it. A file that is not a mapping, has no valid `base` or a bad `version` is
refused as a whole.

Value formats:

- **color**: `#rrggbb` text; readers also take `rrggbb` and `#rgb` in either
  case and store `#rrggbb` lower-case. A bare number is not a color.
- **number**: a YAML number (a bool is not one). A `px` setting is a whole
  number of pixels (`dp` on Android): `8.0` reads as `8`. Every other number
  is a **fraction or factor**, kept to two decimals: `shadow_strength: 0.35`
  is 35 %, `font_scale: 1.1` is 110 %.
- **choice**: exactly one of the listed strings.
- **font**: a family name; quotes, backslashes and braces are never allowed.
  Empty is the system font.
- **image**: `images/<name>` (see Images). Empty is no image.

## Settings

Generated from `THEME_KEYS` in `src/openemux/core/custom_themes.py`. A key
only one app has is ignored by the other: the desktop-only ones are
`font_family`, `sidebar_width` and `density_fine` (a fine factor multiplied
into the `density` choice: compact ×0.85, default ×1, comfortable ×1.15).

| Key | Section | Kind | Range / choices | Light default | Dark default | Platforms |
|---|---|---|---|---|---|---|
| `window_bg` | colors | color | `#rrggbb` | `#fafafa` | `#242424` | both |
| `sidebar_bg` | colors | color | `#rrggbb` | `#ebebeb` | `#303030` | both |
| `headerbar_bg` | colors | color | `#rrggbb` | `#ebebeb` | `#303030` | both |
| `library_bg` | colors | color | `#rrggbb` | `#ffffff` | `#1e1e1e` | both |
| `card_bg` | colors | color | `#rrggbb` | `#ffffff` | `#363636` | both |
| `popover_bg` | colors | color | `#rrggbb` | `#ffffff` | `#383838` | both |
| `details_bg` | colors | color | `#rrggbb` | `#fafafa` | `#383838` | both |
| `console_list_bg` | colors | color | `#rrggbb` | `#ffffff` | `#24242c` | both |
| `text_primary` | text | color | `#rrggbb` | `#323232` | `#ffffff` | both |
| `text_secondary` | text | color | `#rrggbb` | `#6e6e6e` | `#a8a8a8` | both |
| `sidebar_text_primary` | text | color | `#rrggbb` | `#2f2f2f` | `#ffffff` | both |
| `sidebar_text_secondary` | text | color | `#rrggbb` | `#626262` | `#b0b0b0` | both |
| `accent` | accent | color | `#rrggbb` | `#1c71d8` | `#78aeed` | both |
| `selection_bg` | accent | color | `#rrggbb` | `#d6d6d6` | `#474747` | both |
| `accent_button_bg` | accent | color | `#rrggbb` | `#3584e4` | `#3584e4` | both |
| `accent_button_fg` | accent | color | `#rrggbb` | `#ffffff` | `#ffffff` | both |
| `border_color` | borders | color | `#rrggbb` | `#dcdcdc` | `#454545` | both |
| `border_width` | borders | number | 0 – 4 px | 0 | 0 | both |
| `corner_radius` | borders | number | 0 – 28 px | 12 | 12 | both |
| `shadow_color` | borders | color | `#rrggbb` | `#000000` | `#000000` | both |
| `shadow_strength` | borders | number | 0 – 1 | 0.35 | 0.35 | both |
| `icon_scale` | icons | number | 0.75 – 1.5 | 1 | 1 | both |
| `icon_color` | icons | color | `#rrggbb` | `#323232` | `#ffffff` | both |
| `font_scale` | typography | number | 0.85 – 1.3 | 1 | 1 | both |
| `font_family` | typography | font | a family name, `[\w .&+()-]{1,64}` | (system font) | (system font) | desktop only |
| `density` | spacing | choice | `compact`, `default`, `comfortable` | `default` | `default` | both |
| `density_fine` | spacing | number | 0.8 – 1.2 | 1 | 1 | desktop only |
| `grid_gap` | spacing | number | 0 – 32 px | 24 | 24 | both |
| `card_scale` | spacing | number | 0.75 – 1.5 | 1 | 1 | both |
| `sidebar_width` | spacing | number | 200 – 420 px | 300 | 300 | desktop only |
| `library_image` | backgrounds | image | `images/<name>.(png\|jpg\|jpeg\|webp)` | (none) | (none) | both |
| `library_image_fit` | backgrounds | choice | `cover`, `contain`, `tile` | `cover` | `cover` | both |
| `library_image_dim` | backgrounds | number | 0 – 0.9 | 0.4 | 0.4 | both |
| `library_image_blur` | backgrounds | number | 0 – 24 px | 0 | 0 | both |
| `sidebar_image` | backgrounds | image | `images/<name>.(png\|jpg\|jpeg\|webp)` | (none) | (none) | both |
| `sidebar_image_fit` | backgrounds | choice | `cover`, `contain`, `tile` | `cover` | `cover` | both |
| `sidebar_image_dim` | backgrounds | number | 0 – 0.9 | 0.4 | 0.4 | both |
| `sidebar_image_blur` | backgrounds | number | 0 – 24 px | 0 | 0 | both |

`console_list_bg` is Big Picture's console list (the TV layout on the
desktop, the shelf on Android). Unset, each console card keeps its own color;
set, every card takes it, with the theme's text on top.

Contrast: the editor warns when a pair the theme changed falls below WCAG AA,
4.5:1 for text and 3:1 for `icon_color` (WCAG 1.4.11, non-text), on the
surfaces and on each dimmed background picture. On the desktop the selected
sidebar row's text is `sidebar_text_primary` taken toward black or white
until it reads on `selection_bg`, so that pair is not checked.

## Images

- An image key's value is `images/<name>`: lowercase letters, digits, `-` and
  `_`, at most 40 characters, then `.png`,
  `.jpg`, `.jpeg` or `.webp`. Nothing else (no `..`, no other folder, no
  absolute path) is accepted.
- PNG, JPEG or WebP only, recognized by the file's signature, at most
  8192 px on either side (read from the header before decoding).
- On import each picture is decoded, scaled to at most **2048 px** on its
  long side and re-encoded (PNG on the desktop, JPEG on Android) into the new
  theme's own folder under a new name, `images/library.png` or
  `images/sidebar.png`, and the key is rewritten to it. The original bytes
  are never kept. A picture that cannot be decoded refuses the whole file.
- A key whose picture is not in the file is dropped (logged) and the rest
  imports.
- Export writes each picture the keys name once, under its value
  (`images/library.png`).

## Limits on import

| | |
|---|---|
| The file | 48 MiB (checked first, before it is opened) |
| Entries, all of them | 32 |
| `theme.yaml` | 64 KiB |
| One image | 16 MiB |
| Everything unpacked | 48 MiB |
| Compression ratio of an entry over 1 MiB | 100 : 1 |

The sizes are checked on the zip's central directory before anything is read,
and again on the bytes actually decompressed, so a header that lies (a zip
bomb) stops at the limit.

An import never overwrites a theme: it is built in a hidden folder inside the
themes folder and only then saved under a fresh id; a name already taken
becomes "Name (2)". A refused file leaves nothing behind. The desktop logs
the reason as one of `not-a-zip`, `too-many-entries`, `bad-entry`,
`symlink`, `too-large`, `ratio`, `corrupt`, `bad-yaml`, `bad-theme`,
`bad-image`, `write-failed`.

## Ready-made themes

Both apps ship the same five read-only themes, with the same ids and values.
Android's `theme.yaml` files (`openemux-android`,
`pkg/android/openemux/src/main/assets/themes/<id>/theme.yaml`) are the
reference; the desktop ships copies at
`src/openemux/ui/assets/themes/<id>/theme.yaml`, and the only difference is
the picture's name (`images/library.png` here, `.webp` on Android). The
picture is drawn for OpenEmux from `<id>/library.svg` (MIT,
`tools/theme_backgrounds.py`), 1600 × 1000. A ready-made id is reserved: a
user theme never takes it. "Duplicate" makes an editable copy; exporting one
writes an ordinary theme file.

The values (a blank cell is the base's default):

| Key | `pastel` | `dracula` | `kitty` | `neon` | `tokyo-night` |
|---|---|---|---|---|---|
| name | Pastel | Dracula | Kitty | Neon | Tokyo Night |
| base | light | dark | dark | dark | dark |
| `window_bg` | `#fff7fa` | `#282a36` | `#1f1a25` | `#0d0221` | `#1a1b26` |
| `sidebar_bg` | `#f6efff` | `#21222c` | `#1a1620` | `#120530` | `#16161e` |
| `headerbar_bg` | `#fbe4ef` | `#44475a` | `#2e2636` | `#1d0b3a` | `#24283b` |
| `library_bg` | `#fff7fa` | `#282a36` | `#1f1a25` | `#0d0221` | `#1a1b26` |
| `card_bg` | `#ffffff` | `#343746` | `#2b2432` | `#1a0a36` | `#24283b` |
| `popover_bg` | `#ffffff` | `#303241` | `#2b2432` | `#1a0a36` | `#1f2335` |
| `details_bg` | `#fff7fa` | `#282a36` | `#1f1a25` | `#0d0221` | `#1a1b26` |
| `console_list_bg` | `#fbe4ef` | `#383a4a` | `#2e2636` | `#1d0b3a` | `#24283b` |
| `text_primary` | `#3b2f40` | `#f8f8f2` | `#f6ecf4` | `#f4eeff` | `#c0caf5` |
| `text_secondary` | `#66586b` | `#c3c5d8` | `#c9b8cc` | `#bfaee0` | `#a9b1d6` |
| `sidebar_text_primary` | `#8a3f9c` | `#ff79c6` | `#f7b9d7` | `#ff4fb0` | `#7aa2f7` |
| `sidebar_text_secondary` | `#66586b` | `#b4b7cc` | `#bba9bf` | `#ab98d0` | `#9aa5ce` |
| `accent` | `#a63a74` | `#bd93f9` | `#f7b9d7` | `#05d9e8` | `#7aa2f7` |
| `selection_bg` | `#fbd3e6` | `#4b4f68` | `#4d3855` | `#3b1670` | `#2e3c64` |
| `accent_button_bg` | `#b04a80` | `#bd93f9` | `#f7b9d7` | `#ff2a6d` | `#7aa2f7` |
| `accent_button_fg` | `#ffffff` | `#21222c` | `#2a1e2e` | `#12001c` | `#16161e` |
| `border_color` | `#f2d3e2` | `#44475a` | `#3d3245` | `#7b2ff7` | `#292e42` |
| `border_width` | `1` |  |  | `1` |  |
| `corner_radius` | `22` | `14` | `26` | `10` | `12` |
| `shadow_color` | `#e7a9c6` | `#000000` | `#000000` | `#ff2a6d` | `#000000` |
| `shadow_strength` | `0.3` | `0.3` | `0.3` | `0.6` | `0.3` |
| `icon_color` | `#8a6f8f` | `#bd93f9` | `#d8c4e6` | `#05d9e8` | `#7dcfff` |
| `library_image` | `images/library.png` | `images/library.png` | `images/library.png` | `images/library.png` | `images/library.png` |
| `library_image_dim` | `0.3` | `0.7` | `0.7` | `0.5` | `0.7` |
| `library_image_blur` | `0` | `0` | `0` | `0` | `0` |

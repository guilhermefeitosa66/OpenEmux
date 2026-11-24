# Ready-made themes: pictures and colors

## Pictures

Every picture in this folder was drawn for OpenEmux, from shapes, by
`tools/theme_backgrounds.py` (issue 1012): `<id>/library.svg` is the source and
`<id>/images/library.png` the rendering the app uses. The scenes are the Android
app's (`openemux-android`, `pkg/android/openemux/art/themes/`, also original),
laid out again for a wide desktop window. Nothing here is copied, traced or
derived from another project, wallpaper site or desktop (Caelestia included):
"in the spirit of" a look means the mood only.

| Theme | Picture | Author | License |
|---|---|---|---|
| Pastel | clouds, a sun and pastel waves | OpenEmux contributors | MIT (the app's) |
| Dracula | a crescent moon, bats and pine hills at night | OpenEmux contributors | MIT (the app's) |
| Kitty | a cat sitting by a ball of yarn, hearts and paw prints | OpenEmux contributors | MIT (the app's) |
| Neon | a striped sun, mountains and a perspective grid | OpenEmux contributors | MIT (the app's) |
| Tokyo Night | a city skyline with lit windows and a moon | OpenEmux contributors | MIT (the app's) |

## Colors

`<id>/theme.yaml` holds each theme's values, copied from the Android app's
(`pkg/android/openemux/src/main/assets/themes/<id>/theme.yaml`), the reference
for both apps; only the picture's file name differs. Dracula
(https://draculatheme.com, MIT) and Tokyo Night
(https://github.com/enkia/tokyo-night-vscode-theme, MIT) are credited in
`THIRD_PARTY_NOTICES.md`; Pastel and Neon come from the app's own palettes
(issue 983); Kitty's colors are the app's own.

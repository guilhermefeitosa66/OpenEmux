# Controller drawings

One folder per console: `background.png`, one image per control and a
`layout.json` with each control's rect and bind, read by
`openemux.core.controller_layouts`. The input page draws the console's
controller from them (issue 760).

They are generated, not drawn here: `tools/export_controller_art.py` takes the
default bundled skin of each console from the Android app
(`openemux-android`, `pkg/android/openemux/src/main/assets/skins/<CONSOLE>.zip`,
OpenEmux's own skin format), crops its `phone-portrait` layout below the game
screen and scales it to half size. Re-run it when the Android skins change:

    tools/export_controller_art.py                  # ../openemux-android
    tools/export_controller_art.py --android DIR    # another checkout

The output is deterministic, so a re-run with unchanged skins leaves no diff.

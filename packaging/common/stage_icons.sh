#!/bin/sh
# Install the application icons into a staging root, at the sizes the desktop
# actually asks for.
#
# Split out of stage_tree.sh so it can be run — and checked — on its own:
# tests/test_icon_sizes.py stages the icons into a temporary directory and
# measures every file, which is the only way to catch the bug below.
#
# **Every file must be exactly the size its directory claims.** The source
# logo is 735x776 — neither square nor 512 — and it used to be copied in
# unresized, so `hicolor/512x512/apps` held a 735x776 image. The smaller
# entries were rendered with `-resize NxN`, which preserves aspect ratio, so
# they came out 30x32, 45x48, 61x64, 121x128 and 242x256. Not one of the six
# was the size it was filed under. `-extent` pads the resized image out to a
# square on a transparent background, which is what makes the claim true.
#
# The small end matters as much as the large: a Plasma menu asks for 22 or 24
# pixels and GNOME's overview for 32, so those are the entries the app is most
# often drawn from, and they did not exist at all before.
#
# Usage: DESTDIR=<stage> APP_ID=<id> LOGO=<png> stage_icons.sh
set -eu
: "${DESTDIR:?DESTDIR is required}"
: "${APP_ID:?APP_ID is required}"
: "${LOGO:?LOGO is required}"

#: The themed sizes. A menu that does not scale picks the nearest exact match,
#: so the ladder is what keeps the icon sharp from a 16px list row to a 512px
#: software-centre banner.
SIZES="16 22 24 32 48 64 128 256 512"

#: What /usr/share/pixmaps gets: one moderate size, for the older
#: Cinnamon/MATE/XFCE menus that read it instead of doing a theme lookup.
PIXMAP_SIZE=48

# IMv7 renamed the tool to `magick` and deprecated `convert` (Arch ships v7),
# while Debian and Fedora still provide `convert` — so take whichever is here.
if command -v magick >/dev/null 2>&1; then
    RESIZE=magick
elif command -v convert >/dev/null 2>&1; then
    RESIZE=convert
else
    # No ImageMagick: ship the artwork unresized rather than no icon at all.
    # Every package build declares it as a build dependency, so this is the
    # hand-run case.
    echo "stage_icons: no ImageMagick; installing the unresized logo" >&2
    install -Dm644 "$LOGO" \
        "$DESTDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
    install -Dm644 "$LOGO" "$DESTDIR/usr/share/pixmaps/$APP_ID.png"
    exit 0
fi

for size in $SIZES; do
    install -d "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps"
    "$RESIZE" "$LOGO" -resize "${size}x${size}" \
        -background none -gravity center -extent "${size}x${size}" \
        "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
    chmod 644 "$DESTDIR/usr/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
done

# install -d first: ImageMagick writes files, it does not create directories.
install -d "$DESTDIR/usr/share/pixmaps"
"$RESIZE" "$LOGO" -resize "${PIXMAP_SIZE}x${PIXMAP_SIZE}" \
    -background none -gravity center -extent "${PIXMAP_SIZE}x${PIXMAP_SIZE}" \
    "$DESTDIR/usr/share/pixmaps/$APP_ID.png"
chmod 644 "$DESTDIR/usr/share/pixmaps/$APP_ID.png"

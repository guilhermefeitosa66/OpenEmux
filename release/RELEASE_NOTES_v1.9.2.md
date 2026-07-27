# OpenEmux 1.9.2

One change, and the honest reason for it: this was meant to be part of 1.9.1 and missed the build.

## The artwork Import tab

Opening a game's artwork manager and going to **Import** used to split the height between a drop hint and the image you had just dropped, with the edit controls on one row and *Save as* on another.

- **The image gets the whole area.** The drop invitation steps aside once there is an image, and a trash button in its top corner clears it when you want to try another one.
- **The controls are one row** — crop, flip, rotate, reset, and the destination the image will be saved as — instead of two toolbars competing for the eye. Crop and Reset carry icons like the transforms already did.

Everything else in this release is 1.9.1: the context-menu crash fix, per-ROM artwork sync as a background action with the manager on its own menu entries, search results laid out on the library's grid with a check on the picked image, and a cancel button for a running search. If you are coming from 1.9.0, the [1.9.1 notes](RELEASE_NOTES_v1.9.1.md) cover all of it.

## Upgrading

Nothing to do. Settings, playlists, artwork and input profiles are all kept.

## Verify what you downloaded

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

# OpenEmux 1.10.1

A single fix, for a bug that made games unplayable in a way that pointed nowhere near its actual cause.

## Games ran far too fast

If you installed OpenEmux from the **`.deb`, the `.rpm` or the AppImage**, games could run at several times their normal speed — on a 240 Hz display, up to four times too fast. The Flatpak was unaffected, which made the whole thing look like a broken build.

It was not a build problem, and it was not a speed setting. It was **audio**.

OpenEmux ships its own copy of RetroArch, but launches it against the RetroArch configuration already on your machine. If that configuration names an audio driver the bundled RetroArch was not compiled with — `pipewire` is the common one, and a perfectly ordinary value on a modern desktop — RetroArch cannot honour it, falls back to ALSA, and ALSA fails on a PipeWire system. Audio never starts.

That is where the speed comes from: **RetroArch keeps emulation in time using the audio clock.** Take the audio away and the pacing falls through to the display's refresh rate, so a 60 fps console is driven at whatever your monitor runs at. Nothing on screen suggests audio had anything to do with it.

The Flatpak escaped this because it plays through the RetroArch Flatpak, a build that does have the `pipewire` driver.

## The fix

OpenEmux now chooses the audio driver from what your system actually offers, instead of inheriting one from a configuration that may have been written for a different RetroArch. When a PulseAudio socket is reachable — which covers both real PulseAudio and PipeWire, since PipeWire serves the same socket — it asks for `pulse`, a driver present in every RetroArch build OpenEmux launches. When nothing is found, it says nothing at all and leaves your setup exactly as it was.

If you run a deliberate JACK or bare-ALSA setup, `runtime.retroarch.audio_driver` in `~/.openemux/config.yaml` takes an explicit driver name, or `inherit` to go back to the previous behaviour.

## Verify what you downloaded

Every release ships a **`SHA256SUMS`** file. Download it next to your artifact and run:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

`OK` means the file is exactly what was published. Anything else means it is corrupt or has been tampered with — don't run it.

## Upgrading

Nothing to do, and nothing to undo. Settings, playlists, artwork, save states and input profiles are all kept. If you had previously changed an audio setting by hand trying to fix the speed, you can put it back the way you like it — OpenEmux no longer depends on it being right.

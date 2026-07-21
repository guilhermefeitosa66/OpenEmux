# OpenEmux 1.5.1

A fix for the 1.5.0 AppImage, which did not start at all:

```
usr/bin/openemux-run: exec: .../usr/bin/python3: not found
```

The `.deb` and `.rpm` from 1.5.0 are unaffected — nothing else changed in this release.

## What went wrong

The bundled Python's ELF interpreter path is *relative* (`lib64/ld-linux-x86-64.so.2`), so it is resolved against whatever the working directory happens to be. appimage-builder's exec hooks change into `runtime/compat` before launching anything, and that directory had no `lib64` in it — so the loader could not be found and the kernel reported the interpreter itself as missing.

1.5.0 restructured the bundle's entry point to a shell script, so that it could set up the environment that fixed cover art and cartridge rendering. That is also what pulled the hooks into the chain: the previous entry point was a static binary, which ignores them. The bundle assembled correctly either way, which is why the build reported success.

The missing `lib64` link is now created, and the build **launches the finished AppImage** and fails if it does not reach the UI — the check that would have caught this before it shipped.

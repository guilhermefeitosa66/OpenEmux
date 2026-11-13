# Performance checks

Scripts behind the library-performance scenarios of the test book (issues 899,
900 and the rest of the November 2026 review). They run in the devbox, never on
the developer's screen.

```bash
make devbox-up
# a 3000-game library with art, in the container's own home
./devbox/devbox.sh exec env OPENEMUX_SRC=$PWD/src /usr/bin/python3 -I \
    tools/perf/gen_library.py /home/$USER/.local/share/openemux-devbox/home/games/big 3000 0.8
# point the devbox config at it, then drive a session
./devbox/devbox.sh exec env DEVBOX_REPO=$PWD tools/perf/library_bench.sh --use ~/games/big
./devbox/devbox.sh exec env DEVBOX_REPO=$PWD COLD=1 tools/perf/library_bench.sh big-cold
```

`library_bench.sh` prints one JSON object per step: main-thread and
whole-process settle times after opening "All", searching, zooming in and out,
and the RSS after each step, after ten console visits and back on "All", plus
the number of cards the grids built (from the app log). Compare two checkouts by
running it with `DEVBOX_REPO` pointing at each.

The library lives in the box's home (`~/games/big` inside the container), so
`make devbox-seed --wipe` removes it; the pool of base images under
`_art_pool/` is what every cover is hard-linked from.

/*
 * ELF entry point for the AppImage.
 *
 * appimage-builder's AppRun2 refuses to deploy unless app_info.exec is a real
 * ELF executable ("Main executable is not an elf executable"), so the bundle
 * cannot point straight at a shell script. This static binary exists only to
 * be that ELF: it resolves $APPDIR and hands over to openemux-run, the shell
 * script that sets up the bundle's environment (typelibs, gdk-pixbuf loaders,
 * icon theme) and starts Python.
 *
 * It also parks the loader variables on the way through. openemux-run is a
 * `#!/bin/sh` script, so the kernel loads the *host's* shell under whatever
 * LD_LIBRARY_PATH this exec carries -- and AppRun points that at the bundle.
 * On any distribution whose /bin/sh is newer than Ubuntu noble's libraries the
 * shell then resolves the wrong ones and the launch dies before a single line
 * of the script runs:
 *
 *   /bin/sh: symbol lookup error: /bin/sh: undefined symbol: rl_print_keybinding
 *
 * (Arch: bash linked against readline 8.3, bundle carries 8.2.) Nothing in the
 * shell needs the bundle's libraries; only the interpreter it execs does, so
 * the value is stashed as APPDIR_SHELL_LD_LIBRARY_PATH and openemux-run puts
 * it back immediately before exec'ing python3.
 *
 * Not *emptied*, though: AppRun sets LD_PRELOAD to the bare name
 * "libapprun_hooks.so", which the loader resolves through LD_LIBRARY_PATH,
 * and that hook is what rewrites the environment of the next exec. A shell
 * that fails to preload it hands the bundled python3 the host's libc and the
 * launch dies one step later on "__pointer_chk_guard, version GLIBC_PRIVATE".
 * So the shell keeps exactly the components that hold the hook (one
 * directory, holding nothing else) and loses the rest.
 *
 * Built by the recipe with: gcc -static openemux-launcher.c -O2 -s
 */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* appimage-builder's exec hook, named in LD_PRELOAD without a directory. */
#define HOOKS_SO "libapprun_hooks.so"

/* Park LD_LIBRARY_PATH and leave the shell only what HOOKS_SO needs. */
static void narrow_library_path(void) {
    const char *value = getenv("LD_LIBRARY_PATH");
    char kept[PATH_MAX];
    char probe[PATH_MAX];
    char *copy, *dir, *saveptr = NULL;

    if (!value || value[0] == '\0') {
        return;
    }
    setenv("APPDIR_SHELL_LD_LIBRARY_PATH", value, 1);

    copy = strdup(value);
    if (!copy) {
        return; /* Nothing narrowed is better than an empty path. */
    }
    kept[0] = '\0';
    for (dir = strtok_r(copy, ":", &saveptr); dir;
         dir = strtok_r(NULL, ":", &saveptr)) {
        if (snprintf(probe, sizeof(probe), "%s/" HOOKS_SO, dir) >= (int)sizeof(probe)) {
            continue;
        }
        if (access(probe, R_OK) != 0) {
            continue;
        }
        if (kept[0] != '\0') {
            strncat(kept, ":", sizeof(kept) - strlen(kept) - 1);
        }
        strncat(kept, dir, sizeof(kept) - strlen(kept) - 1);
    }
    free(copy);

    if (kept[0] != '\0') {
        setenv("LD_LIBRARY_PATH", kept, 1);
    } else {
        unsetenv("LD_LIBRARY_PATH");
    }
}

int main(int argc, char **argv) {
    const char *appdir = getenv("APPDIR");
    if (!appdir || appdir[0] == '\0') {
        fprintf(stderr, "openemux-launcher: APPDIR is not set\n");
        return 1;
    }

    narrow_library_path();

    char runner[PATH_MAX];
    snprintf(runner, sizeof(runner), "%s/usr/bin/openemux-run", appdir);

    char **child_argv = calloc((size_t)argc + 1, sizeof(char *));
    if (!child_argv) {
        fprintf(stderr, "openemux-launcher: out of memory\n");
        return 1;
    }

    child_argv[0] = runner;
    for (int i = 1; i < argc; i++) {
        child_argv[i] = argv[i];
    }
    child_argv[argc] = NULL;

    execv(runner, child_argv);
    perror("openemux-launcher: execv");
    free(child_argv);
    return 1;
}

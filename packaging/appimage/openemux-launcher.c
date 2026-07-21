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
 * Built by the recipe with: gcc -static openemux-launcher.c -O2 -s
 */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *appdir = getenv("APPDIR");
    if (!appdir || appdir[0] == '\0') {
        fprintf(stderr, "openemux-launcher: APPDIR is not set\n");
        return 1;
    }

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

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *appdir = getenv("APPDIR");
    if (!appdir || appdir[0] == '\0') {
        fprintf(stderr, "opemux-launcher: APPDIR is not set\n");
        return 1;
    }

    char project_root[PATH_MAX];
    char python_bin[PATH_MAX];
    char main_py[PATH_MAX];
    char pythonpath[PATH_MAX * 2];

    snprintf(project_root, sizeof(project_root), "%s/usr/lib/opemux", appdir);
    snprintf(python_bin, sizeof(python_bin), "%s/usr/bin/python3", appdir);
    snprintf(main_py, sizeof(main_py), "%s/src/opemux/main.py", project_root);

    const char *existing_pythonpath = getenv("PYTHONPATH");
    if (existing_pythonpath && existing_pythonpath[0] != '\0') {
        snprintf(
            pythonpath,
            sizeof(pythonpath),
            "%s/src:%s",
            project_root,
            existing_pythonpath
        );
    } else {
        snprintf(pythonpath, sizeof(pythonpath), "%s/src", project_root);
    }

    setenv("OPEMUX_PROJECT_ROOT", project_root, 1);
    setenv("PYTHONPATH", pythonpath, 1);

    if (chdir(appdir) != 0) {
        perror("opemux-launcher: chdir");
        return 1;
    }

    char **child_argv = calloc((size_t)argc + 2, sizeof(char *));
    if (!child_argv) {
        fprintf(stderr, "opemux-launcher: out of memory\n");
        return 1;
    }

    child_argv[0] = python_bin;
    child_argv[1] = main_py;
    for (int i = 1; i < argc; i++) {
        child_argv[i + 1] = argv[i];
    }
    child_argv[argc + 1] = NULL;

    execv(python_bin, child_argv);
    perror("opemux-launcher: execv");
    free(child_argv);
    return 1;
}

/*
 * Entry point of the Windows bundle: OpenEmux.exe.
 *
 * The bundle is a relocated MSYS2 MINGW64 prefix -- bin/, lib/, share/, etc/ --
 * with the app's src/ and the vendored RetroArch beside it. Nothing in it knows
 * where the user installed it, so something has to look around at startup and
 * say so. That is all this program does: work out its own directory, point the
 * runtime at the bundle, and hand over to Python.
 *
 * Built by packaging/windows/build.sh with the mingw-w64 cross compiler:
 *
 *     x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows \
 *         openemux-launcher.c -o OpenEmux.exe
 *
 * -mwindows marks it as a GUI subsystem binary, so double-clicking it opens no
 * console. It starts pythonw.exe for the same reason -- python.exe is a console
 * application and would put a black window behind the app for its whole run.
 */

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define MAX_PATH_LONG 32768

/* Every buffer here is `static`. At 32768 wide characters each -- the ceiling
 * on a Windows long path -- putting them on the stack would spend most of the
 * default 1 MB before doing any work. This program is single-threaded and runs
 * once, so static costs nothing. */

/* Set NAME to "<root><suffix>". */
static BOOL set_rooted(const wchar_t *name, const wchar_t *root, const wchar_t *suffix) {
    static wchar_t value[MAX_PATH_LONG];
    if (_snwprintf(value, MAX_PATH_LONG, L"%s%s", root, suffix) < 0) {
        return FALSE;
    }
    return SetEnvironmentVariableW(name, value);
}

static void fail(const wchar_t *message) {
    /* No console to print to: -mwindows means stderr goes nowhere a user can
     * see. A message box is the only way this reaches them. */
    MessageBoxW(NULL, message, L"OpenEmux", MB_ICONERROR | MB_OK);
}

/* wWinMain, not wmain. `-mwindows` selects the GUI subsystem and `-municode`
 * the wide entry point, and together they make the C runtime start at
 * wWinMainCRTStartup -- which calls wWinMain. A wmain here links against
 * nothing and the build fails with an undefined reference. Nothing is lost:
 * the command line is read from GetCommandLineW below, so argv was never
 * wanted. */
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    (void)instance;
    (void)previous;
    (void)command;
    (void)show;

    static wchar_t self[MAX_PATH_LONG];
    DWORD length = GetModuleFileNameW(NULL, self, MAX_PATH_LONG);
    if (length == 0 || length >= MAX_PATH_LONG) {
        fail(L"Could not determine the OpenEmux install directory.");
        return 1;
    }

    /* Strip "\OpenEmux.exe" to leave the install root. */
    wchar_t *separator = wcsrchr(self, L'\\');
    if (separator == NULL) {
        fail(L"Could not determine the OpenEmux install directory.");
        return 1;
    }
    *separator = L'\0';
    const wchar_t *root = self;

    /* Where the app's project root is. get_project_root() reads this first, so
     * it never has to guess from __file__ inside a relocated bundle. */
    SetEnvironmentVariableW(L"OPENEMUX_PROJECT_ROOT", root);

    /* Tells main.py this is an installed copy rather than a source checkout, so
     * it does not try to write desktop-integration files. On Linux the same
     * question is answered by the /usr install prefix, which means nothing
     * here. */
    SetEnvironmentVariableW(L"OPENEMUX_PACKAGED", L"1");

    set_rooted(L"PYTHONPATH", root, L"\\src");

    /* A PYTHONHOME inherited from the user's environment -- pyenv, conda, a
     * system Python -- would send the bundled interpreter looking for its
     * standard library in the wrong prefix and it would not start. The bundle
     * keeps MSYS2's bin/ + lib/ layout, so Python finds its own prefix without
     * being told. */
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);

    /* The GTK stack. GI_TYPELIB_PATH is what makes `gi.require_version("Adw")`
     * resolve; XDG_DATA_DIRS is where the icon theme and the compiled schemas
     * are found. */
    set_rooted(L"GI_TYPELIB_PATH", root, L"\\lib\\girepository-1.0");
    set_rooted(L"GSETTINGS_SCHEMA_DIR", root, L"\\share\\glib-2.0\\schemas");
    set_rooted(L"XDG_DATA_DIRS", root, L"\\share");
    set_rooted(L"GDK_PIXBUF_MODULE_FILE", root,
               L"\\lib\\gdk-pixbuf-2.0\\2.10.0\\loaders.cache");

    /* HTTPS. OpenSSL bakes its default CA path in at build time, and MSYS2
     * builds it as C:\msys64\mingw64\etc\ssl\cert.pem -- a path that does not
     * exist on a user's machine. Without this every HTTPS request fails to
     * verify, which on first boot means no cores download and no cover art:
     * the app installs cleanly and then cannot fetch anything. Both variables
     * are set because OpenSSL consults the file and the directory separately.
     */
    set_rooted(L"SSL_CERT_FILE", root, L"\\etc\\ssl\\certs\\ca-bundle.crt");
    set_rooted(L"SSL_CERT_DIR", root, L"\\etc\\ssl\\certs");

    /* The bundle's DLLs must win over anything already on PATH -- a system-wide
     * GTK or a different Python on PATH would otherwise be loaded into this
     * process and crash it on an ABI mismatch. Prepended rather than replacing
     * PATH outright, so tools the user expects to be reachable still are. */
    {
        static wchar_t path_value[MAX_PATH_LONG];
        static wchar_t inherited[MAX_PATH_LONG];
        DWORD have = GetEnvironmentVariableW(L"PATH", inherited, MAX_PATH_LONG);
        if (have > 0 && have < MAX_PATH_LONG) {
            _snwprintf(path_value, MAX_PATH_LONG, L"%s\\bin;%s", root, inherited);
        } else {
            _snwprintf(path_value, MAX_PATH_LONG, L"%s\\bin", root);
        }
        SetEnvironmentVariableW(L"PATH", path_value);
    }

    /* Everything after our own executable name on the command line is passed
     * through untouched. Taken from GetCommandLineW rather than rebuilt from
     * argv, so the user's own quoting survives exactly as they wrote it. */
    const wchar_t *command_line = GetCommandLineW();
    const wchar_t *arguments = command_line;
    if (*arguments == L'"') {
        arguments++;
        while (*arguments && *arguments != L'"') {
            arguments++;
        }
        if (*arguments == L'"') {
            arguments++;
        }
    } else {
        while (*arguments && *arguments != L' ' && *arguments != L'\t') {
            arguments++;
        }
    }

    static wchar_t interpreter[MAX_PATH_LONG];
    _snwprintf(interpreter, MAX_PATH_LONG, L"%s\\bin\\pythonw.exe", root);

    static wchar_t child_command[MAX_PATH_LONG];
    if (_snwprintf(child_command, MAX_PATH_LONG, L"\"%s\" -m openemux.main%s",
                   interpreter, arguments) < 0) {
        fail(L"The OpenEmux command line is too long to start.");
        return 1;
    }

    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    ZeroMemory(&process, sizeof(process));

    /* The working directory is the install root so a relative path in the
     * config -- "vendors/RetroArch-Win64/retroarch.exe" is the default --
     * resolves the same way it does from a source checkout. */
    if (!CreateProcessW(interpreter, child_command, NULL, NULL, TRUE, 0, NULL,
                        root, &startup, &process)) {
        static wchar_t message[MAX_PATH_LONG];
        _snwprintf(message, MAX_PATH_LONG,
                   L"OpenEmux could not start its Python runtime.\n\n"
                   L"Expected: %s\n"
                   L"Windows error: %lu\n\n"
                   L"The installation looks incomplete. Reinstalling should fix it.",
                   interpreter, (unsigned long)GetLastError());
        fail(message);
        return 1;
    }

    /* Waited on rather than left to run detached: the exit code has to reach
     * whatever started us, and a launcher that returns immediately makes the
     * app look like it closed the moment it opened. */
    WaitForSingleObject(process.hProcess, INFINITE);

    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hProcess);
    CloseHandle(process.hThread);
    return (int)exit_code;
}

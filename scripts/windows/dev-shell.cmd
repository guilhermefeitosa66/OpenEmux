@echo off
rem Open an MSYS2 MINGW64 shell already sitting in the OpenEmux checkout.
rem
rem This exists so the system PATH never has to be touched. Putting
rem C:\msys64\mingw64\bin on the global PATH would shadow system DLLs for every
rem process on the machine; MSYS2 sets up the environment for this one shell
rem instead. Inside it, `make run`, `make test` and `make coverage` work exactly
rem as they do on Linux.
rem
rem Override the MSYS2 location with:  set MSYS2_ROOT=D:\msys64 && dev-shell.cmd

setlocal
if "%MSYS2_ROOT%"=="" set "MSYS2_ROOT=C:\msys64"

if not exist "%MSYS2_ROOT%\msys2_shell.cmd" (
    echo MSYS2 not found at %MSYS2_ROOT%.
    echo Run scripts\windows\setup-dev.ps1 first, or set MSYS2_ROOT.
    exit /b 1
)

rem -mingw64  select the MINGW64 environment ^(native x86_64 GTK4 + Python^)
rem -where    start in the repo root rather than the MSYS2 home directory
"%MSYS2_ROOT%\msys2_shell.cmd" -mingw64 -where "%~dp0..\.."

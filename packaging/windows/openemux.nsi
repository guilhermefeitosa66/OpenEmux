; NSIS script for the OpenEmux Windows installer.
;
; Compiled by packaging/windows/build.sh with makensis, natively on Linux inside
; the container from packaging/docker/windows.Dockerfile. No Wine is involved --
; see that file for why this is NSIS and not the Inno Setup named in issue #118.
;
; Values come from the command line:
;
;   makensis -DVERSION=1.11.3 -DBUNDLE_DIR=... -DOUTPUT_FILE=... openemux.nsi

!ifndef VERSION
  !error "VERSION must be passed with -DVERSION=<x.y.z>"
!endif
!ifndef BUNDLE_DIR
  !error "BUNDLE_DIR must be passed with -DBUNDLE_DIR=<path to the staged tree>"
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE must be passed with -DOUTPUT_FILE=<path>"
!endif

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

Name "OpenEmux ${VERSION}"
OutFile "${OUTPUT_FILE}"

; Per-user install, which is the whole reason there is no UAC prompt. It is also
; load-bearing beyond convenience: OpenEmux downloads libretro cores into
; vendors\RetroArch-Win64\cores on first boot. Under Program Files that write
; fails for a standard user, and the app would install cleanly and then be
; unable to launch a single game.
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\OpenEmux"

; Remember where a previous version went, so an upgrade lands on top of it
; instead of installing a second copy beside it.
InstallDirRegKey HKCU "Software\OpenEmux" "InstallDir"

; The payload is a few hundred megabytes of DLLs and RetroArch assets, which
; compress well and slowly. Solid LZMA is paid once per release and saved on
; every download.
SetCompressor /SOLID lzma
SetCompressorDictSize 64

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "OpenEmux"
VIAddVersionKey "FileDescription" "OpenEmux installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "Guilherme Feitoza"
VIAddVersionKey "LegalCopyright" "MIT Licensed. See LICENSE."

!define MUI_ICON "${BUNDLE_DIR}\openemux.ico"
!define MUI_UNICON "${BUNDLE_DIR}\openemux.ico"
!define MUI_ABORTWARNING

!define MUI_FINISHPAGE_RUN "$INSTDIR\OpenEmux.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start OpenEmux"

!insertmacro MUI_PAGE_LICENSE "${BUNDLE_DIR}\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "PortugueseBR"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "Spanish"

; The AppUserModelID the app declares for its process and every window
; (APP_ID in src/openemux/main.py -- tests/test_windows_shell_identity.py keeps
; the two equal). The app's windows belong to pythonw.exe, not to OpenEmux.exe,
; so without one shared id a pinned Start Menu shortcut and the running window
; are two taskbar buttons (issue #509).
!define APP_USER_MODEL_ID "io.github.guilhermefeitosa66.OpenEmux"

; Write APP_USER_MODEL_ID into the shortcut at LNK. Through the System plugin
; that ships with NSIS, so the build image needs nothing new: the .lnk's
; IPropertyStore (SHGetPropertyStoreFromParsingName, GPS_READWRITE = 2), then
; SetValue (vtable slot 6) of PKEY_AppUserModel_ID as a VT_LPWSTR (31) and
; Commit (slot 7). Best-effort: a failure leaves a shortcut that still starts
; the app, only as a second taskbar button, and never stops the install.
!macro SetShortcutAppId LNK
  Push $0
  Push $1
  Push $2
  Push $3
  System::Call 'shell32::SHGetPropertyStoreFromParsingName(w "${LNK}", p 0, i 2, g "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}", *p .r1) i .r0'
  ${If} $0 = 0
    System::Call '*(&g16 "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", i 5) p .r2'
    System::Call '*(&i2 31, &i2 0, &i2 0, &i2 0, w "${APP_USER_MODEL_ID}") p .r3'
    System::Call '$1->6(p r2, p r3) i .r0'
    ${If} $0 = 0
      System::Call '$1->7() i .r0'
    ${EndIf}
    System::Free $2
    System::Free $3
    System::Call '$1->2()'
  ${EndIf}
  Pop $3
  Pop $2
  Pop $1
  Pop $0
!macroend

Section "OpenEmux" SecMain
  SectionIn RO

  ; An upgrade over an older bundle must not leave that bundle's DLLs behind:
  ; a stale libgtk from a previous release sitting next to a new libglib is an
  ; ABI mismatch that crashes at startup. Removing the parts the build owns is
  ; safe -- everything here is reinstalled immediately below, and the user's
  ; library lives in %USERPROFILE%\.openemux, nowhere near this directory.
  RMDir /r "$INSTDIR\bin"
  RMDir /r "$INSTDIR\lib"
  RMDir /r "$INSTDIR\share"
  RMDir /r "$INSTDIR\etc"
  RMDir /r "$INSTDIR\src"

  SetOutPath "$INSTDIR"
  File /r "${BUNDLE_DIR}\*.*"

  WriteRegStr HKCU "Software\OpenEmux" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\OpenEmux" "Version" "${VERSION}"

  CreateDirectory "$SMPROGRAMS\OpenEmux"
  CreateShortCut "$SMPROGRAMS\OpenEmux\OpenEmux.lnk" "$INSTDIR\OpenEmux.exe" \
    "" "$INSTDIR\OpenEmux.exe" 0 SW_SHOWNORMAL "" "OpenEmux"
  !insertmacro SetShortcutAppId "$SMPROGRAMS\OpenEmux\OpenEmux.lnk"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortCut "$SMPROGRAMS\OpenEmux\Uninstall OpenEmux.lnk" "$INSTDIR\Uninstall.exe"

  ; Registered under HKCU, matching the per-user install: this is what puts
  ; OpenEmux in "Installed apps" for this user and nowhere else.
  !define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenEmux"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "OpenEmux"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\OpenEmux.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Guilherme Feitoza"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://github.com/guilhermefeitosa66/OpenEmux"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ; Reported in "Installed apps". Measured rather than hardcoded, because the
  ; bundle's size moves with every GTK and RetroArch bump.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  ; /r on the whole directory, deliberately: it also takes the cores OpenEmux
  ; downloaded on first boot and RetroArch's own runtime state, none of which
  ; the installer tracked and all of which would otherwise be left behind.
  RMDir /r "$INSTDIR"

  Delete "$SMPROGRAMS\OpenEmux\OpenEmux.lnk"
  Delete "$SMPROGRAMS\OpenEmux\Uninstall OpenEmux.lnk"
  RMDir "$SMPROGRAMS\OpenEmux"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenEmux"
  DeleteRegKey HKCU "Software\OpenEmux"

  ; The user's library and settings live in %USERPROFILE%\.openemux and are
  ; deliberately NOT touched. Uninstalling must not delete someone's playlists,
  ; save states, input profiles and cover art.
SectionEnd

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

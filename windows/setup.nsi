; MD-Prep Studio — Windows installer (NSIS 3)
; Build from the folder prepared by build.sh:
;   makensis -DLANG_ES setup.nsi      -> Spanish installer
;   makensis setup.nsi                -> English installer
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APPNAME "MD-Prep Studio"
!ifndef VERSION
  !define VERSION "1.1.0"
!endif
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MD-Prep"

!ifdef LANG_ES
  !define LCODE "es"
  OutFile "MD-Prep_Studio_${VERSION}_Windows_ES.exe"
!else
  !define LCODE "en"
  OutFile "MD-Prep_Studio_${VERSION}_Windows_EN.exe"
!endif

Name "${APPNAME}"
InstallDir "$LOCALAPPDATA\MD-Prep"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show
BrandingText "${APPNAME} ${VERSION}"

!define MUI_ICON "mdprep.ico"
!define MUI_UNICON "mdprep.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\MD-Prep.cmd"
!define MUI_FINISHPAGE_RUN_TEXT "$(RunText)"

!define MUI_WELCOMEPAGE_TEXT "$(WelcomeText)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "$(UnConfirmText)"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!ifdef LANG_ES
  !insertmacro MUI_LANGUAGE "Spanish"
  LangString WelcomeText ${LANG_SPANISH} "Este asistente instala MD-Prep Studio, que prepara dinámicas moleculares proteína–ligando para GROMACS a partir de un complejo de docking.$\r$\n$\r$\nGROMACS y AmberTools no existen para Windows, así que la plataforma se instala dentro de WSL (el subsistema de Linux de Windows), en un sistema propio llamado MD-Prep. No toca tus otros programas.$\r$\n$\r$\nNecesitas internet: se descargan unos 1.5 GB y la instalación tarda 10-20 minutos. Si WSL no está activado, Windows pedirá permiso de administrador y habrá que reiniciar una vez."
  LangString RunText ${LANG_SPANISH} "Abrir MD-Prep Studio"
  LangString RebootText ${LANG_SPANISH} "WSL quedó activado. Reinicia Windows: el instalador continuará solo al iniciar sesión (si no, vuelve a ejecutarlo)."
  LangString ErrorText ${LANG_SPANISH} "La instalación no terminó. Revisa el registro:$\r$\n$INSTDIR\install.log"
  LangString StepText ${LANG_SPANISH} "Instalando el sistema Linux y las herramientas de dinámica molecular (10-20 minutos)..."
  LangString UninstText ${LANG_SPANISH} "Desinstalar MD-Prep Studio"
  LangString RemoveText ${LANG_SPANISH} "Eliminando el sistema Linux de MD-Prep (WSL)..."
  LangString UnConfirmText ${LANG_SPANISH} "Se eliminará MD-Prep Studio y su sistema Linux, incluidos los sistemas preparados que estén dentro (descarga antes los ZIP que necesites)."
!else
  !insertmacro MUI_LANGUAGE "English"
  LangString WelcomeText ${LANG_ENGLISH} "This wizard installs MD-Prep Studio, which prepares protein–ligand molecular dynamics simulations for GROMACS from a docking complex.$\r$\n$\r$\nGROMACS and AmberTools are not available for Windows, so the platform is installed inside WSL (the Windows Subsystem for Linux), in its own system called MD-Prep. Your other programs are not touched.$\r$\n$\r$\nAn internet connection is required: about 1.5 GB is downloaded and the installation takes 10-20 minutes. If WSL is not enabled yet, Windows will ask for administrator permission and one restart."
  LangString RunText ${LANG_ENGLISH} "Open MD-Prep Studio"
  LangString RebootText ${LANG_ENGLISH} "WSL has been enabled. Restart Windows: the installer will resume when you sign in (otherwise run it again)."
  LangString ErrorText ${LANG_ENGLISH} "The installation did not finish. Check the log:$\r$\n$INSTDIR\install.log"
  LangString StepText ${LANG_ENGLISH} "Installing the Linux system and the molecular dynamics tools (10-20 minutes)..."
  LangString UninstText ${LANG_ENGLISH} "Uninstall MD-Prep Studio"
  LangString RemoveText ${LANG_ENGLISH} "Removing the MD-Prep Linux system (WSL)..."
  LangString UnConfirmText ${LANG_ENGLISH} "MD-Prep Studio and its Linux system will be removed, including the prepared systems stored inside it (download any ZIP you need first)."
!endif

Section "MD-Prep Studio" SecMain
  SetOutPath "$INSTDIR"
  File "install_windows.ps1"
  File "wsl_setup.sh"
  File "mdprep.ico"
  File "LICENSE.txt"
  SetOutPath "$INSTDIR\app"
  File /r "app\*.*"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\mdprep.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1

  DetailPrint "$(StepText)"
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install_windows.ps1" -Lang ${LCODE} -InstDir "$INSTDIR"'
  Pop $0
  ${If} $0 == "3010"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\RunOnce" "MD-Prep-Setup" '"$EXEPATH"'
    MessageBox MB_OK|MB_ICONINFORMATION "$(RebootText)"
    Quit
  ${ElseIf} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "$(ErrorText)"
    Abort
  ${EndIf}

  CreateShortcut "$DESKTOP\MD-Prep Studio.lnk" "$INSTDIR\MD-Prep.cmd" "" "$INSTDIR\mdprep.ico" 0
  CreateDirectory "$SMPROGRAMS\MD-Prep Studio"
  CreateShortcut "$SMPROGRAMS\MD-Prep Studio\MD-Prep Studio.lnk" "$INSTDIR\MD-Prep.cmd" "" "$INSTDIR\mdprep.ico" 0
  CreateShortcut "$SMPROGRAMS\MD-Prep Studio\$(UninstText).lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  DetailPrint "$(RemoveText)"
  nsExec::ExecToLog 'wsl.exe --terminate MD-Prep'
  Pop $0
  nsExec::ExecToLog 'wsl.exe --unregister MD-Prep'
  Pop $0
  Delete "$DESKTOP\MD-Prep Studio.lnk"
  RMDir /r "$SMPROGRAMS\MD-Prep Studio"
  Delete "$LOCALAPPDATA\Microsoft\WindowsApps\prepmd.cmd"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
SectionEnd

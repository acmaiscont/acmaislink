Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef FLAVOR
  !define FLAVOR "update"
!endif
Var InstallerMutex
Var AppMutex
Var StageDir
Var BackupDir
Var ExistingMoved
Name "ACMAIS LINK"
OutFile "..\artifacts\ACMAIS-LINK-${VERSION}-x64-${FLAVOR}.exe"
InstallDir "$LOCALAPPDATA\Programs\ACMAIS LINK"
RequestExecutionLevel user
SetCompressor lzma
SetCompressorDictSize 32
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1046 "ProductName" "ACMAIS LINK"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador ACMAIS LINK"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "LegalCopyright" "ACMAIS"
!define MUI_ICON "..\src\acmais_link\assets\logo.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\versions\${VERSION}\ACMAIS LINK.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir ACMAIS LINK"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Function .onInit
  StrCpy $InstallerMutex 0
  StrCpy $AppMutex 0
  ${IfNot} ${RunningX64}
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Este pacote requer Windows 10/11 de 64 bits." /SD IDOK
    Abort
  ${EndIf}
  ${If} $INSTDIR != "$LOCALAPPDATA\Programs\ACMAIS LINK"
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "O ACMAIS LINK deve ser instalado na pasta padrão deste usuário. Execute o instalador sem alterar o diretório de destino." /SD IDOK
    Abort
  ${EndIf}
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\ACMAIS_LINK_Installer") p .r0 ?e'
  Pop $1
  ${If} $0 == 0
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Não foi possível iniciar a instalação. Feche este assistente e tente novamente." /SD IDOK
    Abort
  ${EndIf}
  ${If} $1 == 183
    System::Call 'kernel32::CloseHandle(p r0)'
    SetErrorLevel 2
    MessageBox MB_ICONINFORMATION "Já existe uma instalação do ACMAIS LINK em andamento. Conclua ou feche o outro assistente antes de tentar novamente." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $InstallerMutex $0
FunctionEnd

Function ReleaseAppMutex
  ${If} $AppMutex != 0
    System::Call 'kernel32::CloseHandle(p $AppMutex)'
    StrCpy $AppMutex 0
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  Call ReleaseAppMutex
FunctionEnd

Function .onInstFailed
  Call ReleaseAppMutex
FunctionEnd

Function .onGUIEnd
  Call ReleaseAppMutex
  ${If} $InstallerMutex != 0
    System::Call 'kernel32::CloseHandle(p $InstallerMutex)'
    StrCpy $InstallerMutex 0
  ${EndIf}
FunctionEnd

Function CheckRuntime
  StrCpy $0 ""
  SetRegView 32
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${EndIf}
FunctionEnd

Section "Instalar"
  SetShellVarContext current
  Call CheckRuntime
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    !if "${FLAVOR}" == "full"
      InitPluginsDir
      SetOutPath "$PLUGINSDIR"
      SetCompress off
      File "..\.tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
      SetCompress auto
      DetailPrint "Instalando Microsoft WebView2. Aguarde..."
      ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebView2RuntimeInstallerX64.exe" /silent /install' $1
      Call CheckRuntime
      ${If} $0 == ""
      ${OrIf} $0 == "0.0.0.0"
        SetErrorLevel 3
        MessageBox MB_ICONSTOP "O Microsoft WebView2 não foi instalado (código $1). Reinicie o Windows e execute novamente este pacote completo. Se o problema continuar, solicite ajuda ao suporte." /SD IDOK
        Abort
      ${EndIf}
    !else
      SetErrorLevel 3
      MessageBox MB_YESNO|MB_ICONINFORMATION "Este computador ainda não tem o Microsoft WebView2, necessário para abrir o ACMAIS LINK.$\r$\n$\r$\nBaixe o instalador completo: ACMAIS-LINK-${VERSION}-x64-full.exe. Ele já inclui esse componente.$\r$\n$\r$\nDeseja abrir a página oficial de downloads?" /SD IDNO IDNO runtime_missing
      ExecShell "open" "https://github.com/acmaiscont/acmaislink/releases"
      runtime_missing:
      Abort
    !endif
  ${EndIf}
  wait_app:
  ; Hold the same mutex as the app until installation ends, closing the race
  ; between the user's launch and the directory replacement below.
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\ACMAIS_LINK_SingleInstance") p .r0 ?e'
  Pop $1
  ${If} $0 == 0
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Não foi possível verificar se o ACMAIS LINK está fechado. Feche o aplicativo e tente novamente." /SD IDOK
    Abort
  ${EndIf}
  ${If} $1 == 183
    System::Call 'kernel32::CloseHandle(p r0)'
    IfSilent 0 +3
    SetErrorLevel 2
    Abort
    MessageBox MB_RETRYCANCEL|MB_ICONINFORMATION "Feche a janela do ACMAIS LINK e clique em Repetir para continuar a instalação. Seus cadastros serão preservados." /SD IDCANCEL IDRETRY wait_app
    SetErrorLevel 2
    Abort
  ${EndIf}
  StrCpy $AppMutex $0
  StrCpy $ExistingMoved 0
  System::Call 'kernel32::GetCurrentProcessId() i .r3'
  System::Call 'kernel32::GetTickCount() i .r4'
  choose_install_paths:
  StrCpy $StageDir "$INSTDIR\versions\.staging-${VERSION}-$3-$4"
  StrCpy $BackupDir "$INSTDIR\versions\.previous-${VERSION}-$3-$4"
  IfFileExists "$StageDir" next_install_path
  IfFileExists "$BackupDir" next_install_path install_files
  next_install_path:
  IntOp $4 $4 + 1
  Goto choose_install_paths
  install_files:
  DetailPrint "Preparando os arquivos do ACMAIS LINK ${VERSION}..."
  ClearErrors
  SetOutPath "$StageDir"
  File /r "..\release-v${VERSION}\ACMAIS LINK\*"
  ${If} ${Errors}
    Call ReleaseAppMutex
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Não foi possível preparar todos os arquivos. A instalação anterior foi preservada. Verifique o espaço livre e tente novamente." /SD IDOK
    Abort
  ${EndIf}
  ClearErrors
  FileOpen $0 "$StageDir\.complete" w
  IfErrors marker_failed
  FileWrite $0 "${VERSION}"
  FileClose $0
  IfErrors marker_failed marker_ready
  marker_failed:
    Call ReleaseAppMutex
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Não foi possível concluir a preparação dos arquivos. A instalação anterior foi preservada. Tente novamente." /SD IDOK
    Abort
  marker_ready:
  ; Release the working directory before renaming staging on Windows.
  SetOutPath "$INSTDIR"
  IfFileExists "$INSTDIR\versions\${VERSION}" 0 promote_staging
    DetailPrint "Preservando a edição anterior em uma cópia de segurança..."
    ClearErrors
    Rename "$INSTDIR\versions\${VERSION}" "$BackupDir"
    ${If} ${Errors}
      Call ReleaseAppMutex
      SetErrorLevel 1
      MessageBox MB_ICONSTOP "Não foi possível substituir a edição instalada. Ela continua disponível. Feche programas que estejam usando a pasta do ACMAIS LINK e tente novamente." /SD IDOK
      Abort
    ${EndIf}
    StrCpy $ExistingMoved 1
  promote_staging:
  ClearErrors
  Rename "$StageDir" "$INSTDIR\versions\${VERSION}"
  ${If} ${Errors}
    ${If} $ExistingMoved == 1
      ClearErrors
      Rename "$BackupDir" "$INSTDIR\versions\${VERSION}"
      ${If} ${Errors}
        Call ReleaseAppMutex
        SetErrorLevel 1
        MessageBox MB_ICONSTOP "Não foi possível concluir a instalação nem restaurar automaticamente a edição anterior. Seus cadastros estão preservados. A cópia anterior está em:$\r$\n$BackupDir$\r$\n$\r$\nSolicite ajuda ao suporte para restaurar essa pasta." /SD IDOK
        Abort
      ${EndIf}
    ${EndIf}
    Call ReleaseAppMutex
    SetErrorLevel 1
    MessageBox MB_ICONSTOP "Não foi possível concluir a instalação. A edição anterior, se existente, foi preservada. Tente novamente." /SD IDOK
    Abort
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\ACMAIS LINK"
  CreateShortcut "$SMPROGRAMS\ACMAIS LINK\ACMAIS LINK.lnk" "$INSTDIR\versions\${VERSION}\ACMAIS LINK.exe"
  CreateShortcut "$DESKTOP\ACMAIS LINK.lnk" "$INSTDIR\versions\${VERSION}\ACMAIS LINK.exe"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "DisplayName" "ACMAIS LINK"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "Publisher" "ACMAIS"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK" "NoRepair" 1
  ; Release before the finish page so its Run action can open the installed app.
  Call ReleaseAppMutex
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  StrCmp $INSTDIR "$LOCALAPPDATA\Programs\ACMAIS LINK" +3
    MessageBox MB_ICONSTOP "Diretório de instalação inesperado. Desinstalação cancelada."
    Abort
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\ACMAIS_LINK_SingleInstance") p .r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_ICONSTOP "Feche o ACMAIS LINK antes de desinstalar."
    Abort
  ${EndIf}
  RMDir /r "$INSTDIR\versions"
  Delete "$DESKTOP\ACMAIS LINK.lnk"
  Delete "$SMPROGRAMS\ACMAIS LINK\ACMAIS LINK.lnk"
  RMDir "$SMPROGRAMS\ACMAIS LINK"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ACMAIS LINK"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  ; Company configuration, passwords and WebView2 remain available for reinstallation.
SectionEnd

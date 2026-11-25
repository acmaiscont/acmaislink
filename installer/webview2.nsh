!macro ReadWebView2Version ROOT
  ReadRegStr $0 ${ROOT} "${WEBVIEW2_KEY}" "pv"
  ${If} $0 == "0.0.0.0"
    StrCpy $0 ""
  ${EndIf}
!macroend

Function CheckRuntime
  SetRegView 32
  !insertmacro ReadWebView2Version HKLM
  ${If} $0 == ""
    !insertmacro ReadWebView2Version HKCU
  ${EndIf}
  ${If} $0 == ""
  ${AndIf} ${RunningX64}
    SetRegView 64
    !insertmacro ReadWebView2Version HKLM
    ${If} $0 == ""
      !insertmacro ReadWebView2Version HKCU
    ${EndIf}
    SetRegView 32
  ${EndIf}
  ClearErrors
FunctionEnd

Function InstallWebView2
  DetailPrint "Instalando Microsoft Edge WebView2 Runtime. Aguarde..."
  ClearErrors
  ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
  ${If} ${Errors}
    StrCpy $1 "não foi possível iniciar o instalador"
    Call WebView2InstallFailed
  ${EndIf}
  ${If} $1 != 0
    StrCpy $1 "código $1"
    Call WebView2InstallFailed
  ${EndIf}
  Call CheckRuntime
  ${If} $0 == ""
    StrCpy $1 "o runtime não apareceu no Registro"
    Call WebView2InstallFailed
  ${EndIf}
FunctionEnd

Function WebView2InstallFailed
  DetailPrint "Falha ao instalar o Microsoft Edge WebView2 Runtime ($1)."
  SetErrorLevel 3
  MessageBox MB_ICONSTOP "Não foi possível instalar o Microsoft Edge WebView2 Runtime ($1). A instalação do ACMAIS LINK foi interrompida. Verifique a conexão com a internet e tente novamente." /SD IDOK
  Abort
FunctionEnd

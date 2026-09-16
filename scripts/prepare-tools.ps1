$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    New-Item -ItemType Directory -Force '.tools\nsis-current' | Out-Null
    Invoke-WebRequest 'https://github.com/electron-userland/electron-builder-binaries/releases/download/nsis%402.0.1/nsis-bundle-3.12.tar.gz' -OutFile '.tools\nsis-bundle-3.12.tar.gz'
    if ((Get-FileHash '.tools\nsis-bundle-3.12.tar.gz').Hash -ne 'FE36A357F3A220DB893498E830FD80E0769768A18A99F4E4D2447B982538FEED') {
        throw 'Hash do compilador inválido.'
    }
    tar -xzf '.tools\nsis-bundle-3.12.tar.gz' -C '.tools\nsis-current'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao extrair NSIS.' }
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/?linkid=2124701' -OutFile '.tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    $signature = Get-AuthenticodeSignature '.tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'Assinatura Microsoft inválida.'
    }
} finally { Pop-Location }

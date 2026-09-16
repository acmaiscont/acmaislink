param([string]$Nsis = "$PSScriptRoot\..\.tools\nsis-current\nsis-bundle\windows\makensis.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousNsisDir = $env:NSISDIR
$env:NSISDIR = Split-Path -Parent (Resolve-Path $Nsis).Path
Push-Location $projectRoot
try {
    $version = (& '.\.venv\Scripts\python.exe' -c 'from acmais_link import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Versão inválida.' }
    & '.\.venv\Scripts\python.exe' scripts/verify_release.py verify
    if ($LASTEXITCODE -ne 0) { throw 'Recompile o projeto antes de gerar os pacotes.' }
    $runtime = Join-Path $projectRoot '.tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    $signature = Get-AuthenticodeSignature -LiteralPath $runtime
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'Instalador do WebView2 sem assinatura válida da Microsoft.'
    }
    New-Item -ItemType Directory -Force artifacts | Out-Null
    foreach ($flavor in @('update', 'full')) {
        & $Nsis '/INPUTCHARSET' 'UTF8' "/DVERSION=$version" "/DFLAVOR=$flavor" 'installer\acmais.nsi'
        if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar pacote $flavor." }
    }
    $hashes = Get-FileHash "artifacts\ACMAIS-LINK-$version-x64-*.exe" -Algorithm SHA256
    $hashes | ForEach-Object { "$($_.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($_.Path))" } |
        Set-Content "artifacts\SHA256SUMS.txt" -Encoding utf8
} finally { $env:NSISDIR = $previousNsisDir; Pop-Location }

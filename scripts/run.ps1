$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Execute scripts\setup.ps1 antes de iniciar o aplicativo.'
}
& $Python -m acmais_link.main


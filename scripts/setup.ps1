$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = 'python'

if (-not (Test-Path (Join-Path $Root '.venv'))) {
    & $Python -m venv (Join-Path $Root '.venv')
}

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar pip.' }
& $VenvPython -m pip install -r (Join-Path $Root 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
& $VenvPython -m pip install --no-deps -e "$Root"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar projeto.' }
Write-Host 'Ambiente do ACMAIS LINK preparado.'

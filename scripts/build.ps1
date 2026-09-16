$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw 'Execute scripts\setup.ps1 antes de gerar o aplicativo.'
}
Push-Location $Root
try {
    $version = (& $Python -c 'from acmais_link import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Versão inválida.' }
    # OneDrive may mark generated folders read-only, which prevents PyInstaller
    # from replacing its own output. Never touch source/profile directories.
    $outputDir = [IO.Path]::GetFullPath((Join-Path $Root "release-v$version"))
    if (-not $outputDir.StartsWith(([IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Diretório de saída fora do projeto.'
    }
    if (Test-Path -LiteralPath $outputDir) {
        $generatedItems = @(Get-Item -LiteralPath $outputDir -Force) + @(Get-ChildItem -LiteralPath $outputDir -Recurse -Force)
        foreach ($item in $generatedItems) {
            if ($item.Attributes -band [IO.FileAttributes]::ReadOnly) {
                $item.Attributes = $item.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
            }
        }
    }
    & $Python scripts/verify_release.py snapshot
    if ($LASTEXITCODE -ne 0) { throw 'Fontes inconsistentes.' }
    & $Python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Testes reprovados.' }
    & $Python -m PyInstaller --noconfirm --distpath "release-v$version" --workpath "build-v$version" 'ACMAIS_LINK.spec'
    if ($LASTEXITCODE -ne 0) { throw 'Falha no PyInstaller.' }
    & $Python scripts/verify_release.py record
    if ($LASTEXITCODE -ne 0) { throw 'Os arquivos mudaram durante a compilação.' }
}
finally {
    Pop-Location
}

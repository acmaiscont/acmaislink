function Assert-AcmaisSignature {
    param([Parameter(Mandatory)][string]$Path)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Thumbprint -ne $env:ACMAIS_SIGNING_THUMBPRINT -or
        -not $signature.TimeStamperCertificate) {
        throw "Assinatura ou carimbo de tempo inválido: $Path"
    }
}

function Protect-AcmaisExecutable {
    param([Parameter(Mandatory)][string]$Path)
    $thumbprint = $env:ACMAIS_SIGNING_THUMBPRINT
    if (-not $thumbprint) {
        Write-Warning "Arquivo sem assinatura ACMais: $Path"
        return
    }
    if ($thumbprint -notmatch '^[A-Fa-f0-9]{40}$') {
        throw 'ACMAIS_SIGNING_THUMBPRINT deve ser a impressão digital do certificado.'
    }
    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint"
    if (-not $certificate.HasPrivateKey) {
        throw 'O certificado de assinatura precisa de uma chave privada acessível.'
    }
    Set-AuthenticodeSignature -LiteralPath $Path -Certificate $certificate -HashAlgorithm SHA256 `
        -TimestampServer 'http://timestamp.digicert.com' | Out-Null
    Assert-AcmaisSignature -Path $Path
}

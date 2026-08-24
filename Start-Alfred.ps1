#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectDirectory = $PSScriptRoot
Set-Location -LiteralPath $ProjectDirectory

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Start-Process "https://www.docker.com/products/docker-desktop/"
        throw "Docker Desktop is required. Install it, then open Alfred again."
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path -LiteralPath $dockerDesktop) { Start-Process -FilePath $dockerDesktop | Out-Null }
        Write-Host -NoNewline "Starting Docker Desktop"
        $ready = $false
        foreach ($attempt in 1..60) {
            Start-Sleep -Seconds 2
            & docker info *> $null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Write-Host -NoNewline "."
        }
        Write-Host ""
        if (-not $ready) { throw "Docker Desktop did not become ready. Open Docker Desktop and try again." }
    }

    & (Join-Path $ProjectDirectory "install-om-automate.ps1") -NoBuild
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

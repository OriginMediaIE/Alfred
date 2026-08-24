#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ReleaseRef = $(if ($env:ALFRED_RELEASE_REF) { $env:ALFRED_RELEASE_REF } else { "latest" }),
    [string]$InstallDirectory = $(if ($env:ALFRED_INSTALL_DIR) { $env:ALFRED_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "Alfred" })
)

$ErrorActionPreference = "Stop"
$Repository = "OriginMediaIE/Alfred"
$DownloadRoot = $null

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Fail([string]$Message) { throw $Message }

try {
    Write-Step "Checking Docker Desktop"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Start-Process "https://www.docker.com/products/docker-desktop/"
        Fail "Docker Desktop is required. The download page has been opened. Install it, open it, then double-click this installer again."
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path -LiteralPath $dockerDesktop) { Start-Process -FilePath $dockerDesktop | Out-Null }
        Write-Host -NoNewline "Docker Desktop is starting"
        $ready = $false
        foreach ($attempt in 1..60) {
            Start-Sleep -Seconds 2
            & docker info *> $null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            Write-Host -NoNewline "."
        }
        Write-Host ""
        if (-not $ready) { Fail "Docker Desktop did not become ready. Open Docker Desktop, wait for it to finish starting, and run this installer again." }
    }

    Write-Step "Choosing the Alfred release"
    if ($ReleaseRef -eq "latest") {
        try {
            $release = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers @{ "User-Agent" = "Alfred-Installer" }
            $ReleaseRef = [string]$release.tag_name
        } catch {
            $ReleaseRef = "main"
            Write-Host "No tagged release was found; using the main branch."
        }
    }
    if ($ReleaseRef -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or $ReleaseRef.Contains("..")) {
        Fail "The requested release name is not safe: $ReleaseRef"
    }
    Write-Host ("Installing release: " + $ReleaseRef)

    Write-Step "Downloading Alfred from GitHub"
    $DownloadRoot = Join-Path ([IO.Path]::GetTempPath()) ("alfred-installer-" + [Guid]::NewGuid().ToString("N"))
    $archive = Join-Path $DownloadRoot "alfred.zip"
    $expanded = Join-Path $DownloadRoot "expanded"
    New-Item -ItemType Directory -Path $expanded -Force | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repository/archive/$ReleaseRef.zip" -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
    if (-not $source -or -not (Test-Path -LiteralPath (Join-Path $source.FullName "docker-compose.yml"))) {
        Fail "The downloaded release is incomplete."
    }

    Write-Step "Installing Alfred"
    New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallDirectory "data") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallDirectory "logs") -Force | Out-Null
    & robocopy $source.FullName $InstallDirectory /MIR /XD data logs /XF .env .env.bak.* secrets.env secrets.env.* /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -gt 7) { Fail "Windows could not copy the Alfred release into $InstallDirectory (robocopy exit $LASTEXITCODE)." }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDirectory ".env"))) {
        Copy-Item -LiteralPath (Join-Path $InstallDirectory ".env.example") -Destination (Join-Path $InstallDirectory ".env")
    }

    Write-Step "Starting Alfred"
    & (Join-Path $InstallDirectory "install-om-automate.ps1") -Pull
    if ($LASTEXITCODE -ne 0) { Fail "Alfred did not pass its startup readiness check." }

    Write-Step "Creating Alfred shortcuts"
    & (Join-Path $InstallDirectory "scripts\install-docker-launcher.ps1")
    if ($LASTEXITCODE -ne 0) { Write-Warning "The app is installed, but the optional shortcuts could not be created." }

    Write-Host ""
    Write-Host ("Installed files: " + $InstallDirectory) -ForegroundColor Green
    Write-Host ("Private data:    " + (Join-Path $InstallDirectory "data"))
    Write-Host "Open Alfred:     http://127.0.0.1:7000"
} catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($DownloadRoot -and (Test-Path -LiteralPath $DownloadRoot)) {
        Remove-Item -LiteralPath $DownloadRoot -Recurse -Force
    }
}

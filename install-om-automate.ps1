#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$NoBuild,
    [switch]$Pull,
    [switch]$NoOpen,
    [ValidateSet("cpu", "nvidia", "amd")][string]$Accelerator = "cpu",
    [ValidateRange(1, 3600)][int]$TimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
$AppName = "OM Automate"
$RepoDir = $PSScriptRoot
Set-Location -LiteralPath $RepoDir

function Write-Step([string]$Message) { Write-Host ""; Write-Host ("==> " + $Message) -ForegroundColor Cyan }
function Fail([string]$Message) { throw $Message }
function Read-EnvValue([string]$Name) {
    if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) { return $null }
    foreach ($line in [IO.File]::ReadLines((Join-Path $RepoDir ".env"))) {
        if ($line -match "^\s*#") { continue }
        if ($line -match ("^" + [Regex]::Escape($Name) + "=(.*)$")) {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2) {
                $first = $value[0]
                $last = $value[$value.Length - 1]
                if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            return $value
        }
    }
    return $null
}

Write-Step "Preflight"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker Desktop with Compose v2 is required." }
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is unavailable (expected: docker compose)." }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop is installed but its daemon is not running." }

if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) {
    Write-Step "Creating private environment file"
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env without overwriting any existing configuration."
} else {
    Write-Host "Using existing .env unchanged."
}

$dataRaw = if ($env:APP_DATA_DIR) { $env:APP_DATA_DIR } else { Read-EnvValue "APP_DATA_DIR" }
if (-not $dataRaw) { $dataRaw = ".\data" }
$repoFull = [IO.Path]::GetFullPath($RepoDir).TrimEnd('\')
$dataCandidate = if ([IO.Path]::IsPathRooted($dataRaw)) { $dataRaw } else { Join-Path $RepoDir $dataRaw }
$dataFull = [IO.Path]::GetFullPath($dataCandidate).TrimEnd('\')
$pathRoot = [IO.Path]::GetPathRoot($dataFull).TrimEnd('\')
if ($dataFull -eq $repoFull -or $dataFull -eq $pathRoot) { Fail "Refusing broad APP_DATA_DIR: $dataFull" }
if (Test-Path -LiteralPath $dataFull) {
    $item = Get-Item -LiteralPath $dataFull -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "Refusing symlink/reparse-point APP_DATA_DIR: $dataFull" }
} else {
    New-Item -ItemType Directory -Path $dataFull | Out-Null
}
Write-Host ("Data path: " + $dataFull)
$firstBoot = -not (Test-Path -LiteralPath (Join-Path $dataFull "auth.json"))

$bindValue = if ($env:APP_BIND) { $env:APP_BIND } else { Read-EnvValue "APP_BIND" }
if (-not $bindValue) { $bindValue = "127.0.0.1" }
if ($bindValue -notin @("127.0.0.1", "localhost")) {
    if ($env:OM_AUTOMATE_ALLOW_NETWORK -ne "1") {
        Fail "APP_BIND=$bindValue is not loopback. Set OM_AUTOMATE_ALLOW_NETWORK=1 only after configuring authenticated HTTPS."
    }
    $authValue = if ($env:AUTH_ENABLED) { $env:AUTH_ENABLED } else { Read-EnvValue "AUTH_ENABLED" }
    $bypassValue = if ($env:LOCALHOST_BYPASS) { $env:LOCALHOST_BYPASS } else { Read-EnvValue "LOCALHOST_BYPASS" }
    $cookiesValue = if ($env:SECURE_COOKIES) { $env:SECURE_COOKIES } else { Read-EnvValue "SECURE_COOKIES" }
    $originsValue = if ($env:ALLOWED_ORIGINS) { $env:ALLOWED_ORIGINS } else { Read-EnvValue "ALLOWED_ORIGINS" }
    if (-not $authValue) { $authValue = "true" }
    if (-not $bypassValue) { $bypassValue = "false" }
    if (-not $cookiesValue) { $cookiesValue = "false" }
    if ($authValue.ToLowerInvariant() -notin @("1", "true", "yes", "on")) { Fail "Network binding requires AUTH_ENABLED=true." }
    if ($bypassValue.ToLowerInvariant() -notin @("0", "false", "no", "off")) { Fail "Network binding requires LOCALHOST_BYPASS=false." }
    if ($cookiesValue.ToLowerInvariant() -notin @("1", "true", "yes", "on")) { Fail "Network binding requires SECURE_COOKIES=true behind HTTPS." }
    if (-not $originsValue -or $originsValue -notmatch "https://") { Fail "Network binding requires an exact HTTPS origin in ALLOWED_ORIGINS." }
}
$portValue = if ($env:APP_PORT) { $env:APP_PORT } else { Read-EnvValue "APP_PORT" }
if (-not $portValue) { $portValue = "7000" }
$port = 0
if (-not [int]::TryParse($portValue, [ref]$port) -or $port -lt 1 -or $port -gt 65535) { Fail "APP_PORT must be between 1 and 65535." }

$composeArgs = @("-f", "docker-compose.yml")
if ($Accelerator -eq "nvidia") { $composeArgs += @("-f", "docker/gpu.nvidia.yml") }
if ($Accelerator -eq "amd") { $composeArgs += @("-f", "docker/gpu.amd.yml") }
& docker compose @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) { Fail "Compose configuration validation failed." }
Write-Host ("Compose configuration: valid ({0} profile)." -f $Accelerator)

if ($Check) {
    Write-Host ""
    Write-Host "Preflight passed. No images were pulled, built, or started." -ForegroundColor Green
    exit 0
}

$lockPath = Join-Path $RepoDir ".om-automate-install.lock"
$lockStream = $null
try {
    try { $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) }
    catch { Fail "Another install appears to be running ($lockPath)." }

    Write-Step "Starting exact OM Automate services"
    if ($Pull) {
        Write-Step "Downloading the published OM Automate images"
        & docker compose @composeArgs pull
        if ($LASTEXITCODE -ne 0) { Fail "Docker Compose could not pull the published images." }
    }
    $upArgs = @("compose") + $composeArgs + @("up", "-d")
    if ($Pull -or $NoBuild) { $upArgs += "--no-build" } else { $upArgs += "--build" }
    & docker @upArgs
    if ($LASTEXITCODE -ne 0) { Fail "Docker Compose failed to start OM Automate." }

    $healthHost = if ($bindValue -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $bindValue }
    $healthUrl = "http://${healthHost}:${port}/api/health"
    $readyUrl = "http://${healthHost}:${port}/api/ready"
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    Write-Step "Waiting for the application readiness gate"
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $readyUrl -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { $healthy = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        & docker compose @composeArgs ps
        Fail "Readiness verification timed out after ${TimeoutSeconds}s. Inspect with: docker compose logs --tail=200 odysseus"
    }

    & docker compose @composeArgs ps
    Write-Host ""
    Write-Host ("{0} is live at {1} and ready at {2}" -f $AppName, $healthUrl, $readyUrl) -ForegroundColor Green
    Write-Host "Your existing .env and data directory were preserved."
    if ($firstBoot) {
        $temporaryLine = (& docker compose @composeArgs logs --no-color odysseus 2>$null | Select-String -Pattern "Temporary password:" | Select-Object -Last 1).Line
        Write-Host ""
        Write-Host "First login" -ForegroundColor Cyan
        Write-Host "  Username: admin"
        if ($temporaryLine) {
            $temporaryPassword = ($temporaryLine -split "Temporary password:", 2)[1].Trim()
            Write-Host ("  Temporary password: " + $temporaryPassword)
            Write-Host "  Change this password after signing in."
        } else {
            Write-Host "  Run: docker compose logs odysseus"
            Write-Host "  Look for the most recent 'Temporary password' line."
        }
    }
    if (-not $NoOpen) { Start-Process ("http://{0}:{1}" -f $healthHost, $port) }
} finally {
    if ($lockStream) { $lockStream.Dispose() }
    if (Test-Path -LiteralPath $lockPath) { Remove-Item -LiteralPath $lockPath -Force }
}

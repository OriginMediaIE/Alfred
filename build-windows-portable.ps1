#Requires -Version 5.1
<#
  Build a portable Windows distribution for OM Automate.

  Output layout:
    dist\OM Automate\OM Automate.exe
    dist\OM Automate\static\...
    dist\OM Automate\scripts\...
    dist\OM Automate\mcp_servers\...
    dist\OM Automate\services\hwfit\data\...

  The app then keeps using its normal filesystem layout when frozen.

  Usage:
    powershell -ExecutionPolicy Bypass -File .\build-windows-portable.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($msg) { Write-Host ""; Write-Host ("==> " + $msg) -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host ("ERROR: " + $msg) -ForegroundColor Red
    exit 1
}

try {
    $brandManifest = Get-Content (Join-Path $PSScriptRoot "static\manifest.json") -Raw | ConvertFrom-Json
    $appName = [string]$brandManifest.om_automate.native_labels.application
    if (-not $appName -or $appName -ne [string]$brandManifest.name) {
        throw "PWA and native application names do not match."
    }
    if ($appName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "Native application name is not safe for a Windows artifact."
    }
} catch {
    Fail ("Brand configuration is invalid: " + $_.Exception.Message)
}

Write-Step "Checking for Python"
$pyExe = $null
if (Test-Path ".\.venv\Scripts\python.exe") {
    $pyExe = (Resolve-Path ".\.venv\Scripts\python.exe").Path
} else {
    foreach ($c in @("py", "python")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $pyExe = $cmd.Source; break }
    }
    if ($pyExe -like "*WindowsApps*python.exe") {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            $pyExe = $pyCmd.Source
        }
    }
}
if (-not $pyExe) {
    Fail "Python not found on PATH. Install Python 3.11+ first."
}
Write-Host ("Using Python: " + $pyExe)

Write-Step "Installing build dependencies"
& $pyExe -m pip install --upgrade pip --quiet
& $pyExe -m pip install -r requirements-om.lock "pyinstaller==6.21.0" "pystray==0.19.5"
if ($LASTEXITCODE -ne 0) { Fail "Dependency install failed." }

Write-Step "Building portable exe bundle"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

$dataArgs = @(
    "--add-data", "static;static",
    "--add-data", "scripts;scripts",
    "--add-data", "mcp_servers;mcp_servers",
    "--add-data", "services/hwfit/data;services/hwfit/data",
    "--add-data", "config;config",
    "--add-data", ".env.example;.env.example"
)

& $pyExe -m PyInstaller --noconfirm --clean --onedir --noconsole --icon=static/icon.ico --name $appName @dataArgs launcher.py
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller build failed." }

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host ("Portable app folder: " + (Join-Path $PSScriptRoot ("dist\" + $appName))) -ForegroundColor Green
Write-Host "Distribute the whole folder (or zip it) so static assets and scripts stay with the exe." -ForegroundColor Green

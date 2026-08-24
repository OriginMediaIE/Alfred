#Requires -Version 5.1
[CmdletBinding()]
param([switch]$Replace)

$ErrorActionPreference = "Stop"
$ProjectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$StartCommand = Join-Path $ProjectDirectory "Start-Alfred.cmd"
$Icon = Join-Path $ProjectDirectory "static\icon.ico"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Alfred.lnk"
$StartMenuDirectory = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartMenuShortcut = Join-Path $StartMenuDirectory "Alfred.lnk"

if (-not (Test-Path -LiteralPath $StartCommand)) { throw "Missing launcher command: $StartCommand" }
New-Item -ItemType Directory -Path $StartMenuDirectory -Force | Out-Null

function Install-Shortcut([string]$Path) {
    if ((Test-Path -LiteralPath $Path) -and -not $Replace) {
        Write-Host ("Shortcut already exists: " + $Path)
        return
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $StartCommand
    $shortcut.WorkingDirectory = $ProjectDirectory
    if (Test-Path -LiteralPath $Icon) { $shortcut.IconLocation = $Icon }
    $shortcut.Description = "Start Alfred / OM Automate"
    $shortcut.Save()
    Write-Host ("Created shortcut: " + $Path)
}

Install-Shortcut $DesktopShortcut
Install-Shortcut $StartMenuShortcut
Write-Host "pin_status=manual_pin_required"
Write-Host "Windows controls taskbar pinning. Right-click the Alfred shortcut and choose 'Pin to taskbar'."

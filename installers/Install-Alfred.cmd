@echo off
setlocal
title Alfred Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Alfred.ps1"
set "ALFRED_EXIT=%ERRORLEVEL%"
echo.
if "%ALFRED_EXIT%"=="0" (
  echo Alfred installation finished successfully.
) else (
  echo Alfred was not installed. Read the error above, then run this installer again.
)
echo.
pause
exit /b %ALFRED_EXIT%

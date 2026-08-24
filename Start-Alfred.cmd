@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Alfred.ps1" %*
set "ALFRED_EXIT=%ERRORLEVEL%"
if not "%ALFRED_EXIT%"=="0" pause
exit /b %ALFRED_EXIT%

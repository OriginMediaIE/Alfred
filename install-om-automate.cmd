@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-om-automate.ps1" %*
exit /b %ERRORLEVEL%

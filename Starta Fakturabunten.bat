@echo off
setlocal
set "STARTER=%~dp0autostart\start_fakturabunten.ps1"
if not exist "%STARTER%" (
    echo Startfilen saknas: "%STARTER%"
    exit /b 1
)
powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%STARTER%"
set "RC=%ERRORLEVEL%"
exit /b %RC%

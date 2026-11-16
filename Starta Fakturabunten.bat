@echo off
setlocal
set "STARTER=%~dp0autostart\start_fakturabunten.ps1"
if not exist "%STARTER%" (
    echo Startfilen saknas: "%STARTER%"
    pause
    exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%STARTER%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    pause
)
exit /b %RC%

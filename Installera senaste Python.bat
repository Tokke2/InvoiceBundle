@echo off
setlocal
set "SCRIPT=%~dp0autostart\install_python.ps1"
if not exist "%SCRIPT%" (
    echo Python-skriptet saknas: "%SCRIPT%"
    pause
    exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Python kunde inte uppdateras eller installeras. Se logs\starta.log.
    pause
)
exit /b %RC%

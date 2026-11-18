@echo off
setlocal
cd /d "%~dp0.."
echo Removing SHADOW DOWNLOAD autostart task...
.venv\Scripts\python.exe tools\service_manager.py uninstall
echo.
pause
endlocal

@echo off
setlocal
cd /d "%~dp0.."
echo Installing SHADOW DOWNLOAD autostart task...
.venv\Scripts\python.exe tools\service_manager.py install
echo.
pause
endlocal

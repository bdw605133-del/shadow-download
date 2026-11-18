@echo off
setlocal
cd /d "%~dp0.."
.venv\Scripts\python.exe tools\service_manager.py restart
echo.
pause
endlocal

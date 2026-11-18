@echo off
setlocal
cd /d "%~dp0.."
set SHADOW_ENV=production
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment is missing. Run scripts\start_local.bat first.
  exit /b 1
)
.venv\Scripts\python.exe wsgi.py
endlocal

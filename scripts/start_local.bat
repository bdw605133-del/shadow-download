@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
  .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
echo Starting SHADOW DOWNLOAD at http://127.0.0.1:8000
.venv\Scripts\python.exe app.py
endlocal

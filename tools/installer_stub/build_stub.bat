@echo off
setlocal
set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSDEV%" set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSDEV%" set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSDEV%" (
  echo Visual Studio 2022 x64 build tools not found.
  exit /b 1
)
call "%VSDEV%" >nul || exit /b 1
cd /d "%~dp0"
cl.exe /nologo /O2 /DUNICODE /D_UNICODE /EHsc stub.cpp /link /SUBSYSTEM:WINDOWS shell32.lib ole32.lib user32.lib advapi32.lib /OUT:shadow_installer_stub.exe
if errorlevel 1 exit /b 1
echo Built shadow_installer_stub.exe
endlocal

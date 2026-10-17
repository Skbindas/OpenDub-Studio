@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo OpenDub Studio environment not found.
  call "%~dp0..\install.bat"
  if errorlevel 1 exit /b 1
)

set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
"%PYTHON%" -m backend.worker %*
endlocal

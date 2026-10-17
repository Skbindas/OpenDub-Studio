@echo off
setlocal
cd /d "%~dp0"
title OpenDub Studio

if not exist ".venv\Scripts\python.exe" (
  echo OpenDub Studio environment not found.
  echo Running installer first...
  call "%~dp0install.bat"
  if errorlevel 1 (
    echo Installer encountered an error.
    pause
    exit /b 1
  )
)

set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -u "%~dp0scripts\launch.py"
if errorlevel 1 (
  echo.
  echo [OpenDub] Launcher exited with code %errorlevel%.
)
endlocal

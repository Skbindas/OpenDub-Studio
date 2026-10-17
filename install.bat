@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo        OpenDub Studio - Installer
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  echo Install Python 3.10+ and enable "Add Python to PATH".
  pause
  exit /b 1
)

python "%~dp0scripts\bootstrap.py"
if errorlevel 1 (
  echo.
  echo Installation failed.
  pause
  exit /b 1
)

echo.
echo Installation completed successfully.
pause
endlocal

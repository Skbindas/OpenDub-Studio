@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo OpenDub Studio environment not found.
  echo Run install.bat first.
  exit /b 1
)

echo ==========================================
echo   OpenDub Studio - Speaker Diarization
echo ==========================================
echo.
echo Installing pyannote.audio Community-1 runtime with PyTorch 2.11 + TorchCodec 0.16.0...
echo This may download a large dependency set.
echo.

".venv\Scripts\python.exe" -m pip install --upgrade --force-reinstall --no-cache-dir -r requirements-diarization.txt
if errorlevel 1 (
  echo.
  echo Diarization installation failed.
  exit /b 1
)

echo.
echo Speaker diarization runtime installed with pinned PyTorch/TorchCodec compatibility.
echo.
echo Opening the Community-1 model page now. Accept its access conditions while signed in to the same Hugging Face account as your token.
start "" "https://huggingface.co/pyannote/speaker-diarization-community-1"
echo.
echo NEXT:
echo 1. Accept the Community-1 model conditions at:
echo    https://huggingface.co/pyannote/speaker-diarization-community-1
echo 2. Create a Hugging Face access token.
echo 3. In a new CMD window run:
echo    setx HF_TOKEN "hf_YOUR_TOKEN"
echo 4. Close and reopen CMD, then run start.bat.
echo 5. In OpenDub Diagnostics, the model authorization is checked when diarization runs.
echo.
pause
endlocal

@echo off
setlocal
cd /d "%~dp0"
echo Installing or updating BabyMind...
py -m pip install -e .
if errorlevel 1 (
  echo.
  echo Installation failed. Check that Python 3.10+ is installed.
  pause
  exit /b 1
)
echo.
echo Starting BabyMind for this computer and trusted Wi-Fi devices...
echo The access token will appear below. Keep it private.
babymind-web --lan
pause

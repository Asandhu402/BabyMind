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
echo Starting BabyMind on this computer...
py -m babymind.server
pause

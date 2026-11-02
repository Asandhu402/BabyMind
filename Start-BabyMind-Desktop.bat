@echo off
setlocal
cd /d "%~dp0"
echo Installing or updating BabyMind desktop requirements...
py -m pip install -e .
if errorlevel 1 (
  echo.
  echo Installation failed. Check your Python installation and internet connection.
  pause
  exit /b 1
)
echo.
echo Starting BabyMind desktop...
py -m babymind.desktop
if errorlevel 1 (
  echo.
  echo BabyMind desktop stopped with an error.
  pause
)
endlocal

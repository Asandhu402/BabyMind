@echo off
setlocal
cd /d "%~dp0"
if not exist "BabyMind-iPhone.exe" (
  echo BabyMind-iPhone.exe is missing. Download and extract the complete portable package.
  pause
  exit /b 1
)
echo Starting BabyMind's secure iPhone companion server.
echo Keep this window open while using BabyMind on your iPhone.
echo Use only on a trusted private Wi-Fi network.
echo.
"BabyMind-iPhone.exe"
echo.
echo BabyMind iPhone server stopped.
pause

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

py -m pip install --upgrade pip
py -m pip install -e ".[build]"

py -m PyInstaller --noconfirm --clean --windowed --name BabyMind --paths src --collect-all webview --add-data "src/babymind/web;babymind/web" run_desktop.py

Write-Host ""
Write-Host "Build complete: dist\BabyMind\BabyMind.exe"
Write-Host "Copy the entire dist\BabyMind folder when moving the app to another PC."

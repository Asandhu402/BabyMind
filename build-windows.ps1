$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

py -m pip install --upgrade pip
py -m pip install -e ".[build]"

py -m PyInstaller --noconfirm --clean --windowed --name BabyMind --paths src --collect-all webview --collect-all cryptography --add-data "src/babymind/web;babymind/web" run_desktop.py

# Bundle a separate console runner so the packaged desktop app can execute
# only the fixed Python unittest-discovery workflow after explicit approval.
py -m PyInstaller --noconfirm --clean --console --name BabyMindTestRunner --paths src --collect-all cryptography src/babymind/test_runner.py
$testRunnerTarget = Join-Path $PSScriptRoot "dist\\BabyMind\\tools\\BabyMindTestRunner"
New-Item -ItemType Directory -Force -Path $testRunnerTarget | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "dist\\BabyMindTestRunner\\*") -Destination $testRunnerTarget -Recurse -Force
if (-not (Test-Path (Join-Path $testRunnerTarget "BabyMindTestRunner.exe"))) {
    throw "Could not stage the approved project test runner."
}

# Bundle the official llama.cpp Windows CPU runtime. The GGUF model is
# downloaded and checksum-verified by BabyMind on first launch.
$runtimeUrl = "https://github.com/ggml-org/llama.cpp/releases/download/b11960/llama-b11960-bin-win-cpu-x64.zip"
$tempRoot = Join-Path $env:TEMP ("babymind-llama-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $tempRoot "llama.cpp.zip"
$extract = Join-Path $tempRoot "extract"
$runtimeTarget = Join-Path $PSScriptRoot "dist\BabyMind\llama.cpp"

try {
    New-Item -ItemType Directory -Force -Path $tempRoot, $extract | Out-Null
    Write-Host "Downloading official llama.cpp Windows CPU runtime..."
    Invoke-WebRequest -Uri $runtimeUrl -OutFile $archive
    $runtimeHash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($runtimeHash -ne "73f962f82850d244db47eaacb9d913637027b82399124324298576d58c5f4287") {
        throw "The downloaded llama.cpp archive failed its SHA-256 integrity check."
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force

    $server = Get-ChildItem -Path $extract -Filter "llama-server.exe" -Recurse |
        Select-Object -First 1
    if (-not $server) {
        throw "The llama.cpp archive did not contain llama-server.exe."
    }

    New-Item -ItemType Directory -Force -Path $runtimeTarget | Out-Null
    Copy-Item -Path (Join-Path $server.Directory.FullName "*") -Destination $runtimeTarget -Recurse -Force

    if (-not (Test-Path (Join-Path $runtimeTarget "llama-server.exe"))) {
        throw "Could not stage llama-server.exe in the BabyMind package."
    }

    @"
BabyMind Windows portable package

1. Double-click BabyMind.exe.
2. On first launch, approve the one-time download of the local AI model (about 2.8 GB).
3. Keep the internet connection active until setup finishes.
4. Later launches use the saved model locally and do not need the download again.

The model is stored in your user profile under .babymind\models.
Inference runs on this PC. No LM Studio account or API key is needed.
Microsoft Edge WebView2 Runtime is required by the desktop window and is
normally present on current Windows 11 systems.
"@ | Set-Content -Path (Join-Path $PSScriptRoot "dist\BabyMind\FIRST-RUN.txt") -Encoding UTF8
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

Write-Host ""
Write-Host "Build complete: dist\BabyMind\BabyMind.exe"
Write-Host "The package includes BabyMind, Python, and llama.cpp."
Write-Host "The verified GGUF model downloads once on first launch."

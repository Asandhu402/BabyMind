$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip
python -m pip install -e ".[build]"

$webAssets = Join-Path $PSScriptRoot "src\babymind\web"

python -m PyInstaller --noconfirm --clean --windowed --name BabyMind --paths src --collect-all webview --collect-all cryptography --add-data "$webAssets;babymind/web" run_desktop.py

# Build a small console companion so the same portable package can expose
# authenticated HTTPS access to an iPhone on the same trusted Wi-Fi network.
# This entry point prepares the same verified local model before starting
# server.py in mandatory --lan mode.
python -m PyInstaller --noconfirm --onefile --console --name BabyMind-iPhone --paths src --workpath build/pyinstaller-iphone --distpath dist/iphone --specpath build/spec-iphone --collect-all cryptography --hidden-import tkinter --hidden-import tkinter.messagebox --hidden-import tkinter.ttk --add-data "$webAssets;babymind/web" run_iphone.py
if ($LASTEXITCODE -ne 0) { throw "Could not build the BabyMind iPhone companion." }



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

    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "dist\\iphone\\BabyMind-iPhone.exe") -Destination (Join-Path $PSScriptRoot "dist\\BabyMind\\BabyMind-iPhone.exe") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Start-BabyMind-iPhone-Portable.bat") -Destination (Join-Path $PSScriptRoot "dist\\BabyMind\\Start-BabyMind-iPhone.bat") -Force

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

iPhone companion (same trusted private Wi-Fi only):
1. Close BabyMind.exe first; run only one BabyMind launcher at a time.
2. Connect the iPhone and this PC to the same private Wi-Fi network.
3. Double-click Start-BabyMind-iPhone.bat. Either launcher can perform the
   first model download; the model file is shared between both launchers.
3. Allow Windows Firewall access on Private networks only, if prompted.
4. Keep this console open and keep the PC awake. Follow the printed HTTPS URL,
   one-time token, and lan-ca.crt certificate instructions.
5. Transfer only lan-ca.crt to the iPhone, install its profile, then enable
   full trust in Settings > General > About > Certificate Trust Settings.
6. Open the printed HTTPS URL in Safari and enter the token. Do not share it.

Do not use guest/public Wi-Fi, enable Public firewall access, or configure
router port forwarding. The iPhone is a browser companion; this PC runs the
model and stores BabyMind data. Real iPhone pairing still requires a device test.
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

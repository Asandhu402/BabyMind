#!/usr/bin/env bash
# Ubuntu desktop installer. Run as a normal user; sudo is used only for apt.
set -euo pipefail
umask 077

fail() { printf 'BabyMind installation stopped: %s\\n' "$*" >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'Ubuntu x86-64 is required.'
[[ $EUID -ne 0 ]] || fail 'Run as your normal desktop user, not root; the installer will use sudo for packages.'
[[ -r /etc/os-release ]] || fail 'Cannot identify this operating system.'
# shellcheck source=/dev/null
. /etc/os-release
version=${VERSION_ID:-0}
[[ ${ID:-} == ubuntu && ${version%%.*} =~ ^[0-9]+$ && ${version%%.*} -ge 22 ]] || fail 'Ubuntu 22.04 or newer is required.'
command -v sudo >/dev/null || fail 'sudo is required to install Ubuntu packages.'
command -v apt-get >/dev/null || fail 'apt-get is required.'
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f $source_dir/pyproject.toml && -f $source_dir/build-linux.sh && -f $source_dir/src/babymind/install_model.py ]] || fail 'Run install-linux.sh from a complete BabyMind checkout.'

install_root="${XDG_DATA_HOME:-$HOME/.local/share}/babymind"
bin_dir="$HOME/.local/bin"
applications="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
launcher="$bin_dir/babymind"
desktop="$applications/babymind.desktop"
current="$install_root/current"

# Refuse to replace unrelated files or point our installation at another tree.
if [[ -e $install_root || -L $install_root ]]; then
  [[ -d $install_root && ! -L $install_root && -f $install_root/.babymind-managed ]] || fail "Existing $install_root is not installer-managed; it was not changed."
fi
if [[ -e $install_root/versions || -L $install_root/versions ]]; then
  [[ -d $install_root/versions && ! -L $install_root/versions ]] || fail 'The versions path is not a directory owned by this installer.'
fi
if [[ -e $current || -L $current ]]; then
  [[ -L $current && -f $current/.babymind-installed ]] || fail "Existing $current is not a BabyMind installation; it was not changed."
  target=$(readlink -f -- "$current") || fail 'Cannot resolve existing installation.'
  [[ $target == "$install_root"/versions/* ]] || fail 'Existing installation points outside the BabyMind versions directory.'
fi
if [[ -e $launcher || -L $launcher ]]; then
  [[ -L $launcher && $(readlink -- "$launcher") == "$current/BabyMind" ]] || fail "Existing $launcher is not our launcher; it was not changed."
fi
if [[ -e $desktop || -L $desktop ]]; then
  [[ -f $desktop && ! -L $desktop ]] && grep -qx 'X-BabyMind-Installer=true' "$desktop" || fail "Existing $desktop is not our desktop entry; it was not changed."
fi

printf '%s\\n' 'Installing Ubuntu packages (sudo may ask for your password)...'
sudo apt-get update
# libasound2 has been renamed in newer Ubuntu releases.
if apt-cache show libasound2t64 >/dev/null 2>&1; then audio=libasound2t64; else audio=libasound2; fi
sudo apt-get install -y ca-certificates curl git python3 python3-venv python3-pip python3-dev \\
  build-essential cmake pkg-config tar libnss3 libgl1 libegl1 libgbm1 libdrm2 "$audio" \\
  libdbus-1-3 libfontconfig1 libfreetype6 libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxrandr2 \\
  libxtst6 libxi6 libxss1 libxshmfence1 libxkbfile1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \\
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \\
  libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-render0 libxcb-shape0 libxcb-xkb1 libxcb-xinerama0

# Use Ubuntu's packaged Python, not an unrelated virtual environment or custom
# Python earlier on PATH; its matching shared library is provided by apt.
python=/usr/bin/python3
[[ -x $python ]] || fail 'Ubuntu Python is missing after package installation.'
# Fail before downloading the multi-gigabyte model if the interpreter is outside
# the tested dependency range. Python 3.15 is the newest supported series.
"$python" - <<'PYTHON'
import sys
version = sys.version_info[:2]
if not ((3, 11) <= version < (3, 16)):
    print(
        "BabyMind requires Python >=3.11,<3.16; "
        f"found {sys.version.split()[0]}. Install a supported Python and retry.",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(f"Using supported Python {sys.version.split()[0]}.")
PYTHON
printf '%s\\n' 'Downloading and verifying the local AI model (about 2.71 GB if not already present)...'
# Keep the app and model under the same normal per-user defaults for desktop launches.
env -u BABYMIND_GGUF_MODEL BABYMIND_HOME="$HOME/.babymind" PYTHONPATH="$source_dir/src" \\
  "$python" -m babymind.install_model

mkdir -p -- "$install_root/versions" "$bin_dir" "$applications"
printf '%s\\n' 'BabyMind Linux installer v1' > "$install_root/.babymind-managed"
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p -- "$cache_root"
work=$(mktemp -d "$cache_root/babymind-build.XXXXXXXX")
staged=''
cleanup() {
  rm -rf -- "$work"
  if [[ -n $staged && -d $staged ]]; then rm -rf -- "$staged"; fi
}
trap cleanup EXIT
printf '%s\\n' 'Building the Linux desktop and local CPU runtime; this can take several minutes...'
mkdir -p -- "$work/source"
# Build in our own temporary directory; never clean or overwrite the caller's checkout.
tar -C "$source_dir" --exclude='./.git' --exclude='./.venv' --exclude='./build' \\
  --exclude='./dist' --exclude='./state' --exclude='./.babymind' -cf - . | tar -C "$work/source" -xf -
(cd "$work/source" && BABYMIND_BUILD_PYTHON="$python" ./build-linux.sh)
[[ -x $work/source/dist/BabyMind/BabyMind && -x $work/source/dist/BabyMind/llama.cpp/llama-server ]] || fail 'The build did not produce both desktop and runtime executables.'
# Catch a missing runtime shared library before publishing the installation.
"$work/source/dist/BabyMind/llama.cpp/llama-server" --version
"$work/source/dist/BabyMind/BabyMind" --check-package
"$work/source/dist/BabyMind/BabyMind" --check-desktop-deps

# Preserve older versions for recovery. Publish a completed version by atomic symlink swap.
staged=$(mktemp -d "$install_root/versions/install.XXXXXXXX")
cp -a -- "$work/source/dist/BabyMind/." "$staged/"
printf '%s\\n' 'BabyMind Linux installer v1' > "$staged/.babymind-installed"
newlink="$install_root/.current.$$"
[[ ! -e $newlink && ! -L $newlink ]] || fail 'Temporary install link already exists.'
ln -s -- "$staged" "$newlink"
mv -Tf -- "$newlink" "$current"
staged=''
if [[ ! -L $launcher ]]; then ln -s -- "$current/BabyMind" "$launcher"; fi

# Desktop Entry Exec uses its own quoting rules; escape literal shell characters
# and percent codes rather than asking a shell to interpret the user's home path.
"$python" - "$desktop" "$current/BabyMind" <<'PY'
import os, sys, tempfile
path, executable = sys.argv[1:]
quoted = '"' + executable.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\`').replace('$', '\\\$').replace('%', '%%') + '"'
data = '[Desktop Entry]\\nType=Application\\nName=BabyMind\\nComment=Local AI workspace\\nExec=' + quoted + '\\nTerminal=false\\nCategories=Utility;\\nX-BabyMind-Installer=true\\n'
fd, temp = tempfile.mkstemp(prefix='.babymind-', dir=os.path.dirname(path), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(data)
    os.replace(temp, path)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
PY
printf '\\n%s\\n' 'BabyMind is installed. Open BabyMind from your Applications menu,' \\
  "or start it with: $launcher" \\
  "Model and personal data: $HOME/.babymind" \\
  'Previous app versions are kept in the BabyMind installation directory.'

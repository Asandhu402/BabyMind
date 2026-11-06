#!/usr/bin/env bash
# BabyMind one-shot Linux installer + launcher.
#
# Run as a normal user:
#   bash install-and-run-linux.sh
# or from a fresh machine with only curl present:
#   bash -c 'curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/install-and-run-linux.sh | bash'
#
# It detects the distro, installs any missing required software/patches via the
# system package manager, downloads the BabyMind source, builds and installs
# the app plus its local AI model, then starts BabyMind automatically.
set -euo pipefail

say() { printf '\n==> %s\n' "$*"; }
fail() { printf 'BabyMind install-and-run stopped: %s\n' "$*" >&2; exit 1; }

[[ $(uname -s) == Linux ]] || fail 'This installer only supports Linux.'
[[ $(uname -m) == x86_64 ]] || fail 'This installer supports x86-64 only.'
[[ $EUID -ne 0 ]] || fail 'Run as your normal user, not root.'

# --- 1. Detect the package manager and required software ---------------------
say 'Detecting system and required software…'
if command -v apt-get >/dev/null 2>&1; then
  PM=apt; PKG_UPDATE='apt-get update'; PKG_INSTALL='apt-get install -y'
elif command -v dnf >/dev/null 2>&1; then
  PM=dnf; PKG_UPDATE='dnf makecache'; PKG_INSTALL='dnf install -y'
elif command -v pacman >/dev/null 2>&1; then
  PM=pacman; PKG_UPDATE='pacman -Sy'; PKG_INSTALL='pacman -S --noconfirm'
else
  fail 'No supported package manager found (apt, dnf or pacman). Install the prerequisites manually, see docs/LINUX_PORTABLE.md.'
fi
printf 'Package manager: %s\n' "$PM"

install_pkgs() {
  # $@ = package names for the detected package manager.
  command -v sudo >/dev/null 2>&1 || fail 'sudo is required to install system packages.'
  say "Installing missing packages: $*"
  sudo $PKG_UPDATE
  sudo $PKG_INSTALL "$@"
}

case $PM in
  apt)
    # libasound2 was renamed to libasound2t64 on newer Ubuntu/Debian.
    if sudo apt-cache show libasound2t64 >/dev/null 2>&1; then audio=libasound2t64; else audio=libasound2; fi
    # Check each requirement first so we only invoke the package manager when
    # something is actually missing.
    missing=()
    for tool in git curl python3 make c++ cmake pkg-config tar; do
      command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || missing+=("python3-venv" "python3-pip")
    if ((${#missing[@]})); then
      install_pkgs "${missing[@]}" python3-dev build-essential ca-certificates \
        libnss3 libgl1 libegl1 libgbm1 libdrm2 "$audio" libdbus-1-3 libfontconfig1 libfreetype6 \
        libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxrandr2 libxtst6 libxi6 \
        libxss1 libxshmf1 libxkbfile1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
        libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shm0 libxcb-sync0 \
        libxcb-xfixes0 libxcb-render0 libxcb-shape0 libxcb-xkb1 libxcb-xinerama0
    else
      say 'All required software is already present.'
    fi
    ;;
  dnf)
    missing=()
    for tool in git curl python3 make c++ cmake pkg-config tar; do
      command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    if ((${#missing[@]})); then
      install_pkgs "${missing[@]}" python3-devel gcc-c++ make cmake alsa-lib mesa-libGL \
        nss nspr dbus-glib fontconfig freetype libX11-xcb libXcomposite libXdamage libXfixes \
        libXrender libXrandr libXtst libXi libXScrnSaver libxkbfile libxkbcommon libxkbcommon-x11 \
        libxcb-devel
    else
      say 'All required software is already present.'
    fi
    ;;
  pacman)
    missing=()
    for tool in git curl python make c++ cmake pkg-config tar; do
      command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    if ((${#missing[@]})); then
      install_pkgs "${missing[@]}" base-devel cmake alsa-lib mesa nss dbus-glib fontconfig freetype2 \
        libx11 libxcomposite libxdamage libxfixes libxrender libxrandr libxtst libxi libxss \
        libxkbfile libxkbcommon libxkbcommon-x11 libxcb
    else
      say 'All required software is already present.'
    fi
    ;;
esac

for tool in git curl python3 cmake c++; do
  command -v "$tool" >/dev/null 2>&1 || fail "Required tool '$tool' is still missing after installation."
done

# BabyMind needs Python 3.13 or newer. Accept a versioned interpreter, because a
# distro whose default python3 is older can have python3.13+ installed alongside.
python3_ok=
for candidate in python3.15 python3.14 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null; then
    python3_ok=1
    break
  fi
done
[[ -n $python3_ok ]] || fail "BabyMind requires Python 3.13 or newer, but $(python3 -V 2>&1) was found. Install python3.13+ (Ubuntu 26.04 or newer ships it) and re-run."

# --- 2. Get the BabyMind source ----------------------------------------------
say 'Fetching the BabyMind source…'
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P || true)
if [[ -n $script_dir && -f $script_dir/pyproject.toml && -f $script_dir/install-linux.sh ]]; then
  source_dir=$script_dir
  say "Using the checkout at $source_dir"
else
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  git clone --depth 1 https://github.com/Asandhu402/BabyMind.git "$work/repo"
  source_dir=$work/repo
  say "Cloned BabyMind into $source_dir (temporary; removed after install)"
fi

# --- 3. Build, install, and download the model --------------------------------
say 'Building and installing BabyMind and its local AI model (this can take a while)…'
bash "$source_dir/install-linux.sh"

# --- 4. Run BabyMind -----------------------------------------------------------
launcher="$HOME/.local/bin/babymind"
say 'Starting BabyMind…'
if [[ -x $launcher ]]; then
  exec "$launcher"
else
  fail "Installed launcher not found at $launcher; start BabyMind from your Applications menu."
fi

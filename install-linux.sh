#!/usr/bin/env bash
# Linux desktop installer for apt-get, dnf, pacman and zypper systems.
# Run as your normal desktop user; sudo is used only for system packages.
# bootstrap-linux.sh prepares a fresh machine, including a Python 3.13-3.15
# interpreter, and then runs this script.
set -euo pipefail
umask 077

fail() { printf 'BabyMind installation stopped: %s\n' "$*" >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'Linux x86-64 is required.'
# The floor is set by PySide6's published x86-64 wheel: the bundled Qt cannot
# load on an older libc than the wheel it ships in was built against.
GLIBC_MIN=2.28
[[ $EUID -ne 0 ]] || fail 'Run as your normal desktop user, not root; the installer will use sudo for packages.'
[[ -r /etc/os-release ]] || fail 'Cannot identify this operating system.'
if [[ -e /lib/ld-musl-x86_64.so.1 ]] || ldd --version 2>/dev/null | grep -qi musl; then
  fail 'Alpine/musl is unsupported: PySide6 publishes no musl wheels, so Qt cannot be installed there.'
fi
glibc=$(ldd --version 2>/dev/null | awk 'NR == 1 {print $NF}' || true)
case ${glibc:-} in
  [0-9]*.[0-9]*)
    min_major=${GLIBC_MIN%%.*}
    min_minor=${GLIBC_MIN#*.}
    glibc_major=${glibc%%.*}
    glibc_rest=${glibc#*.}
    glibc_minor=${glibc_rest%%.*}
    if ((glibc_major < min_major || (glibc_major == min_major && glibc_minor < min_minor))); then
      fail "glibc $GLIBC_MIN or newer is required (this system has $glibc)."
    fi
    ;;
  *) printf 'Could not read the glibc version; continuing.\n' >&2 ;;
esac
command -v sudo >/dev/null || fail 'sudo is required to install system packages.'
PM=
for candidate in apt-get dnf pacman zypper; do
  if command -v "$candidate" >/dev/null 2>&1; then PM=$candidate; break; fi
done
[[ -n $PM ]] || fail 'A supported package manager (apt-get, dnf, pacman or zypper) is required; run bootstrap-linux.sh on other systems.'
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

install_system_packages() {
  case $PM in
    apt-get)
      sudo apt-get update
      # libasound2 has been renamed in newer Ubuntu releases.
      if apt-cache show libasound2t64 >/dev/null 2>&1; then audio=libasound2t64; else audio=libasound2; fi
      sudo apt-get install -y ca-certificates curl git python3 python3-venv python3-pip python3-dev \
        build-essential cmake pkg-config tar libnss3 libgl1 libegl1 libgbm1 libdrm2 "$audio" \
        libdbus-1-3 libfontconfig1 libfreetype6 libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxrandr2 \
        libxtst6 libxi6 libxss1 libxshmfence1 libxkbfile1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
        libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-render0 libxcb-shape0 libxcb-xkb1 libxcb-xinerama0

      ;;
    dnf)
      sudo dnf install -y ca-certificates curl git tar gcc gcc-c++ make cmake pkgconf-pkg-config \
        python3 python3-devel python3-pip alsa-lib mesa-libGL mesa-libEGL mesa-libgbm libdrm nss nspr \
        dbus-glib fontconfig freetype libX11-xcb libXcomposite libXdamage libXfixes libXrender libXrandr \
        libXtst libXi libXScrnSaver libxkbfile libxkbcommon libxkbcommon-x11 libxcb
      ;;
    pacman)
      sudo pacman -S --noconfirm --needed ca-certificates curl git tar base-devel cmake pkgconf \
        python python-pip alsa-lib mesa nss nspr dbus-glib fontconfig freetype2 \
        libx11 libxcomposite libxdamage libxfixes libxrender libxrandr libxtst libxi libxss \
        libxkbfile libxkbcommon libxkbcommon-x11 libxcb
      ;;
    zypper)
      sudo zypper --non-interactive install ca-certificates curl git tar gcc gcc-c++ make cmake pkg-config \
        python3 python3-devel python3-pip libasound2 libglvnd0 libgbm1 libdrm2 libnss3 mozilla-nspr \
        dbus-1-glib fontconfig freetype2 libX11-xcb1 libXcomposite1 libXdamage1 libXfixes3 libXrender1 \
        libXrandr2 libXtst6 libXi6 libXScrnSaver1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shm0 \
        libxcb-sync1 libxcb-xfixes0 libxcb-render0 libxcb-shape0 libxcb-xinerama0
      ;;
  esac
}

printf 'Installing %s packages (sudo may ask for your password)...\n' "$PM"
install_system_packages

# Python 3.13 or newer is required; bootstrap-linux.sh provides it when the
# distribution does not. BABYMIND_BUILD_PYTHON points at that interpreter.
python=/usr/bin/python3
if [[ -n ${BABYMIND_BUILD_PYTHON:-} ]]; then
  python=$BABYMIND_BUILD_PYTHON
else
  for candidate in /usr/bin/python3.15 /usr/bin/python3.14 /usr/bin/python3.13 /usr/bin/python3; do
    [[ -x $candidate ]] || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null; then
      python=$candidate
      break
    fi
  done
fi
python_version_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null
}
python_has_venv() { "$1" -c 'import venv, ensurepip' >/dev/null 2>&1; }
python_has_shared_library() {
  local libdir ldlib
  libdir=$("$1" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")' 2>/dev/null) || return 1
  ldlib=$("$1" -c 'import sysconfig; print(sysconfig.get_config_var("LDLIBRARY") or "")' 2>/dev/null) || return 1
  [[ -n $libdir && -n $ldlib && -e $libdir/$ldlib ]]
}

[[ -x $python ]] || fail "Python interpreter is missing: $python"
python_version_ok "$python" || fail \
  "BabyMind requires Python 3.13 or newer, but $python reports $("$python" -V 2>&1). Run bootstrap-linux.sh to install the newest supported Python, or install a distribution package such as python3.13."
# A versioned distribution interpreter needs its own venv, pip and header packages.
if [[ $python == /usr/bin/python3.* ]] && { ! python_has_venv "$python" || ! python_has_shared_library "$python"; }; then
  python_suffix=${python#/usr/bin/python}
  if [[ $python_suffix != 3 ]]; then
    case $PM in
      apt-get) sudo apt-get install -y "python${python_suffix}-venv" "python${python_suffix}-pip" "python${python_suffix}-dev" ;;
      dnf) sudo dnf install -y "python${python_suffix}-devel" "python${python_suffix}-pip" ;;
      zypper) sudo zypper --non-interactive install "python${python_suffix//./}" "python${python_suffix//./}-devel" ;;
      pacman) ;;
    esac
  fi
fi
python_has_venv "$python" || fail "$python cannot create virtual environments; install its venv package (for example python3.13-venv) and re-run."
if ! python_has_shared_library "$python"; then
  printf 'warning: %s has no shared libpython; the frozen build stops with its own message if it cannot find one.\n' "$python" >&2
fi
printf '%s\n' 'Downloading and verifying the local AI model (about 2.71 GB if not already present)...'
# Keep the app and model under the same normal per-user defaults for desktop launches.
env -u BABYMIND_GGUF_MODEL BABYMIND_HOME="$HOME/.babymind" PYTHONPATH="$source_dir/src" \
  "$python" -m babymind.install_model

mkdir -p -- "$install_root/versions" "$bin_dir" "$applications"
printf '%s\n' 'BabyMind Linux installer v1' > "$install_root/.babymind-managed"
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p -- "$cache_root"
work=$(mktemp -d "$cache_root/babymind-build.XXXXXXXX")
staged=''
cleanup() {
  rm -rf -- "$work"
  if [[ -n $staged && -d $staged ]]; then rm -rf -- "$staged"; fi
}
trap cleanup EXIT
printf '%s\n' 'Building the Linux desktop and local CPU runtime; this can take several minutes...'
mkdir -p -- "$work/source"
# Build in our own temporary directory; never clean or overwrite the caller's checkout.
tar -C "$source_dir" --exclude='./.git' --exclude='./.venv' --exclude='./build' \
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
printf '%s\n' 'BabyMind Linux installer v1' > "$staged/.babymind-installed"
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
quoted = '"' + executable.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
data = '[Desktop Entry]\nType=Application\nName=BabyMind\nComment=Local AI workspace\nExec=' + quoted + '\nTerminal=false\nCategories=Utility;\nX-BabyMind-Installer=true\n'
fd, temp = tempfile.mkstemp(prefix='.babymind-', dir=os.path.dirname(path), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(data)
    os.replace(temp, path)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
PY
printf '\n%s\n' 'BabyMind is installed. Open BabyMind from your Applications menu,' \
  "or start it with: $launcher" \
  "Model and personal data: $HOME/.babymind" \
  'Previous app versions are kept in the BabyMind installation directory.'

# The documented one-command installer asks for the app to be started, so the
# single copy-paste ends with BabyMind running. Detach it so the terminal (and
# the piped installer script) is not held open by the app.
if [[ ${BABYMIND_LAUNCH_AFTER_INSTALL:-0} == 1 ]]; then
  printf '%s\n' 'Starting BabyMind...'
  if command -v setsid >/dev/null 2>&1; then
    setsid -- "$launcher" </dev/null >/dev/null 2>&1 &
  else
    "$launcher" </dev/null >/dev/null 2>&1 &
  fi
fi

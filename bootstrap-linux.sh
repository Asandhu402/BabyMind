#!/usr/bin/env bash
# One-command bootstrap for a fresh x86-64 Linux machine.
#
#   bash bootstrap-linux.sh                 prepare this machine and install BabyMind
#   bash bootstrap-linux.sh --prepare-only  install prerequisites and the newest Python
#   bash bootstrap-linux.sh --dry-run       print the plan and change nothing
#
# Nothing has to be installed first. The script discovers the package manager,
# installs the tools it needs, and picks the newest supported Python: an
# interpreter that is already present, a distribution package, or the newest
# CPython release built from python.org source. It then hands over to
# install-linux.sh, which installs the Qt/WebEngine libraries, the model, the
# CPU runtime and the desktop entry.
set -euo pipefail

# The pinned dependency set supports CPython 3.13-3.15 (see docs/PYTHON_SUPPORT.md).
MIN_MINOR=13
MAX_MINOR=15
REPO=${BABYMIND_GITHUB_REPO:-Asandhu402/BabyMind}
REF=${BABYMIND_GITHUB_REF:-main}
PREPARE_ONLY=${BABYMIND_BOOTSTRAP_PREPARE_ONLY:-0}
DRY_RUN=${BABYMIND_BOOTSTRAP_DRY_RUN:-0}

say() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'BabyMind bootstrap stopped: %s\n' "$*" >&2; exit 1; }

for argument in "$@"; do
  case $argument in
    --prepare-only) PREPARE_ONLY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h)
      if [[ -f ${BASH_SOURCE[0]} ]]; then
        sed -n '2,14p' "${BASH_SOURCE[0]}"
      else
        printf 'Usage: bash bootstrap-linux.sh [--dry-run] [--prepare-only]\n'
      fi
      exit 0
      ;;
    *) die "Unknown option: $argument (use --dry-run or --prepare-only)." ;;
  esac
done

# --- 1. Host checks ----------------------------------------------------------
say 'Checking this machine'
[[ $(uname -s) == Linux ]] || die 'BabyMind runs on Linux only.'
[[ $(uname -m) == x86_64 ]] || die "BabyMind needs 64-bit x86 (x86_64); this machine reports $(uname -m)."
# The glibc floor comes from PySide6's published wheels, not from our own code:
# the bundled Qt cannot load on an older libc than the wheel it ships in was
# built against. The x86-64 wheel is manylinux_2_28 from PySide6 6.8 onwards.
GLIBC_MIN=2.28
[[ $EUID -ne 0 ]] || die 'Run as your normal desktop user, not root: sudo is used only for packages.'
[[ -r /etc/os-release ]] || die 'Cannot identify this distribution (/etc/os-release is missing).'
# shellcheck source=/dev/null
. /etc/os-release
DISTRO=${PRETTY_NAME:-${NAME:-Linux}}
if [[ -e /lib/ld-musl-x86_64.so.1 ]] || ldd --version 2>/dev/null | grep -qi musl; then
  die 'Alpine/musl is unsupported: PySide6 publishes no musl wheels, so Qt cannot be installed there.'
fi
glibc=$(ldd --version 2>/dev/null | awk 'NR == 1 {print $NF}' || true)
case ${glibc:-} in
  [0-9]*.[0-9]*)
    glibc_major=${glibc%%.*}
    glibc_rest=${glibc#*.}
    glibc_minor=${glibc_rest%%.*}
    min_major=${GLIBC_MIN%%.*}
    min_minor=${GLIBC_MIN#*.}
    if ((glibc_major < min_major || (glibc_major == min_major && glibc_minor < min_minor))); then
      die "glibc $GLIBC_MIN or newer is required (this system has $glibc)."
    fi
    ;;
  *) warn 'Could not read the glibc version; continuing.' ;;
esac
note "$DISTRO on $(uname -m), glibc ${glibc:-unknown}"
command -v sudo >/dev/null 2>&1 || die 'sudo is required to install system packages.'

# --- 2. Package manager ------------------------------------------------------
say 'Selecting a package manager'
PM=${BABYMIND_BOOTSTRAP_PM:-}
if [[ -z $PM ]]; then
  for candidate in apt-get dnf pacman zypper; do
    if command -v "$candidate" >/dev/null 2>&1; then PM=$candidate; break; fi
  done
fi
case ${PM:-} in
  apt-get|dnf|pacman|zypper) ;;
  '') die 'No supported package manager found (apt-get, dnf, pacman or zypper).' ;;
  *) die "Unsupported package manager: $PM (use apt-get, dnf, pacman or zypper)." ;;
esac
command -v "$PM" >/dev/null 2>&1 || die "Configured package manager not found: $PM"
note "Using $PM"

sudo_cmd=(sudo)

pm_update() {
  case $PM in
    apt-get) "${sudo_cmd[@]}" apt-get update ;;
    dnf) "${sudo_cmd[@]}" dnf -y makecache ;;
    pacman) "${sudo_cmd[@]}" pacman -Sy --noconfirm ;;
    zypper) "${sudo_cmd[@]}" zypper --non-interactive refresh ;;
  esac
}

pm_install() {
  (($#)) || return 0
  case $PM in
    apt-get) "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf) "${sudo_cmd[@]}" dnf install -y "$@" ;;
    pacman) "${sudo_cmd[@]}" pacman -S --noconfirm --needed "$@" ;;
    zypper) "${sudo_cmd[@]}" zypper --non-interactive install "$@" ;;
  esac
}

# Every system change goes through here so --dry-run stays truthful.
install_packages() {
  (($#)) || return 0
  if [[ $DRY_RUN == 1 ]]; then
    note "Would install with $PM: $*"
    return 0
  fi
  pm_install "$@"
}

refresh_packages() {
  [[ $DRY_RUN == 1 ]] && return 0
  pm_update
}

# --- 3. Tools the bootstrap itself needs -------------------------------------
say 'Checking required tools'
missing=()
for tool in tar gzip; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  missing+=(curl ca-certificates)
fi
if ((${#missing[@]})); then
  note "Installing: ${missing[*]}"
  refresh_packages
  install_packages "${missing[@]}"
else
  note 'curl or wget, tar and gzip are present'
fi

if command -v curl >/dev/null 2>&1; then
  # --retry only covers timeouts and 4xx/5xx; a transfer failure such as an
  # HTTP/2 stream error (curl exit 92) aborts on the first try without this.
  # The flag needs curl 7.71+, so only use it when this curl knows it.
  curl_retry_all=''
  if curl --help all 2>/dev/null | grep -q -- '--retry-all-errors'; then
    curl_retry_all='--retry-all-errors --retry-delay 2'
  fi
  # shellcheck disable=SC2086  # $curl_retry_all holds flags only and must word-split
  download() { curl -fsSL --retry 3 $curl_retry_all --connect-timeout 20 "$1"; }
  # shellcheck disable=SC2086
  download_to() { curl -fsSL --retry 3 $curl_retry_all --connect-timeout 20 --output "$2" "$1"; }
elif command -v wget >/dev/null 2>&1; then
  download() { wget -qO- --tries=3 --timeout=20 "$1"; }
  download_to() { wget -q --tries=3 --timeout=20 --output-document="$2" "$1"; }
else
  die 'curl or wget is required; both are missing after installing packages.'
fi

# --- 4. Newest supported Python ---------------------------------------------
python_version() { "$1" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null; }

python_supported() {
  local version major rest minor
  version=$(python_version "$1") || return 1
  [[ -n $version ]] || return 1
  major=${version%%.*}
  rest=${version#*.}
  minor=${rest%%.*}
  ((major == 3 && minor >= MIN_MINOR && minor <= MAX_MINOR))
}

# PyInstaller needs a shared libpython, so reject statically linked interpreters.
python_has_shared_library() {
  local libdir ldlib
  libdir=$("$1" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")' 2>/dev/null) || return 1
  ldlib=$("$1" -c 'import sysconfig; print(sysconfig.get_config_var("LDLIBRARY") or "")' 2>/dev/null) || return 1
  [[ -n $libdir && -n $ldlib && -e $libdir/$ldlib ]]
}

python_has_venv() { "$1" -c 'import venv, ensurepip' >/dev/null 2>&1; }

python_ready() {
  [[ -x ${1:-} ]] || return 1
  python_supported "$1" && python_has_shared_library "$1" && python_has_venv "$1"
}

python_libdir() { "$1" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")' 2>/dev/null; }

# Highest minor first: anything already installed is preferred over downloads.
# SYSTEM_PYTHON_DIR is where distributions install their interpreters; override it
# (BABYMIND_BOOTSTRAP_SYSTEM_PYTHON_DIR) only for unusual prefixes or tests.
SYSTEM_PYTHON_DIR=${BABYMIND_BOOTSTRAP_SYSTEM_PYTHON_DIR:-/usr/bin}
scan_python() {
  local candidate
  for candidate in \
      "$(command -v python3.15 2>/dev/null || true)" "$SYSTEM_PYTHON_DIR/python3.15" \
      "$(command -v python3.14 2>/dev/null || true)" "$SYSTEM_PYTHON_DIR/python3.14" \
      "$(command -v python3.13 2>/dev/null || true)" "$SYSTEM_PYTHON_DIR/python3.13" \
      "$(command -v python3 2>/dev/null || true)" "$SYSTEM_PYTHON_DIR/python3"; do
    [[ -n $candidate && -x $candidate ]] || continue
    if python_ready "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

distro_python_packages() {
  case $PM in
    apt-get) printf '%s\n' "python3.$1" "python3.$1-venv" "python3.$1-dev" ;;
    dnf) printf '%s\n' "python3.$1" "python3.$1-devel" ;;
    pacman) : ;; # Arch ships one rolling python; there are no versioned packages
    zypper) printf '%s\n' "python3$1" "python3$1-devel" ;;
  esac
}

python_build_packages() {
  case $PM in
    apt-get) printf '%s\n' build-essential pkg-config libssl-dev zlib1g-dev libbz2-dev \
      liblzma-dev libffi-dev libsqlite3-dev libreadline-dev libncurses-dev ;;
    dnf) printf '%s\n' gcc gcc-c++ make pkgconf-pkg-config openssl-devel zlib-devel \
      bzip2-devel xz-devel libffi-devel sqlite-devel readline-devel ncurses-devel ;;
    pacman) printf '%s\n' base-devel openssl zlib bzip2 xz libffi sqlite readline ncurses ;;
    zypper) printf '%s\n' gcc gcc-c++ make pkg-config libopenssl-devel zlib-devel \
      libbz2-devel xz-devel libffi-devel sqlite3-devel readline-devel ncurses-devel ;;
  esac
}

# Newest final CPython release the pinned dependency set supports.
newest_python_release() {
  local listing version
  listing=$(download https://www.python.org/ftp/python/ 2>/dev/null || true)
  version=$(printf '%s\n' "$listing" \
    | grep -oE '3\.[0-9]+\.[0-9]+/' \
    | tr -d '/' \
    | awk -F. -v min="$MIN_MINOR" -v max="$MAX_MINOR" '$1 == 3 && $2 >= min && $2 <= max' \
    | sort -V | tail -n 1)
  printf '%s' "${version:-}"
}

build_python() {
  local version=$1 prefix=$2 work log jobs
  mapfile -t packages < <(python_build_packages)
  say "Installing Python build dependencies with $PM"
  refresh_packages
  install_packages "${packages[@]}"
  work=$(mktemp -d "${TMPDIR:-/tmp}/babymind-python.XXXXXXXX")
  log=$work/build.log
  say "Downloading CPython $version from python.org"
  if ! download_to "https://www.python.org/ftp/python/$version/Python-$version.tgz" "$work/Python.tgz"; then
    rm -rf -- "$work"
    die "Could not download CPython $version from python.org."
  fi
  tar -xzf "$work/Python.tgz" -C "$work"
  jobs=$(nproc 2>/dev/null || echo 2)
  say "Building CPython $version with $jobs parallel jobs (this takes several minutes)"
  if ! (
    cd "$work/Python-$version"
    ./configure --prefix="$prefix" --enable-shared --with-ensurepip=install >"$log" 2>&1
    make -j"$jobs" >>"$log" 2>&1
    make install >>"$log" 2>&1
  ); then
    warn "CPython build failed; the end of the log follows."
    tail -n 30 "$log" >&2 || true
    rm -rf -- "$work"
    die "Building CPython $version failed. Install a distribution package for Python 3.13-3.15 (for example python3.13, python3.13-venv and python3.13-dev) and re-run."
  fi
  rm -rf -- "$work"
  [[ -x $prefix/bin/python3 ]] || die "CPython $version did not install into $prefix."
}

say "Looking for Python 3.$MIN_MINOR to 3.$MAX_MINOR"
PYTHON=
PYTHON_ORIGIN=
PYTHON_LIBDIR=
if [[ -n ${BABYMIND_BOOTSTRAP_PYTHON:-} ]]; then
  python_ready "$BABYMIND_BOOTSTRAP_PYTHON" \
    || die "BABYMIND_BOOTSTRAP_PYTHON=$BABYMIND_BOOTSTRAP_PYTHON is not a supported Python 3.$MIN_MINOR-3.$MAX_MINOR with venv support and a shared libpython."
  PYTHON=$BABYMIND_BOOTSTRAP_PYTHON
  PYTHON_ORIGIN='BABYMIND_BOOTSTRAP_PYTHON'
else
  PYTHON=$(scan_python || true)
  [[ -n $PYTHON ]] && PYTHON_ORIGIN='already installed'
fi

if [[ -z $PYTHON ]]; then
  [[ $DRY_RUN == 1 ]] || refresh_packages
  for minor in 15 14 13; do
    mapfile -t packages < <(distro_python_packages "$minor")
    ((${#packages[@]})) || continue
    if [[ $DRY_RUN == 1 ]]; then
      note "Would try the distribution's Python 3.$minor packages: ${packages[*]}"
      continue
    fi
    note "Trying the distribution's Python 3.$minor packages"
    if install_packages "${packages[@]}" >/dev/null 2>&1; then :; else
      note "No complete Python 3.$minor package set from $PM"
    fi
    PYTHON=$(scan_python || true)
    if [[ -n $PYTHON ]]; then
      PYTHON_ORIGIN="$PM package"
      break
    fi
  done
fi

if [[ -z $PYTHON ]]; then
  version=${BABYMIND_BOOTSTRAP_PYTHON_VERSION:-}
  [[ -n $version ]] || version=$(newest_python_release)
  [[ -n $version ]] || version="3.$MAX_MINOR.0"
  case $version in
    3.1[3-5].*) ;;
    *) die "Unsupported Python version to build: $version (use 3.13, 3.14 or 3.15)." ;;
  esac
  prefix=${BABYMIND_BOOTSTRAP_PYTHON_PREFIX:-${XDG_CACHE_HOME:-$HOME/.cache}/babymind/python/$version}
  if [[ $DRY_RUN == 1 ]]; then
    note "If no distribution package provides Python 3.$MIN_MINOR-3.$MAX_MINOR, would build CPython $version from source into $prefix"
    PYTHON=$prefix/bin/python3
    PYTHON_ORIGIN='source build (planned)'
  else
    build_python "$version" "$prefix"
    PYTHON=$prefix/bin/python3
    PYTHON_ORIGIN="CPython $version built from source"
    PYTHON_LIBDIR=$(python_libdir "$PYTHON")
  fi
fi

python_ready "$PYTHON" || [[ $DRY_RUN == 1 ]] \
  || die "The selected interpreter is not usable: $PYTHON"
note "Python: $PYTHON (from $PYTHON_ORIGIN)"

# --- 5. BabyMind source ------------------------------------------------------
say 'Locating the BabyMind source'
source_dir=
if [[ -n ${BABYMIND_BOOTSTRAP_SOURCE:-} ]]; then
  source_dir=$(cd -- "$BABYMIND_BOOTSTRAP_SOURCE" 2>/dev/null && pwd -P) \
    || die "BABYMIND_BOOTSTRAP_SOURCE does not exist: $BABYMIND_BOOTSTRAP_SOURCE"
elif [[ -f $PWD/pyproject.toml && -f $PWD/install-linux.sh && -d $PWD/src/babymind ]]; then
  source_dir=$PWD
  note "Using this checkout: $source_dir"
else
  if [[ $DRY_RUN == 1 ]]; then
    note "Would download https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF"
    source_dir=
  else
    work=$(mktemp -d "${TMPDIR:-/tmp}/babymind-source.XXXXXXXX")
    trap 'rm -rf -- "$work"' EXIT
    note "Downloading the newest $REPO ($REF)"
    download_to "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" "$work/babymind.tar.gz" \
      || die "Could not download the BabyMind source from GitHub."
    mkdir -p "$work/src"
    tar -xzf "$work/babymind.tar.gz" -C "$work/src" --strip-components=1
    source_dir=$work/src
  fi
fi
if [[ -n $source_dir ]]; then
  [[ -f $source_dir/install-linux.sh ]] || die "No install-linux.sh in $source_dir"
fi

# --- 6. Plan, prepare or install --------------------------------------------
if [[ $DRY_RUN == 1 ]]; then
  say 'Plan (dry run, nothing was changed)'
  note "Distribution: $DISTRO"
  note "Package manager: $PM"
  note "Python: $PYTHON ($PYTHON_ORIGIN)"
  [[ -n $source_dir ]] && note "Source: $source_dir"
  note 'Next: install-linux.sh installs the Qt 6/WebEngine libraries, downloads'
  note 'the pinned 2.71 GB model, builds the CPU runtime and desktop, and adds'
  note 'the application-menu entry. Re-run without --dry-run to do that.'
  exit 0
fi

if [[ -n $PYTHON_LIBDIR ]]; then
  export LD_LIBRARY_PATH="$PYTHON_LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export BABYMIND_BUILD_PYTHON=$PYTHON

if [[ $PREPARE_ONLY == 1 ]]; then
  say 'This machine is ready for BabyMind'
  note "Python $PYTHON_ORIGIN: $PYTHON"
  note "Continue with: bash ${source_dir:-<checkout>}/install-linux.sh"
  exit 0
fi

say 'Installing BabyMind'
# install-linux.sh owns the Qt/WebEngine package lists, the model download, the
# build and the per-user installation, so both entry points share one code path.
# It runs as a child (not via exec) so the downloaded source is still cleaned up.
bash "$source_dir/install-linux.sh"

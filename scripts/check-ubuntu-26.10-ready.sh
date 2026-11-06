#!/usr/bin/env bash
# Read-only readiness check: is THIS machine able to test BabyMind on Ubuntu
# 26.10? Prints one line per requirement and a summary. Changes nothing.
#
# Usage: bash scripts/check-ubuntu-26.10-ready.sh
# Exit status: 0 if no FAIL, 1 otherwise (WARN never fails the run).
set -uo pipefail

fails=0
warns=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; warns=$((warns + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fails=$((fails + 1)); }
info() { printf '       %s\n' "$*"; }

echo "BabyMind Ubuntu 26.10 test readiness"

# --- OS, architecture ---------------------------------------------------------
if [[ -r /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  if [[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 26.10 ]]; then
    pass "Ubuntu 26.10 (${PRETTY_NAME:-unknown})"
  else
    fail "expected Ubuntu 26.10, found ${PRETTY_NAME:-unknown} (ID=${ID:-?} VERSION_ID=${VERSION_ID:-?})"
  fi
else
  fail '/etc/os-release is missing; cannot identify the distribution'
fi

arch=$(uname -m)
[[ $arch == x86_64 ]] && pass "x86-64 ($arch)" || fail "expected x86-64, found $arch"

# --- glibc (26.10 ships 2.43) ------------------------------------------------
glibc=$(ldd --version 2>/dev/null | awk 'NR == 1 {print $NF}')
if [[ ${glibc:-} =~ ^[0-9]+\.[0-9]+ ]]; then
  major=${glibc%%.*}; minor=${glibc#*.}
  if (( major > 2 || (major == 2 && minor >= 43) )); then
    pass "glibc $glibc (portable artifact needs >= 2.43)"
  else
    fail "glibc $glibc is below 2.43 (Ubuntu 26.04/26.10 floor for the portable archive)"
  fi
else
  warn "could not read the glibc version"
fi

# --- Package manager and privileges -------------------------------------------
command -v apt-get >/dev/null 2>&1 && pass 'apt-get present' || fail 'apt-get missing (not a Debian-based system?)'
if sudo -n true 2>/dev/null; then
  pass 'sudo works without a password (workflows need it)'
else
  warn 'sudo needs a password or is missing; CI jobs use sudo for apt and sysctl'
fi

# --- Toolchain ----------------------------------------------------------------
for tool in git curl tar cmake c++ make; do
  if command -v "$tool" >/dev/null 2>&1; then pass "$tool present"; else warn "$tool missing (needed for source builds; apt can install it)"; fi
done
if [[ -f /etc/ssl/certs/ca-certificates.crt ]]; then pass 'ca-certificates present'; else warn 'ca-certificates missing (sudo apt-get install -y ca-certificates)'; fi

# --- Python 3.13-3.15 ---------------------------------------------------------
py_ok=0
for candidate in python3.15 python3.14 python3.13 python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  ver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
  case $ver in
    3.13|3.14|3.15) pass "$candidate -> CPython $("$candidate" -V 2>&1 | awk '{print $2}')"; py_ok=1; break ;;
    *) info "$candidate reports $ver (not supported)" ;;
  esac
done
(( py_ok )) || fail 'no supported Python 3.13-3.15 (Ubuntu 26.10 ships 3.14.7)'

# --- Network (short timeouts; failures here block CI and installs) -----------
check_url() {
  local name=$1 url=$2 required=${3:-required}
  code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 8 --max-time 15 "$url" 2>/dev/null)
  if [[ $code == 2* || $code == 3* || $code == 404 ]]; then
    pass "reachable: $name ($url -> $code)"
  elif [[ $required == optional ]]; then
    warn "unreachable: $name ($url -> ${code:-no response})"
  else
    fail "unreachable: $name ($url -> ${code:-no response})"
  fi
}
check_url 'GitHub' 'https://github.com/' required
check_url 'PyPI' 'https://pypi.org/simple/' required
check_url 'PyPI files host' 'https://files.pythonhosted.org/' required
check_url 'Hugging Face (model)' 'https://huggingface.co/' required
check_url 'Ubuntu archive (apt)' 'http://archive.ubuntu.com/ubuntu/' required
check_url 'python.org (CPython fallback)' 'https://www.python.org/ftp/python/' optional

# --- Resources ----------------------------------------------------------------
disk_kb=$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')
disk_gb=$(( disk_kb / 1024 / 1024 ))
if (( disk_gb >= 10 )); then pass "disk free: ${disk_gb} GB (>= 10 GB needed)"; else fail "disk free: ${disk_gb} GB (need >= 10 GB for the model and build)"; fi

mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_gb=$(( mem_kb / 1024 / 1024 ))
if (( mem_gb >= 8 )); then pass "RAM: ${mem_gb} GB"; elif (( mem_gb >= 4 )); then warn "RAM: ${mem_gb} GB (8 GB+ recommended; CPU inference will be slow)"; else fail "RAM: ${mem_gb} GB (4 GB is the minimum for a 4B-class model)"; fi

# --- Sandbox prerequisites (AppArmor, unprivileged user namespaces) ----------
restrict=$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || true)
if [[ -z $restrict ]]; then
  pass 'unprivileged user namespaces: no AppArmor restriction exposed'
elif [[ $restrict == 0 ]]; then
  pass 'unprivileged user namespaces: enabled (AppArmor restriction off)'
else
  warn "unprivileged user namespaces restricted (sysctl kernel.apparmor_restrict_unprivileged_userns=$restrict); the sandbox fails closed and CI re-enables it with: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0"
fi

# --- GUI test prerequisites ----------------------------------------------------
command -v xvfb-run >/dev/null 2>&1 && pass 'xvfb-run present' || warn 'xvfb-run missing; CI installs it, or: sudo apt-get install -y xvfb xauth'

echo
if (( fails )); then
  printf 'NOT READY: %d failure(s), %d warning(s). See docs/UBUNTU_26_10_TESTING.md.\n' "$fails" "$warns"
  exit 1
else
  printf 'READY (with %d warning(s)). See docs/UBUNTU_26_10_TESTING.md for the acceptance run.\n' "$warns"
  exit 0
fi

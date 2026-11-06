#!/usr/bin/env bash
# Resolve install-linux.sh's package list for one package manager against that
# distribution's own repositories, without installing anything.
#
#   bash scripts/check_distro_packages.sh dnf
#
# The dnf, pacman and zypper lists are otherwise only covered by fixture tests
# with a stubbed package manager. Package names differ per distribution and get
# renamed, so a typo or a stale name would not surface until a user hit it.
# This asks the real package manager to resolve every name in a dry run.
#
# The list is extracted from install-linux.sh rather than repeated here, so the
# check cannot drift from what users actually get.
set -euo pipefail

PM=${1:?usage: check_distro_packages.sh [--list] <dnf|pacman|zypper>}
# --list prints the extracted names and stops. The resolution step needs the
# real package manager and its repositories, which only exist on the target
# distribution; the extraction does not, so it can be tested anywhere.
LIST_ONLY=0
if [[ $PM == --list ]]; then
  LIST_ONLY=1
  PM=${2:?usage: check_distro_packages.sh --list <dnf|pacman|zypper>}
fi
# Only these three. The apt-get arm contains a comment and an if/then that
# word-splitting would turn into package names ("newer", "renamed", "fi"), and
# it needs no checking anyway: CI already installs the apt list for real.
case $PM in
  dnf | pacman | zypper) ;;
  *) echo "unsupported package manager: $PM (expected dnf, pacman or zypper)" >&2; exit 1 ;;
esac
script=$(cd "$(dirname "$0")/.." && pwd)/install-linux.sh
[[ -r $script ]] || { echo "cannot read $script" >&2; exit 1; }

# install-linux.sh has more than one "case $PM" (the Python packages have their
# own, written on a single line), so the whole file cannot be scanned for the
# arm: the first match would never see a terminator. Scope to the body of
# install_system_packages first, then take this manager's arm from that.
packages=$(
  awk '
    /^install_system_packages\(\) \{/ { inbody = 1; next }
    inbody && /^\}/                   { inbody = 0 }
    inbody                            { print }
  ' "$script" | awk -v pm="$PM" '
    $0 ~ "^ *" pm "\\)" { inarm = 1; next }
    inarm && /^ *;;/    { inarm = 0 }
    inarm               { print }
  ' | sed 's/\\//g' | tr -s '[:space:]' '\n' |
    grep -v '^$' | grep -v '^-' | grep -vxE "sudo|install|$PM" | sort -u
)

# An empty list means the extraction broke, not that the distro needs nothing.
# Fail loudly rather than reporting a vacuous pass.
count=$(printf '%s\n' "$packages" | grep -c . || true)
if [[ -z $packages || $count -lt 20 ]]; then
  echo "extraction found only $count package(s) for $PM; expected the full desktop set" >&2
  exit 1
fi

if [[ $LIST_ONLY == 1 ]]; then
  printf '%s\n' "$packages"
  exit 0
fi

echo "Resolving $count $PM packages from install-linux.sh"

# shellcheck disable=SC2086  # $packages is a package list and must word-split
case $PM in
  dnf)
    # --assumeno resolves the whole transaction, then answers "no" to the
    # prompt: every name and dependency must exist, nothing is installed.
    dnf install -y --assumeno $packages
    ;;
  pacman)
    pacman -Sy >/dev/null # a fresh container ships no sync database
    # --print lists the targets it would act on; an unknown name is an error.
    pacman -S --noconfirm --needed --print $packages
    ;;
  zypper)
    zypper --non-interactive refresh >/dev/null
    zypper --non-interactive install --dry-run $packages
    ;;
  *)
    echo "unsupported package manager: $PM" >&2
    exit 1
    ;;
esac

echo "OK: every $PM package name resolved"

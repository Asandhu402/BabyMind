#!/usr/bin/env bash
# Install and launch BabyMind in one step.
#
#   bash install-and-run-linux.sh
#   bash -c 'curl -fsSL https://raw.githubusercontent.com/Asandhu402/BabyMind/main/install-and-run-linux.sh | bash'
#
# The whole "prepare this machine and install" job belongs to bootstrap-linux.sh;
# this wrapper runs it and then starts the app. Run it from a checkout to install
# that checkout instead of downloading the newest source.
set -euo pipefail

say() { printf '\n==> %s\n' "$*"; }
fail() { printf 'BabyMind install-and-run stopped: %s\n' "$*" >&2; exit 1; }

REPO=${BABYMIND_GITHUB_REPO:-Asandhu402/BabyMind}
REF=${BABYMIND_GITHUB_REF:-main}

[[ $(uname -s) == Linux ]] || fail 'This installer only supports Linux.'

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P || true)
if [[ -n $script_dir && -f $script_dir/bootstrap-linux.sh ]]; then
  bootstrap=$script_dir/bootstrap-linux.sh
  export BABYMIND_BOOTSTRAP_SOURCE=$script_dir
else
  say 'Fetching the BabyMind bootstrap'
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  url="https://raw.githubusercontent.com/$REPO/$REF/bootstrap-linux.sh"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --output "$work/bootstrap-linux.sh" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q --tries=3 --output-document="$work/bootstrap-linux.sh" "$url"
  else
    fail 'curl or wget is required here; run the self-contained bootstrap command from the README instead.'
  fi
  bootstrap=$work/bootstrap-linux.sh
fi
[[ -f $bootstrap ]] || fail "Bootstrap script not found: $bootstrap"

bash "$bootstrap"

launcher="$HOME/.local/bin/babymind"
[[ -x $launcher ]] || fail "Installed launcher not found at $launcher; start BabyMind from your Applications menu."
say 'Starting BabyMind'
exec "$launcher"

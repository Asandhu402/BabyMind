#!/usr/bin/env bash
# Install and enable BabyMind's permanent autonomous learning service.
#
# The service runs the frozen desktop executable in its headless
# --learning-service mode. It is enabled by default by install-linux.sh. A
# systemd user session is required; --if-available skips cleanly on machines
# without one (for example CI shells) instead of failing the installation.
set -euo pipefail

die() { printf 'BabyMind learning service installation stopped: %s\n' "$*" >&2; exit 1; }

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/.." && pwd -P)
dry_run=0
if_available=0
model_filename=${BABYMIND_MODEL_FILENAME:-}
launcher=${BABYMIND_LEARNING_LAUNCHER:-$HOME/.local/bin/babymind}
unit_path=${BABYMIND_LEARNING_UNIT_PATH:-$HOME/.config/systemd/user/babymind-learning.service}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --if-available) if_available=1; shift ;;
    --model-filename) [[ $# -ge 2 ]] || die '--model-filename needs a value.'; model_filename=$2; shift 2 ;;
    --launcher) [[ $# -ge 2 ]] || die '--launcher needs a value.'; launcher=$2; shift 2 ;;
    --unit-path) [[ $# -ge 2 ]] || die '--unit-path needs a value.'; unit_path=$2; shift 2 ;;
    -h|--help)
      printf 'Usage: bash scripts/install-learning-service.sh [--dry-run] [--if-available] [--model-filename NAME] [--launcher PATH] [--unit-path PATH]\n'
      exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ -z $model_filename ]]; then
  model_filename=$(sed -n 's/^MODEL_FILENAME = "\(.*\)"$/\1/p' \
    "$repo_root/src/babymind/first_run.py" 2>/dev/null | head -n 1 || true)
fi
[[ -n $model_filename ]] || die 'Could not determine the pinned model filename from first_run.py.'
[[ $model_filename != */* && $model_filename == *.gguf ]] || die 'The model filename is not a plain .gguf name.'

# systemd unit values are not shell words. Quote paths that may contain spaces
# and escape literal percent signs so they are not read as unit specifiers.
systemd_quote() {
  local value=${1//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//%/%%}
  printf '"%s"' "$value"
}
exec_start=$(systemd_quote "$launcher")
model_name=${model_filename//\\/\\\\}
model_name=${model_name//\"/\\\"}
model_name=${model_name//%/%%}
model_env="BABYMIND_GGUF_MODEL=%h/.babymind/models/$model_name"

render_unit() {
  cat <<EOF
[Unit]
Description=BabyMind Permanent Autonomous Learning Service
After=default.target

[Service]
Type=simple
# The launcher symlink survives application upgrades. This mode is headless and
# never opens the Qt window. The supervisor itself is fail-closed and has a
# durable kill switch at ~/.babymind/learning/STOP.
ExecStart=$exec_start --learning-service
Restart=always
RestartSec=30
KillSignal=SIGTERM
TimeoutStopSec=60
Environment="PYTHONUNBUFFERED=1"
Environment="BABYMIND_HOME=%h/.babymind"
Environment="BABYMIND_SANDBOX=require"
Environment="BABYMIND_LLAMA_SERVER=%h/.local/share/babymind/current/llama.cpp/llama-server"
Environment="$model_env"
Environment="BABYMIND_LLAMA_PORT=1236"
EnvironmentFile=-%h/.config/babymind/models.env

[Install]
WantedBy=default.target
EOF
}

if [[ $dry_run == 1 ]]; then
  render_unit
  exit 0
fi

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
  if [[ $if_available == 1 ]]; then
    printf 'BabyMind learning service: no running systemd user session; the in-app supervisor remains active.\n' >&2
    exit 0
  fi
  die 'A running systemd user session is required.'
fi
if [[ ! -x $launcher && ! -L $launcher ]]; then
  die "Install BabyMind first (launcher not found: $launcher)."
fi

mkdir -p -- "$(dirname -- "$unit_path")" "$HOME/.config/babymind"
env_file="$HOME/.config/babymind/models.env"
if [[ ! -e $env_file ]]; then
  install -m 600 /dev/null "$env_file"
fi
chmod 600 "$env_file"

temporary=$(mktemp "$(dirname -- "$unit_path")/.babymind-learning.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT
render_unit > "$temporary"
chmod 644 "$temporary"
mv -f -- "$temporary" "$unit_path"
trap - EXIT
systemctl --user daemon-reload
systemctl --user enable --now babymind-learning.service
printf 'BabyMind autonomous learning service installed and enabled.\n'
printf 'Status:  systemctl --user status babymind-learning.service\n'
printf 'Stop:    babymind learning stop   (or systemctl --user disable --now babymind-learning.service)\n'
printf 'Resume:  babymind learning reset\n'
printf 'Logs:    journalctl --user -u babymind-learning.service\n'

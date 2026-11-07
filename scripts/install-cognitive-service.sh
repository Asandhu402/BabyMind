#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "BabyMind's background service supports Debian-based Linux x86-64 only." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "A running systemd user session is required." >&2
  exit 1
fi
BABYMIND_BIN="$(command -v babymind || true)"
if [[ -z "$BABYMIND_BIN" ]]; then
  echo "Install BabyMind in the current user environment first (babymind command not found)." >&2
  exit 1
fi
mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/babymind"
ENV_FILE="$HOME/.config/babymind/models.env"
if [[ ! -e "$ENV_FILE" ]]; then
  install -m 600 /dev/null "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
cat > "$HOME/.config/systemd/user/babymind-cognitive.service" <<EOF
[Unit]
Description=BabyMind Cognitive Background Agent
After=default.target

[Service]
Type=simple
ExecStart=$BABYMIND_BIN cognitive service --interval 60 --agent BM-01
Restart=on-failure
RestartSec=15
EnvironmentFile=-%h/.config/babymind/models.env
TimeoutStopSec=300
KillSignal=SIGTERM
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now babymind-cognitive.service
echo "BabyMind cognitive service installed and started."
echo "Optional model routes/secrets: edit $ENV_FILE (permissions 600)."
echo "Status: systemctl --user status babymind-cognitive.service"
echo "Stop:   systemctl --user disable --now babymind-cognitive.service"

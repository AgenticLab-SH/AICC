#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/cm-auth-broker
[[ $(id -u) -eq 0 ]] || { echo "rollback must run as root" >&2; exit 2; }

systemctl disable --now cm-auth-broker.service 2>/dev/null || true
if [[ -f "$APP_DIR/backup/broker.py.previous" ]]; then
  install -o root -g root -m 0755 "$APP_DIR/backup/broker.py.previous" "$APP_DIR/broker.py"
  systemctl enable --now cm-auth-broker.service
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8110/health >/dev/null
  echo "cm-auth-broker:restored"
else
  echo "cm-auth-broker:disabled"
fi

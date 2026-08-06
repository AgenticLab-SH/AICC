#!/usr/bin/env bash
# Codex SSH compatibility dispatcher. Installed into WSL by cm; do not edit the
# deployed copy because cm refreshes it from this canonical source.

set -euo pipefail

bridge_env="${CODEX_NATIVE_SSH_ENV:-$HOME/.config/codex-native-ssh/bridge.env}"
if [[ ! -r "$bridge_env" ]]; then
  echo "Codex native SSH bridge is not configured; run cm ssh start" >&2
  exit 78
fi

# The file contains only single-quoted paths generated and validated by cm.
# shellcheck disable=SC1090
source "$bridge_env"

run_bridge() {
  "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" "$1" --manager-dir "$MANAGER_DIR"
}

if [[ $# -eq 1 && "$1" == "--version" ]]; then
  exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" version --manager-dir "$MANAGER_DIR"
fi

app_server_index=-1
for ((index = 0; index < $#; index++)); do
  position=$((index + 1))
  if [[ "${!position}" == "app-server" ]]; then
    app_server_index=$index
    break
  fi
done

if ((app_server_index >= 0)); then
  args=("$@")
  sub_index=$((app_server_index + 1))
  subcommand="${args[$sub_index]:-}"

  if [[ "$subcommand" == "proxy" ]]; then
    exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" proxy --manager-dir "$MANAGER_DIR"
  fi

  if [[ "$subcommand" == "daemon" ]]; then
    daemon_command="${args[$((sub_index + 1))]:-}"
    case "$daemon_command" in
      bootstrap | start | restart)
        exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" daemon-bootstrap --manager-dir "$MANAGER_DIR"
        ;;
      version)
        exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" daemon-version --manager-dir "$MANAGER_DIR"
        ;;
      stop)
        exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" stop --manager-dir "$MANAGER_DIR"
        ;;
    esac
  fi

  for ((index = sub_index; index < ${#args[@]}; index++)); do
    if [[ "${args[$index]}" == "--listen" && "${args[$((index + 1))]:-}" == unix://* ]]; then
      exec "$WINDOWS_PYTHON" "$BRIDGE_SCRIPT" bootstrap --manager-dir "$MANAGER_DIR"
    fi
  done
fi

exec "$REAL_CODEX" "$@"

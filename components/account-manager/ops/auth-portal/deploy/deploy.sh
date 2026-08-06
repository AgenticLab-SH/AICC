#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/cm-auth-broker
STATE_DIR=/var/lib/cm-auth-broker
ENV_FILE=/etc/cm-auth-broker.env
SERVICE_FILE=/etc/systemd/system/cm-auth-broker.service
CODEX_VERSION=0.146.0-alpha.3.1
case "$(uname -m)" in
  aarch64|arm64)
    CODEX_PACKAGE_URL=https://registry.npmjs.org/@openai/codex/-/codex-0.146.0-alpha.3.1-linux-arm64.tgz
    CODEX_PACKAGE_SHA256=2c32bb19d97a3362dc7e24325a058e52370e3aff43268e9bc52250a8b9bc413e
    CODEX_ARCHIVE_PATH=package/vendor/aarch64-unknown-linux-musl/bin/codex
    ;;
  x86_64|amd64)
    CODEX_PACKAGE_URL=https://registry.npmjs.org/@openai/codex/-/codex-0.146.0-alpha.3.1-linux-x64.tgz
    CODEX_PACKAGE_SHA256=d495bfa843ed9198327cc087b69b99aff09a66d4f5e7139137bc72d02ccf3e53
    CODEX_ARCHIVE_PATH=package/vendor/x86_64-unknown-linux-musl/bin/codex
    ;;
  *)
    echo "unsupported server architecture: $(uname -m)" >&2
    exit 2
    ;;
esac
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

[[ $(id -u) -eq 0 ]] || { echo "deploy must run as root" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "missing protected environment file" >&2; exit 2; }
[[ $(stat -c '%a' "$ENV_FILE") == 600 ]] || { echo "environment file must be mode 600" >&2; exit 2; }
grep -q '^CM_AUTH_SESSION_SECRET=.' "$ENV_FILE" || { echo "missing session signing secret" >&2; exit 2; }
[[ -f "$HERE/../broker.py" ]] || { echo "missing broker.py" >&2; exit 2; }
[[ -f "$HERE/cm-auth-broker.service" ]] || { echo "missing service unit" >&2; exit 2; }

if ! id cm-auth >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin cm-auth
fi
install -d -o root -g root -m 0755 "$APP_DIR" "$APP_DIR/bin"
install -d -o cm-auth -g cm-auth -m 0700 "$STATE_DIR"

if [[ -f "$APP_DIR/broker.py" ]]; then
  install -d -o root -g root -m 0700 "$APP_DIR/backup"
  cp -a "$APP_DIR/broker.py" "$APP_DIR/backup/broker.py.previous"
fi
install -o root -g root -m 0755 "$HERE/../broker.py" "$APP_DIR/broker.py"

current_version=""
if [[ -x "$APP_DIR/bin/codex" ]]; then
  current_version="$($APP_DIR/bin/codex --version 2>/dev/null || true)"
fi
if [[ "$current_version" != *"$CODEX_VERSION"* ]]; then
  package=$(mktemp /var/tmp/cm-codex.XXXXXX.tgz)
  extract=$(mktemp -d /var/tmp/cm-codex.XXXXXX)
  curl --fail --silent --show-error --location "$CODEX_PACKAGE_URL" --output "$package"
  printf '%s  %s\n' "$CODEX_PACKAGE_SHA256" "$package" | sha256sum --check --status
  tar -xzf "$package" -C "$extract" "$CODEX_ARCHIVE_PATH"
  install -o root -g root -m 0755 \
    "$extract/$CODEX_ARCHIVE_PATH" "$APP_DIR/bin/codex"
  rm -f "$package"
  find "$extract" -depth -delete
fi

install -o root -g root -m 0644 "$HERE/cm-auth-broker.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable cm-auth-broker.service
systemctl restart cm-auth-broker.service
for _ in $(seq 1 20); do
  if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:8110/health >/dev/null; then
    echo "cm-auth-broker:ok"
    exit 0
  fi
  sleep 1
done
systemctl status cm-auth-broker.service --no-pager --lines=20 >&2
exit 1

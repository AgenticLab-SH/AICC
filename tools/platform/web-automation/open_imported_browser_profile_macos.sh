#!/bin/sh
set -eu

name="${1:-}"
root="${IMPORTED_BROWSER_ROOT:-$HOME/.ai-control-center/browser-profiles/imported-windows}"
binary=""
profile=""
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
identity_page=""

case "$name" in
  chrome-main)
    app="/Applications/Google Chrome.app"
    data="$root/chrome-main/User Data"
    port=""
    ;;
  chrome-cdp-primary)
    app="$HOME/Applications/CDP Chrome 9222.app"
    data="$root/chrome-cdp-primary/UserData"
    port="9222"
    profile="Default"
    identity_page="$script_dir/browser-identities/chatgpt-9222.html"
    ;;
  chrome-cdp-bulk)
    app="$HOME/Applications/CDP Chrome 9223.app"
    data="$root/chrome-cdp-bulk/UserData"
    port="9223"
    profile="Default"
    identity_page="$script_dir/browser-identities/chatgpt-9223.html"
    ;;
  whale-main)
    app="/Applications/Whale.app"
    data="$root/whale-main/User Data"
    port=""
    ;;
  whale-cdp)
    app="$HOME/Applications/CDP Whale.app"
    data="${WHALE_CDP_USER_DATA_DIR:-$HOME/.ai-control-center/browser-profiles/whale/9335/UserData}"
    port="9335"
    profile="${WHALE_CDP_PROFILE_DIRECTORY:-Profile 1}"
    ;;
  *)
    printf '%s\n' 'usage: open_imported_browser_profile_macos.sh chrome-main|chrome-cdp-primary|chrome-cdp-bulk|whale-main|whale-cdp' >&2
    exit 2
    ;;
esac

if [ -z "$binary" ] && [ ! -d "$app" ]; then
  printf 'Browser application missing: %s\n' "$app" >&2
  exit 1
fi
if [ ! -d "$data" ]; then
  printf 'Imported browser profile missing: %s\n' "$data" >&2
  exit 1
fi

if [ -n "$port" ]; then
  if [ -n "$identity_page" ] && [ ! -f "$identity_page" ]; then
    printf 'Browser identity page missing: %s\n' "$identity_page" >&2
    exit 1
  fi
  identity_url="file://$identity_page"
  if [ -n "$binary" ]; then
    exec "$binary" --user-data-dir="$data" --profile-directory="$profile" --remote-debugging-address=127.0.0.1 --remote-debugging-port="$port" '--remote-allow-origins=*' --no-first-run --no-default-browser-check --new-window "$identity_url" 'https://chatgpt.com/'
  fi
  if [ "$name" = "chrome-cdp-primary" ] || [ "$name" = "chrome-cdp-bulk" ] || [ "$name" = "whale-cdp" ]; then
    exec open "$app"
  fi
  exec open -na "$app" --args --user-data-dir="$data" --profile-directory="$profile" --remote-debugging-address=127.0.0.1 --remote-debugging-port="$port" --no-first-run --no-default-browser-check --new-window "$identity_url" 'https://chatgpt.com/'
fi
exec open -na "$app" --args --user-data-dir="$data" --no-first-run --no-default-browser-check

#!/usr/bin/env bash
# Links `cm` into a directory on PATH. Creates nothing outside that link and
# never touches Codex credentials or shell profiles.
set -euo pipefail

repo_root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${CM_INSTALL_DIR:-$HOME/.local/bin}"
launcher="$repo_root/bin/cm"

if [ ! -f "$launcher" ]; then
  echo "Launcher not found: $launcher" >&2
  exit 1
fi

chmod +x "$launcher"
mkdir -p "$install_dir"

link_path="$install_dir/cm"
if [ -e "$link_path" ] && [ ! -L "$link_path" ]; then
  echo "Refusing to replace an existing non-symlink: $link_path" >&2
  echo "Move it aside, or set CM_INSTALL_DIR to another directory." >&2
  exit 1
fi

ln -sfn "$launcher" "$link_path"
echo "Linked $link_path -> $launcher"

case ":$PATH:" in
  *":$install_dir:"*) ;;
  *) echo "Note: $install_dir is not on PATH. Add it to your shell profile." ;;
esac

"$link_path" --help >/dev/null 2>&1 || true
echo "Done. Run: cm doctor"

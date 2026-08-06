#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

command -v node >/dev/null 2>&1 || { echo "Node.js 20 이상이 필요합니다." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm을 찾을 수 없습니다." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3.11 이상이 필요합니다." >&2; exit 1; }
command -v pwsh >/dev/null 2>&1 || { echo "PowerShell 7(pwsh)이 필요합니다." >&2; exit 1; }

if [[ -f .gitmodules ]] && command -v git >/dev/null 2>&1; then
  git submodule update --init --recursive
fi
if [[ "${1:-}" != "--no-link" ]]; then
  npm link
  for linked_command in aicc cm; do
    command -v "$linked_command" >/dev/null 2>&1 || {
      echo "npm link 후 $linked_command 명령을 찾을 수 없습니다." >&2
      exit 1
    }
  done
fi
node bin/aicc setup
node bin/aicc guidance deploy

echo
if [[ "${1:-}" == "--no-link" ]]; then
  echo "설정 완료: ./bin/aicc open"
else
  echo "설정 완료: aicc open"
fi

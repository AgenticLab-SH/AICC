#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "verify:mac은 macOS에서만 실행할 수 있습니다." >&2
  exit 2
fi

export PYTHONDONTWRITEBYTECODE=1

npm run check
npm test
npm run smoke
npm run test:account-manager
npm run test:workspace-mcp
npm run test:guidance
npm run test:browser
python3 -m unittest discover -s tools/platform/test -p 'test_project_portfolio.py' -v

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir . --redact --no-banner
else
  echo "참고: gitleaks가 없어 비밀정보 검사를 건너뜁니다." >&2
fi

git diff --check
echo "macOS verification passed."

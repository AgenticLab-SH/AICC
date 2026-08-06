# 에이전트 운영 지도

## 시작 순서

1. 루트와 가장 가까운 `AGENTS.md`, 현재 branch와 `git status --short`를 확인한다.
2. `aicc status`, `aicc cli status`, `aicc workspace status`, `aicc agents status`를
   읽기 전용으로 확인한다.
3. 계정, provider, 포트, 브라우저 slot과 workspace를 추측하지 않는다.

## 정본

| 대상 | 정본 | 생성·개인 상태 |
|---|---|---|
| AICC CLI/웹 | `src/`, `public/`, `bin/` | 전역 npm 링크 |
| Account Manager | `components/account-manager/` | `~/.codex-multi`, AICC private state |
| Workspace MCP | `components/workspace-mcp/`, `src/workspace-mcp.mjs` | `~/.ai-control-center/workspace-mcp` |
| Codex agent | `guidance/agents/codex/` | `~/.codex/agents` 생성본 |
| 지침·스킬 | `guidance/` | Codex·Claude home 생성본 |
| 브라우저 운영 | `tools/platform/` | 등록 런처·프로필·lease |
| OCX | submodule 포인터와 adapter | `~/.opencodex` |

표에 없는 별도 제어 루트, 모델 브리지, 에이전트 홈, 포트, provider 또는 복구
절차를 새 코드에 만들지 않는다.

## 변경 흐름

- 일반 코드: 정본 수정 -> 가까운 테스트 -> `npm run verify:mac`
- 지침·스킬: 정본 수정 -> `aicc guidance plan` -> `deploy` -> `check`
- Codex agent: `aicc agents plan` -> `deploy` -> `check`
- Workspace MCP: 고정 도구 schema와 sandbox 테스트 -> Tunnel health/ready -> ChatGPT 실제 호출
- 모델 경로: `manage-codex-model-routes`를 사용하고 활성 task 동안 OCX를 재시작하지 않는다.

macOS 로그인 자동 시작은 저장소의 설치기로만 갱신한다.

```bash
node tools/platform/dashboard/install-launch-agent.mjs
node tools/platform/workspace-mcp/install-launch-agent.mjs
```

9222/9223은 계정이 고정된 등록 CDP Chrome slot이고, Whale 9335는 사용자가 정한
기본 브라우저다. 인증된 UI 작업은 private coordination과 task-owned target lease를
따른다. 정상 Chrome, 다른 계정 또는 다른 profile로 조용히 우회하지 않는다.

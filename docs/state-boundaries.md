# 상태와 인증 경계

| 경로 | 소유자 | 내용 |
|---|---|---|
| AICC clone | Git | 공유 가능한 소스·정본 |
| `~/.ai-control-center` | AICC | 개인 설정, Workspace MCP, 브라우저 registry, 복구본 |
| `~/.codex` | Codex | 인증, task DB, 생성된 스킬·agent |
| `~/.codex-multi` | Account Manager | 격리 계정 상태 |
| `~/.opencodex` | OCX | provider, account pool, runtime 설정 |
| 등록 browser profile | 각 launcher | 로그인, extension, 캐시 |

Workspace MCP runtime key와 profile은
`~/.ai-control-center/workspace-mcp`에 0600/0700으로 둔다. 저장소, 프롬프트,
로그 또는 명령행에 키 값을 노출하지 않는다.

표에 없는 도구별 상태 루트는 만들지 않는다. 이전 실험의 상태는 활성 경로에서
제거하고, 필요한 복구본만 접근 권한이 제한된 단일 보관소에 둔다.

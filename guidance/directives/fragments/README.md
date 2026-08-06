# directives/fragments

AICC에서 각 에이전트 홈 진입 파일을 생성할 때 사용하는 실제 원문 조각입니다.

- `common.md`: 모든 에이전트가 공유하는 짧은 공통 운영 기준
- `agents/codex.md`: Codex `AGENTS.md`에 붙는 전용 규칙
- `agents/claude.md`: 공통 `AGENTS.md`를 import한 Claude `CLAUDE.md`에 붙는 전용 규칙

`tools/platform/core/deploy_directives.ps1`는 이 조각들을 합쳐 Codex·Claude에만 배포합니다. 생성된 홈 파일은 직접 수정하지 않습니다.
Claude의 프로젝트별 개인 설정은 해당 저장소의 gitignored `CLAUDE.local.md`에 두며, 전역 생성 대상으로 만들지 않습니다.

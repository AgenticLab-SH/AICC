# 통합 구조 이전

현재 AICC는 Account Manager, OCX adapter, Workspace MCP, 브라우저 운영과 지침 정본만
유지한다. 대체된 실험 구성은 검증 뒤 활성 경로에서 제거한다.

이전 시에는 먼저 private 복구점을 만들고 새 기능의 로컬·실제 연결 증거를 확인한다.
그 뒤 오래된 LaunchAgent, port, provider, custom model, 전역 CLI, source와 state를
참조 순서의 역순으로 제거한다. Codex 인증/task, OCX의 비대상 provider, 사용자
브라우저 profile과 독립 웹서비스 Tunnel은 보존한다.

`cm`은 Account Manager 호환 별칭으로만 유지한다. 새 자동화는 `aicc` 명령을 쓴다.

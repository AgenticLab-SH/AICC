# 안전 실행 계약

## AICC 제어면

계정과 OCX 변경은 이름이 고정된 action만 사용한다. 미리보기, 짧게 유효한 일회용
토큰, 단일 writer lock, 실행 전 상태 비교, 실행 후 검증과 복구를 거친다. AICC 웹
API는 loopback·동일 출처·JSON 요청만 허용한다.

## Workspace MCP 데이터면

Workspace MCP는 임의 절대 경로를 받지 않는다. 먼저 등록 별칭을 열고 만료되는
lease를 얻어야 한다. 읽기, 검색, 패치, 명령, Git 변경 검토와 AICC 스킬 읽기만
고정 schema로 제공한다. 비밀 파일과 Git 내부 메타데이터를 차단하고, 명령 환경에서
토큰·인증 변수를 제거한다. 프로세스 세션은 재부팅 뒤 자동 재실행하지 않는다.

## 완료 증거

- 단위 테스트와 실제 seatbelt 파일 생성·패치 smoke
- Tunnel launchd loaded, healthz와 readyz
- OCX 10100 health와 비대상 provider 보존
- `aicc agents check`, `aicc guidance check`
- 실제 ChatGPT connector의 workspace 목록·읽기·쓰기 호출

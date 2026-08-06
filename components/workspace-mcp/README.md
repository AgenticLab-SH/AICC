# AICC Workspace MCP

ChatGPT Business의 Secure MCP Tunnel이 직접 실행하는 AICC 소유 STDIO 서버입니다.
별도 로컬 HTTP 포트나 공개 reverse proxy를 열지 않습니다.

고정 도구 표면은 등록 워크스페이스 열기·목록, 범위 읽기, 검색, 패치, macOS
샌드박스 명령, 프로세스 입력, Git 변경 검토, AICC 정본 스킬 목록·읽기입니다.
임의 절대 경로는 받을 수 없고, 쓰기와 명령 실행에는 만료되는 workspace lease가
필요합니다. `.env`, 개인 키, 패키지 인증 파일, Git 내부 메타데이터는 차단합니다.

브라우저 및 Computer Use는 이 서버에 섞지 않습니다. 두 기능은 Codex가 제공하는
별도 네이티브 도구와 AICC의 브라우저 lease 정책을 따릅니다.
